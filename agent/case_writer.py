"""Policy-gated case writer: the only component allowed to write to TigerGraph.

The reasoning agent reaches TigerGraph through MCP with a read-only tool allowlist; writes (InvestigationCase,
EvidenceRequest, ActionRecord and their edges) go through this service, which also enforces the approval model:
`auto` actions are executed (simulated) immediately, `L1`/`L2` actions are stored as pending approval.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "graph"))

from agent.llm import embed  # noqa: E402

PENDING = {"L1": "pending_approval_team_lead", "L2": "pending_approval_fraud_manager"}


def graph_case_id(case_id: str) -> str:
    """HHG-006 -> CASE-2016-006. Autonomous finds keep their own namespace (AUTO-007 -> CASE-2016-AUTO-007), so they
    can never overwrite a benchmark case's vertex."""
    prefix, num = case_id.rsplit("-", 1)
    return f"CASE-2016-{num}" if prefix == "HHG" else f"CASE-2016-{prefix}-{num}"


def write_case(ans: dict, r: dict, opened_at: str, dry: bool = False) -> dict:
    """Upsert the investigation into TigerGraph as case memory. Returns {'ok', 'graph_case_id', 'n_vertices', 'n_edges'}."""
    from tg import conn, retry

    gid = graph_case_id(ans["case_id"])
    c = ans["case"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = (f"{ans['case_id']} {c['verdict']} {c['pattern']} p={c['fraud_probability']}. {c['summary']} "
            f"Final actions: {', '.join(a['action'] for a in ans['next_best_actions']['final'])}.")
    emb = embed([text])[0]
    vert = {
        "id": gid, "case_ref": ans["case_id"], "trigger_type": r["ep"].case["trigger_type"],
        "opened_at": opened_at, "updated_at": now, "status": c["status"], "verdict": c["verdict"],
        "fraud_probability": c["fraud_probability"], "pattern": c["pattern"],
        "pattern_description": c["pattern_description"], "exposure_usd": c["exposure_usd"], "summary": c["summary"],
        "sar_filed": ans["sar"]["file"],
        "initial_actions": "|".join(a["action"] for a in ans["next_best_actions"]["initial"]),
        "final_actions": "|".join(a["action"] for a in ans["next_best_actions"]["final"]),
        "what_changed": ans["next_best_actions"]["what_changed"], "stop_reason": ans["stop_reason"],
        "answer_json": json.dumps(ans)[:60000], "emb": emb,
    }
    if dry:
        return {"ok": True, "graph_case_id": gid, "n_vertices": 0, "n_edges": 0}
    cx = conn()
    nv = ne = 0
    nv += retry(lambda: cx.upsertVertices("InvestigationCase", [(gid, {k: v for k, v in vert.items() if k != "id"})]))
    flagged = r["ep"].txn["id"]
    txn_edges = [(t, {"role": "flagged" if t == flagged else "affected"}) for t in c["affected_txn_ids"]]
    if flagged not in c["affected_txn_ids"]:
        txn_edges.append((flagged, {"role": "flagged"}))
    ne += retry(lambda: cx.upsertEdges("InvestigationCase", "CASE_TXN", "Transaction",
                                       [(gid, t, a) for t, a in txn_edges], vertexMustExist=True))
    cards = [(r["ep"].case["card_id"], {"role": "subject"})] + [(k, {"role": "connected"}) for k in c["connected_card_ids"]]
    ne += retry(lambda: cx.upsertEdges("InvestigationCase", "CASE_CARD", "Card", [(gid, k, a) for k, a in cards], vertexMustExist=True))
    devs = list(c["connected_device_profiles"])
    if r["ep"].txn.get("device"):
        devs.append(r["ep"].txn["device"])
    if devs:
        ne += retry(lambda: cx.upsertEdges("InvestigationCase", "CASE_DEVICE", "DeviceProfile",
                                           [(gid, d, {}) for d in sorted(set(devs))], vertexMustExist=True))
    if c["similar_prior_cases"]:
        ne += retry(lambda: cx.upsertEdges("InvestigationCase", "CASE_CITES", "ClosedCase",
                                           [(gid, k, {"score": 1.0, "reason": "retrieved as memory"}) for k in c["similar_prior_cases"]],
                                           vertexMustExist=True))
    inv_cites = sorted({x for x in r["facts"].get("ring_fraud_cases", []) if str(x).startswith("HHG-")})
    if inv_cites:
        ne += retry(lambda: cx.upsertEdges("InvestigationCase", "CASE_CITES_INV", "InvestigationCase",
                                           [(gid, graph_case_id(k), {"score": 1.0, "reason": "shared device"}) for k in inv_cites],
                                           vertexMustExist=True))
    rules = sorted({m for stage in ("initial", "final") for a in ans["next_best_actions"][stage]
                    for m in __import__("re").findall(r"\b(R\d+|3a|3b)\b", a["reason"])})
    sec = sorted({m for stage in ("initial", "final") for a in ans["next_best_actions"][stage]
                  for m in __import__("re").findall(r"[Ss]ection (\d)", a["reason"])})
    rules += sec
    if rules:
        ne += retry(lambda: cx.upsertEdges("InvestigationCase", "CASE_RULE", "PolicyRule", [(gid, x, {}) for x in rules],
                                           vertexMustExist=True))
    ne += retry(lambda: cx.upsertEdges("InvestigationCase", "CASE_PATTERN", "FraudPattern", [(gid, c["pattern"], {})],
                                       vertexMustExist=True))
    reqs = []
    for i, e in enumerate(ans["evidence_requests"], 1):
        rid = f"{gid}-REQ{i}"
        reqs.append((rid, {"req_type": e["type"], "asked_after_step": e["asked_after_step"],
                           "assumed_response": e["assumed_response"], "created_at": now}))
    if reqs:
        nv += retry(lambda: cx.upsertVertices("EvidenceRequest", reqs))
        ne += retry(lambda: cx.upsertEdges("InvestigationCase", "CASE_REQUEST", "EvidenceRequest", [(gid, rid, {}) for rid, _ in reqs]))
    acts = []
    for stage in ("initial", "final"):
        for i, a in enumerate(ans["next_best_actions"][stage], 1):
            aid = f"{gid}-{stage[0].upper()}{i}"
            status = "executed_simulated" if a["route"] == "auto" else PENDING[a["route"]]
            if stage == "initial" and ans["evidence_requests"]:
                status = "superseded" if a["route"] != "auto" else status
            acts.append((aid, {"action": a["action"], "route": a["route"], "reason": a["reason"], "stage": stage,
                               "status": status, "approver_role": {"auto": "agent", "L1": "team_lead", "L2": "fraud_manager"}[a["route"]],
                               "decided_at": now}))
    if acts:
        nv += retry(lambda: cx.upsertVertices("ActionRecord", acts))
        ne += retry(lambda: cx.upsertEdges("InvestigationCase", "CASE_ACTION", "ActionRecord", [(gid, aid, {}) for aid, _ in acts]))
    return {"ok": True, "graph_case_id": gid, "n_vertices": nv, "n_edges": ne}


def decide_action(action_id: str, approve: bool, role: str) -> dict:
    """Approval inbox: a human with the right role approves/rejects an L1/L2 action (written back to the graph)."""
    from tg import conn, retry
    cx = conn()
    rec = retry(lambda: cx.getVerticesById("ActionRecord", action_id))
    if not rec:
        return {"ok": False, "error": "unknown action"}
    attrs = rec[0]["attributes"]
    need = {"L1": {"team_lead", "fraud_manager"}, "L2": {"fraud_manager"}, "auto": {"agent", "team_lead", "fraud_manager"}}[attrs["route"]]
    if role not in need:
        return {"ok": False, "error": f"role {role} may not approve a {attrs['route']} action"}
    status = ("approved_by_" if approve else "rejected_by_") + role
    retry(lambda: cx.upsertVertices("ActionRecord", [(action_id, {"status": status, "approver_role": role,
                                                                    "decided_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})]))
    return {"ok": True, "status": status}
