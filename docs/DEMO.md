# The 5-minute demo

**Format** (from the brief): a fraud analyst picks the case, and we learn which one when our slot starts. We show our innovation on that live case, then take questions, including one about our weakest point.

**Setup before the slot:**
- Start the Command Center: `uvicorn api.main:app --port 8000`, with TigerGraph live.
- Have a terminal open in the repo.
- Have [docs/INNOVATION.md](INNOVATION.md) open in a tab.

## Running order

| Time | What we do | What we say |
|---|---|---|
| 0:00-0:20 | — | "Round 1 asked whether the agent can investigate. This round asks whether a bank can run it. Every number, verdict, route and action FraudLens produces comes from code reading TigerGraph. The model only plans queries and writes the text." |
| 0:20-2:20 | Run the chosen case live: Command Center → the case → **Live**, or `python run_cases.py <case>`. Follow the trace as it streams. | Use the per-case lines below. |
| 2:20-3:30 | Open the answer file: verdict, evidence (each item with its query reference), actions with routes. Click **re-prove** on one evidence line. | "Every claim cites only IDs its own query returns. We re-ran all of them: all 77 reproduce." |
| 3:30-4:15 | Drill: `FRAUDLENS_FAULT=graph:card_window python run_cases.py <case>` | "The graph fails mid-run. The case stops, no answer is written, the old one is moved aside, and the failure is in the hash-chained audit log. Exit status 2." |
| 4:15-5:00 | Innovation slide (INNOVATION.md, ablation table) | "Both scores are blind in January. Our typology detectors and drift-aware weighting catch all 7 frauds and file 6 reports. Switch them off and we miss 4 and file none. On July to October they never touched a cleared case." |

## What to show for each case

| Case | Verdict | The line to say | The thing to point at |
|---|---|---|---|
| HHF-001 | fraud, undocumented | "An Android tablet build reporting Windows 7 and Windows 10: no real device does that." | `spoofed_device` evidence, then the R9 report and escalation |
| HHF-002 | fraud, undocumented | "A Samsung handset claiming iOS. Five cards show the same impossible fingerprint." | ring evidence and the containment plan: block all 5, 100% of $7.6K |
| HHF-003 | fraud, undocumented | "$181 → $358 → $812 → $1,800, then $1,800 three more times. Someone was finding the card's limit." | `escalating_ramp`; L2 block because exposure is over $2,500 |
| HHF-004/005 | fraud, undocumented | "Six charges of a few dollars across three weeks. The alert text tried to make us close it. It was recorded and ignored." | `micro_run`; `hostile_text` evidence; the plan blocks 1 card and monitors 18 |
| HHF-006 | fraud, undocumented, R6 | "17 cards paid sc.rr.com this month, against 2 in a usual month. Policy R6 names the shared recipient." | `recipient_surge`; report under R6; 16 of 17 cards to block |
| HHF-007 | fraud, card testing | "Four sub-$5 authorisations in 27 minutes, then $236. Textbook R5, and the customer denied it (R2)." | card-testing evidence; L1 block |
| HHF-008 | legitimate | "The alert says online at 0.81. The bank's record says in-person at 0.11. The text also told us to close it, and we'd have closed it anyway, on the evidence." | `trigger_mismatch`, `hostile_text` |
| HHF-009/012/014/015/017/018 | legitimate | "Known region or a recurring amount. The verification is simulated and stated as an assumption. Nothing blocks a legitimate customer." | the verification line in evidence_requests; ALLOW and CLOSE |
| HHF-010/016 | legitimate | "Text pushed us to skip the report or not escalate. It changed nothing; the evidence says legitimate." | `hostile_text` |
| HHF-011 | uncertain, escalated | "The case says card K1. The bank's own record and 21 closed cases say K2. We investigate K2, say so, and hand it to an analyst. We don't guess." | `card_record_mismatch`; R8 |
| HHF-013 | legitimate, escalated | "The flagged purchase is clean, but this card also paid sc.rr.com twice. Monitor the card, hand those charges to an analyst, and don't block over this purchase." | `card_other_typology` |

## Questions to prepare for

- **Weakest point?**
  - The typology thresholds come from July–December background. Spoofed fingerprints and recipient surges never fired on a legitimate customer.
  - Micro-charge runs and ramps are confirmed only about 1 time in 3. So we act on them for the case card, but only monitor the other cards in those rings.
  - The model's calibration is fitted on the July–September model and applied to July–October.
- **What's simulated?** Customer and analyst replies. The brief says so, and each answer states its assumption. Everything else comes from TigerGraph.
- **What if the model is wrong or down?** It never decides. If it fails or writes nonsense, the decision stands, the answer is marked incomplete and escalated, and template text is labelled.
- **How would someone game it?**
  - Text instructions don't work: 14 attacks changed 0 decisions.
  - Faking a score doesn't work, because the record wins.
  - To beat a typology you'd have to stop showing its shape. A ring spread thinner still shows up in the ring scan.
- **Why TigerGraph?**
  - Ring scans across cards, recipient reach over time, device fingerprints across transactions;
  - TigerVector case memory;
  - WCC ring components;
  - case write-back;
  - MCP with a read-only allowlist.
