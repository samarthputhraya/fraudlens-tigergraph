# Demo video script (target 4:15, record at 1920×1080, 125% zoom)

**Setup before recording**
- Have `uvicorn api.main:app --port 8000` running against TigerGraph Savanna, with the header pill showing "TigerGraph Savanna · MCP".
- Have the Savanna GraphStudio tab open on the Fraud graph.
- Pre-warm HHG-014 once, so that a live re-run is quick.
- Record the screen plus a voice-over. OBS or the Windows Game Bar (Win+Alt+R) both work. Use a clean browser profile, with no bookmarks bar.

| Time | Screen | Voice-over |
|---|---|---|
| 0:00–0:15 | Title card: FraudLens, "The model predicts. TigerGraph proves." | "Fraud analysts spend their day collecting evidence, not deciding. And in this bank's data, most high-score alerts are legitimate. FraudLens is a team of AI investigators on TigerGraph that closes that gap." |
| 0:15–0:40 | README architecture diagram (or the slide in docs) | "An alert comes in. A lead investigator and four specialist agents query TigerGraph through the official MCP server, with read-only access. Code, not the LLM, owns the numbers, the policy and the approvals. A compliance agent red-teams every decision before it's written back to the graph as case memory." |
| 0:40–1:40 | **Alert Queue → HHG-014 → Investigate live.** Timeline streams on the left: GSQL tool calls tagged "via MCP"; specialists appear. The graph canvas grows; ring cards glow red. | "Here's an analyst request: several cards show purchases from the same unusual device. Watch the Network analyst ask TigerGraph who else used this device profile. Nineteen other cardholders in eight days, the device new to every account, all behind an anonymous proxy. The Precedent analyst's graph-filtered vector search finds four closed cases from August with the same device. None of the five known patterns fits, so the agent names it: a shared-device ring." |
| 1:40–2:10 | Right column: probability gauge and evidence waterfall, then the stop-rule indicator lights at ≥ 0.85. | "Each finding carries a likelihood ratio measured on 400,000 transactions. The ledger reaches 0.97 on independent evidence, which meets policy section 6, so the agent stops investigating and acts." |
| 2:10–2:40 | NBA panel: BLOCK_CARD (L1), FILE_REPORT (L2), MONITOR_CONNECTED_CARDS, ESCALATE, each with its rule cited. Open **Case File**, click **Re-prove** on the device evidence and show the live rows and milliseconds. | "Every recommendation cites its rule and every claim cites a query. Click re-prove, and the claim is re-run live on TigerGraph Savanna. Nothing is taken on faith." |
| 2:40–3:10 | Open **HHG-010**: initial VERIFY/STEP_UP, then the simulated no-reply, then the final MONITOR + DECLINE + ESCALATE. Show the branch tree (confirm / deny / no-reply). | "Uncertain alerts are where it matters. $1,000.03 from a new device: one weak signal, so R1 says verify before blocking. The agent computes every branch. If the customer confirms, it closes. If they deny, it blocks and files a report, because the amount is over $1,000. If there's no reply, it declines and escalates under R4. The recommendation changes as the evidence comes in." |
| 3:10–3:35 | **Approval Inbox**: switch the role to Team Lead, try to approve FILE_REPORT and get refused; switch to Fraud Manager and approve. Then GraphStudio shows the InvestigationCase vertex and its ActionRecord. | "The agent can only execute auto actions. A team lead can't approve a suspicious activity report; only a fraud manager can. Every decision lands in the graph, so the next investigation remembers it." |
| 3:35–4:00 | **Insights**: backtest tiles and the rings list; then `cases_autonomous/`. | "We backtested on the bank's closed cases, with no look-ahead. Episode reconstruction scores 0.82 Jaccard. And with no alert at all, the monitor found more sub-threshold structuring rings in November and December." |
| 4:00–4:15 | Closing card: the GitHub, blog and @TigerGraphDB handles | "FraudLens: agentic, calibrated and provable, built on TigerGraph. The model predicts; TigerGraph proves." |

**Tips**
- Speak slowly. If a live run lags, cut to the pre-recorded replay of the same case (it's identical data).
- Keep the cursor still while the graph animates.
- Upload to YouTube as unlisted and put the link in the README, the blog and the form.
