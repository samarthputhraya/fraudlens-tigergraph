"""Offline DuckDB mirror of the installed GSQL queries (same inputs, same output shapes).

Used only for development and the large closed-case backtest (thousands of investigations in minutes).
Production investigations and the submitted answer files run against TigerGraph via MCP (graph_client.py).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import numpy as np

from agent.graph_client import ToolCall, Trace, fmt_ts

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "prep" / "hhgoa.duckdb"

TXN_COLS = """t.TransactionID AS id, t.card_id, t.customer_id, strftime(t.ts_dt, '%Y-%m-%d %H:%M:%S') AS ts, t.amt,
  t.ProductCD AS product, t.channel, t.score AS risk_score, coalesce(t.addr1,'') AS addr1,
  coalesce(t.P_emaildomain,'') AS p_email, coalesce(t.R_emaildomain,'') AS r_email,
  coalesce(try_cast(t.dist1 AS DOUBLE), -1) AS dist1, coalesce(t.M4,'') AS m4, coalesce(t.M6,'') AS m6,
  coalesce(t.M1,'')||coalesce(t.M2,'')||coalesce(t.M3,'') AS m123, coalesce(t.M7,'')||coalesce(t.M8,'')||coalesce(t.M9,'') AS m789,
  coalesce(try_cast(t.C1 AS DOUBLE), -1) AS c1, coalesce(try_cast(t.C13 AS DOUBLE), -1) AS c13,
  coalesce(try_cast(t.D1 AS DOUBLE), -1) AS d1, coalesce(try_cast(t.D15 AS DOUBLE), -1) AS d15,
  coalesce(i.device_profile,'') AS device, coalesce(i.id_15,'') AS is_new, coalesce(i.id_23,'') AS proxy"""


class MirrorGraph:
    def __init__(self) -> None:
        self.con = duckdb.connect(str(DB), read_only=True)
        self.trace = Trace()
        self.agent = "lead"
        self._closed_emb = None
        self._know = None
        self._acct_ready = False

    def _log(self, query: str, params: dict, rows: int, t0: float, agent: str | None = None) -> None:
        import time
        self.trace.add(ToolCall(agent or self.agent, "mirror", query, params, rows, (time.time() - t0) * 1000, True, "mirror"))

    def _rows(self, sql: str, args: list | None = None) -> list[dict]:
        cur = self.con.execute(sql, args or [])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    # ---- queries --------------------------------------------------------------------------
    def txn_context(self, txn_id: str, agent: str | None = None) -> dict:
        import time
        t0 = time.time()
        rows = self._rows(f"""SELECT {TXN_COLS}, coalesce(i.id_34,'') AS id_34, coalesce(i.DeviceType,'') AS device_type
            FROM txn t LEFT JOIN ident i ON i.TransactionID = t.TransactionID WHERE t.TransactionID = ?""", [txn_id])
        txn = rows[0] if rows else {}
        if txn.get("device"):
            d = self._rows("SELECT count(*) n FROM ident WHERE device_profile = ?", [txn["device"]])[0]
            txn["device_txns"] = d["n"]
            parts = txn["device"].split(" | ")
            txn["device_generic"] = sum(1 for p in (parts[0], parts[1], parts[3]) if not p) >= 2 if len(parts) == 4 else True
        card = self._rows("""SELECT card_id AS id, any_value(customer_id) customer_id, any_value(coalesce(card4,'')) network,
            any_value(coalesce(card6,'')) card_type, count(*) n_txn FROM txn WHERE card_id = ? GROUP BY card_id""",
                          [txn.get("card_id")])
        self._log("txn_context", {"txn": txn_id}, 1, t0, agent)
        return {"txn": txn, "card": card[0] if card else {}}

    def card_window(self, card_id: str, start, end, agent: str | None = None) -> list[dict]:
        import time
        t0 = time.time()
        rows = self._rows(f"""SELECT {TXN_COLS} FROM txn t LEFT JOIN ident i ON i.TransactionID = t.TransactionID
            WHERE t.card_id = ? AND t.ts_dt BETWEEN CAST(? AS TIMESTAMP) AND CAST(? AS TIMESTAMP)
            ORDER BY t.ts_dt, t.TransactionID""", [card_id, fmt_ts(start), fmt_ts(end)])
        self._log("card_window", {"card": card_id, "start_ts": fmt_ts(start), "end_ts": fmt_ts(end)}, len(rows), t0, agent)
        return rows

    def card_profile(self, card_id: str, before, recent_days: int = 30, agent: str | None = None) -> dict:
        import time
        t0 = time.time()
        b = fmt_ts(before)
        rows = self._rows(f"""SELECT {TXN_COLS} FROM txn t LEFT JOIN ident i ON i.TransactionID = t.TransactionID
            WHERE t.card_id = ? AND t.ts_dt < CAST(? AS TIMESTAMP)""", [card_id, b])
        prof: dict = {"n_txn": len(rows), "amts": [r["amt"] for r in rows]}
        recent_start = (datetime.fromisoformat(b) - timedelta(days=recent_days)).strftime("%Y-%m-%d %H:%M:%S")
        prof["n_recent"] = sum(1 for r in rows if r["ts"] >= recent_start)
        prof["n_online"] = sum(1 for r in rows if r["channel"] == "online")
        prof["amt_max"] = max(prof["amts"], default=0.0)
        prof["amt_sum"] = sum(prof["amts"])
        prof["first_ts"] = min((r["ts"] for r in rows), default="")
        prof["last_ts"] = max((r["ts"] for r in rows), default="")
        for key, col in (("region", "addr1"), ("device", "device")):
            n, first, last = {}, {}, {}
            for r in rows:
                v = r[col]
                if not v:
                    continue
                n[v] = n.get(v, 0) + 1
                first[v] = min(first.get(v, r["ts"]), r["ts"])
                last[v] = max(last.get(v, r["ts"]), r["ts"])
            prof[f"{key}_n"], prof[f"{key}_first"], prof[f"{key}_last"] = n, first, last
        for key, col in (("product_n", "product"), ("channel_n", "channel"), ("p_email_n", "p_email")):
            d = {}
            for r in rows:
                if r[col]:
                    d[r[col]] = d.get(r[col], 0) + 1
            prof[key] = d
        self._log("card_profile", {"card": card_id, "before_ts": b, "recent_days": recent_days}, len(rows), t0, agent)
        return prof

    def recurring_match(self, card_id: str, amt: float, tol: float, before, agent: str | None = None) -> list[dict]:
        import time
        t0 = time.time()
        rows = self._rows(f"""SELECT {TXN_COLS} FROM txn t LEFT JOIN ident i ON i.TransactionID = t.TransactionID
            WHERE t.card_id = ? AND t.ts_dt < CAST(? AS TIMESTAMP) AND abs(t.amt - ?) <= ? ORDER BY t.ts_dt""",
                          [card_id, fmt_ts(before), amt, tol])
        self._log("recurring_match", {"card": card_id, "amt": amt, "tol": tol, "before_ts": fmt_ts(before)}, len(rows), t0, agent)
        return rows

    def device_neighbors(self, device_id: str, start, end, agent: str | None = None) -> dict:
        import time
        t0 = time.time()
        rows = self._rows(f"""SELECT {TXN_COLS} FROM txn t JOIN ident i ON i.TransactionID = t.TransactionID
            WHERE i.device_profile = ? AND t.ts_dt BETWEEN CAST(? AS TIMESTAMP) AND CAST(? AS TIMESTAMP)
            ORDER BY t.ts_dt""", [device_id, fmt_ts(start), fmt_ts(end)])
        ids = [r["id"] for r in rows]
        cases = {}
        if ids:
            for r in self._rows("""SELECT tid, list(case_id) cs FROM (SELECT case_id, unnest(string_split(txn_ids,'|')) tid FROM closed)
                                   WHERE tid IN (SELECT unnest(?)) GROUP BY tid""", [ids]):
                cases[r["tid"]] = r["cs"]
        for r in rows:
            r["closed_cases"] = cases.get(r["id"], [])
            r["inv_cases"] = []
        n_all = self._rows("""SELECT count(DISTINCT t.card_id) n FROM ident i JOIN txn t ON t.TransactionID = i.TransactionID
                              WHERE i.device_profile = ?""", [device_id])[0]["n"]
        parts = device_id.split(" | ")
        generic = sum(1 for p in (parts[0], parts[1], parts[3]) if not p) >= 2 if len(parts) == 4 else True
        self._log("device_neighbors", {"dev": device_id, "start_ts": fmt_ts(start), "end_ts": fmt_ts(end)}, len(rows), t0, agent)
        return {"device": {"id": device_id, "is_generic": generic}, "n_cards_all_time": n_all, "txns": rows}

    def region_activity(self, region: str, start, end, max_cards: int = 200, agent: str | None = None) -> dict:
        import time
        t0 = time.time()
        rows = self._rows("""WITH w AS (SELECT card_id, any_value(customer_id) customer_id, count(*) n_window, sum(amt) amt_window
                  FROM txn WHERE addr1 = ? AND ts_dt BETWEEN CAST(? AS TIMESTAMP) AND CAST(? AS TIMESTAMP) GROUP BY card_id),
               f AS (SELECT card_id, min(ts_dt) first_in_region FROM txn WHERE addr1 = ? GROUP BY card_id)
            SELECT w.card_id AS id, w.customer_id, w.n_window, w.amt_window,
                   strftime(f.first_in_region, '%Y-%m-%d %H:%M:%S') first_in_region
            FROM w JOIN f USING(card_id)""", [region, fmt_ts(start), fmt_ts(end), region])
        new = [r for r in rows if r["first_in_region"] >= fmt_ts(start)]
        new.sort(key=lambda r: -r["n_window"])
        self._log("region_activity", {"region": region, "start_ts": fmt_ts(start), "end_ts": fmt_ts(end)}, len(rows), t0, agent)
        return {"n_cards": len(rows), "n_new_cards": len(new), "new_cards": new[:max_cards]}

    def prior_cases(self, card_id: str, agent: str | None = None) -> dict:
        import time
        t0 = time.time()
        cust = card_id.split("-")[0]
        cards = self._rows("""SELECT card_id id, any_value(coalesce(card4,'')) network, any_value(coalesce(card6,'')) card_type,
            count(*) n_txn FROM txn WHERE customer_id = ? GROUP BY card_id""", [cust])
        cc = self._rows("""SELECT case_id id, card_id, opened_at, outcome, pattern, CAST(exposure_usd AS DOUBLE) exposure_usd,
            CAST(n_txns AS INT) n_txns, actions_taken, report_filed = 'Yes' report_filed, analyst_notes FROM closed WHERE customer_id = ?""", [cust])
        cx = self._rows("""SELECT case_id id, card_id, opened_at, outcome, pattern, analyst_notes FROM closed
            WHERE list_contains(string_split(coalesce(connected_card_ids,''), '|'), ?)""", [card_id])
        self._log("prior_cases", {"card": card_id}, len(cc) + len(cx), t0, agent)
        return {"customer_cards": cards, "closed_cases": cc, "connected_cases": cx, "investigations": []}

    def _ensure_accounts(self) -> None:
        if self._acct_ready:
            return
        self.con.execute("""CREATE TEMP TABLE IF NOT EXISTS acct AS SELECT TransactionID tid,
            CASE WHEN try_cast(D1 AS DOUBLE) IS NULL THEN NULL ELSE card_id || '|' || coalesce(addr1,'') || '|' ||
            CAST(CAST(floor(CAST(TransactionDT AS DOUBLE)/86400) - CAST(D1 AS DOUBLE) AS BIGINT) AS VARCHAR) END account_id FROM txn""")
        self.con.execute("""CREATE TEMP TABLE IF NOT EXISTS case_txn AS SELECT tid, list(case_id) cases, list(outcome) outcomes,
            list(pattern) patterns FROM (SELECT case_id, outcome, pattern, unnest(string_split(txn_ids,'|')) tid FROM closed) GROUP BY tid""")
        self._acct_ready = True

    def account_history(self, txn_id: str, lookback_days: int = 200, agent: str | None = None) -> dict:
        import time
        t0 = time.time()
        self._ensure_accounts()
        acc = self._rows("SELECT account_id FROM acct WHERE tid = ?", [txn_id])
        aid = acc[0]["account_id"] if acc else None
        if not aid:
            self._log("account_history", {"txn": txn_id, "lookback_days": lookback_days}, 0, t0, agent)
            return {"account": {}, "history": []}
        ts = self._rows("SELECT strftime(ts_dt, '%Y-%m-%d %H:%M:%S') ts FROM txn WHERE TransactionID = ?", [txn_id])[0]["ts"]
        since = (datetime.fromisoformat(ts) - timedelta(days=lookback_days)).strftime("%Y-%m-%d %H:%M:%S")
        rows = self._rows(f"""SELECT {TXN_COLS}, coalesce(ct.cases, []) closed_cases, coalesce(ct.outcomes, []) outcomes,
               coalesce(ct.patterns, []) patterns
            FROM acct a JOIN txn t ON t.TransactionID = a.tid LEFT JOIN ident i ON i.TransactionID = t.TransactionID
            LEFT JOIN case_txn ct ON ct.tid = t.TransactionID
            WHERE a.account_id = ? AND t.ts_dt < CAST(? AS TIMESTAMP) AND t.ts_dt >= CAST(? AS TIMESTAMP) ORDER BY t.ts_dt""",
                          [aid, ts, since])
        n = self._rows("SELECT count(*) n FROM acct WHERE account_id = ?", [aid])[0]["n"]
        self._log("account_history", {"txn": txn_id, "lookback_days": lookback_days}, len(rows), t0, agent)
        return {"account": {"id": aid, "n_txn": n}, "history": rows}

    def similar_cases(self, qv, devices, cards, k: int = 8, pattern: str = "", agent: str | None = None) -> dict:
        import time
        t0 = time.time()
        if self._closed_emb is None:
            data = json.loads((ROOT / "data" / "prep" / "closed_emb.json").read_text())
            self._closed_ids = list(data.keys())
            m = np.array([data[i] for i in self._closed_ids], dtype=np.float32)
            self._closed_emb = m / np.linalg.norm(m, axis=1, keepdims=True)
            self._closed_meta = {r["id"]: r for r in self._rows("""SELECT case_id id, card_id, opened_at, outcome, pattern,
                CAST(exposure_usd AS DOUBLE) exposure_usd, report_filed='Yes' report_filed, actions_taken, analyst_notes FROM closed""")}
        q = np.array(qv, dtype=np.float32)
        q /= np.linalg.norm(q)
        sims = self._closed_emb @ q
        order = np.argsort(-sims)
        hits = []
        for i in order:
            meta = self._closed_meta[self._closed_ids[i]]
            if pattern and meta["pattern"] != pattern:
                continue
            hits.append({**meta, "distance": float(1 - sims[i])})
            if len(hits) >= k:
                break
        graph_ids = set()
        if cards:
            for r in self._rows("SELECT case_id FROM closed WHERE card_id IN (SELECT unnest(?))", [list(cards)]):
                graph_ids.add(r["case_id"])
        if devices:
            for r in self._rows("""SELECT DISTINCT c.case_id FROM (SELECT case_id, unnest(string_split(txn_ids,'|')) tid FROM closed) c
                JOIN ident i ON i.TransactionID = c.tid WHERE i.device_profile IN (SELECT unnest(?))""", [list(devices)]):
                graph_ids.add(r["case_id"])
        ghits = []
        if graph_ids:
            idx = [self._closed_ids.index(g) for g in graph_ids if g in self._closed_meta]
            for i in sorted(idx, key=lambda j: -sims[j])[:k]:
                ghits.append({**self._closed_meta[self._closed_ids[i]], "distance": float(1 - sims[i])})
        self._log("similar_cases", {"k": k, "pattern": pattern, "devices": devices, "cards": cards}, len(hits) + len(ghits), t0, agent)
        return {"vector_hits": hits, "graph_hits": ghits, "investigation_hits": []}

    def search_knowledge(self, qv, k: int = 6, agent: str | None = None) -> dict:
        import time
        t0 = time.time()
        if self._know is None:
            kn = json.loads((ROOT / "data" / "prep" / "knowledge.json").read_text())
            self._know = kn["chunks"]
            m = np.array([c["emb"] for c in self._know], dtype=np.float32)
            self._know_m = m / np.linalg.norm(m, axis=1, keepdims=True)
        q = np.array(qv, dtype=np.float32)
        q /= np.linalg.norm(q)
        sims = self._know_m @ q
        order = np.argsort(-sims)[:k]
        chunks = [{k2: v for k2, v in self._know[i].items() if k2 != "emb"} | {"distance": float(1 - sims[i])} for i in order]
        self._log("search_knowledge", {"k": k}, len(chunks), t0, agent)
        return {"chunks": chunks}

    def ids_exist(self, txns, cards, cases, customers, agent: str | None = None) -> dict:
        found = {
            "txns": {r["id"] for r in self._rows("SELECT TransactionID id FROM txn WHERE TransactionID IN (SELECT unnest(?))", [list(txns) or [""]])},
            "cards": {r["id"] for r in self._rows("SELECT DISTINCT card_id id FROM txn WHERE card_id IN (SELECT unnest(?))", [list(cards) or [""]])},
            "closed_cases": {r["id"] for r in self._rows("SELECT case_id id FROM closed WHERE case_id IN (SELECT unnest(?))", [list(cases) or [""]])},
            "customers": {r["id"] for r in self._rows("SELECT DISTINCT customer_id id FROM txn WHERE customer_id IN (SELECT unnest(?))", [list(customers) or [""]])},
        }
        return found
