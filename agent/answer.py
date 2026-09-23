"""Assemble the answer file (README "Answer Format") and validate it against the schema and the policy."""
from __future__ import annotations

import re
from typing import Any

from agent.policy import route

PATTERNS = {"card_testing", "card_not_present_fraud", "card_not_present_new_device", "out_of_region_use",
            "account_takeover", "undocumented", "none"}
STATUSES = {"open", "closed_fraud", "closed_legitimate", "escalated"}
VERDICTS = {"fraud", "legitimate", "uncertain"}
REQ_TYPES = {"customer_validation", "step_up_auth", "analyst_info"}
SOURCES = {"graph", "document", "customer", "external"}


def similar_prior_cases(r: dict) -> list[str]:
    """Closed-case IDs actually retrieved and used as memory, strongest first."""
    out: list[str] = []
    f = r["facts"]
    for c in f.get("account_prior_fraud", []) or []:
        out.append(c)
    for c in f.get("ring_fraud_cases", []) or []:
        if c.startswith("CC-"):
            out.append(c)
    mem = r["ep"].memory or {}
    want = r["pattern"] if r["pattern"] != "none" else None
    for hit in (mem.get("graph_hits") or [])[:4]:
        if not want or hit.get("pattern") == want or r["verdict"] == "legitimate":
            out.append(hit["id"])
    for hit in (mem.get("vector_hits") or [])[:6]:
        if want and hit.get("pattern") == want:
            out.append(hit["id"])
        elif r["verdict"] == "legitimate" and hit.get("outcome") == "cleared":
            out.append(hit["id"])
    for fnd in r["findings"]:
        if fnd.key in ("card_prior_cleared", "account_prior_cleared", "card_connected_to_fraud"):
            out.extend(e for e in fnd.entity_ids if str(e).startswith("CC-"))
    seen, res = set(), []
    for c in out:
        if c not in seen and str(c).startswith("CC-"):
            seen.add(c)
            res.append(c)
    return res[:8]


def evidence_list(r: dict, knowledge_refs: list[dict]) -> list[dict]:
    ev = []
    for f in sorted(r["findings"], key=lambda x: -abs(x.weight)):
        if abs(f.weight) < 0.05 and f.key not in ("known_device",):
            continue
        ev.append({"claim": f.claim, "source": f.source, "ref": f.ref or "query:unknown",
                   "entity_ids": [str(e) for e in f.entity_ids]})
    mem = r["ep"].memory or {}
    hits = similar_prior_cases(r)
    if hits:
        rows = {h["id"]: h for h in (mem.get("graph_hits") or []) + (mem.get("vector_hits") or [])}
        desc = []
        for c in hits[:4]:
            h = rows.get(c)
            if h:
                desc.append(f"{c} ({h.get('outcome')}, {h.get('pattern')})")
            else:
                desc.append(c)
        ev.append({"claim": "Case memory: similar closed cases retrieved by graph-filtered vector search and account lineage: "
                            + "; ".join(desc),
                   "source": "graph", "ref": r["ep"].refs.get("memory", "query:similar_cases"), "entity_ids": hits[:6]})
    for k in knowledge_refs[:2]:
        ev.append({"claim": k["claim"], "source": "document", "ref": k["ref"], "entity_ids": []})
    if r.get("customer_evidence"):
        ev.append(r["customer_evidence"])
    return ev


def build_answer(case: dict, r: dict, texts: dict, meta: dict) -> dict:
    ep = r["ep"]
    s = r["situation"]
    legit = r["verdict"] == "legitimate"
    episode = [] if legit else list(r["episode"])
    exposure = 0.0 if legit else round(float(r["exposure"]), 2)
    connected_cards = [] if legit else sorted(set(r["facts"].get("connected_cards") or []) - {case["card_id"]})
    connected_devices = [] if legit else sorted(r["facts"].get("connected_devices") or []) if r["facts"].get("shared_links") else []
    sar_file = any(a["action"] == "FILE_REPORT" for a in r["final"])
    subjects = []
    if sar_file:
        subjects = [case["customer_id"], case["card_id"]] + connected_cards[:20] + connected_devices[:3]
    initial = [dict(a) for a in r["initial"]]
    final = [dict(a) for a in r["final"]]
    for a in initial + final:
        a["route"] = route(a["action"], exposure if exposure else r["exposure"])
    if not r["evidence_requests"]:
        what_changed = "nothing"
    else:
        what_changed = texts.get("what_changed") or ""
    answer = {
        "case_id": case["case_id"],
        "case": {
            "status": r["status"],
            "verdict": r["verdict"],
            "fraud_probability": round(float(r["p_final"]), 2),
            "pattern": r["pattern"] if not legit else "none",
            "pattern_description": (texts.get("pattern_description") or r["pattern_description"]) if r["pattern"] == "undocumented" and not legit else "",
            "affected_txn_ids": episode,
            "first_suspicious_txn_id": episode[0] if episode else "",
            "connected_card_ids": connected_cards,
            "connected_device_profiles": connected_devices,
            "exposure_usd": exposure,
            "evidence": evidence_list(r, meta.get("knowledge_refs", [])),
            "similar_prior_cases": similar_prior_cases(r),
            "summary": texts.get("summary", ""),
            "written_to_graph": bool(meta.get("written_to_graph")),
            "graph_case_id": meta.get("graph_case_id", ""),
        },
        "evidence_requests": [dict(e, asked_after_step=meta.get("asked_after_step", e.get("asked_after_step", 0)))
                              for e in r["evidence_requests"]],
        "next_best_actions": {"initial": initial, "final": final if r["evidence_requests"] else initial,
                              "what_changed": what_changed},
        "sar": {
            "file": sar_file,
            "reason": texts.get("sar_reason") or "",
            "narrative": texts.get("sar_narrative", "") if sar_file else "",
            "subjects": subjects,
            "total_amount_usd": exposure if sar_file else 0,
            "activity_dates": [r["dates"][0], r["dates"][-1]] if sar_file and r["dates"] else [],
        },
        "stop_reason": texts.get("stop_reason", ""),
        "tool_calls": int(meta.get("tool_calls", r["tool_calls"])),
        "tokens": int(meta.get("tokens", 0)),
        "latency_s": round(float(meta.get("latency_s", r["latency_s"])), 1),
    }
    return answer


