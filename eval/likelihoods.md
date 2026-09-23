# Evidence likelihood ratios (how the calibration ledger is fitted)

Fitted on July–October data. Fraud side: the **14,055** transactions that belong to confirmed-fraud closed cases.
Background side: the **402,449** transactions not in any closed case. LR = P(feature | fraud) / P(feature | background).

| Feature | P(fraud) | P(background) | LR | Used as |
|---|---|---|---|---|
| Online channel | 0.565 | 0.267 | 2.12 | (in the risk score) |
| Device profile marked New (online) | 0.158 | 0.114 | **1.39** | `new_device` 1.4 |
| Anonymous or hidden proxy | 0.009 | 0.003 | **2.99** | `proxy` 3.0 |
| Amount above the card's previous maximum | 0.014 | 0.011 | **1.26** | `amount_above_max` 1.3 |
| Product code never used on the card | 0.007 | 0.004 | **1.81** | `new_product` 1.8 |
| Card-present in a region new to the card | 0.009 | 0.020 | **0.46** | `region_new` 0.6 (travel) |
| Card-present in a region with at least 3 prior visits | 0.386 | 0.626 | **0.62** | `region_known` 0.65 |
| Online purchase on an almost-only-in-person card | 0.005 | 0.002 | **2.69** | `channel_shift` 2.7 |
| Risk score < 0.10 | 0.062 | 0.434 | 0.14 | prior (risk-score alerts) |
| Risk score 0.30–0.50 | 0.215 | 0.086 | 2.52 | prior |
| Risk score 0.50–0.70 | 0.205 | 0.034 | 6.04 | prior |
| Risk score 0.70–0.85 | 0.176 | 0.018 | 9.59 | prior |
| Risk score ≥ 0.85 | 0.087 | 0.003 | 24.99 | prior |

**Prior for a risk-score alert.** The base rate is 3.4%, multiplied by the score-bin LR:

| Score | Prior probability of fraud |
|---|---|
| 0.5–0.7 | 17% |
| 0.7–0.85 | 25% |
| ≥ 0.85 | 47% |

This matches the README's warning that most alerts above 0.7 are legitimate.

**Graph-only signals the model can't see:**

| Signal | Basis | LR |
|---|---|---|
| Prior confirmed fraud on the same resolved account (card + billing region + account-open day) | October: 42% fraud vs a 2.7% base rate; 0 of 144 cleared alerts had it | 12 |
| Sub-threshold structuring: at least 3 online purchases in $400–500 within 60 minutes | Matches the 5 undocumented closed cases CC-3748, CC-3841, CC-3907, CC-4086, CC-4124 | 40 |
| Card testing: at least 3 online authorisations under $5 within an hour, then a larger purchase | Policy R5, pattern 1 | 30 |
| Shared-device ring: a rare profile used as a New device by at least 3 other customers, concentrated in the window | Matches the SM-G935F closed cases CC-2649, CC-2971, CC-2985, CC-3035 | 14–28 |
| Shared rare device with 2 other customers (R6) | | 7 |
| Same-day-of-month recurring amount (R7 dispute) | | 0.3 |

**Fraud episodes.** Consecutive transactions on the same account are at most 48 hours apart in 99% of confirmed cases, and a gap over 48 hours starts a new case. The episode builder uses this chain.
