"""Backtest the containment planner on the bank's own rings, against blocking every ring card.

The closed-case history holds 6 ring cases whose connected_card_ids name 130 other cards. For each ring, as of the
day it was opened:
- the shared element is every named device profile the ring case's own fraud transactions used;
- each connected card's evidence is what it did on that shared element in the 30 days before (how many uses, whether
  marked New, whether behind an anonymising proxy, how much it spent there);
- conf() turns that evidence into a probability with a fixed rule (no labels involved).
The labels come afterwards: a connected card is compromised if it has its own confirmed-fraud case within 30 days of
the ring case, and the exposure a block stops is the sum of that card's confirmed-fraud transactions in those cases.
A blocked card with no fraud case of its own is an innocent customer acted against.

  python eval/containment_backtest.py   ->  eval/containment_backtest.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.containment import Member, plan  # noqa: E402
from agent.paths import DB  # noqa: E402


def conf(n: int, new: int, proxied: int) -> float:
    """Evidence on the card itself, beyond ring membership. In these rings every card that touched the shared device did
    so as a New device behind a proxy - that is what made it a ring member - so those flags carry no information about
    which members are compromised. Membership alone gets 0.5; a card that never touched the shared element gets 0.3."""
    return 0.5 if n else 0.3


def main() -> None:
    con = duckdb.connect(str(DB), read_only=True)
    q = lambda s, p=None: con.execute(s, p or []).fetchall()  # noqa: E731
    rings = q("""SELECT case_id, card_id, opened_at, txn_ids, connected_card_ids FROM closed
                 WHERE connected_card_ids IS NOT NULL AND connected_card_ids <> '' ORDER BY opened_at""")
    out = {"rings": [], "totals": {}}
    totals: dict = {}
    for case_id, card, opened, txn_ids, conn in rings:
        own = [t for t in (txn_ids or "").split("|") if t]
        devices = [r[0] for r in q("""SELECT DISTINCT i.device_profile FROM ident i WHERE list_contains(?, i.TransactionID)
                       AND ((CASE WHEN i.DeviceInfo IS NULL THEN 1 ELSE 0 END) + (CASE WHEN i.id_30 IS NULL THEN 1 ELSE 0 END)
                            + (CASE WHEN i.id_33 IS NULL THEN 1 ELSE 0 END)) < 2""", [own])]
        members, truth = [], {}
        for c in conn.split("|"):
            ev = q("""SELECT t.TransactionID, t.amt, coalesce(i.id_15, ''), coalesce(i.id_23, '') FROM txn t
                      JOIN ident i USING (TransactionID)
                      WHERE t.card_id = ? AND list_contains(?, i.device_profile)
                        AND t.ts_dt BETWEEN CAST(? AS TIMESTAMP) - INTERVAL 30 DAY AND CAST(? AS TIMESTAMP)""",
                   [c, devices, opened, opened])
            n, new = len(ev), sum(1 for e in ev if e[2] == "New")
            proxied = sum(1 for e in ev if str(e[3]).startswith("IP_PROXY"))
            members.append(Member(c, round(sum(e[1] for e in ev), 2), conf(n, new, proxied),
                                  f"{n} use(s) of the shared device, {new} as New, {proxied} proxied", [e[0] for e in ev]))
            fraud = q("""SELECT coalesce(sum(t.amt), 0) FROM closed cc, unnest(string_split(cc.txn_ids, '|')) AS u(tid)
                         JOIN txn t ON t.TransactionID = u.tid
                         WHERE cc.card_id = ? AND cc.outcome = 'confirmed_fraud'
                           AND abs(date_diff('day', CAST(cc.opened_at AS TIMESTAMP), CAST(? AS TIMESTAMP))) <= 30""", [c, opened])
            truth[c] = round(float(fraud[0][0] or 0), 2)
        ring = {"case": case_id, "card": card, "opened_at": opened, "shared_devices": len(devices),
                "connected": len(members), "compromised": sum(1 for v in truth.values() if v > 0),
                "labelled_fraud_usd": round(sum(truth.values()), 2), "strategies": {}}
        for cost in (100.0, 250.0, 500.0):
            p = plan(members, innocent_cost=cost)
            blocked = {b["card"] for b in p["block"]}
            strategies = {"planner": blocked, "block_every_ring_card": {m.card for m in members},
                          "block_any_shared_use": {m.card for m in members if m.txns}}
            for name, cards in strategies.items():
                stopped = round(sum(truth[c] for c in cards), 2)
                innocent = sum(1 for c in cards if truth[c] == 0)
                key = f"{name}@{int(cost)}"
                ring["strategies"][key] = {"blocked": len(cards), "fraud_stopped_usd": stopped, "innocent_blocked": innocent,
                                           "net_usd": round(stopped - cost * innocent, 2)}
                t = totals.setdefault(key, {"blocked": 0, "fraud_stopped_usd": 0.0, "innocent_blocked": 0, "net_usd": 0.0})
                for k in t:
                    t[k] = round(t[k] + ring["strategies"][key][k], 2)
        out["rings"].append(ring)
    all_fraud = round(sum(r["labelled_fraud_usd"] for r in out["rings"]), 2)
    out["totals"] = totals
    out["labelled_fraud_usd"] = all_fraud
    out["connected_cards"] = sum(r["connected"] for r in out["rings"])
    out["compromised_cards"] = sum(r["compromised"] for r in out["rings"])
    (ROOT / "eval" / "containment_backtest.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{len(out['rings'])} rings, {out['connected_cards']} connected cards, {out['compromised_cards']} with their own "
          f"confirmed fraud, ${all_fraud:,.2f} labelled fraud on them")
    print(f"{'strategy':32s} {'blocked':>8s} {'fraud stopped':>14s} {'% of fraud':>10s} {'innocent':>9s} {'net':>11s}")
    for key, t in sorted(totals.items(), key=lambda kv: (kv[0].split('@')[1], kv[0])):
        pct = 100 * t["fraud_stopped_usd"] / all_fraud if all_fraud else 0
        print(f"{key:32s} {t['blocked']:>8.0f} {t['fraud_stopped_usd']:>14,.2f} {pct:>9.1f}% {t['innocent_blocked']:>9.0f} {t['net_usd']:>11,.2f}")


if __name__ == "__main__":
    main()
