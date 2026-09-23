"""LangGraph orchestration of the virtual fraud team.

intake -> gather (core toolkit on TigerGraph) -> lead_plan (LLM picks extra graph queries) -> specialists (4 in
parallel) -> decide (detectors, calibrated ledger, policy engine, simulated evidence request) -> recall (hybrid
GraphRAG: case memory + policy/FinCEN knowledge) -> review (compliance red-team) -> write (summary + SAR) ->
finalize (assemble, validate, write case memory to TigerGraph).
"""
from __future__ import annotations

import json
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from agent import roles
from agent.answer import build_answer, similar_prior_cases, validate
from agent.assess import ledger, pattern_of, verdict_of
from agent.core import REPLY_TEXT, amount_of, choose_reply, situation
from agent.detectors import run_detectors
from agent.evidence import P, gather, recall
from agent.llm import Usage
from agent.policy import plan, status_of

ROOT = Path(__file__).resolve().parents[1]
PATTERN_QUERY = {
    "undocumented": "coordinated fraud not matching a documented typology, several cardholders, same device or purchases just under a threshold",
    "card_testing": "run of very small online authorizations followed by a larger purchase, testing a stolen card number",
    "card_not_present_fraud": "online purchases inconsistent with the cardholder's usual merchants and amounts",
    "card_not_present_new_device": "online purchases from a device not previously seen on this account",
    "out_of_region_use": "card-present use in a billing region the cardholder had no history in",
    "account_takeover": "mixed-channel activity inconsistent with the cardholder; credentials and card data both used",
    "none": "model scored transaction; cardholder confirmed the purchase; alert cleared",
}


class State(TypedDict, total=False):
    case: dict
    ep: Any
    first_findings: list
    lead: dict
    specialists: dict
    result: dict
    critic: dict
    texts: dict
    answer: dict
    problems: list
    written: dict
    t0: float
    calls0: int


