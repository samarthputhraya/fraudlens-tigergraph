"""Print a compact analyst dossier for each benchmark case (used to build and review the golden sheet)."""
from __future__ import annotations

import csv
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.evidence import P, gather  # noqa: E402
from agent.mirror import MirrorGraph  # noqa: E402


def main(ids: list[str]) -> None:
    g = MirrorGraph()
    cases = list(csv.DictReader((ROOT / "data" / "raw" / "case_pack.csv").open(encoding="utf-8")))
    for c in cases:
        if ids and c["case_id"] not in ids:
            continue
        ep = gather(c, g)
        t, ts = ep.txn, ep.ts
        print(f"\n===== {c['case_id']} {c['trigger_type']} opened {c['opened_at']} | {c['trigger_text'][:90]}")
        print(f"FLAG {t['id']} {t['ts']} ${t['amt']} {t['product']} {t['channel']} addr={t['addr1']} score={t['risk_score']} "
              f"pe={t['p_email']} re={t['r_email']} dev=[{t.get('device')}] new={t.get('is_new')} proxy={t.get('proxy')} "
              f"m4={t.get('m4')} m6={t.get('m6')} m123={t.get('m123')} dist1={t.get('dist1')} D1={t.get('d1')}")
        pr = ep.profile
        amts = sorted(pr["amts"])
        q = (lambda p: amts[int(p * (len(amts) - 1))] if amts else None)
        print(f"PROFILE n={pr['n_txn']} recent30={pr['n_recent']} online={pr['n_online']} amt p50={q(.5)} p95={q(.95)} max={pr['amt_max']} "
              f"products={pr['product_n']} region_here={pr['region_n'].get(t['addr1'], 0)} top_regions={Counter(pr['region_n']).most_common(4)}")
        if t.get("device"):
            print(f"  device seen on card before: {pr['device_n'].get(t['device'], 0)} (first {pr['device_first'].get(t['device'])})")
        acc = ep.account
        hist = acc.get("history", [])
        fr = [h for h in hist if "confirmed_fraud" in (h.get("outcomes") or [])]
        cl = [h for h in hist if "cleared" in (h.get("outcomes") or [])]
        print(f"ACCOUNT {acc.get('account', {}).get('id')} prior_txns={len(hist)} fraud_txns={len(fr)} cleared_txns={len(cl)} "
              f"fraud_cases={sorted({x for h in fr for x in h['closed_cases']})[:6]} last_fraud={fr[-1]['ts'] if fr else None}")
        for h in hist[-6:]:
            print(f"     acct {h['id']} {h['ts']} ${h['amt']} {h['product']} {h['channel']} addr={h['addr1']} dev={h.get('device','')[:40]} {h.get('is_new')} {h.get('closed_cases')}")
        rec = ep.recurring
        months = sorted({r['ts'][:7] for r in rec})
        print(f"RECURRING ±1%: n={len(rec)} months={months[-8:]} last={[ (r['ts'][:16], r['amt'], r['product']) for r in rec[-4:]]}")
        near = [w for w in ep.window if abs((P(w['ts']) - ts).total_seconds()) <= 3 * 86400]
        print(f"WINDOW ±3d (n={len(near)}):")
        for w in near[:30]:
            mark = "*" if w["id"] == t["id"] else " "
            print(f"   {mark}{w['id']} {w['ts']} ${w['amt']:>8} {w['product']} {w['channel'][:6]} addr={w['addr1']:>6} sc={w['risk_score']} "
                  f"dev={w.get('device','')[:45]} {w.get('is_new')} {w.get('proxy')}")
        if ep.device:
            d = ep.device
            others = [x for x in d["txns"] if x["card_id"] != c["card_id"]]
            custs = {x["customer_id"] for x in others}
            print(f"DEVICE generic={d['device'].get('is_generic')} cards_all_time={d['n_cards_all_time']} window_txns={len(d['txns'])} "
                  f"other_cards={len({x['card_id'] for x in others})} other_customers={len(custs)} new_on_others={sum(1 for x in others if x['is_new']=='New')}")
            for x in others[:12]:
                print(f"     {x['id']} {x['ts']} {x['card_id']} ${x['amt']} {x['product']} new={x['is_new']} px={x['proxy']} cases={x.get('closed_cases')}")
        if ep.region:
            print(f"REGION {t['addr1']} last3d cards={ep.region['n_cards']} new_to_region={ep.region['n_new_cards']}")
        pc = ep.prior
        print(f"PRIOR closed on customer: {Counter((x['outcome'], x['pattern']) for x in pc['closed_cases']).most_common(5)} connected={[(x['id'], x['outcome']) for x in pc['connected_cases']]}")


if __name__ == "__main__":
    main(sys.argv[1:])
