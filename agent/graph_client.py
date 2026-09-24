"""Graph access for the agent.

Primary path: the official TigerGraph MCP server (`tigergraph-mcp`, stdio) -> `tigergraph__run_installed_query`.
Fallback path: pyTigerGraph REST (same installed queries) if the MCP process is unavailable.
Every call is recorded (tool, query, params, rows, latency) so the answer file's `tool_calls` is real and every
evidence item can cite a replayable `query:<name>(...)` reference.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "graph"))


_RENAME = {"new_flag": "is_new", "proxy_type": "proxy"}  # GSQL reserves is_new; map back to the agent's names
VERTEX_PARAMS = {"txn_context": ("txn",), "card_window": ("card",), "card_profile": ("card",),
                 "recurring_match": ("card",), "device_neighbors": ("dev",), "region_activity": ("region",),
                 "prior_cases": ("card",), "account_history": ("txn",), "case_graph": ("ic",)}
SET_VERTEX_PARAMS = {"similar_cases": ("devices", "cards")}
ALLOWED_MCP_TOOLS = ",".join([
    "run_installed_query", "get_query_description", "get_query_metadata", "is_query_installed", "show_query",
    "search_top_k_similarity", "get_graph_schema", "get_node", "get_nodes", "get_neighbors", "get_vertex_count",
    "get_edge_count",
])


def _clean_key(k: str) -> str:
    """'T.@device' -> 'device', 'T.amt' -> 'amt'."""
    k = k.split(".")[-1].lstrip("@")
    return _RENAME.get(k, k)


def _flatten_vertices(items: list) -> list[dict]:
    out = []
    for v in items or []:
        if isinstance(v, dict) and "attributes" in v:
            row = {_clean_key(k): val for k, val in v["attributes"].items()}
            row.setdefault("id", v.get("v_id"))
            out.append(row)
        else:
            out.append(v)
    return out


def normalize(result: list) -> dict:
    """Merge TigerGraph PRINT blocks into one dict; vertex-set projections become lists of flat dicts."""
    merged: dict[str, Any] = {}
    for block in result or []:
        for k, v in block.items():
            if isinstance(v, list) and v and isinstance(v[0], dict) and "v_id" in v[0]:
                merged[k] = _flatten_vertices(v)
            else:
                merged[k] = v
    return merged


def fmt_ts(ts: datetime | str) -> str:
    return ts if isinstance(ts, str) else ts.strftime("%Y-%m-%d %H:%M:%S")


# as-of bound for case-memory queries called outside an investigation (the UI, ad-hoc re-proves): all memory visible
AS_OF_NOW = "2100-01-01 00:00:00"


def local_query_descriptions() -> dict[str, str]:
    import re
    out = {}
    for f in sorted((ROOT / "graph" / "queries").glob("*.gsql")):
        text = f.read_text(encoding="utf-8")
        m, d = re.search(r"QUERY (\w+)\(", text), re.search(r"/\*(.*?)\*/", text, re.S)
        if m:
            out[m.group(1)] = " ".join(d.group(1).split()) if d else ""
    return out


@dataclass
class ToolCall:
    agent: str
    tool: str
    query: str
    params: dict
    rows: int
    ms: float
    ok: bool
    via: str

    def ref(self) -> str:
        short = {k: v for k, v in self.params.items() if k not in ("qv",)}
        args = ", ".join(f"{k}={v}" for k, v in short.items())
        return f"query:{self.query}({args})"


@dataclass
class Trace:
    calls: list[ToolCall] = field(default_factory=list)
    listeners: list = field(default_factory=list)

    def add(self, call: ToolCall) -> None:
        self.calls.append(call)
        for fn in self.listeners:
            try:
                fn(call)
            except Exception:  # noqa: BLE001 - UI listeners must never break an investigation
                pass


class _MCPBridge:
    """Keeps one persistent stdio session to tigergraph-mcp on a background event loop."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.session = None
        self._ctx = None
        fut = asyncio.run_coroutine_threadsafe(self._start(), self.loop)
        fut.result(timeout=120)

    async def _start(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        exe = shutil.which("tigergraph-mcp") or str(Path(sys.executable).parent / "tigergraph-mcp")
        env = {k: v for k, v in os.environ.items() if k.startswith("TG_")}
        env.update({"TG_LOG_TOOL_CALLS": "true", "PATH": os.environ.get("PATH", ""),
                    "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), "PYTHONIOENCODING": "utf-8"})
        if "tgcloud" in env.get("TG_HOST", ""):
            env.setdefault("TG_TGCLOUD", "true")
        # Least privilege: the reasoning agent may read and run installed investigation queries, nothing else
        # (no schema, loading, DML or GSQL tools). Writes go through agent/case_writer.py only.
        params = StdioServerParameters(command=exe, args=["--allowed-tools", ALLOWED_MCP_TOOLS], env=env)
        self._ctx = stdio_client(params)
        read, write = await self._ctx.__aenter__()
        self._session_ctx = ClientSession(read, write)
        self.session = await self._session_ctx.__aenter__()
        await self.session.initialize()

    def call(self, tool: str, args: dict, timeout: float = 180) -> dict:
        async def _go():
            res = await self.session.call_tool(tool, args)
            text = "".join(getattr(c, "text", "") for c in res.content)
            # the server returns a ```json fenced ToolResponse followed by markdown suggestions/metadata
            import re as _re
            m = _re.search(r"```json\s*(\{.*?\})\s*```", text, _re.S)
            body = m.group(1) if m else text[text.find("{"):text.rfind("}") + 1]
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return {"success": False, "error": text[:500]}
        return asyncio.run_coroutine_threadsafe(_go(), self.loop).result(timeout=timeout)


class GraphClient:
    def __init__(self, use_mcp: bool = True) -> None:
        self.trace = Trace()
        self.agent = "lead"
        self._mcp = None
        self.use_mcp = use_mcp and os.getenv("TG_USE_MCP", "1") == "1"
        if self.use_mcp:
            try:
                self._mcp = _MCPBridge()
            except Exception as e:  # noqa: BLE001
                print(f"[graph] MCP unavailable ({e}); using pyTigerGraph REST")
                self._mcp = None

    # ---- core -------------------------------------------------------------------------------
    @staticmethod
    def _post_params(query: str, params: dict) -> dict:
        """JSON POST form for installed queries: VERTEX<T> -> {"id": v}, SET<VERTEX<T>> -> [{"id": v}, ...]."""
        out = dict(params)
        for k in VERTEX_PARAMS.get(query, ()):
            if k in out and not isinstance(out[k], dict):
                out[k] = {"id": str(out[k])}
        for k in SET_VERTEX_PARAMS.get(query, ()):
            if k in out:
                out[k] = [{"id": str(v)} for v in (out[k] or [])]
        return out

    def run(self, query: str, params: dict | None = None, agent: str | None = None) -> dict:
        params = params or {}
        post = self._post_params(query, params)
        t0 = time.time()
        via = "mcp" if self._mcp else "rest"
        ok = True
        try:
            if self._mcp:
                resp = self._mcp.call("tigergraph__run_installed_query", {"query_name": query, "params": post})
                if not resp.get("success", False):
                    raise RuntimeError(resp.get("error") or resp.get("summary"))
                raw = resp["data"]["result"]
            else:
                from tg import run_query
                raw = run_query(query, post)
        except Exception as e:  # noqa: BLE001
            if self._mcp:  # one REST retry keeps the investigation alive if the MCP call fails
                from tg import run_query
                via = "rest"
                raw = run_query(query, post)
                print(f"[graph] MCP call failed for {query}: {str(e)[:120]} -> REST ok")
            else:
                ok = False
                raise
        out = normalize(raw)
        rows = sum(len(v) for v in out.values() if isinstance(v, list))
        self.trace.add(ToolCall(agent or self.agent, "tigergraph__run_installed_query", query,
                                {k: v for k, v in params.items()}, rows, (time.time() - t0) * 1000, ok, via))
        return out

    def describe_queries(self, agent: str = "lead") -> dict[str, str]:
        """Tool discovery: read installed-query descriptions from TigerGraph through MCP."""
        t0 = time.time()
        out: dict[str, str] = {}
        via = "mcp" if self._mcp else "local"
        try:
            if self._mcp:
                resp = self._mcp.call("tigergraph__get_query_description", {"query_name": "all"})
                data = resp.get("data") or {}
                raw = data.get("descriptions") or data.get("result") or data
                items = raw.get("queries", raw) if isinstance(raw, dict) else raw
                if isinstance(items, list):
                    for q in items:
                        if isinstance(q, dict) and q.get("queryName"):
                            out[q["queryName"]] = q.get("description", "")
                elif isinstance(items, dict):
                    out = {k: (v if isinstance(v, str) else json.dumps(v)[:300]) for k, v in items.items()}
        except Exception:  # noqa: BLE001
            out = {}
        if not out:
            out = local_query_descriptions()
            via = "local" if not self._mcp else "mcp+local"
        self.trace.add(ToolCall(agent, "tigergraph__get_query_description", "describe_queries", {"query_name": "all"},
                                len(out), (time.time() - t0) * 1000, True, via))
        return out

    # ---- typed wrappers (one per installed query) ---------------------------------------------
    def txn_context(self, txn_id: str, **kw) -> dict:
        out = self.run("txn_context", {"txn": txn_id}, **kw)
        return {"txn": (out.get("txn") or [{}])[0], "card": (out.get("card") or [{}])[0]}

    def card_window(self, card_id: str, start, end, **kw) -> list[dict]:
        out = self.run("card_window", {"card": card_id, "start_ts": fmt_ts(start), "end_ts": fmt_ts(end)}, **kw)
        return sorted(out.get("txns", []), key=lambda r: (r["ts"], r["id"]))

    def card_profile(self, card_id: str, before, recent_days: int = 30, **kw) -> dict:
        return self.run("card_profile", {"card": card_id, "before_ts": fmt_ts(before), "recent_days": recent_days}, **kw)

    def recurring_match(self, card_id: str, amt: float, tol: float, before, **kw) -> list[dict]:
        out = self.run("recurring_match", {"card": card_id, "amt": amt, "tol": tol, "before_ts": fmt_ts(before)}, **kw)
        return sorted(out.get("matches", []), key=lambda r: r["ts"])

    def device_neighbors(self, device_id: str, start, end, **kw) -> dict:
        out = self.run("device_neighbors", {"dev": device_id, "start_ts": fmt_ts(start), "end_ts": fmt_ts(end)}, **kw)
        out["txns"] = sorted(out.get("txns", []), key=lambda r: r["ts"])
        out["device"] = (out.get("device") or [{}])[0]
        return out

    def region_activity(self, region: str, start, end, max_cards: int = 200, **kw) -> dict:
        return self.run("region_activity", {"region": region, "start_ts": fmt_ts(start), "end_ts": fmt_ts(end),
                                            "max_cards": max_cards}, **kw)

    def prior_cases(self, card_id: str, before=None, **kw) -> dict:
        # case memory is as-of: investigations opened at or after `before` (the case's open time) are invisible
        return self.run("prior_cases", {"card": card_id, "before_ts": fmt_ts(before) if before else AS_OF_NOW}, **kw)

    def account_history(self, txn_id: str, lookback_days: int = 200, **kw) -> dict:
        out = self.run("account_history", {"txn": txn_id, "lookback_days": lookback_days}, **kw)
        out["history"] = sorted(out.get("history", []), key=lambda r: r["ts"])
        out["account"] = (out.get("account") or [{}])[0]
        return out

    def similar_cases(self, qv: list[float], devices: list[str], cards: list[str], k: int = 8,
                      pattern: str = "", before=None, **kw) -> dict:
        return self.run("similar_cases", {"qv": qv, "devices": devices, "cards": cards, "k": k, "pattern": pattern,
                                          "before_ts": fmt_ts(before) if before else AS_OF_NOW}, **kw)

    def search_knowledge(self, qv: list[float], k: int = 6, **kw) -> dict:
        return self.run("search_knowledge", {"qv": qv, "k": k}, **kw)

    def ids_exist(self, txns: list[str], cards: list[str], cases: list[str], customers: list[str], **kw) -> dict:
        out = self.run("ids_exist", {"txn_ids": txns, "card_ids": cards, "case_ids": cases,
                                     "customer_ids": customers}, **kw)
        return {k: {r["id"] for r in out.get(k, [])} for k in ("txns", "cards", "closed_cases", "customers")}

    def structuring_scan(self, start, end, lo: float = 400.0, hi: float = 500.0, min_n: int = 3, **kw) -> list[dict]:
        return self.run("structuring_scan", {"start_ts": fmt_ts(start), "end_ts": fmt_ts(end), "lo": lo, "hi": hi,
                                             "min_n": min_n}, **kw).get("cards", [])

    def card_testing_scan(self, start, end, small: float = 5.0, min_n: int = 3, **kw) -> list[dict]:
        return self.run("card_testing_scan", {"start_ts": fmt_ts(start), "end_ts": fmt_ts(end), "small": small,
                                              "min_n": min_n}, **kw).get("cards", [])

    def model_ring_scan(self, start, end, min_p: float = 0.6, min_customers: int = 3, max_cards_all: int = 12, **kw) -> list[dict]:
        return self.run("model_ring_scan", {"start_ts": fmt_ts(start), "end_ts": fmt_ts(end), "min_p": min_p,
                                            "min_customers": min_customers, "max_cards_all": max_cards_all}, **kw).get("devices", [])

    def alert_scan(self, start, end, min_score: float = 0.85, max_n: int = 500, **kw) -> list[dict]:
        return self.run("alert_scan", {"start_ts": fmt_ts(start), "end_ts": fmt_ts(end), "min_score": min_score,
                                       "max_n": max_n}, **kw).get("alerts", [])

    def ring_components(self, **kw) -> dict:
        return self.run("ring_components", {}, **kw)
