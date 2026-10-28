# Innovation claim: finding the fraud no model can see

**The one idea we want judged:** January's fraud is new, so every score-based signal is blind to it. FraudLens finds it in the *shape* of the activity on the graph instead:
- four new-typology detectors, each with a ring scan across cards;
- a model whose weight is bounded on unseen data, so a low score never counts as innocence.

When a ring is found, a containment planner decides which cards to block on each card's own evidence. All numbers below come from code in this repo, run on the offline mirror of the same data; the official TigerGraph run reproduces them.

## The problem we measured

Both scores are low on every flagged transaction:

| | Flagged transactions in the 18-case pack |
|---|---|
| Our transaction model's score (validation AUC 0.972, against the bank's 0.866) | **all 18 are 0.29 or below**; 16 are below 0.02 |
| The bank's own `risk_score` in its transaction record | 0.01 to 0.31 |

A score-led agent therefore calls everything legitimate. Our Round 1 design did exactly that on January data.

## What we built (`agent/typologies.py`, `graph/queries/19_typology_scan.gsql`, `20_recipient_activity.gsql`)

| Detector | The signature, read only up to the case's open time |
|---|---|
| `micro_run` | Charges too small to trip a threshold: 4 or more online charges under $10, on 3 or more days, on a card with at most one such charge in the previous 90 days |
| `recipient_surge` | Many cards paying one recipient: the e-mail domain this card paid is suddenly paid by 5 or more cards in 30 days, at least 3x its own monthly reach |
| `spoofed_device` | A fingerprint no real device produces: one handset model (for example an Android build) reporting Windows, iOS or Mac OS, as a New device |
| `escalating_ramp` | Limit probing: consecutive purchases that keep roughly doubling until they hit a ceiling, then repeat at it |

**Ring scans.** Each detector also scans the same 30-day window for other cards carrying the same signature. That turns one card's anomaly into coordinated, undocumented activity, which brings in R9 and the section 3a report requirement. For a recipient surge, the shared element is the recipient e-mail domain that R6 names.

**Drift-aware weighting** (`agent/assess.py`). For January the case no longer starts from the model's score. It starts from the trigger's own prior, and the model becomes one piece of evidence with its likelihood ratio bounded to between 0.5 and 8.

## Measured effect: ablation on the 18 cases (`eval/ablation.py`)

| Variant | Fraud | Uncertain | Legitimate | Blocks | Reports filed |
|---|---|---|---|---|---|
| **FraudLens (full)** | **7** | 1 | 10 | 7 | **6** |
| Without the typology detectors | 7 | 1 | 10 | 7 | 1 |
| Without drift-aware weighting | 7 | 1 | 10 | 7 | 6 |
| Without both (roughly the Round 1 agent) | 3 | 4 | 11 | 3 | 0 |

- **Without both**, 4 cases change:
  - HHF-002 is called **legitimate**, though a spoofed-fingerprint purchase of $2,167 sits behind it.
  - HHF-003, HHF-004 and HHF-005 drop to **uncertain**. These are an $8,551 ramp and two micro-charge runs the customers disputed.
- **Without the detectors alone**, verdicts hold but 5 of the 6 reports disappear. The pattern can't be named, so R9 and section 3a never trigger.

## Measured cost: does it act against innocent customers? (`eval/typology_backtest.py`)

We ran every detector over every card at each month-end from August to January. August to October are the months whose labels are complete.

| | Aug | Sep | Oct | Nov | Dec | **Jan** |
|---|---|---|---|---|---|---|
| micro_run | 5 | 7 | 3 | 1 | 5 | **27** |
| recipient_surge | 39* | 18 | 9 | 0 | 0 | **17** |
| spoofed_device | 0 | 0 | 0 | 0 | 0 | **6** |
| escalating_ramp | 8 | 4 | 4 | 3 | 5 | **14** |

**Hits on a cleared (legitimate) case across the labelled months: 0.**

\* August's baseline has only July behind it. The September and October surges (protonmail.com) line up with confirmed fraud: 17 of 27 cards.

Precision on the labelled months sets how far the containment planner trusts a ring member:
- micro-charge runs and ramps are about 1 in 3 confirmed, so their ring members are monitored, not blocked;
- spoofed fingerprints never occur in the background.

## From finding to action: the containment planner (challenge 7, `agent/containment.py`)

**The rule:** block card *c* only if `conf(c) * exposure(c) - (1 - conf(c)) * $250 > 0` and `conf(c) >= 0.7`, where `conf` comes from the card's **own** signature, never from ring membership alone. Every other ring card is monitored, which costs a legitimate customer nothing.

- **Bank's 6 historical rings (130 connected cards):** blocking every ring card would have acted against **93 customers with no confirmed fraud of their own** within 30 days. Only 11 of the 116 cards that touched a ring's shared device were ever confirmed as fraud *on* it. The planner blocks none on membership alone (`eval/containment_backtest.py`).
- **January's rings,** from the case files:

| Ring | Plan |
|---|---|
| Spoofed fingerprints (HHF-002) | Block all 5 cards (100% of $7,611 at risk) |
| `sc.rr.com` recipient (HHF-006) | Block 16 of 17 (98.4% of $7,612) |
| Micro-charges (HHF-004) | Block the case card, monitor 18 (step-up stops a $3 charge without reissuing 18 cards) |
| Escalating ramps (HHF-003) | Block the case card, monitor 13 lower-confidence ring members |

## Every claim can be checked (`eval/attest_check.py`)

We re-ran the query behind every evidence claim in all 18 answers:
- **78 of 78 query-backed claims** returned every ID they cite (0 mismatches);
- 18 vector-search claims need the query embedding to replay;
- 28 claims are not queries (customer responses, the policy, the alert text).

On TigerGraph the same script runs with `--graph`.