class Investigator:
    def __init__(self, g: Any, emit: Callable[[str, dict], None] | None = None, write_graph: bool = True,
                 use_llm: bool = True) -> None:
        self.g = g
        self.emit = emit or (lambda k, d: None)
        self.write_graph = write_graph
        self.use_llm = use_llm
        self.app = self._build()

    # ------------------------------------------------------------------ nodes
    def intake(self, s: State) -> State:
        Usage.reset()
        c = s["case"]
        self.emit("trigger", {"case_id": c["case_id"], "trigger_type": c["trigger_type"], "text": c["trigger_text"],
                              "opened_at": c["opened_at"]})
        return {"t0": time.time(), "calls0": len(self.g.trace.calls)}

    def gather(self, s: State) -> State:
        self.emit("stage", {"stage": "gather", "agent": "lead",
                            "msg": "Core toolkit: flagged transaction, card window, card baseline, recurring charges, resolved "
                                   "account history, device neighbours, region activity and prior cases"})
        names = {"context": "lead", "window": "transaction", "profile": "transaction", "recurring": "transaction",
                 "account": "identity", "device": "network", "region": "network", "prior": "precedent"}
        ep = gather(s["case"], self.g, names)
        findings, _ = run_detectors(ep)
        first = [{"key": f.key, "claim": f.claim[:220], "lr": f.lr} for f in findings]
        return {"ep": ep, "first_findings": first}

    def lead_plan(self, s: State) -> State:
        if not self.use_llm:
            return {"lead": {"hypotheses": [], "extra_calls": [], "focus": ""}}
        ep = s["ep"]
        t = {k: ep.txn.get(k) for k in ("id", "ts", "amt", "product", "channel", "addr1", "risk_score", "device", "is_new", "proxy", "p_email", "r_email")}
        if not hasattr(self, "_catalog"):
            try:
                self._catalog = self.g.describe_queries(agent="lead")
            except Exception:  # noqa: BLE001
                self._catalog = {}
        try:
            lead = roles.lead_plan(s["case"], t, s["first_findings"], self._catalog)
        except Exception as e:  # noqa: BLE001
            lead = {"hypotheses": [], "extra_calls": [], "focus": f"(planner unavailable: {e})"}
        self.emit("plan", {"agent": "lead", "hypotheses": lead.get("hypotheses", []), "calls": lead.get("extra_calls", [])})
        ts, opened = ep.ts, ep.opened_at
        for call in (lead.get("extra_calls") or [])[:3]:
            tool = call.get("tool")
            try:
                if tool == "device_neighbors" and ep.txn.get("device"):
                    days = max(7, min(120, int(call.get("days_back") or 60)))
                    ep.extra["device_wide"] = self.g.device_neighbors(ep.txn["device"], ts - timedelta(days=days), opened, agent="network")
                elif tool == "card_window":
                    days = max(7, min(90, int(call.get("days_back") or 45)))
                    ep.extra["card_window_wide"] = self.g.card_window(ep.case["card_id"], ts - timedelta(days=days), opened, agent="transaction")
                elif tool == "region_activity" and ep.txn.get("addr1"):
                    days = max(1, min(14, int(call.get("days_back") or 7)))
                    ep.extra["region_wide"] = self.g.region_activity(ep.txn["addr1"], ts - timedelta(days=days), opened, 50, agent="network")
                elif tool == "similar_cases_by_pattern":
                    pat = call.get("pattern") or "none"
                    if pat in PATTERN_QUERY:
                        from agent.llm import embed_query
                        ep.extra[f"similar_{pat}"] = self.g.similar_cases(embed_query(PATTERN_QUERY[pat]), [], [ep.case["card_id"]], 5, pat, agent="precedent")
                elif tool == "recurring_match":
                    tol = max(0.5, min(5.0, float(call.get("tol_pct") or 2))) / 100 * float(ep.txn["amt"])
                    ep.extra["recurring_wide"] = self.g.recurring_match(ep.case["card_id"], float(ep.txn["amt"]), round(tol, 2), ts, agent="transaction")
            except Exception as e:  # noqa: BLE001
                self.emit("warning", {"msg": f"extra call {tool} failed: {e}"})
        return {"lead": lead}

    def specialists(self, s: State) -> State:
        if not self.use_llm:
            return {"specialists": {}}
        ep = s["ep"]
        hist = ep.account.get("history", [])
        near = [w for w in ep.window if abs((P(w["ts"]) - ep.ts).total_seconds()) <= 72 * 3600]
        slices = {
            "transaction": {"flagged": ep.txn, "window_72h": near[:40],
                            "baseline": {k: ep.profile.get(k) for k in ("n_txn", "n_recent", "n_online", "amt_max", "product_n", "channel_n")},
                            "recurring_matches": ep.recurring[-8:], "wider_window": (ep.extra.get("card_window_wide") or [])[-30:]},
            "identity": {"flagged_device": {k: ep.txn.get(k) for k in ("device", "is_new", "proxy", "id_34", "device_type", "m4", "m6", "m123")},
                         "device_seen_on_card": ep.profile.get("device_n", {}).get(ep.txn.get("device", ""), 0),
                         "account": ep.account.get("account"), "account_history_last": hist[-15:]},
            "network": {"device_neighbors": {"n_cards_all_time": (ep.device or {}).get("n_cards_all_time"),
                                             "txns": ((ep.device or {}).get("txns") or [])[-30:]},
                        "device_wide": ((ep.extra.get("device_wide") or {}).get("txns") or [])[-30:],
                        "region": ep.region or ep.extra.get("region_wide") or {},
                        "connected_cases": (ep.prior or {}).get("connected_cases", [])},
            "precedent": {"closed_cases_on_customer": (ep.prior or {}).get("closed_cases", [])[-12:],
                          "similar_by_pattern": {k: v for k, v in ep.extra.items() if k.startswith("similar_")}},
        }
        self.emit("stage", {"stage": "specialists", "agent": "lead", "msg": "Four specialist analysts reviewing their evidence in parallel"})
        out = roles.run_specialists(s["case"], slices)
        for n, o in out.items():
            self.emit("specialist", {"agent": n, "risk": o.get("risk"), "assessment": o.get("assessment"),
                                     "key_points": o.get("key_points", [])})
        return {"specialists": out}

    def decide(self, s: State) -> State:
        ep, case = s["ep"], s["case"]
        findings, facts = run_detectors(ep)
        for f in findings:
            self.emit("finding", {"key": f.key, "claim": f.claim, "lr": f.lr, "family": f.family, "ref": f.ref,
                                  "entity_ids": f.entity_ids[:8]})
        led = ledger(case["trigger_type"], findings, float(ep.txn.get("risk_score") or 0.5))
        verdict0 = verdict_of(led["p"], led, case["trigger_type"])
        pattern0, desc0 = pattern_of(verdict0 if verdict0 != "uncertain" else "fraud", facts, ep.txn)
        exposure0, dates0 = amount_of(ep, facts["episode"])
        sit = situation(ep, findings, facts, led, verdict0, pattern0, exposure0)
        pl = plan(sit)
        self.emit("assessment", {"p": led["p"], "prior": led["prior"], "verdict": verdict0, "pattern": pattern0,
                                 "contributions": led["contributions"], "exposure": exposure0,
                                 "initial": pl["initial"], "branches": pl.get("branches", {})})
        steps_so_far = len(self.g.trace.calls) - s["calls0"]
        reply, reqs, cust_ev = None, [], None
        final = pl["initial"]
        p_final, verdict, pattern, desc = led["p"], verdict0, pattern0, desc0
        if pl.get("evidence_request"):
            reply = choose_reply(sit)
            rtype, rtext = pl["evidence_request"]
            text = (rtext or (sit.legit_explanation[0].upper() + sit.legit_explanation[1:])) if reply == "confirm" else REPLY_TEXT[reply]
            reqs.append({"type": rtype, "asked_after_step": steps_so_far, "assumed_response": text})
            final = pl["branches"][reply]
            if reply == "confirm":
                p_final, verdict, pattern, desc = 0.05, "legitimate", "none", ""
            elif reply == "deny":
                p_final, verdict = round(min(0.97, max(0.88, led["p"] + 0.3)), 2), "fraud"
            else:
                verdict = "uncertain"
            cust_ev = {"claim": f"{'Step-up authentication' if rtype == 'step_up_auth' else 'Customer verification'} "
                                f"(simulated, assumption stated in evidence_requests): {text}",
                       "source": "customer", "ref": "evidence_request:1", "entity_ids": [ep.txn["id"]]}
            self.emit("evidence_request", {"type": rtype, "branch": reply, "assumed_response": text,
                                           "asked_after_step": steps_so_far})
        elif case["trigger_type"] == "customer_report":
            cust_ev = {"claim": f"The customer reported that they never made the ${float(ep.txn['amt']):,.2f} purchase "
                                f"({ep.txn['id']}); under R2 this is a denial", "source": "customer",
                       "ref": f"trigger:{case['case_id']}", "entity_ids": [ep.txn["id"]]}
            verdict = "fraud" if led["p"] >= 0.5 else "uncertain"
        if verdict == "legitimate":
            episode, exposure, dates = [], 0.0, []
        else:
            episode, exposure, dates = facts["episode"], exposure0, dates0
            if pattern == "none":
                pattern, desc = pattern_of("fraud", facts, ep.txn)
        res = {"ep": ep, "findings": findings, "facts": facts, "ledger": led, "situation": sit, "plan": pl, "reply": reply,
               "evidence_requests": reqs, "customer_evidence": cust_ev, "initial": pl["initial"], "final": final,
               "verdict": verdict, "verdict0": verdict0, "p_final": p_final, "pattern": pattern,
               "pattern_description": desc, "episode": episode, "exposure": exposure, "dates": dates,
               "status": status_of(final, verdict), "tool_calls": 0, "latency_s": 0.0}
        self.emit("decision", {"verdict": verdict, "p": p_final, "pattern": pattern, "final": final, "status": res["status"],
                               "exposure": exposure, "episode": episode})
        return {"result": res}

    def recall(self, s: State) -> State:
        r, ep = s["result"], s["ep"]
        hyp = PATTERN_QUERY.get(r["pattern"], "")
        devices = sorted(r["facts"].get("connected_devices") or ([] if not ep.txn.get("device") else [ep.txn["device"]]))
        recall(ep, self.g, hyp, devices[:3], [ep.case["card_id"]] + sorted(r["facts"].get("connected_cards") or [])[:10], "",
               agent="precedent")
        self.emit("memory", {"agent": "precedent", "similar": similar_prior_cases(r),
                             "knowledge": [c.get("section") for c in (ep.knowledge or {}).get("chunks", [])]})
        return {}

    def review(self, s: State) -> State:
        if not self.use_llm:
            return {"critic": {"agree": True, "issues": [], "what_would_change_verdict": ""}}
        r = s["result"]
        chunks = [c["body"] for c in (s["ep"].knowledge or {}).get("chunks", []) if "Policy" in c.get("source", "") or "Fraud Policy" in c.get("source", "")]
        from agent.rules_text import RULES_TEXT
        draft = self._draft(s)
        try:
            out = roles.critic(draft, [RULES_TEXT] + chunks[:3])
        except Exception as e:  # noqa: BLE001
            out = {"agree": True, "issues": [f"(reviewer unavailable: {e})"], "what_would_change_verdict": ""}
        self.emit("review", {"agent": "compliance", **out})
        return {"critic": out}

    def write(self, s: State) -> State:
        r, ep = s["result"], s["ep"]
        sar = any(a["action"] == "FILE_REPORT" for a in r["final"])
        want_desc = r["pattern"] == "undocumented"
        guidance = [c["body"] for c in (ep.knowledge or {}).get("chunks", [])][:4]
        draft = self._draft(s)
        texts = self._fallback_texts(s)
        if self.use_llm:
            try:
                out = roles.writer(draft, guidance, sar, want_desc)
                allowed = self._allowed_ids(s)
                for k in ("summary", "sar_narrative", "pattern_description"):
                    v = out.get(k)
                    if not v:
                        continue
                    bad = roles.unknown_ids(v, allowed)
                    contradiction = self._contradicts(v, r, sar, k)
                    if bad or contradiction:
                        self.emit("warning", {"msg": f"writer text '{k}' rejected ({'unknown IDs ' + ','.join(bad[:3]) if bad else contradiction}); kept template"})
                        continue
                    texts[k] = v
            except Exception as e:  # noqa: BLE001
                self.emit("warning", {"msg": f"writer unavailable: {e}"})
        if not r["evidence_requests"]:
            texts["what_changed"] = "nothing"
        return {"texts": texts}

    @staticmethod
    def _contradicts(text: str, r: dict, sar: bool, key: str) -> str:
        """Guard: narrative text must agree with the deterministic decision."""
        low = text.lower()
        final = {a["action"] for a in r["final"]}
        if key == "summary":
            if not sar and any(w in low for w in ("suspicious activity report", " sar ", "sar.", "file a report", "files a report", "filing a report", "file a sar", "will file")):
                return "mentions a SAR that is not being filed"
            if r["verdict"] == "legitimate" and any(w in low for w in ("confirmed fraud", "is fraud", "fraud ring", "account takeover", "block the card", "blocked")):
                return "describes fraud but the verdict is legitimate"
            if r["verdict"] == "fraud" and any(w in low for w in ("legitimate purchase", "no fraud", "closed as legitimate")):
                return "describes a legitimate outcome but the verdict is fraud"
            if "BLOCK_CARD" not in final and any(w in low for w in ("block the card", "will block", "card will be blocked", "blocks the card")):
                return "mentions a card block that is not recommended"
            if "ESCALATE_TO_ANALYST" not in final and "escalat" in low:
                return "mentions an escalation that is not recommended"
        return ""

    def finalize(self, s: State) -> State:
        r, case = s["result"], s["case"]
        ep = s["ep"]
        from agent.case_writer import graph_case_id, write_case
        meta = {"tool_calls": len(self.g.trace.calls) - s["calls0"], "tokens": Usage.tokens(),
                "latency_s": time.time() - s["t0"], "written_to_graph": self.write_graph,
                "graph_case_id": graph_case_id(case["case_id"]) if self.write_graph else "",
                "knowledge_refs": self._knowledge_refs(s)}
        if r["evidence_requests"]:
            meta["asked_after_step"] = r["evidence_requests"][0]["asked_after_step"]
        ans = build_answer(case, r, s["texts"], meta)
        ids = set(ans["case"]["affected_txn_ids"]) | {ans["case"]["first_suspicious_txn_id"]} - {""}
        exists = self.g.ids_exist(sorted(ids), ans["case"]["connected_card_ids"], ans["case"]["similar_prior_cases"], [case["customer_id"]])
        amounts = {}
        for w in ep.window + ep.account.get("history", []) + ((ep.device or {}).get("txns") or []) + [ep.txn]:
            amounts[w["id"]] = float(w["amt"])
        exists["amounts"] = amounts
        # drop anything the validator cannot find in the graph (never cite a made-up ID)
        ans["case"]["similar_prior_cases"] = [x for x in ans["case"]["similar_prior_cases"] if x in exists["closed_cases"]]
        ans["case"]["connected_card_ids"] = [x for x in ans["case"]["connected_card_ids"] if x in exists["cards"]]
        written = {"ok": False}
        if self.write_graph:
            try:
                written = write_case(ans, r, case["opened_at"])
                ans["case"]["written_to_graph"] = bool(written.get("ok"))
                ans["case"]["graph_case_id"] = written.get("graph_case_id", "")
            except Exception as e:  # noqa: BLE001
                ans["case"]["written_to_graph"] = False
                ans["case"]["graph_case_id"] = ""
                self.emit("warning", {"msg": f"graph write failed: {e}"})
        ans["tool_calls"] = len(self.g.trace.calls) - s["calls0"]
        ans["tokens"] = Usage.tokens()
        ans["latency_s"] = round(time.time() - s["t0"], 1)
        problems = validate(ans, exists)
        self.emit("final", {"answer": ans, "problems": problems, "written": written})
        return {"answer": ans, "problems": problems, "written": written}

    # ------------------------------------------------------------------ helpers
    def _draft(self, s: State) -> dict:
        r, ep = s["result"], s["ep"]
        rows = {w["id"]: w for w in ep.window + ep.account.get("history", []) + ((ep.device or {}).get("txns") or []) + [ep.txn]}
        return {
            "case_id": s["case"]["case_id"], "trigger": s["case"]["trigger_text"], "opened_at": s["case"]["opened_at"],
            "customer_id": s["case"]["customer_id"], "card_id": s["case"]["card_id"],
            "flagged": {k: ep.txn.get(k) for k in ("id", "ts", "amt", "product", "channel", "addr1", "risk_score", "device", "is_new", "proxy", "p_email")},
            "verdict": r["verdict"], "fraud_probability": r["p_final"], "initial_probability": r["ledger"]["p"],
            "pattern": r["pattern"], "episode": [{k: rows[i].get(k) for k in ("id", "ts", "amt", "channel", "addr1", "device")} for i in r["episode"] if i in rows],
            "exposure_usd": r["exposure"], "connected_cards": sorted(r["facts"].get("connected_cards") or [])[:25],
            "connected_devices": sorted(r["facts"].get("connected_devices") or []),
            "evidence": [{"claim": f.claim, "ref": f.ref} for f in r["findings"]],
            "evidence_request": r["evidence_requests"], "initial_actions": r["initial"], "final_actions": r["final"],
            "status": r["status"], "similar_prior_cases": similar_prior_cases(r),
            "sar_filed": any(a["action"] == "FILE_REPORT" for a in r["final"]),
            "assumed_reply_branch": r.get("reply"),
        }

    def _allowed_ids(self, s: State) -> set[str]:
        r, ep, case = s["result"], s["ep"], s["case"]
        ids = {case["customer_id"], case["card_id"], ep.txn["id"], *r["episode"], *(r["facts"].get("connected_cards") or []),
               *similar_prior_cases(r)}
        ids |= {c.split("-K")[0] for c in (r["facts"].get("connected_cards") or [])}
        for f in r["findings"]:
            ids |= {str(e) for e in f.entity_ids}
        return ids

    def _knowledge_refs(self, s: State) -> list[dict]:
        r = s["result"]
        rules = sorted({m for a in r["final"] + r["initial"] for m in __import__("re").findall(r"\b(R\d+)\b", a["reason"])},
                       key=lambda x: int(x[1:]))
        refs = []
        if rules:
            refs.append({"claim": f"Fraud Policy rules applied to this case: {', '.join(rules)} (retrieved from the policy "
                                  f"knowledge graph via GraphRAG)", "ref": "document:Fraud Policy v1.0 section 3 " + "/".join(rules)})
        chunks = (s["ep"].knowledge or {}).get("chunks", [])
        fin = [c for c in chunks if "FinCEN" in c.get("source", "")]
        if fin and any(a["action"] == "FILE_REPORT" for a in r["final"]):
            refs.append({"claim": "The SAR narrative follows FinCEN narrative guidance (who, what, when, where, how, why)",
                         "ref": f"document:{fin[0]['source']}"})
        return refs

    def _fallback_texts(self, s: State) -> dict:
        r, case, ep = s["result"], s["case"], s["ep"]
        t = ep.txn
        acts = ", ".join(a["action"] for a in r["final"])
        top = sorted(r["findings"], key=lambda f: -abs(f.weight))[:2]
        summary = (f"{case['trigger_type'].replace('_', ' ').capitalize()} on {t['ts'][:10]}: ${float(t['amt']):,.2f} "
                   f"{t['channel'].replace('_', '-')} transaction {t['id']} on card {case['card_id']}. "
                   f"Verdict: {r['verdict']} (probability {r['p_final']:.2f}), pattern {r['pattern']}. "
                   + (" ".join(f.claim.split(';')[0] + '.' for f in top) + " " if top else "")
                   + f"Recommended: {acts}.")
        led, reply, p0 = r["ledger"], r.get("reply"), r["ledger"]["p"]
        fams = ", ".join(led["fraud_families"]) or "the pattern detector"
        legit_fams = ", ".join(led["legit_families"]) or "the account's own history"
        final_names = ", ".join(a["action"] for a in r["final"])
        if reply == "confirm":
            stop = ("Section 6: the verification response settled the question - the cardholder confirmed the transaction, "
                    "so further investigation would not change the decision.")
            what = (f"The assumed {'step-up' if r['evidence_requests'][0]['type'] == 'step_up_auth' else 'customer'} response "
                    f"(\"{r['evidence_requests'][0]['assumed_response']}\") settled the alert: probability fell from {p0:.2f} to "
                    f"{r['p_final']:.2f} and the recommendation moved from verification to {final_names} (R3"
                    f"{', R7' if r['facts'].get('recurring') else ''}).")
        elif reply == "deny":
            stop = ("Section 6: the cardholder's denial settled the question and, with the graph evidence, supports a "
                    "defensible fraud decision; further queries would not change the actions.")
            what = (f"The assumed denial raised the probability from {p0:.2f} to {r['p_final']:.2f}; under R2 the "
                    f"recommendation moved from verification to {final_names}"
                    + (f", including a suspicious activity report because {__import__('agent.policy', fromlist=['sar_reason']).sar_reason(r['situation'])}." if any(a['action'] == 'FILE_REPORT' for a in r['final']) else "."))
        elif reply == "no_reply":
            esc = any(a["action"] == "ESCALATE_TO_ANALYST" for a in r["final"])
            stop = ("Section 6: further automated steps are unlikely to change the decision without the cardholder's reply; "
                    + ("the case is handed to an analyst (R8)." if esc else "the card is monitored for 72 hours and the case stays open."))
            what = (f"No reply within 24 hours left the alert unresolved at probability {p0:.2f}; R4 replaces verification with "
                    f"{final_names}" + (" and R8 escalates it because exposure exceeds $500." if esc else "."))
        elif case["trigger_type"] == "customer_report" and r["verdict"] == "fraud":
            stop = (f"Section 6: the customer's denial (R2) plus independent graph evidence ({fams}) support a defensible "
                    f"decision at probability {r['p_final']:.2f}; further queries would not change the actions.")
            what = "nothing"
        elif r["verdict"] == "uncertain":
            stop = "The graph evidence conflicts with the customer's report, so the case goes to an analyst under R8 instead of being guessed."
            what = "nothing"
        elif r["verdict"] == "fraud":
            stop = (f"Section 6: fraud probability {r['p_final']:.2f} >= 0.85 on independent evidence ({fams}); "
                    f"further queries would not change the actions.")
            what = "nothing"
        else:
            stop = (f"Section 6: fraud probability {r['p_final']:.2f} <= 0.15 on independent legitimate signals ({legit_fams}); "
                    f"contacting the cardholder would not change the decision.")
            what = "nothing"
        sar_file = any(a["action"] == "FILE_REPORT" for a in r["final"])
        from agent.policy import sar_reason
        sar_reason_txt = (f"Section 3a: fraud confirmed or strongly suspected and {sar_reason(r['situation'])}." if sar_file else
                          "Section 3a: no report required - " + ("the activity is legitimate." if r["verdict"] == "legitimate" else
                                                                  f"exposure ${r['exposure']:,.2f} is under $1,000 with no shared device, region cluster or coordinated pattern."
                                                                  if r["verdict"] == "fraud" else "fraud is not confirmed or strongly suspected."))
        narrative = ""
        if sar_file:
            rows = {w["id"]: w for w in ep.window + ep.account.get("history", []) + ((ep.device or {}).get("txns") or []) + [t]}
            items = [rows[i] for i in r["episode"] if i in rows]
            listing = "; ".join(f"{x['id']} on {x['ts'][:16]} for ${float(x['amt']):,.2f} ({x.get('channel', '').replace('_', '-')})" for x in items[:8])
            conn = sorted(r["facts"].get("connected_cards") or [])
            devs = sorted(r["facts"].get("connected_devices") or [])
            why = " ".join(f.claim.split(";")[0] + "." for f in sorted(r["findings"], key=lambda f: -f.weight)[:3] if f.lr > 1)
            who = "The cardholder denied making the transactions." if (r.get("reply") == "deny" or case["trigger_type"] == "customer_report") else \
                  "The activity was identified by the bank's investigation before any customer report."
            narrative = (
                f"This report concerns suspected unauthorized card activity on card {case['card_id']} held by customer "
                f"{case['customer_id']}. Between {r['dates'][0]} and {r['dates'][-1]}, {len(items)} transaction(s) totaling "
                f"${r['exposure']:,.2f} were identified as part of one fraud episode: {listing}. "
                f"The activity was classified as {r['pattern'].replace('_', ' ')}. {why} "
                + (f"The same device profile ({devs[0]}) links this card to {len(conn)} other card(s), including "
                   f"{', '.join(conn[:6])}, indicating a common actor across cardholders. " if conn and devs else "")
                + f"{who} The bank recommends {', '.join(a['action'] for a in r['final'])}; the card block and this "
                f"filing await human approval under the bank's routing policy.")
        return {"summary": summary, "stop_reason": stop, "sar_reason": sar_reason_txt,
                "what_changed": what, "sar_narrative": narrative, "pattern_description": r["pattern_description"]}

    def _build(self):
        g = StateGraph(State)
        for name in ("intake", "gather", "lead_plan", "specialists", "decide", "recall", "review", "write", "finalize"):
            g.add_node(name, getattr(self, name))
        g.add_edge(START, "intake")
        g.add_edge("intake", "gather")
        g.add_edge("gather", "lead_plan")
        g.add_edge("lead_plan", "specialists")
        g.add_edge("specialists", "decide")
        g.add_edge("decide", "recall")
        g.add_edge("recall", "review")
        g.add_edge("review", "write")
        g.add_edge("write", "finalize")
        g.add_edge("finalize", END)
        return g.compile()

    def run(self, case: dict) -> dict:
        out = self.app.invoke({"case": case}, {"recursion_limit": 40})
        return out
