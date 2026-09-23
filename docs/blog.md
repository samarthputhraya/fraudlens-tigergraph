# The model predicts. TigerGraph proves: building an agentic fraud investigator on a graph

*How we built FraudLens for the TigerGraph × Hacker House Goa 2026 challenge: a team of AI investigators that works
through fraud alerts on a TigerGraph knowledge graph, decides the next best action under a real fraud policy, and
backs every claim with a query you can re-run.*

---

## The problem

Fraud analysts spend most of their time collecting evidence, not deciding. For every alert they pull the
transaction history, check the device and the region, look for connected cards, read old cases, re-read the policy,
and write it all up. A risk score doesn't settle an alert. In this dataset the bank's model scored thousands of
transactions above 0.7, and **most of them were legitimate**. Some real fraud scored close to zero.

The challenge gave us 590,742 IEEE-CIS card transactions with no fraud label. It also gave us 5,565 closed
investigations, a five-pattern typology, a ten-rule fraud policy, and 20 alerts to investigate. Our goal was not a
better classifier. It was an **investigator** that:
- knows what to look at;
- knows when the evidence is not enough and asks for more;
- follows the policy to the letter;
- leaves a record the next investigation can learn from.

## What we built

FraudLens is a virtual fraud team:

- **Lead Investigator** (Gemini 3.1 Pro on Vertex AI). It reads the alert, forms competing hypotheses, and picks extra graph queries from a menu of installed GSQL queries.
- **Four specialist analysts**, running in parallel. Each sees only its slice of the evidence:
  - *Transaction*: velocity, bursts, recurring charges, card testing, structuring.
  - *Identity & Device*: new devices, proxies, the resolved cardholder account.
  - *Network & Ring*: what happened on *other* cards.
  - *Precedent*: closed cases and policy documents.
- **A deterministic core** covering detectors, a calibrated log-odds ledger, and the policy engine. It owns every number, ID, route and SAR decision.
- **Compliance Reviewer**. A red-team agent that checks the draft against the policy before anything is written.
- **Writer**. Produces the analyst summary and a FinCEN-style suspicious activity report.
- **Case writer**. The *only* component allowed to write to the graph.

The LLM reasons, chooses tools and writes. It never sets a probability, an exposure, an approval route or a
transaction ID. A validator rejects any answer that mentions an ID that doesn't exist in TigerGraph.

## Architecture

![architecture](architecture.png)

1. **Trigger**: a model score, a customer report, an analyst request or our autonomous monitor.
2. **Investigate**: seven core GSQL queries, plus up to three the Lead Investigator chooses. All go through the **official TigerGraph MCP server** (`tigergraph__run_installed_query`), started with a least-privilege `--allowed-tools` allowlist (query, vector and read tools only; no schema, loading, DML or raw GSQL) and tool-call logging.
3. **Assess**: detectors emit typed findings, each with a likelihood ratio, the entity IDs it rests on, and a replayable reference such as `query:card_window(card=C07297-K1, start_ts=…, end_ts=…)`.
4. **Decide**: the policy engine computes the initial action, the evidence request, and **all three counterfactual branches**:
   - the customer confirms (R3);
   - the customer denies (R2);
   - no reply (R4).

   The evidence picks the branch we assume. We record `initial`, `final` and `what_changed`.
5. **Remember**: hybrid GraphRAG over TigerVector. Every investigation is written back as an `InvestigationCase` with edges to its transactions, cards, devices, cited cases, rules and actions.
6. **Govern**: `auto` actions run immediately (simulated). `L1` and `L2` actions wait in an approval inbox, which checks roles: a team lead cannot approve a fraud manager's `FILE_REPORT`.

## How we used TigerGraph

**Schema.**
- Customer → Card → Transaction, with DeviceProfile, EmailDomain and BillingRegion.
- ClosedCase, PolicyRule, FraudPattern and DocChunk for knowledge.
- InvestigationCase, EvidenceRequest and ActionRecord for the agent's own memory.

The most useful vertex we added was **Account**. The dataset's `customer_id` is really a card-issuer bucket; one
"customer" has more than 10,000 transactions. We resolve the hidden cardholder account as card + billing region +
account-open day, where the open day comes from the D1 "days since first use" field. That's an entity-resolution
step, and it produced the single strongest signal in the project:

> In October, transactions on accounts that already had a confirmed fraud case were fraud **42%** of the time,
> against a **2.7%** base rate. None of the 144 cleared alerts had it.

We also recovered how the bank derived card IDs: the rank of the card network and type within the customer, which
matches **100%** of the 14,955 closed-case transactions. We found how it cut fraud *episodes*: consecutive
transactions on the same account are at most 48 hours apart in 99% of confirmed cases. That became our episode
builder, and it reproduces closed-case transaction sets with a Jaccard overlap of **0.82**.

**17 installed GSQL queries.** Each is described with `UPDATE DESCRIPTION OF QUERY`, so an agent can discover it
through MCP. They include:
- `card_window`, `card_profile` (baseline strictly before the alert, so no look-ahead) and `recurring_match`;
- `account_history`, `device_neighbors`, `region_activity`, `prior_cases`;
- `structuring_scan` and `card_testing_scan`;
- the ring projection;
- a validator that checks every ID we cite.

