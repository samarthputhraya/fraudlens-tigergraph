# Transaction model card (FraudLens v2)

**What it is.** A LightGBM classifier that scores every transaction with the probability that it belongs to a
confirmed-fraud case. It is trained only on the bank's own closed cases (`closed_cases_history.csv`). The public
IEEE-CIS files are never used.

**Why it exists.** In v1 we replayed October's alerts and measured the graph evidence alone at AUC 0.55 among
high-score alerts, which is barely better than a coin flip. "Is this high-score alert fraud or a false alarm?" is
the core question of a risk-score case, so v1's weakest link sat exactly where half the grade is.

## Data and label

| | |
|---|---|
| Positive label | the transaction is listed in a confirmed-fraud closed case (14,055 transactions, July–October) |
| Negative | every other transaction, including the 900 cleared alerts |
| Train | July–September (316,984 transactions) |
| Validation | October (100,420 transactions, 3.3% fraud) |
| Production model | July–October, same number of boosting rounds (+10%), scores November–December |

## Features: nothing from the future

Every feature on a transaction uses only what the bank knew when that transaction happened.

- **The row itself.** Amount, product, card fields, billing region, e-mail domains, and the unnamed Vesta `C`, `D`,
  `M` and `V` columns and identity record. We say in the evidence that these are unnamed signals.
- **Running aggregates over earlier transactions only.** These cover the same resolved account (card + billing
  region + account-open day, the graph's `Account` vertex), the same card, the same device profile and the same
  e-mail domain.
- **Graph memory.** Confirmed-fraud and cleared closed cases on the same account and card that were already closed
  before the transaction. This is the `Account → Transaction → ClosedCase` path in TigerGraph.

## Results (October hold-out; the model never saw October labels)

| Metric | With the bank's risk score | Without it |
|---|---|---|
| AUC, all October transactions | **0.973** | 0.941 |
| AUC among alerts scored ≥ 0.5 (n = 5,335) | **0.933** | 0.887 |
| AUC, confirmed-case vs cleared-alert transactions (n = 3,425) | 0.881 | **0.909** |

We calibrate probabilities with isotonic regression fitted on October. Reliability bins are in
[`model_report.json`](model_report.json).

## How the agent uses it

1. **Scores live in the graph.** `graph/setup.py scores` writes the calibrated score onto each `Transaction` vertex
   as `model_p`. Every installed query returns it next to the raw evidence, so the agent reads it through the
   TigerGraph MCP tools like any other attribute.
2. **Starting point of the ledger.** For a risk-score alert, the calibrated score is the starting probability.
   - A customer's own dispute starts at 0.86, because every confirmed case in the bank's history began as a customer
     report, and moves by the model's likelihood ratio.
   - An analyst request starts at 0.45 and moves the same way.
   - Signals the model already sees (new device, proxy, amount, region, account history) are shown in the evidence
     but not counted twice.
3. **Evidence the model cannot see still moves the probability.** This covers other cards on the same rare device
   that the model scores as fraud (R6), same-signature undocumented patterns (structuring, device rings), card-testing
   sequences, and recurring charges from the same cardholder (R7).
4. **Episode.** The bank's closed cases chain fraud transactions on the same card while consecutive gaps stay within
   48 hours. We sample that chain 4,000 times from the calibrated scores and keep the transactions that belong to it
   in at least half of the draws.
5. **Pattern.** We apply the labelling rule read off the bank's 4,665 confirmed cases:

   | Episode | Pattern | Agreement |
   |---|---|---|
   | All online, any device marked New | `card_not_present_new_device` | 100% |
   | All online, no New device | `card_not_present_fraud` | 100% |
   | Mixed channels | `account_takeover` | 100% |
   | Card-present in the card's home region | `account_takeover` | 95% |
   | Card-present elsewhere or across regions | `out_of_region_use` | 95% |

## Limits

- **Seeded rows.** The model has no signal on the few rows the organisers seeded, such as the SM-G935F ring and the
  sub-$500 structuring. Dedicated graph detectors handle those.
- **The bank's own score.** It is an input and it helps, but the model is still strong without it (last column
  above).
- **Probability is not proof.** Every verdict still goes through the policy engine: R1 verification, R2 denial,
  section 6 stop rule.
