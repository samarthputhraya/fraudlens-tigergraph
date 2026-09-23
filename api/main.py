"""FraudLens Command Center API: live investigations over SSE, case files, approvals, re-prove, graph view, metrics.

Run:  uvicorn api.main:app --port 8000     (serves the React build from api/static at /)
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import queue
import re
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

CASES = ROOT / "cases"
AUTO = ROOT / "cases_autonomous"
ADHOC = ROOT / "runs" / "adhoc"
TRACES = ROOT / "runs" / "traces"
APPROVALS = ROOT / "runs" / "approvals.json"
for d in (CASES, ADHOC, TRACES):
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="FraudLens Command Center")
_graph = None
_graph_lock = threading.Lock()
_run_lock = threading.Lock()


def graph():
    global _graph
    with _graph_lock:
        if _graph is None:
            if os.getenv("TG_HOST") and os.getenv("FRAUDLENS_MIRROR", "0") != "1":
                from agent.graph_client import GraphClient
                _graph = GraphClient(use_mcp=os.getenv("TG_USE_MCP", "1") == "1")
            else:
                from agent.mirror import MirrorGraph
                _graph = MirrorGraph()
    return _graph


def _pack() -> list[dict]:
    rows = list(csv.DictReader((ROOT / "data" / "raw" / "case_pack.csv").open(encoding="utf-8")))
    for r in rows:
        r["source"] = "benchmark"
    for f in sorted(ADHOC.glob("*.case.json")):
        rows.append(json.loads(f.read_text(encoding="utf-8")))
    for f in sorted(AUTO.glob("*.json")) if AUTO.exists() else []:
        a = json.loads(f.read_text(encoding="utf-8"))
        if "row" in a:
            rows.append(a["row"])
    return rows


def _answer_path(case_id: str) -> Path:
    for d in (CASES, AUTO, ADHOC):
        p = d / f"{case_id}.json"
        if p.exists():
            return p
    return CASES / f"{case_id}.json"


def _answer(case_id: str) -> dict | None:
    p = _answer_path(case_id)
    if not p.exists():
        return None
    a = json.loads(p.read_text(encoding="utf-8"))
    return a.get("answer", a) if "row" in a else a


def _row(r: dict) -> dict:
    a = _answer(r["case_id"])
    c = (a or {}).get("case", {})
    return {**{k: r.get(k, "") for k in ("case_id", "opened_at", "trigger_type", "trigger_text", "flagged_txn_id", "card_id",
                                        "customer_id", "risk_score")},
            "status": c.get("status", "new"), "verdict": c.get("verdict"), "fraud_probability": c.get("fraud_probability"),
            "pattern": c.get("pattern"), "exposure_usd": c.get("exposure_usd"), "sar": (a or {}).get("sar", {}).get("file"),
            "source": r.get("source", "benchmark")}


@app.get("/api/health")
def health():
    tg = bool(os.getenv("TG_HOST")) and os.getenv("FRAUDLENS_MIRROR", "0") != "1"
    return {"graph": "TigerGraph Savanna" if tg else "offline mirror", "host": os.getenv("TG_HOST", ""),
            "graph_name": os.getenv("TG_GRAPHNAME", "Fraud"), "mcp": tg and os.getenv("TG_USE_MCP", "1") == "1",
            "llm": f"{os.getenv('LLM_MODEL_PRO')} + {os.getenv('LLM_MODEL_FLASH')} (Vertex AI)"}


@app.get("/api/cases")
def cases():
    return sorted((_row(r) for r in _pack()), key=lambda x: x["opened_at"])


@app.get("/api/cases/{case_id}")
def case(case_id: str):
    rows = {r["case_id"]: r for r in _pack()}
    if case_id not in rows:
        raise HTTPException(404, "unknown case")
    tp = TRACES / f"{case_id}.json"
    return {"row": _row(rows[case_id]), "answer": _answer(case_id),
            "trace": json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else None}


@app.get("/api/cases/{case_id}/run")
async def run_case(case_id: str):
    rows = {r["case_id"]: r for r in _pack()}
    if case_id not in rows:
        raise HTTPException(404, "unknown case")
    row = rows[case_id]
    q: queue.Queue = queue.Queue()
    g = graph()

    def on_call(call):
        q.put(("tool_call", {"agent": call.agent, "tool": call.tool, "query": call.query, "ref": call.ref(),
                             "rows": call.rows, "ms": round(call.ms, 1), "via": call.via}))

    def worker():
        from agent.workflow import Investigator
        with _run_lock:
            g.trace.listeners.append(on_call)
            n0 = len(g.trace.calls)
            events: list = []

            def emit(kind, data):
                events.append({"t": round(time.time(), 2), "kind": kind, **{k: v for k, v in data.items() if k != "answer"}})
                q.put((kind, data))
            try:
                inv = Investigator(g, emit=emit, write_graph=os.getenv("TG_HOST", "") != "" and os.getenv("FRAUDLENS_MIRROR", "0") != "1")
                out = inv.run(row)
                ans = out["answer"]
                dest = CASES if row.get("source", "benchmark") == "benchmark" else ADHOC
                if os.getenv("FRAUDLENS_PROTECT_CASES", "1") == "1" and dest == CASES:
                    dest = ROOT / "runs" / "live"
                    dest.mkdir(parents=True, exist_ok=True)
                (dest / f"{case_id}.json").write_text(json.dumps(ans, indent=2), encoding="utf-8")
                trace = {"case_id": case_id, "events": events,
                         "tool_calls": [dict(agent=x.agent, tool=x.tool, query=x.query, ref=x.ref(), params=x.params,
                                             rows=x.rows, ms=round(x.ms, 1), via=x.via) for x in g.trace.calls[n0:]],
                         "specialists": out.get("specialists"), "lead": out.get("lead"), "critic": out.get("critic"),
                         "problems": out.get("problems"), "written": out.get("written")}
                (ROOT / "runs" / "live").mkdir(parents=True, exist_ok=True)
                (ROOT / "runs" / "live" / f"{case_id}.trace.json").write_text(json.dumps(trace, default=str, indent=1), encoding="utf-8")
            except Exception as e:  # noqa: BLE001
                q.put(("warning", {"msg": f"investigation failed: {e}"}))
            finally:
                g.trace.listeners.remove(on_call)
                q.put(("done", {}))

    threading.Thread(target=worker, daemon=True).start()

    async def gen():
        while True:
            try:
                kind, data = await asyncio.to_thread(q.get, True, 600)
            except Exception:  # noqa: BLE001
                break
            yield {"event": kind, "data": json.dumps({"kind": kind, **data}, default=str)}
            if kind == "done":
                break
    return EventSourceResponse(gen())


class NewInvestigation(BaseModel):
    txn_id: str
    note: str = ""


@app.post("/api/investigate")
def investigate(body: NewInvestigation):
    g = graph()
    ctx = g.txn_context(body.txn_id)
    t = ctx.get("txn") or {}
    if not t:
        raise HTTPException(404, "unknown transaction")
    from agent.evidence import P
    n = len(list(ADHOC.glob("*.case.json"))) + 1
    cid = f"ANL-{n:03d}"
    row = {"case_id": cid, "opened_at": (P(t["ts"]) + timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"),
           "trigger_type": "analyst_request",
           "trigger_text": f"Analyst request: {body.note or 'review transaction'} (transaction {t['id']}).",
           "flagged_txn_id": t["id"], "card_id": t["card_id"], "customer_id": t["customer_id"], "risk_score": "",
           "source": "analyst"}
    (ADHOC / f"{cid}.case.json").write_text(json.dumps(row), encoding="utf-8")
    return _row(row)


def _approval_store() -> dict:
    return json.loads(APPROVALS.read_text()) if APPROVALS.exists() else {}


@app.get("/api/approvals")
def approvals():
    store = _approval_store()
    out = []
    for r in _pack():
        a = _answer(r["case_id"])
        if not a:
            continue
        gid = a["case"].get("graph_case_id") or f"CASE-2016-{r['case_id'].split('-')[-1]}"
        for i, act in enumerate(a["next_best_actions"]["final"], 1):
            if act["route"] == "auto":
                continue
            aid = f"{gid}-F{i}"
            status = store.get(aid, {}).get("status") or ("pending_approval_team_lead" if act["route"] == "L1" else "pending_approval_fraud_manager")
            out.append({"action_id": aid, "case_id": r["case_id"], "action": act["action"], "route": act["route"],
                        "reason": act["reason"], "status": status, "exposure_usd": a["case"]["exposure_usd"]})
    return out


class Decision(BaseModel):
    approve: bool
    role: str


@app.post("/api/approvals/{action_id}")
def decide(action_id: str, body: Decision):
    item = next((x for x in approvals() if x["action_id"] == action_id), None)
    if not item:
        raise HTTPException(404, "unknown action")
    allowed = {"L1": {"team_lead", "fraud_manager"}, "L2": {"fraud_manager"}}[item["route"]]
    if body.role not in allowed:
        return {"ok": False, "status": item["status"],
                "error": f"A {body.role.replace('_', ' ')} cannot approve an {item['route']} action ({item['action']}); "
                         f"policy section 2 requires {'a fraud manager' if item['route'] == 'L2' else 'a team lead'}."}
    status = ("approved_by_" if body.approve else "rejected_by_") + body.role
    store = _approval_store()
    store[action_id] = {"status": status, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    APPROVALS.write_text(json.dumps(store, indent=1))
    if os.getenv("TG_HOST") and os.getenv("FRAUDLENS_MIRROR", "0") != "1":
        try:
            from agent.case_writer import decide_action
            decide_action(action_id, body.approve, body.role)
        except Exception as e:  # noqa: BLE001
            return {"ok": True, "status": status, "warning": f"graph update failed: {e}"}
    return {"ok": True, "status": status}


class Reprove(BaseModel):
    ref: str


REF_RE = re.compile(r"^query:(\w+)\((.*)\)$", re.S)


def _find_params(ref: str) -> dict | None:
    for d in (TRACES, ROOT / "runs" / "live"):
        for f in d.glob("*.json"):
            try:
                t = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            for c in t.get("tool_calls", []):
                if c.get("ref") == ref and "params" in c:
                    return c["params"]
    return None


@app.post("/api/reprove")
def reprove(body: Reprove):
    m = REF_RE.match(body.ref.strip())
    if not m:
        return {"ok": False, "error": "not a replayable query reference"}
    name = m.group(1)
    params = _find_params(body.ref)
    if params is None:
        params = {}
        for part in re.split(r", (?=\w+=)", m.group(2)):
            if "=" in part:
                k, v = part.split("=", 1)
                params[k.strip()] = v.strip()
    g = graph()
    t0 = time.time()
    try:
        if hasattr(g, "run"):
            out = g.run(name, params, agent="analyst")
            via = g.trace.calls[-1].via if g.trace.calls else "rest"
        else:
            fn = {"card_window": lambda p: {"txns": g.card_window(p["card"], p["start_ts"], p["end_ts"])},
                  "txn_context": lambda p: g.txn_context(p["txn"]),
                  "card_profile": lambda p: g.card_profile(p["card"], p["before_ts"], int(p.get("recent_days", 30))),
                  "recurring_match": lambda p: {"matches": g.recurring_match(p["card"], float(p["amt"]), float(p["tol"]), p["before_ts"])},
                  "device_neighbors": lambda p: g.device_neighbors(p["dev"], p["start_ts"], p["end_ts"]),
                  "account_history": lambda p: g.account_history(p["txn"], int(p.get("lookback_days", 200))),
                  "prior_cases": lambda p: g.prior_cases(p["card"]),
                  "region_activity": lambda p: g.region_activity(p["region"], p["start_ts"], p["end_ts"])}[name]
            out = fn(params)
            via = "mirror"
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:300]}
    rows = [x for v in out.values() if isinstance(v, list) for x in v]
    return {"ok": True, "query": name, "params": params, "rows": len(rows), "ms": round((time.time() - t0) * 1000, 1),
            "via": via, "sample": rows[:8]}


@app.get("/api/graph/{case_id}")
def case_graph(case_id: str):
    a = _answer(case_id)
    rows = {r["case_id"]: r for r in _pack()}
    if not a or case_id not in rows:
        raise HTTPException(404, "no answer yet")
    r = rows[case_id]
    c = a["case"]
    nodes, edges = {}, []

    def node(i, label, typ, **kw):
        nodes.setdefault(i, {"id": i, "label": label, "type": typ, "flagged": False, "affected": False, "fraud": False, "ring": False})
        nodes[i].update(kw)

    card = f"card:{r['card_id']}"
    node(f"cust:{r['customer_id']}", r["customer_id"], "Customer")
    node(card, r["card_id"], "Card")
    edges.append({"source": f"cust:{r['customer_id']}", "target": card, "type": "OWNS"})
    txns = set(c["affected_txn_ids"]) | {r["flagged_txn_id"]}
    for tid in sorted(txns):
        node(f"txn:{tid}", tid, "Transaction", flagged=tid == r["flagged_txn_id"], affected=tid in c["affected_txn_ids"],
             fraud=c["verdict"] == "fraud")
        edges.append({"source": card, "target": f"txn:{tid}", "type": "MADE"})
    for dev in c["connected_device_profiles"]:
        did = f"dev:{dev}"
        node(did, dev.split(" | ")[0] or dev, "DeviceProfile", ring=True)
        for tid in txns:
            edges.append({"source": f"txn:{tid}", "target": did, "type": "FROM_DEVICE"})
        for k in c["connected_card_ids"][:30]:
            node(f"card:{k}", k, "Card", ring=True)
            edges.append({"source": f"card:{k}", "target": did, "type": "CARD_DEVICE"})
    if not c["connected_device_profiles"]:
        for k in c["connected_card_ids"][:30]:
            node(f"card:{k}", k, "Card", ring=True)
            edges.append({"source": card, "target": f"card:{k}", "type": "CONNECTED"})
    for cc in c["similar_prior_cases"]:
        node(f"cc:{cc}", cc, "ClosedCase")
        edges.append({"source": f"inv:{case_id}", "target": f"cc:{cc}", "type": "CASE_CITES"})
    node(f"inv:{case_id}", c.get("graph_case_id") or case_id, "InvestigationCase", fraud=c["verdict"] == "fraud")
    edges.append({"source": f"inv:{case_id}", "target": f"txn:{r['flagged_txn_id']}", "type": "CASE_TXN"})
    return {"nodes": list(nodes.values()), "edges": edges}


@app.get("/api/metrics")
def metrics():
    rep = ROOT / "eval" / "report.json"
    backtest = json.loads(rep.read_text()) if rep.exists() else {}
    verdicts, patterns = {}, {}
    sar = 0
    exp = calls = toks = lat = 0.0
    n = 0
    for f in CASES.glob("HHG-*.json"):
        a = json.loads(f.read_text(encoding="utf-8"))
        c = a["case"]
        verdicts[c["verdict"]] = verdicts.get(c["verdict"], 0) + 1
        patterns[c["pattern"]] = patterns.get(c["pattern"], 0) + 1
        sar += 1 if a["sar"]["file"] else 0
        exp += c["exposure_usd"]
        calls += a["tool_calls"]
        toks += a["tokens"]
        lat += a["latency_s"]
        n += 1
    rings_path = ROOT / "runs" / "rings.json"
    rings = []
    for r in (json.loads(rings_path.read_text()) if rings_path.exists() else []):
        rings.append({"component": r.get("wcc_id") or r.get("component") or (r.get("device") or "")[:40],
                      "members": r.get("members", []),
                      "devices": r.get("devices") or ([r["device"]] if r.get("device") else []),
                      "fraud_cases": r.get("device_cases") or r.get("fraud_cases_on_device") or []})
    rings.sort(key=lambda r: -len(r["members"]))
    return {"backtest": backtest, "portfolio": {"verdicts": verdicts, "patterns": patterns, "sar_filed": sar,
                                                "total_exposure": round(exp, 2), "avg_tool_calls": round(calls / max(n, 1), 1),
                                                "avg_tokens": round(toks / max(n, 1)), "avg_latency_s": round(lat / max(n, 1), 1)},
            "rings": rings}


STATIC = ROOT / "api" / "static"
if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets") if (STATIC / "assets").exists() else None

    @app.get("/{path:path}")
    def spa(path: str):
        f = STATIC / path
        if path and f.exists() and f.is_file():
            return FileResponse(f)
        return FileResponse(STATIC / "index.html")
