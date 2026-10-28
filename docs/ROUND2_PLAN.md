# FraudLens: TigerGraph Final Round plan

Brief: https://hhgoa-tg-round2.vercel.app/ · Dataset: the Google Drive folder linked from the brief · Contact: Devanshu (TigerGraph DevRel)

**Owner:** Samarth, full-time apart from the main HHGoa build's checkpoints. This repo is separate from the HHGoa consumer app ("Check Before You Pay"). Don't share code or config between the two: their failure rules are opposites.

## What wins this round

- **The field:** 6 teams (picked from 215 in Round 1), 18 hidden cases (HHF-001 to HHF-018), 100 points.
- **Prizes:** ₹20,000, ₹15,000 and ₹10,000 for the top 3.
- **Points:** innovation 25 · harness and drills 20 · answers 15 · evidence and policy 10 · use of TigerGraph 10 · engineering 10 · demo 10.
- **9 of the 18 cases are legitimate.** BLOCK_CARD, BLOCK_ALL_CARDS or FILE_REPORT on a legitimate case scores **zero** for that case. Answering "uncertain" and escalating is a correct answer under R1 and R8. Being unsure is free.
- **A claim without attestation counts as wrong.** Attestation means: the claim, the evidence IDs, the query and its parameters, and a timestamp. The judges re-run the query.
- **Any failed gate rules us out:** disallowed data, undeclared data egress, or an unreproducible run.
- **The schedule** (freeze, Stage 1, demo order) is "confirmed on the day". Ask Devanshu today.

## Status: overnight, 29 Oct

| Status | What |
|---|---|
| **Done** (offline mirror) | Gaps 1-8 below; challenges 1, 6 (step-by-step replay, `eval/replay.py`), 7 and 10; the data-quality case (HHF-011) |
| **Done** | Grader 18/18 clean; 159 tests; one-command drills (`eval/drills.py`, 13/13 pass); attack suite (14 attacks, 0 decisions changed); attestation check (77/77, 0 mismatches); ablation; resilience statement; innovation claim; three independent reviews, every finding fixed |
| **Left** (needs TigerGraph) | Everything in [MORNING_RUNBOOK.md](MORNING_RUNBOOK.md) |

TigerGraph Savanna was stopped all night ("Auto start is not enabled for this workspace").

## Gaps in the Round 1 code against the new rules (fix these first)

| # | Where | Problem | Fix |
|---|---|---|---|
| 1 | `api/main.py` `/api/approvals` | The approver's role comes from the request body (`Decision.role`). The brief says that is not enforcement. Approvals are overwritten in a JSON file, so they can be edited. A failed graph update still returns `ok: true` | Server-side auth: a token maps to a role, checked by the backend. Append-only approval log, one decision per action. Return an error, not `ok`, when the write fails |
| 2 | `agent/graph_client.py` | A failed MCP call silently retries over REST. That bypasses the least-privilege allowlist and is logged only with `print` | In official mode, fail closed: stop, report, and write an audit entry. If REST stays as an option at all, it must be declared and switched on explicitly |
| 3 | `api/main.py` `graph()` | When `TG_HOST` is missing, the app silently switches to the DuckDB mirror | Official mode refuses to start without TigerGraph. The mirror is allowed only with an explicit `--mirror` flag, and its output is labelled not official |
| 4 | `agent/workflow.py` `_fallback_texts` | When the LLM fails, template texts produce an answer that looks complete | Mark the case incomplete ("model unavailable"), recommend ESCALATE_TO_ANALYST, and never present a SAR narrative as drafted |
| 5 | `agent/roles.py:47,76` | `trigger_text` goes into prompts raw. Six cases carry hostile text | Fence all free text as untrusted data. Add an injection test suite (challenge 10). Decisions stay in code |
| 6 | `agent/llm.py` | 150 s timeouts | Bound each call, add one retry, then fail closed with a clear error |
| 7 | Data | November–December only | Load January and the replaced `closed_cases_history.csv` (5,585 cases, which now include our HHG-001 to HHG-020 as CC-xxxx). Re-score `model_p` for January without look-ahead. The bank's `risk_score` is near useless in January |
| 8 | Calibration | Round 1 answers were mostly p = 0.05 or 0.97 | Probabilities are scored for calibration. Add a real `uncertain` path for conflicting evidence (R1, R8), and R9 wording for undocumented patterns |

## Policy points that decided Round 1

- **R1 vs R2.** One weak signal, such as a risk score alone: verify before you block. The customer has already denied the charge: block and open a case, with no verification step. Mixing them up costs points either way.
- **§3a SAR.** A report is required when fraud is confirmed or strongly suspected **and** any one of these holds:
  - exposure is over $1,000;
  - there's a connection to a shared device profile, a region cluster or another customer's fraud;
  - the pattern is coordinated or undocumented.

  **A $23 loss that connects to other cards still needs a report.**
- **No tip-off.** Nothing a customer can see may hint at a SAR, including `evidence_requests` text. Add a lint check for it.
- **BLOCK_ALL_CARDS only when R10 allows it.**

## Challenges: go deep on two

1. **Challenge 10, "Break the agent" (Hard).** Build reproducible attacks: instructions hidden in `trigger_text` and analyst notes, signals designed to mislead, activity shaped to look innocent. Then the defences, with before-and-after wrong-verdict counts. It strengthens the drills (20 points) and answer quality at the same time.
2. **Challenge 7, "Containment planner" (Hard).** Given a ring from our existing WCC ring components, find the smallest set of cards to block that cuts the most exposure, and name every legitimate customer that action touches. It's a graph algorithm that changes the output (counts under TigerGraph use) and it has clear value to a bank.
   - **Innovation claim:** "Blocking N cards instead of M stops X% of the exposure and touches 0 legitimate customers." Measure it on the rings in the closed cases, with an ablation against blocking every card.

Stretch, only if time is left: challenge 6 (audit replay). It's cheap if the traces already record every tool call, and it helps the audit-trail drill.

## Order of work

1. Get the dataset and Savanna credits (send Devanshu the org ID). Load January, re-score, re-run the backtest.
2. Run all 18 cases and run `grader/grade.py`. Read every hard and policy finding.
3. Fix gaps 1 to 6, and add tests for them: wrong-role approval, graph down mid-run, a model timeout, garbage model output, the same case run twice.
4. Challenge 10, then challenge 7.
5. Write the deliverables:
   - the one-command runner, e.g. `python run_cases.py HHF-007`, tested from a clean clone;
   - a one-page resilience statement covering every dependency, what data Gemini on Vertex sees, what happens when each one fails, and what gets logged;
   - the innovation claim;
   - README numbers that match a live run.
6. Freeze: give them the commit hash and the 18 answer files. Rehearse the 5-minute demo on a case picked at random, and prepare an answer about our weakest point.

## Questions for Devanshu

- What time are the freeze, Stage 1 and the demo slots?
- Is continuing the Round 1 repo fine? (The brief implies it is.)
- Do the drills run on our machine, or do they need our deployed endpoint and credentials?
- Which model providers are allowed, and is Vertex AI fine if we declare it?
