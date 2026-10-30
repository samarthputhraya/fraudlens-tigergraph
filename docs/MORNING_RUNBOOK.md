# Morning runbook: from "Savanna is back" to a frozen commit

Everything below was prepared overnight on the offline mirror. **TigerGraph Savanna was stopped all night**: it answered "Auto start is not enabled for this workspace". So the only steps left need the live graph. Run them in order from the repo root on the `round2` branch. Allow about 60–90 minutes, most of it loading and query installs.

## 0. Before you start (humans only)

1. **Resume the Savanna workspace.** In the TigerGraph Cloud console, open the workspace and click Resume. Turn on auto-start, so it can't stop again mid-drill.
2. **If the credits ran out,** send your Savanna org ID to Devanshu (TigerGraph DevRel), who offered to add credits.
3. **Add to `.env`** (never commit it):
   ```
   FRAUDLENS_APPROVER_TOKENS=team_lead:<random 24+ chars>,fraud_manager:<random 24+ chars>
   FRAUDLENS_AUDIT_KEY=<random 32+ chars>
   ```
   Tonight's audit log was written without a key. The first entry written after you set it archives that log as `runs/audit/audit.unkeyed-<time>.jsonl` (its hash is recorded) and starts a keyed chain, so `/api/audit/verify` passes from then on. Until the first case runs, it reports the old log as unkeyed: that is expected.
4. **Ask Devanshu:**
   - When are the freeze, Stage 1 and the demo slots?
   - Do the drills run on our laptop or against a deployed endpoint?
   - Is Vertex AI acceptable as the declared model provider?

## 1. Check the connection

```bash
.venv/Scripts/python eval/preflight.py --live
.venv/Scripts/python graph/setup.py stats
```
- **Preflight** checks `.env` (without printing any secret), the data files, the git branch, TigerGraph and one tiny Gemini call. Fix every FAIL before going on. At 04:00 the only FAILs were the two approver tokens, the audit key and TigerGraph itself, all expected.
- **`stats`** should print vertex and edge counts. If it says the workspace isn't running, step 0.1 didn't take.

## 2. Load January (the delta is already exported)

```bash
.venv/Scripts/python graph/setup.py load
```
- This loads `data/prep/load_r2/`: 60,196 January transactions, their edges, the cards and accounts whose totals changed, and all 5,585 closed cases (the history was replaced).
- It is resumable. Progress is kept in `data/prep/loaded_r2.json`.
- To regenerate the CSVs: `.venv/Scripts/python graph/prep.py && .venv/Scripts/python graph/export.py --since 2017-01-01`.
- **If it stops with "The job load_transactions is disabled"** (this happened on 29 Oct): adding `model_p` in Round 1 switched that job off. Drop it and recreate it from `graph/loading_jobs_positional.gsql`, which already has the trailing `_` for `model_p`, then rerun `load`. It resumes where it stopped.

## 3. Install the new and changed queries

```bash
.venv/Scripts/python graph/setup.py queries 03_card_profile 19_typology_scan 20_recipient_activity
.venv/Scripts/python graph/setup.py describe
```
- **New tonight:** `19_typology_scan` and `20_recipient_activity`.
- **Changed tonight:** `03_card_profile` now also prints the card it describes, so attested claims can cite it.
- These three were written tonight and **have not compiled on TigerGraph yet**. If GSQL rejects a line, fix it, then rerun this step. Step 5 checks that their output matches the mirror.

## 4. Model scores and case-memory embeddings

```bash
.venv/Scripts/python graph/setup.py scores    # model_p for Oct-Jan from data/prep/model_scores_r2.parquet
.venv/Scripts/python graph/setup.py vectors   # closed-case embeddings incl. the 20 new cases (closed_emb_r2.json)
```
Keep the Round 1 `InvestigationCase` memory; **don't run `reset_memory`**. The brief treats Round 1 cases as real precedent.

## 5. Check TigerGraph against the mirror

```bash
.venv/Scripts/python eval/parity.py
```
- **Expected:** `18/18 cases identical`. The comparison now includes the 30-day window, the micro-charge baseline, recipient reach and the typology scan sizes.
- **Any DIFF** points at a query or loading problem. Fix it before the official run.

## 6. The official run

```bash
.venv/Scripts/python run_cases.py                 # writes cases_r2/*.json, runs/traces/*, audit entries; case memory to TigerGraph
```
- **Expected verdicts** (mirror run of 30 Oct, `runs/dev_all/`):
  - fraud: HHF-001 to HHF-007
  - uncertain, at 0.5: HHF-011 (the records disagree) and HHF-013 (a clean purchase on a card in the sc.rr.com ring)
  - legitimate: the other 9
- **Exit code:**
  - 0: all answers complete;
  - 3: a model step failed, so read the INCOMPLETE lines and rerun those cases;
  - 2: a case stopped, so read its `runs/traces/<case>.FAILED.*.json`.

## 7. Grade, attest, attack

```bash
mkdir -p runs/grade/official/fraudlens && cp cases_r2/HHF-*.json runs/grade/official/fraudlens/
.venv/Scripts/python data/raw_r2/share/grader/grade.py --teams-dir runs/grade/official --case-pack data/raw_r2/share/cases/case_pack_final.csv --transactions data/raw_r2/share/transactions_2017q1.csv --out runs/grade/official.json
.venv/Scripts/python eval/attest_check.py cases_r2 --graph
.venv/Scripts/python eval/casebook.py              # no card cleared in one case and reported in another (exit 1 if so)
.venv/Scripts/python eval/attack_suite.py
.venv/Scripts/python eval/drills.py --official
.venv/Scripts/python -m pytest tests -q
```
**Expected:**
- grader: 18/18 clean, 0 hard, 0 policy;
- attestation: 0 mismatched;
- attacks: 0 decisions changed;
- drills: all pass (13 with `--official`);
- every test passes.

## 8. Freeze

```bash
git add cases_r2/HHF-0[01][0-9].json docs eval agent api graph ml rag tests run_cases.py README.md
git add runs/traces/HHF-0[01][0-9].json    # the official traces; not the FAILED records
git add -f runs/audit/audit.head            # anchors the audit chain (count + last hash) in git history
git commit -m "Final Round freeze: official answers from TigerGraph"
git rev-parse HEAD      # the hash you hand in
git push origin round2
```
**Hand in:**
- the commit hash;
- `cases_r2/*.json` (18 files);
- the one-command runner (`python run_cases.py HHF-007`);
- `docs/RESILIENCE.md`;
- `docs/INNOVATION.md`.

## 9. The 5-minute demo (the judges pick the case)

1. Run the case live: `python run_cases.py <case>`, or click Run in the Command Center (`uvicorn api.main:app --port 8000`).
2. Walk through the trace: the alert → the evidence queries → the finding that decided it → the policy rule → the actions and their routes.
3. Show one drill live: `FRAUDLENS_FAULT=graph:card_window python run_cases.py <case> --out runs/drills --no-write` gives STOPPED and exit 2. Never drop `--out`: without it the drill moves the official answer into `cases_r2/stale/`. If they ask for more, `python eval/drills.py` runs all 12 in about 80 seconds.
4. **Weakest point, said plainly:**
   - The typology thresholds were set from July–December background. Spoofed fingerprints and recipient surges are clean, but micro-charge runs and ramps are only about 1 in 3 confirmed there, so we monitor ring members rather than block them.
   - The isotonic calibration is fitted on the July–September model and applied to the July–October one.
