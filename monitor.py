"""Autonomous monitoring: sweep Nov-Dec for fraud the model or customers never raised, then investigate it.

Scans (installed GSQL queries on TigerGraph; the offline mirror implements the same scans):
  - structuring_scan: >= 3 online purchases just under $500 within an hour on one card
  - card_testing_scan: >= 3 tiny online authorisations within an hour, then a larger purchase
  - build_ring_links + GDBMS_ALGO WCC (ring_components): rare device profiles used as a NEW device by several cards
Each hit that is not already one of the 20 benchmark cases becomes an autonomous case in cases_autonomous/.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
OUT = ROOT / "cases_autonomous"
START, END = "2016-11-01 00:00:00", "2016-12-31 23:59:59"


def P(s: str) -> datetime:
    return datetime.fromisoformat(s[:19])


def clusters(txns: list[tuple[str, str, float]], window_s: int, min_n: int) -> list[list]:
    txns = sorted(txns, key=lambda x: x[1])
    best = []
    for i, t in enumerate(txns):
        grp = [x for x in txns[i:] if (P(x[1]) - P(t[1])).total_seconds() <= window_s]
        if len(grp) >= min_n and not any(set(y[0] for y in grp) <= set(z[0] for z in b) for b in best):
            best.append(grp)
    return best


def scan(g) -> list[dict]:
    hits = []
    if hasattr(g, "structuring_scan"):
        struct = g.structuring_scan(START, END, 400.0, 500.0, 3, agent="monitor")
        testing = g.card_testing_scan(START, END, 5.0, 3, agent="monitor")
    else:
        struct = testing = []
    if not struct and hasattr(g, "_rows"):
        struct = g._rows("""SELECT card_id id, any_value(customer_id) customer_id, list(TransactionID || '|' || strftime(ts_dt, '%Y-%m-%d %H:%M:%S') || '|' || CAST(amt AS VARCHAR)) txns
            FROM txn WHERE channel='online' AND amt >= 400 AND amt < 500 AND ts_dt BETWEEN ? AND ? GROUP BY card_id HAVING count(*) >= 3""", [START, END])
        testing = g._rows("""SELECT card_id id, any_value(customer_id) customer_id, list(TransactionID || '|' || strftime(ts_dt, '%Y-%m-%d %H:%M:%S') || '|' || CAST(amt AS VARCHAR)) txns
            FROM txn WHERE channel='online' AND amt < 5 AND ts_dt BETWEEN ? AND ? GROUP BY card_id HAVING count(*) >= 3""", [START, END])
    for kind, rows, window, min_n in (("structuring", struct, 3600, 3), ("card_testing", testing, 3600, 3)):
        for r in rows:
            parsed = [tuple(x.split("|")) for x in r["txns"]]
            parsed = [(a, b, float(c)) for a, b, c in parsed]
            for grp in clusters(parsed, window, min_n):
                hits.append({"kind": kind, "card_id": r["id"], "customer_id": r["customer_id"],
                             "flagged": grp[-1][0], "ts": grp[-1][1], "txns": [x[0] for x in grp],
                             "amount": round(sum(x[2] for x in grp), 2)})
    # device rings: rare profiles used as New device by >= 4 customers within 14 days
    if hasattr(g, "_rows"):
        rings = g._rows("""WITH d AS (SELECT i.device_profile dev, t.card_id, t.customer_id, t.TransactionID tid, t.ts_dt, i.id_15
                  FROM ident i JOIN txn t ON t.TransactionID = i.TransactionID WHERE t.ts_dt BETWEEN ? AND ?),
              alltime AS (SELECT i.device_profile dev, count(DISTINCT t.card_id) n_all FROM ident i JOIN txn t ON t.TransactionID=i.TransactionID GROUP BY 1)
            SELECT d.dev, any_value(n_all) n_all, count(DISTINCT d.customer_id) n_cust,
                   avg(CASE WHEN d.id_15='New' THEN 1.0 ELSE 0.0 END) new_share, list(d.card_id || '|' || d.tid || '|' || strftime(d.ts_dt, '%Y-%m-%d %H:%M:%S')) uses
            FROM d JOIN alltime USING(dev) WHERE split_part(d.dev, ' | ', 1) <> '' GROUP BY d.dev
            HAVING count(DISTINCT d.customer_id) >= 4 AND avg(CASE WHEN d.id_15='New' THEN 1.0 ELSE 0.0 END) >= 0.6
               AND avg(CASE WHEN d.proxy IN ('IP_PROXY:ANONYMOUS','IP_PROXY:HIDDEN') THEN 1.0 ELSE 0.0 END) >= 0.5""", [START, END])
    else:
        g.run("build_ring_links", {"start_ts": START, "end_ts": END, "max_cards": 60, "min_cards": 4}, agent="monitor")
        from graph.tg import gsql
        gsql('USE GRAPH Fraud\nCALL GDBMS_ALGO.community.wcc(["Card"], ["RING_LINK"], 0, FALSE, "wcc_id", "")')
        comps = g.ring_components(agent="monitor")
        rings = []
        for cid, members in (comps.get("members") or {}).items():
            devs = (comps.get("devices") or {}).get(cid, [])
            rings.append({"dev": devs[0] if devs else "", "n_cust": len(members), "n_all": len(members), "new_share": 1.0,
                          "uses": [], "members": members})
    ring_summ = []
    for r in rings:
        uses = sorted((tuple(u.split("|")) for u in r.get("uses", [])), key=lambda x: x[2])
        ring_summ.append({"device": r["dev"], "customers": r["n_cust"], "all_time_cards": r["n_all"], "new_share": round(r["new_share"], 2),
                          "members": sorted({u[0] for u in uses}) or r.get("members", [])})
        for card, tid, ts in uses[-1:]:
            hits.append({"kind": "device_ring", "card_id": card, "customer_id": card.split("-")[0], "flagged": tid, "ts": ts,
                         "txns": [u[1] for u in uses if u[0] == card], "device": r["dev"], "ring_size": r["n_cust"]})
    (ROOT / "runs").mkdir(exist_ok=True)
    (ROOT / "runs" / "rings.json").write_text(json.dumps(ring_summ, indent=1))
    return hits


def main(limit: int = 8) -> None:
    use_mirror = "--mirror" in sys.argv or not os.getenv("TG_HOST")
    if use_mirror:
        from agent.mirror import MirrorGraph
        g = MirrorGraph()
    else:
        from agent.graph_client import GraphClient
        g = GraphClient()
    bench = {r["flagged_txn_id"] for r in csv.DictReader((ROOT / "data" / "raw" / "case_pack.csv").open(encoding="utf-8"))}
    bench_cards = {r["card_id"] for r in csv.DictReader((ROOT / "data" / "raw" / "case_pack.csv").open(encoding="utf-8"))}
    hits = [h for h in scan(g) if h["flagged"] not in bench and h["card_id"] not in bench_cards]
    by_kind = defaultdict(list)
    for h in hits:
        by_kind[h["kind"]].append(h)
    print({k: len(v) for k, v in by_kind.items()})
    chosen, seen_cards = [], set()
    for kind in ("structuring", "device_ring", "card_testing"):
        for h in sorted(by_kind[kind], key=lambda h: -len(h["txns"])):
            if h["card_id"] in seen_cards or sum(1 for c in chosen if c["kind"] == kind) >= max(2, limit // 3):
                continue
            seen_cards.add(h["card_id"])
            chosen.append(h)
    chosen = chosen[:limit]
    OUT.mkdir(exist_ok=True)
    from agent.workflow import Investigator
    inv = Investigator(g, write_graph=not use_mirror and "--no-write" not in sys.argv, use_llm="--no-llm" not in sys.argv)
    for i, h in enumerate(chosen, 1):
        cid = f"AUTO-{i:03d}"
        what = {"structuring": f"{len(h['txns'])} online purchases just under $500 within an hour (total ${h.get('amount', 0):,.2f})",
                "card_testing": f"{len(h['txns'])} online authorisations under $5 within an hour",
                "device_ring": f"device profile shared as a New device by {h.get('ring_size')} customers"}[h["kind"]]
        row = {"case_id": cid, "opened_at": (P(h["ts"]) + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
               "trigger_type": "analyst_request",
               "trigger_text": f"Autonomous monitor: {what} on card {h['card_id']}. Investigate transaction {h['flagged']} and related activity.",
               "flagged_txn_id": h["flagged"], "card_id": h["card_id"], "customer_id": h["customer_id"], "risk_score": "",
               "source": "autonomous"}
        out = inv.run(row)
        (OUT / f"{cid}.json").write_text(json.dumps({"row": row, "scan_hit": h, "answer": out["answer"]}, indent=2), encoding="utf-8")
        a = out["answer"]["case"]
        print(cid, h["kind"], h["card_id"], a["verdict"], a["pattern"], a["exposure_usd"], out.get("problems"))


if __name__ == "__main__":
    main()
