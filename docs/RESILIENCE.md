# FraudLens resilience statement

TigerGraph × Hacker House Goa 2026, Final Round.

## What FraudLens depends on

| Dependency | Used for | How we reach it |
|---|---|---|
| **TigerGraph Savanna** (graph `Fraud`) | All evidence. That covers the 20 installed GSQL queries, TigerVector similarity search over case memory, and the WCC ring components. It also stores our own cases back into the graph as memory. | **Reads:** the TigerGraph MCP server (`tigergraph-mcp` 1.0.3, stdio). Its tool allowlist permits running installed queries and reading descriptions, nothing more. **Writes:** only `agent/case_writer.py`, over pyTigerGraph REST. |
| **Gemini on Vertex AI** (`LLM_MODEL_PRO`, `LLM_MODEL_FLASH`, `text-embedding-005`) | The planner, four specialist analysts, the compliance reviewer, the case and SAR writer, and embeddings for case memory. **It never sets a verdict, probability, ID, amount, route or action.** | `google-genai`, authenticated with the service's own Google Cloud identity. There is no API key in the repo. |
| **Local files** | The case pack, traces, audit logs and answers | Repo folders. Secrets live only in `.env`, which is gitignored. |
| **Offline DuckDB mirror** | Development and backtests only | Used only when `--mirror` or `FRAUDLENS_MIRROR=1` is passed. Every answer it produces says `"graph": "offline-mirror", "official": false`. |

## What leaves the bank's boundary

**To Vertex AI (Gemini):**
- **The alert text.** It is fenced as untrusted data and any instruction spans are removed first.
- **The flagged transaction:** its pseudonymous IDs, amount, product code, channel, billing region code, device profile string and e-mail domains.
- **Card and account aggregates:** counts, amounts, and region and product histograms.
- **Slices of graph evidence:** transaction rows with the same fields, plus closed-case outcomes and analyst notes.
- **The decision draft**, so the writer can describe it.

**For embeddings:** case summaries and query text.

**Never sent:** names, card numbers, addresses or credentials. The dataset holds none, and every customer and card ID is pseudonymous.

**To TigerGraph Savanna:** the bank's own dataset (which is where the graph lives) and the case memory we write back.

## What happens when each part fails

Every failure is printed, written to a hash-chained audit log, and never presented as a complete answer.

**TigerGraph**
- **Unreachable at start, or the MCP server won't start:** nothing is investigated. You see `STOPPED: … No case was investigated` and exit status 2. There is no silent switch to REST or to the mirror.
- **A query fails or times out mid-investigation:** that case stops and no answer is written. Any earlier answer for the case is moved to `<out>/stale/`, and a `FAILED` record is kept with the calls made before the failure. The run continues with the next case. Exit status 2.
- **A graph write fails after the decision:** the answer says `written_to_graph: false` and is marked incomplete and escalated. It never claims a save that didn't happen.

**Gemini**
- **A call times out, errors or returns output that breaks the schema:** one retry, then the step is recorded as failed. A circuit breaker skips the case's remaining model calls instead of waiting out each timeout.
- **What still stands:** the decision itself, because it is code. The answer is marked `run.complete: false`, status `escalated`, with `ESCALATE_TO_ANALYST` (R8). Template text is labelled "[Template text …]". Exit status 3.
- **The writer returns text that names IDs not in the evidence, contradicts the decision, or is filler:** it is rejected and handled the same way.

**The input**
- **The flagged transaction doesn't exist, the row is malformed, or the case opens before its transaction:** the case stops with a clear `InvalidInput` and nothing is invented.
- **The case record and the bank's record disagree** (a different card or customer): the investigation reads the bank's record, records the discrepancy, and answers `uncertain` with `ESCALATE_TO_ANALYST` (R8). It never blocks.
- **Hostile or misleading free text:** decisions never read the text. Instruction spans are recorded as evidence and removed before any model sees them. Claims the record contradicts (channel, amount, transaction) are recorded and overridden. When the alert's score and the score stored on the transaction disagree, that is recorded too, and in January neither one is used as evidence. The attack suite in `eval/attack_suite.py` ran 14 attacks: **0 decisions changed, 14 detected, 0 tip-offs.**

**Approvals**
- **Wrong role:** the role comes from the bearer token, never from the request. A team lead gets 403 on an L2 action.
- **The same action decided twice, or two requests racing:** exactly one is recorded; the other gets 409.
- **The answer is incomplete, edited after the agent wrote it, or routed differently from what policy section 2 requires:** 409, and no decision.
- **The graph update fails:** 502, and the decision is **not** recorded.

## What is logged

- **`runs/audit/audit.jsonl`** is append-only. It holds every answered case (verdict, actions, SHA-256 of the answer and of its trace), every stopped case, every dependency failure, and every refused write query.
- **`runs/audit/approvals.jsonl`** holds every approval decision, refusal and failed write.
- **Tamper evidence on both logs:** each entry chains the previous entry's hash and carries an HMAC keyed by `FRAUDLENS_AUDIT_KEY`. A head file anchors the entry count, so `GET /api/audit/verify` detects edits, forged entries, truncation and deletion. While a log fails verification, approvals are suspended (503).
- **`runs/traces/<case>.json`** records every tool call with its parameters, row count, latency, path (MCP or REST) and success.
- **MCP's own tool-call log** is switched on (`TG_LOG_TOOL_CALLS`).
- **Redaction:** traces and audit entries pass through `agent/safety.redact`, which removes tokens, secrets, bearer credentials and the Savanna host.

## Least privilege

- **The investigating agent is read-only.** MCP allows only `run_installed_query` and read tools. On top of that, `GraphClient` refuses any installed query that writes (`build_ring_links`) unless a batch job opts in with `allow_write=True`. Only `monitor.py` does.
- **API re-prove** replays only read queries.
- **The model** has no query access at all. It chooses from a fixed menu of five read queries with bounded parameters.

## How to reproduce each drill

`FRAUDLENS_FAULT` injects a failure at a named step, for example:

```bash
FRAUDLENS_FAULT=graph:card_window python run_cases.py HHF-009       # dependency failing mid-run -> STOPPED, exit 2
FRAUDLENS_FAULT=llm_timeout:* python run_cases.py HHF-009           # model times out -> incomplete + escalated, exit 3
FRAUDLENS_FAULT=llm_garbage:writer python run_cases.py HHF-009      # model returns garbage -> same
python run_cases.py HHF-009 && python run_cases.py HHF-009          # same case twice -> identical decision
python -m pytest tests/test_failclosed.py tests/test_approvals.py tests/test_injection.py
```
