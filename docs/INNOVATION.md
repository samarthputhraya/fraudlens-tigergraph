# Innovation claim: finding the fraud no model can see

**The one idea we want judged:** January's fraud is new, so every score-based signal is blind to it. FraudLens finds it in the *shape* of the activity on the graph instead:
- four new-typology detectors, each with a ring scan across cards;
- a model whose weight is bounded on unseen data, so a low score never counts as innocence.

When a ring is found, a containment planner decides which cards to block on each card's own evidence. All numbers below come from code in this repo, run on the offline mirror of the same data. The backtests are mirror-only; the 18 answers are re-run on TigerGraph in the official run, and `eval/parity.py` checks that TigerGraph returns the same evidence as the mirror.

## The problem we measured

Both scores are low on every flagged transaction:

| | Flagged transactions in the 18-case pack |
|---|---|
| Our transaction model's score (validation AUC 0.972, against the bank's 0.866) | **all 18 are 0.29 or below**; 16 are below 0.02 |
| The bank's own `risk_score` in its transaction record | 0.01 to 0.31 |

A score-led agent therefore misses most of it. Our Round 1 agent, run unchanged on January (`runs/baseline`), called 2 cases fraud, 3 uncertain and 12 legitimate, and stopped on 1. Seven are fraud.

## What we built (`agent/typologies.py`, `graph/queries/19_typology_scan.gsql`, `20_recipient_activity.gsql`)

| Detector | The signature, read only up to the case's open time |
|---|---|
| `micro_run` | Charges too small to trip a threshold: 4 or more online charges under $10, on 3 or more days, on a card with at most one such charge in the previous 90 days. Three or more charges of one exact amount are a subscription and don't count |
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
  - HHF-002 is called **legitimate**, though three spoofed-fingerprint purchases totalling $2,166.71 sit behind it.
  - HHF-003, HHF-004 and HHF-005 drop to **uncertain**. These are an $8,551 ramp and two micro-charge runs the customers disputed.
- **Without the detectors alone**, verdicts hold but 5 of the 6 reports disappear. The pattern can't be named, so R9 and section 3a never trigger.

## Measured cost: does it act against innocent customers? (`eval/typology_backtest.py`)

We ran every detector over every card at each month-end from August to January. August to October are the months whose labels are complete.

| | Aug | Sep | Oct | Nov | Dec | **Jan** |
|---|---|---|---|---|---|---|
| micro_run | 5 | 7 | 3 | 1 | 5 | **24** |
| recipient_surge | 39* | 18 | 9 | 0 | 0 | **17** |
| spoofed_device | 0 | 0 | 0 | 0 | 0 | **6** |
| escalating_ramp | 8 | 4 | 4 | 3 | 5 | **14** |

**Hits on a cleared (legitimate) case across the labelled months: 0.**

\* August's baseline has only July behind it. The September and October surges (protonmail.com) line up with confirmed fraud: 17 of 27 cards.

Precision on the labelled months (August to October) sets how far the containment planner trusts a ring member:
- micro-charge runs are 5 of 15 confirmed and ramps 5 of 16, about 1 in 3, so their ring members are monitored, never blocked, and never named in a regulator report;
- recipient surges in September and October were 17 of 27 confirmed;
- spoofed fingerprints never occur in the background.

## From finding to action: the containment planner (challenge 7, `agent/containment.py`)

**The rule:** block card *c* only if `conf(c) * exposure(c) - (1 - conf(c)) * $250 > 0` and `conf(c) >= 0.7`, where `conf` comes from the card's **own** signature, never from ring membership alone. Every other ring card is monitored, which costs a legitimate customer nothing.

- **The bank's 6 historical device rings** (`eval/containment_backtest.py`; 130 ring memberships, and the rings overlap, since 4 share one device):
  - Blocking every ring card would have stopped **$119,386** of fraud. It would also have blocked **93 memberships with no confirmed fraud of their own** within 30 days. At our assumed $250 harm per innocent block, that is still net positive (+$96,136).
  - The planner blocks **none** of them and stops $0. In those rings the only evidence against a member is the ring itself, which the planner gives a confidence of 0.5, under its 0.7 bar. So this outcome is a rule, not a discovery.
  - **This is a deliberate choice of precision over recall,** following R1 (never block on a single signal). The case card is blocked on its own evidence. The rest of the ring is monitored and goes to an analyst with the evidence, who can block in minutes. A bank that values recall more can lower the bar or the $250 cost: both are parameters, swept from $100 to $500 in the backtest.
- **January's rings,** from the case files. Each plan is a recommendation for the analyst; a case's own actions block only that case's card:

| Ring | Plan |
|---|---|
| Spoofed fingerprints (HHF-002) | Block all 5 cards (100% of $7,611 at risk) |
| `sc.rr.com` recipient (HHF-006) | Block 16 of 17 (98.4% of $7,612) |
| Micro-charges (HHF-004) | Block the case card, monitor the other 15 (none is named in the report) |
| Escalating ramps (HHF-003) | Block the case card, monitor the other 13 (none is named in the report) |

## Every claim can be checked (`eval/attest_check.py`)

We re-ran the query behind every evidence claim in all 18 answers:
- **77 of 77 re-runnable claims** returned every ID they cite (0 mismatches);
- 18 vector-search claims need the query embedding to replay;
- 27 claims are not queries (customer responses, the policy, the alert text).

On TigerGraph the same script runs with `--graph`.