**TigerVector + graph = hybrid GraphRAG.** We embedded the 5,565 closed-case narratives and 242 chunks of policy,
typology and FinCEN guidance (768-d, Vertex `text-embedding-005`). Plain vector search finds cases that *read*
alike. Our `similar_cases` query first builds a **candidate set by graph traversal**: the closed cases reachable
from the alert's device profile and cards. It then runs `vectorSearch()` inside that set. For the device-ring alert
(HHG-014) this pulled the exact four August–September cases where the same Samsung device profile hit other
cardholders. No text query would have found them.

We ran the same query two ways:

| Search (query text: "shared device ring, anonymous proxy, new device, several cardholders") | Top hits |
|---|---|
| Vector only | CC-2060, CC-3977 (ordinary new-device fraud), CC-3035, CC-4491, CC-2649 |
| Vector inside the graph candidate set | **CC-2985, CC-2971, CC-3035, CC-2649**: exactly the four ring cases |

**Graph algorithms.** For ring discovery we project rare device profiles that appeared as a *new* device on several
cards in a time window into Card–`RING_LINK`–Card edges. We then run TigerGraph's built-in
`GDBMS_ALGO.community.wcc` over the projection. The time window matters: a global WCC over card–device edges
collapses into one giant component, because generic browser profiles connect everything.

## The agentic part: deciding under uncertainty

The policy is code. `policy.plan()` is a pure function that returns the recommendation for every possible reply:

- **Verify before blocking.** Probability 0.46 on a $1,000.03 online purchase from a new device (HHG-010) → `CREATE_CASE`, `DECLINE_TRANSACTION` (L1) and `STEP_UP_AUTH` (R1).
  - The evidence can't settle it, so we assume no reply.
  - R4 then gives `MONITOR_CARD` and `DECLINE_TRANSACTION`, plus `ESCALATE_TO_ANALYST`, because $1,000.03 is over the $500 escalation limit (R8).
  - The verdict stays `uncertain`. The README says that is the right answer for designed ambiguity.
- **Know when to stop.** A 0.61-score purchase in a region the card had used ten times before, on an account with a clean history → probability 0.09 on two independent legitimate signals. Section 6 says stop, so `ALLOW_TRANSACTION` and `CLOSE_NO_FRAUD`, with no customer contact.
- **Case vs report.** The rules come from section 3a. A $128 online fraud gets a case only. Four online purchases of $456–$488 in 30 minutes (HHG-006, $1,906.07) get a case **and** a SAR under R9, because amounts chosen to stay under a $500 threshold match none of the five documented patterns.
- **Disputed but legitimate.** A customer disputes a $55.68 charge that recurs on the same day each month (HHG-008). R7 applies: `CREATE_CASE`, `VERIFY_WITH_CUSTOMER` and `WARN_CUSTOMER`, and no block.

**Calibration** is a Bayesian log-odds ledger:
- The prior for a model alert is the base fraud rate times the likelihood ratio of its score band.
- We measured that ratio on 14,055 fraud vs 402,449 background transactions. It gives about 47% for scores of 0.85 and above, which matches the README's warning.
- Each finding adds its own measured ratio.

Some classic "red flags" turned out *not* to be red here. A card-present purchase in a billing region the card had
never used has a likelihood ratio of **0.46**: in this data it usually means travel.

## What we learned

1. **Graph memory beats better prompts.** Our biggest accuracy gains came from entity resolution and graph-filtered retrieval, not from the LLM.
2. **Keep the LLM away from arithmetic and IDs.** Every hallucination we saw early on was a plausible-looking transaction ID. A validator backed by an `ids_exist` query fixed that for good.
3. **Closed histories are biased.** Every cleared case in this bank's history was a high-score model alert, and most confirmed frauds were low-score customer reports. So a naive backtest rewards a model for ignoring the score. We fitted evidence against background transactions instead, and we report only the metrics that history can support.
4. **Least privilege works for agents.** Read-only MCP for reasoning, a single audited write path, and role-checked approvals made the system easier to trust and to debug.

## Results

