"""How often each new-typology detector fires, month by month, and what the bank's own labels say about its hits.

For every card and every month-end from August to January, each detector sees exactly what an investigation opened at
that month-end would see: the card's last 30 days (and a 90-day baseline for micro_run). Hits in August-October are
compared with the closed-case labels, which are complete for those months: a hit whose transactions sit in confirmed
fraud cases is a true positive, one that sits only in cleared cases is an innocent customer the detector would have
acted against.

  python eval/typology_backtest.py   ->  eval/typology_backtest.json (+ a printed table)
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent import typologies as ty  # noqa: E402
from agent.paths import CLOSED_CSV, DB  # noqa: E402

MONTH_ENDS = [datetime(2016, 8, 31, 23, 59, 59), datetime(2016, 9, 30, 23, 59, 59), datetime(2016, 10, 31, 23, 59, 59),
              datetime(2016, 11, 30, 23, 59, 59), datetime(2016, 12, 31, 23, 59, 59), datetime(2017, 1, 31, 23, 59, 59)]
LABELLED = {"2016-08", "2016-09", "2016-10"}


def main() -> None:
    con = duckdb.connect(str(DB), read_only=True)
    rows = con.execute("""
        SELECT t.TransactionID AS id, t.card_id, strftime(t.ts_dt, '%Y-%m-%d %H:%M:%S') AS ts, t.amt, t.ProductCD AS product,
               t.channel, coalesce(t.R_emaildomain, '') AS r_email, coalesce(i.device_profile, '') AS device,
               coalesce(i.id_15, '') AS is_new, coalesce(i.id_23, '') AS proxy
        FROM txn t LEFT JOIN ident i USING (TransactionID)
        WHERE t.channel = 'online' AND t.ts_dt >= TIMESTAMP '2016-05-01'
        ORDER BY t.card_id, t.ts_dt""").fetchall()
    cols = ["id", "card_id", "ts", "amt", "product", "channel", "r_email", "device", "is_new", "proxy"]
    by_card: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_card[r[1]].append(dict(zip(cols, r)))
    labels: dict[str, str] = {}
    for c in con.execute(f"SELECT outcome, txn_ids FROM read_csv('{CLOSED_CSV.as_posix()}', all_varchar=true)").fetchall():
        for tid in (c[1] or "").split("|"):
            if tid:
                labels[tid] = "fraud" if c[0] == "confirmed_fraud" else labels.get(tid, "cleared")

    report: dict = {}
    for end in MONTH_ENDS:
        month = end.strftime("%Y-%m")
        start = end - timedelta(days=ty.LOOKBACK_D)
        base_start = start - timedelta(days=ty.BASELINE_D)
        # recipient reach: cards paying each domain in the window vs the previous six months
        reach_window: dict[str, set] = defaultdict(set)
        reach_months: dict[str, dict] = defaultdict(lambda: defaultdict(set))
        for card, rs in by_card.items():
            for r in rs:
                t = ty.P(r["ts"])
                if r["r_email"] and start < t <= end:
                    reach_window[r["r_email"]].add(card)
                elif r["r_email"] and end - timedelta(days=210) < t <= start:
                    reach_months[r["r_email"]][r["ts"][:7]].add(card)
        hits = defaultdict(list)
        for card, rs in by_card.items():
            w = [r for r in rs if start < ty.P(r["ts"]) <= end]
            if not w:
                continue
            prior_micro = sum(1 for r in rs if base_start < ty.P(r["ts"]) <= start and float(r["amt"]) < ty.MICRO_MAX)
            found = [ty.micro_run(w, end, prior_micro), ty.spoofed_device(w, end), ty.escalating_ramp(w, end)]
            for dom in {r["r_email"] for r in w if r["r_email"]}:
                stats = {"domain": dom, "cards_window": sorted(reach_window[dom]),
                         "monthly_cards": [len(v) for v in reach_months[dom].values()]}
                found.append(ty.recipient_surge(w, end, stats))
            for typ in found:
                if typ is None:
                    continue
                lab = [labels.get(i) for i in typ.txns]
                hits[typ.key].append({"card": card, "txns": typ.txns, "fraud": lab.count("fraud"),
                                      "cleared": lab.count("cleared"), "unlabelled": lab.count(None),
                                      "shared": typ.shared[1] if typ.shared else ""})
        report[month] = {}
        for key, hs in hits.items():
            entry = {"cards": len(hs), "any_fraud_txn": sum(1 for h in hs if h["fraud"]),
                     "only_cleared": sum(1 for h in hs if h["cleared"] and not h["fraud"])}
            if key == "recipient_surge":
                entry["domains"] = sorted({h["shared"] for h in hs})
            report[month][key] = entry
    (ROOT / "eval" / "typology_backtest.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    keys = ["micro_run", "spoofed_device", "escalating_ramp", "recipient_surge"]
    print(f"{'month':8s} " + " ".join(f"{k:>34s}" for k in keys))
    for month, rep in report.items():
        cells = []
        for k in keys:
            e = rep.get(k, {"cards": 0, "any_fraud_txn": 0, "only_cleared": 0})
            cells.append(f"{e['cards']:>5} cards ({e['any_fraud_txn']:>3} fraud, {e['only_cleared']:>2} cleared)")
        print(f"{month:8s} " + " ".join(f"{c:>34s}" for c in cells) + ("  [labels complete]" if month in LABELLED else ""))
    for month, rep in report.items():
        if "recipient_surge" in rep:
            print(month, "surging recipient domains:", rep["recipient_surge"]["domains"])


if __name__ == "__main__":
    main()
