# FraudLens resilience statement (one page)

TigerGraph × Hacker House Goa 2026, Final Round. Full detail, every drill command and the log formats:
[RESILIENCE_DETAIL.md](RESILIENCE_DETAIL.md).

**The rule:** if a dependency fails, the case stops or is marked incomplete. FraudLens never presents a guess, a
template or a save that didn't happen as a complete answer. Decisions are code; the model only plans queries and writes text.

## Dependencies and what leaves the bank

| Dependency | Used for | Access |
|---|---|---|
| **TigerGraph Savanna** | All evidence: 20 installed GSQL queries, vectorSearch over case memory, ring components; case memory written back | Reads only through the **TigerGraph MCP server**, with a read-only allowlist of 12 tools. Writes only through `agent/case_writer.py` |
| **Gemini on Vertex AI** | Planner, 4 specialists, compliance critic, writer, embeddings | Google Cloud service identity; no API key in the repo |

**Sent to Gemini:** the alert text (fenced, instruction spans removed), the flagged transaction and graph evidence by
pseudonymous ID, aggregates, and the decision draft. **Never sent:** names, card numbers, addresses or credentials (the
dataset holds none). The offline DuckDB mirror is used only with `--mirror`, and its answers say `"official": false`.

## When each part fails

| Failure | What happens | Exit |
|---|---|---|
| TigerGraph or MCP unreachable at start | Nothing is investigated. No switch to REST or the mirror | 2 |
| A query fails mid-case | That case stops, no answer is written, an older answer moves to `stale/`, a FAILED record is kept | 2 |
| Graph write-back fails | `written_to_graph: false`, answer marked incomplete and escalated | 3 |
| A model call times out or returns garbage | One retry, then the code's decision stands; text is labelled template, the case is escalated (R8) | 3 |
| Writer text cites unknown IDs or contradicts the decision | Rejected; same as above | 3 |
| Missing transaction, malformed row, case opened before its transaction | Stops as invalid input; nothing invented | 2 |
| Case record and bank record disagree | Reads the bank's record, records the discrepancy, `uncertain` + ESCALATE_TO_ANALYST, never blocks | 0 |
| Hostile free text | Instructions recorded and removed; decisions never read the text. 14 attacks: 0 decisions changed | 0 |
| Wrong approver role / double decision | The server maps the token to a role: 403. A second decision on one action: 409 | n/a |

## Controls and logs

- **Audit log:** append-only, hash-chained and HMAC-keyed, anchored by `runs/audit/audit.head` in the freeze commit.
  `GET /api/audit/verify` detects edits, forgeries, truncation and deletion; approvals stop (503) while it fails.
- **Traces:** every tool call with parameters, row count, latency and path (MCP or REST), per case. Secrets, tokens and
  the Savanna host are redacted.
- **Least privilege:** the agent can't write to the graph, and the model has no direct query access.
- **Case-book gate:** `python eval/casebook.py` fails the freeze if a card is cleared in one case and reported in another.

## Proof

`python eval/drills.py --official` causes every failure above for real and checks the outcome against this page:
**13 of 13 pass** (30 Oct, after the official run). Tests: 187 pass.
