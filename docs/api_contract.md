# Command Center API contract (FastAPI, served on http://localhost:8000)

All JSON. The React app is built into `api/static/` and served by the same FastAPI process at `/`.
During development the Vite dev server proxies `/api` to `http://localhost:8000`.

## Endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/api/health` | `{ "graph": "TigerGraph Savanna" or "offline mirror", "host": str, "graph_name": "Fraud", "mcp": bool, "llm": str }` |
| GET | `/api/cases` | `[CaseRow]`: the 20 benchmark cases + ad-hoc/autonomous cases, sorted by `opened_at` |
| GET | `/api/cases/{case_id}` | `{ "row": CaseRow, "answer": Answer or null, "trace": Trace or null }` |
| GET | `/api/cases/{case_id}/run` | **Server-Sent Events** stream of `Event`s while the agent investigates live; ends with an `event: done` |
| POST | `/api/investigate` | body `{ "txn_id": str, "note": str }` creates an analyst-request case; returns `CaseRow` (then open `/run`) |
| GET | `/api/approvals` | `[Approval]`: every L1/L2 action awaiting a human |
| POST | `/api/approvals/{action_id}` | body `{ "approve": bool, "role": "team_lead" or "fraud_manager" }` returns `{ ok, status, error? }` (403-style `ok:false` when the role may not approve that route) |
| POST | `/api/reprove` | body `{ "ref": "query:card_window(card=..., start_ts=..., end_ts=...)" }` re-runs that installed GSQL query live; returns `{ ok, query, params, rows, ms, via, sample: [..first 8 rows..] }` |
| GET | `/api/graph/{case_id}` | `{ nodes: [GNode], edges: [GEdge] }` neighbourhood for Cytoscape |
| GET | `/api/metrics` | backtest + portfolio metrics (see below) |

### CaseRow
```json
{ "case_id": "HHG-014", "opened_at": "2016-11-22 20:11:00", "trigger_type": "risk_score|customer_report|analyst_request|autonomous",
  "trigger_text": "...", "flagged_txn_id": "3478561", "card_id": "C13487-K1", "customer_id": "C13487", "risk_score": "0.61" or "",
  "status": "open|closed_fraud|closed_legitimate|escalated|new", "verdict": "fraud|legitimate|uncertain|null",
  "fraud_probability": 0.97, "pattern": "undocumented", "exposure_usd": 187.33, "sar": true, "source": "benchmark|analyst|autonomous" }
```

### Answer
Exactly the README answer format (see `cases/HHG-014.json` for a real example). Key paths:
`case.status, case.verdict, case.fraud_probability, case.pattern, case.pattern_description, case.affected_txn_ids,
case.connected_card_ids, case.connected_device_profiles, case.exposure_usd, case.evidence[{claim, source, ref, entity_ids}],
case.similar_prior_cases, case.summary, case.written_to_graph, case.graph_case_id, evidence_requests[{type, asked_after_step, assumed_response}],
next_best_actions.initial[{action, route, reason}], next_best_actions.final[...], next_best_actions.what_changed,
sar{file, reason, narrative, subjects, total_amount_usd, activity_dates}, stop_reason, tool_calls, tokens, latency_s`.

### Trace (saved run, `runs/traces/{case_id}.json`, see `runs/traces/HHG-014.json`)
```json
{ "case_id": "...", "events": [Event...], "tool_calls": [{ "agent", "tool", "query", "ref", "rows", "ms", "via" }],
  "specialists": { "transaction|identity|network|precedent": { "assessment", "risk", "key_points": [], "open_questions": [] } },
  "lead": { "hypotheses": [], "extra_calls": [{ "tool", "why", ...}], "focus": "" },
  "critic": { "agree": bool, "issues": [], "what_would_change_verdict": "" }, "problems": [], "written": {...} }
```

### Event (SSE `data:` JSON; `kind` is also sent as the SSE `event:` name)
| kind | fields |
|---|---|
| `trigger` | case_id, trigger_type, text, opened_at |
| `stage` | stage (gather/specialists/...), agent, msg |
| `tool_call` | agent (lead/transaction/identity/network/precedent), tool, query, ref, rows, ms, via ("mcp"/"rest"/"mirror") |
| `plan` | agent="lead", hypotheses[], calls[{tool, why}] |
| `specialist` | agent, risk (low/medium/high), assessment, key_points[] |
| `finding` | key, claim, lr (likelihood ratio, >1 pushes toward fraud), family, ref, entity_ids[] |
| `assessment` | p (initial probability), prior, verdict, pattern, contributions[{key, family, lr, delta_logodds}], exposure, initial[actions], branches{confirm,deny,no_reply: [actions]} |
| `evidence_request` | type, branch (confirm/deny/no_reply), assumed_response, asked_after_step |
| `decision` | verdict, p, pattern, final[actions], status, exposure, episode[txn ids] |
| `memory` | agent="precedent", similar[CC ids], knowledge[section titles] |
| `review` | agent="compliance", agree, issues[], what_would_change_verdict |
| `warning` | msg |
| `final` | answer (Answer), problems[], written{ok, graph_case_id, n_vertices, n_edges} |
| `done` | (no fields) |

### Approval
```json
{ "action_id": "CASE-2016-014-F1", "case_id": "HHG-014", "action": "BLOCK_CARD", "route": "L1|L2", "reason": "...",
  "status": "pending_approval_team_lead|pending_approval_fraud_manager|approved_by_team_lead|...", "exposure_usd": 187.33 }
```

### GNode / GEdge (Cytoscape elements)
```json
{ "id": "txn:3478561", "label": "$74.96 11-22", "type": "Transaction|Card|Customer|DeviceProfile|BillingRegion|ClosedCase|InvestigationCase|Account",
  "flagged": bool, "affected": bool, "fraud": bool, "ring": bool }
{ "source": "card:C13487-K1", "target": "txn:3478561", "type": "MADE|FROM_DEVICE|BILLED_IN|INVOLVES|CASE_CITES|ON_ACCOUNT|..." }
```

### Metrics
```json
{ "backtest": { "n_cases": int, "pattern_accuracy": float, "verdict_accuracy": float, "episode_jaccard": float,
                "exposure_mae": float, "sar_agreement": float, "brier": float,
                "reliability": [{ "bin": "0.0-0.1", "predicted": float, "observed": float, "n": int }] },
  "portfolio": { "verdicts": {"fraud": n, "legitimate": n, "uncertain": n}, "patterns": {..}, "sar_filed": n,
                 "total_exposure": float, "avg_tool_calls": float, "avg_tokens": float, "avg_latency_s": float },
  "rings": [{ "component": id, "members": [card ids], "devices": [..], "fraud_cases": [..] }] }
```