<!-- RESULTS_TABLE -->
| Case | Trigger | Verdict | p | Pattern | Exposure | SAR | Initial → Final actions | Graph |
|---|---|---|---|---|---|---|---|---|
| [HHG-001](cases/HHG-001.json) | risk score | legitimate | 0.09 | none | $0.00 | — | ALLOW_TRANSACTION CLOSE_NO_FRAUD | ✅ |
| [HHG-002](cases/HHG-002.json) | risk score | legitimate | 0.05 | none | $0.00 | — | CREATE_CASE VERIFY_WITH_CUSTOMER **→** ALLOW_TRANSACTION CLOSE_NO_FRAUD | ✅ |
| [HHG-003](cases/HHG-003.json) | customer report | fraud | 0.66 | out of region use | $165.93 | — | BLOCK_CARD CREATE_CASE | ✅ |
| [HHG-004](cases/HHG-004.json) | customer report | fraud | 0.67 | card not present new device | $128.33 | — | BLOCK_CARD CREATE_CASE | ✅ |
| [HHG-005](cases/HHG-005.json) | risk score | legitimate | 0.05 | none | $0.00 | — | CREATE_CASE VERIFY_WITH_CUSTOMER **→** ALLOW_TRANSACTION CLOSE_NO_FRAUD | ✅ |
| [HHG-006](cases/HHG-006.json) | customer report | fraud | 0.97 | undocumented | $1,906.07 | ✅ | BLOCK_CARD CREATE_CASE FILE_REPORT ESCALATE_TO_ANALYST | ✅ |
| [HHG-007](cases/HHG-007.json) | risk score | fraud | 0.97 | account takeover | $111.92 | — | CREATE_CASE DECLINE_TRANSACTION VERIFY_WITH_CUSTOMER **→** BLOCK_CARD CREATE_CASE | ✅ |
| [HHG-008](cases/HHG-008.json) | customer report | legitimate | 0.05 | none | $0.00 | — | CREATE_CASE VERIFY_WITH_CUSTOMER WARN_CUSTOMER **→** CREATE_CASE WARN_CUSTOMER CLOSE_NO_FRAUD | ✅ |
| [HHG-009](cases/HHG-009.json) | customer report | fraud | 0.60 | card not present fraud | $30.02 | — | BLOCK_CARD CREATE_CASE | ✅ |
| [HHG-010](cases/HHG-010.json) | risk score | uncertain | 0.56 | card not present new device | $1,000.03 | — | CREATE_CASE DECLINE_TRANSACTION STEP_UP_AUTH **→** MONITOR_CARD DECLINE_TRANSACTION ESCALATE_TO_ANALYST | ✅ |
| [HHG-011](cases/HHG-011.json) | customer report | fraud | 0.92 | card not present new device | $235.66 | ✅ | BLOCK_CARD CREATE_CASE FILE_REPORT MONITOR_CONNECTED_CARDS | ✅ |
| [HHG-012](cases/HHG-012.json) | risk score | legitimate | 0.05 | none | $0.00 | — | CREATE_CASE VERIFY_WITH_CUSTOMER **→** ALLOW_TRANSACTION CLOSE_NO_FRAUD | ✅ |
| [HHG-013](cases/HHG-013.json) | risk score | uncertain | 0.51 | card not present new device | $35.66 | — | CREATE_CASE DECLINE_TRANSACTION STEP_UP_AUTH **→** MONITOR_CARD DECLINE_TRANSACTION | ✅ |
| [HHG-014](cases/HHG-014.json) | analyst request | fraud | 0.97 | undocumented | $187.33 | ✅ | BLOCK_CARD CREATE_CASE FILE_REPORT MONITOR_CONNECTED_CARDS ESCALATE_TO_ANALYST | ✅ |
| [HHG-015](cases/HHG-015.json) | risk score | legitimate | 0.05 | none | $0.00 | — | CREATE_CASE VERIFY_WITH_CUSTOMER **→** ALLOW_TRANSACTION CLOSE_NO_FRAUD | ✅ |
| [HHG-016](cases/HHG-016.json) | customer report | fraud | 0.68 | card not present new device | $59.67 | — | BLOCK_CARD CREATE_CASE | ✅ |
| [HHG-017](cases/HHG-017.json) | risk score | legitimate | 0.05 | none | $0.00 | — | CREATE_CASE VERIFY_WITH_CUSTOMER **→** ALLOW_TRANSACTION CLOSE_NO_FRAUD | ✅ |
| [HHG-018](cases/HHG-018.json) | customer report | fraud | 0.90 | out of region use | $39.08 | — | BLOCK_CARD CREATE_CASE | ✅ |
| [HHG-019](cases/HHG-019.json) | risk score | fraud | 0.97 | card not present new device | $99.92 | ✅ | CREATE_CASE DECLINE_TRANSACTION STEP_UP_AUTH MONITOR_CONNECTED_CARDS **→** BLOCK_CARD CREATE_CASE FILE_REPORT MONITOR_CONNECTED_CARDS | ✅ |
| [HHG-020](cases/HHG-020.json) | risk score | uncertain | 0.59 | card not present new device | $125.08 | — | CREATE_CASE DECLINE_TRANSACTION STEP_UP_AUTH **→** MONITOR_CARD DECLINE_TRANSACTION | ✅ |

Average per case: **12.2 graph/retrieval tool calls**, **8,563 LLM tokens**, **97 s**. Every file passes the schema + ID + policy validator.


## What we'd improve with more time

- Replace the hand-set likelihood ratios for the graph-only signals with a model trained on graph features (FastRP embeddings of the card–device–account neighbourhood).
- Stream new transactions into TigerGraph and run the monitor continuously instead of as a sweep.
- Replace simulated customer replies with a real two-way channel, and learn which verification step (OTP vs call) resolves which alert type fastest.
- Use Louvain communities over the full shared-entity graph to find rings that share emails or regions, not only devices.

*Code, answer files and the demo video: [GitHub](#). Built with TigerGraph Savanna, TigerGraph MCP, GSQL, TigerVector
and Gemini on Vertex AI.* @TigerGraphDB