def validate(ans: dict, exists: dict | None = None) -> list[str]:
    """Schema + policy lint. Returns a list of problems (empty = valid)."""
    p = []
    c = ans.get("case", {})
    for k in ("status", "verdict", "fraud_probability", "pattern", "pattern_description", "affected_txn_ids",
              "first_suspicious_txn_id", "connected_card_ids", "connected_device_profiles", "exposure_usd", "evidence",
              "similar_prior_cases", "summary", "written_to_graph", "graph_case_id"):
        if k not in c:
            p.append(f"case.{k} missing")
    for k in ("case_id", "case", "evidence_requests", "next_best_actions", "sar", "stop_reason", "tool_calls", "tokens", "latency_s"):
        if k not in ans:
            p.append(f"{k} missing")
    if c.get("status") not in STATUSES:
        p.append(f"bad status {c.get('status')}")
    if c.get("verdict") not in VERDICTS:
        p.append(f"bad verdict {c.get('verdict')}")
    if c.get("pattern") not in PATTERNS:
        p.append(f"bad pattern {c.get('pattern')}")
    if not 0 <= float(c.get("fraud_probability", -1)) <= 1:
        p.append("fraud_probability out of range")
    if c.get("pattern") == "undocumented" and not c.get("pattern_description"):
        p.append("undocumented pattern needs pattern_description")
    if c.get("verdict") == "legitimate" and (c.get("affected_txn_ids") or c.get("exposure_usd") or ans["sar"]["file"]):
        p.append("legitimate verdict must have empty episode, zero exposure and no SAR")
    for e in c.get("evidence", []):
        if e.get("source") not in SOURCES or not e.get("claim") or "ref" not in e or "entity_ids" not in e:
            p.append(f"bad evidence item {str(e)[:60]}")
    for e in ans.get("evidence_requests", []):
        if e.get("type") not in REQ_TYPES:
            p.append(f"bad evidence request type {e.get('type')}")
    nba = ans.get("next_best_actions", {})
    for stage in ("initial", "final"):
        for a in nba.get(stage, []):
            try:
                if route(a["action"], float(c.get("exposure_usd") or 0) or 0.0) != a["route"] and a["action"] != "BLOCK_CARD":
                    p.append(f"{stage} {a['action']} route {a['route']} wrong")
            except ValueError:
                p.append(f"unknown action {a.get('action')}")
            if not re.search(r"\b(R\d+|[Ss]ection \d|3a|3b)\b", a.get("reason", "")):
                p.append(f"{stage} {a['action']} reason does not cite a rule")
    final_acts = {a["action"] for a in nba.get("final", [])}
    if ans["sar"]["file"] != ("FILE_REPORT" in final_acts):
        p.append("sar.file disagrees with FILE_REPORT in final actions")
    if ans["sar"]["file"]:
        if not ans["sar"]["narrative"] or len(ans["sar"]["activity_dates"]) != 2:
            p.append("SAR narrative/activity_dates missing")
    else:
        if ans["sar"]["narrative"] or ans["sar"]["subjects"] or ans["sar"]["total_amount_usd"] or ans["sar"]["activity_dates"]:
            p.append("sar fields must be empty when file is false")
    if not ans.get("evidence_requests") and nba.get("final") != nba.get("initial"):
        p.append("final must equal initial when nothing was requested")
    if "BLOCK_ALL_CARDS" in final_acts:
        p.append("R10: BLOCK_ALL_CARDS not justified")
    if exists is not None:
        for t in c.get("affected_txn_ids", []) + ([c["first_suspicious_txn_id"]] if c.get("first_suspicious_txn_id") else []):
            if t not in exists["txns"]:
                p.append(f"unknown txn id {t}")
        for k in c.get("connected_card_ids", []):
            if k not in exists["cards"]:
                p.append(f"unknown card id {k}")
        for k in c.get("similar_prior_cases", []):
            if k not in exists["closed_cases"]:
                p.append(f"unknown closed case {k}")
    exp = round(float(c.get("exposure_usd") or 0), 2)
    if c.get("verdict") != "legitimate" and exists is not None and exists.get("amounts"):
        tot = round(sum(abs(exists["amounts"].get(t, 0)) for t in c.get("affected_txn_ids", [])), 2)
        if abs(tot - exp) > 0.011:
            p.append(f"exposure {exp} != sum of affected {tot}")
    return p
