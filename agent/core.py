"""Deterministic investigation core: gather -> detect -> assess -> policy -> simulated reply -> final -> answer.

The LangGraph workflow (agent/workflow.py) wraps these steps with specialist agents, an LLM critic, GraphRAG and
narrative generation, but every number, ID, route and SAR decision is produced here, by code.
"""
from __future__ import annotations

import time
from datetime import timedelta
from typing import Any, Callable

from agent.assess import ledger, pattern_of, verdict_of
from agent.detectors import Finding, region_label, run_detectors
from agent.evidence import EvidencePack, P, gather
from agent.policy import Situation, plan, sar_required, status_of

Emit = Callable[[str, dict], None]


def _noop(kind: str, data: dict) -> None:
    pass


def situation(ep: EvidencePack, findings: list[Finding], facts: dict, led: dict, verdict: str, pattern: str,
              exposure: float) -> Situation:
    t = ep.txn
    fraud_fams = len(led["fraud_families"])
    legit_fams = len(led["legit_families"])
    shared_desc = ""
    if facts.get("connected_devices"):
        shared_desc = "device profile " + sorted(facts["connected_devices"])[0]
    elif facts["shared_links"]:
        kind, val = facts["shared_links"][0]
        shared_desc = f"{kind} {val}"
    explanation = ""
    if not facts["online"]:
        explanation = f"cardholder confirmed they made the purchase in billing region {region_label(t.get('addr1'))} (travel / local purchase)"
    elif facts.get("new_device"):
        explanation = "cardholder confirmed the purchase was made from their own new device"
    elif facts.get("amount_anomaly"):
        explanation = "cardholder confirmed the purchase; amount unusual but consistent with their stated intent"
    else:
        explanation = "cardholder confirmed they made the purchase"
    conflict = ep.case["trigger_type"] == "customer_report" and led["p"] < 0.5 and not facts.get("recurring")
    return Situation(
        trigger=ep.case["trigger_type"], p=led["p"], verdict=verdict, pattern=pattern, exposure=exposure,
        online=facts["online"], shared=bool(facts["shared_links"]), connected_cards=sorted(facts["connected_cards"]),
        shared_desc=shared_desc, recurring=bool(facts.get("recurring")), card_testing=bool(facts.get("card_testing")),
        ct_cleared_over_100=bool(facts.get("card_testing_cleared_over_100")),
        strong_families=fraud_fams + (1 if led["strong"] else 0), legit_families=legit_fams,
        single_signal=fraud_fams <= 1 and not led["strong"], conflict=conflict, legit_explanation=explanation)


def choose_reply(s: Situation) -> str:
    """Simulated customer / step-up response (the README says replies are not provided: we state the assumption)."""
    if s.trigger == "customer_report" and s.recurring:
        return "confirm" if s.p < 0.5 else "deny"
    if s.p >= 0.60:
        return "deny"
    if s.p <= 0.40:
        return "confirm"
    return "no_reply"


REPLY_TEXT = {
    "deny": "Cardholder states they did not make the flagged transaction(s) and still has the card",
    "no_reply": "No reply from the cardholder within 24 hours of the verification request",
}


def amount_of(ep: EvidencePack, ids: list[str]) -> tuple[float, list[str]]:
    rows = {w["id"]: w for w in ep.window}
    rows[ep.txn["id"]] = ep.txn
    for h in ep.account.get("history", []):
        rows.setdefault(h["id"], h)
    for x in (ep.device or {}).get("txns", []):
        rows.setdefault(x["id"], x)
    tot = round(sum(abs(float(rows[i]["amt"])) for i in ids if i in rows), 2)
    dates = sorted(rows[i]["ts"][:10] for i in ids if i in rows)
    return tot, dates


def investigate(case: dict, g: Any, emit: Emit = _noop) -> dict:
    t0 = time.time()
    n_calls0 = len(g.trace.calls)
    emit("stage", {"stage": "gather", "msg": "Pulling the flagged transaction, card, account, device and case memory from TigerGraph"})
    ep = gather(case, g)
    emit("stage", {"stage": "detect", "msg": "Running detectors"})
    findings, facts = run_detectors(ep)
    for f in findings:
        emit("finding", {"key": f.key, "claim": f.claim, "lr": f.lr, "family": f.family, "ref": f.ref})
    led = ledger(case["trigger_type"], findings, float(ep.txn.get("risk_score") or 0.5))
    verdict0 = verdict_of(led["p"], led, case["trigger_type"])
    pattern0, desc0 = pattern_of(verdict0 if verdict0 != "uncertain" else "fraud", facts, ep.txn)
    episode = facts["episode"]
    exposure0, dates0 = amount_of(ep, episode)
    s = situation(ep, findings, facts, led, verdict0, pattern0, exposure0)
    pl = plan(s)
    emit("assessment", {"p": led["p"], "verdict": verdict0, "pattern": pattern0, "ledger": led})

    reply = None
    evidence_requests = []
    customer_evidence = None
    final = pl["initial"]
    p_final, verdict, pattern, desc = led["p"], verdict0, pattern0, desc0
    if pl.get("evidence_request"):
        reply = choose_reply(s)
        rtype, rtext = pl["evidence_request"]
        if reply == "confirm":
            text = rtext or (s.legit_explanation[0].upper() + s.legit_explanation[1:])
        else:
            text = REPLY_TEXT[reply]
        evidence_requests.append({"type": rtype, "asked_after_step": 0, "assumed_response": text})
        final = pl["branches"][reply]
        if reply == "confirm":
            p_final, verdict, pattern, desc = 0.05, "legitimate", "none", ""
        elif reply == "deny":
            p_final, verdict = min(0.97, max(0.88, led["p"] + 0.3)), "fraud"
            # a denial can make the case SAR-eligible; plan() already built the deny branch with fraud semantics
        else:
            verdict = "uncertain"
        customer_evidence = {"claim": text, "source": "customer" if rtype != "analyst_info" else "external",
                             "ref": "evidence_request:1", "entity_ids": []}
        emit("evidence_request", {"type": rtype, "assumed_response": text, "branch": reply})
    elif case["trigger_type"] == "customer_report":
        customer_evidence = {"claim": f"The customer reported that they never made the ${float(ep.txn['amt']):,.2f} purchase "
                                      f"({ep.txn['id']})", "source": "customer", "ref": f"trigger:{case['case_id']}",
                             "entity_ids": [ep.txn["id"]]}
        if verdict == "uncertain" and not s.conflict:
            verdict = "fraud" if led["p"] >= 0.5 else "uncertain"
        if s.conflict:
            verdict = "uncertain"

    if verdict == "legitimate":
        episode, exposure, dates = [], 0.0, []
    else:
        exposure, dates = exposure0, dates0
        if verdict == "fraud" and pattern == "none":
            pattern, desc = pattern_of("fraud", facts, ep.txn)
    status = status_of(final, verdict)
    return {
        "ep": ep, "findings": findings, "facts": facts, "ledger": led, "situation": s, "plan": pl, "reply": reply,
        "evidence_requests": evidence_requests, "customer_evidence": customer_evidence,
        "initial": pl["initial"], "final": final, "verdict": verdict, "verdict0": verdict0, "p_final": p_final,
        "pattern": pattern, "pattern_description": desc, "episode": episode, "exposure": exposure, "dates": dates,
        "status": status, "sar_file": any(a["action"] == "FILE_REPORT" for a in final),
        "tool_calls": len(g.trace.calls) - n_calls0, "latency_s": time.time() - t0,
    }
