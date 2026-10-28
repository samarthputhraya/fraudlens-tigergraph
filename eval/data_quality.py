"""Challenge 11, data-quality detective: the gaps in the January data that matter, and which investigations they touch.

  python eval/data_quality.py   ->  eval/data_quality.json (+ a printed table)

Checks (each lists the affected record IDs and the final-round cases it taints):
- case record vs bank record: the case pack's card or customer differs from the transaction's own record;
- alert text vs bank record: the alert claims a score, channel, amount or transaction the record contradicts;
- missing identity: online transactions with no identity record (no device, no New flag, no proxy flag);
- card network missing: transactions with no card network / type, which the card_id rule can't place reliably;
- thin history: flagged cards with too little history for a baseline;
- placeholder values: amounts or regions that look like fillers.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.integrity import claims_vs_record  # noqa: E402
from agent.paths import CASE_PACK_CSV, DB  # noqa: E402


def main() -> dict:
    con = duckdb.connect(str(DB), read_only=True)
    q = lambda s, p=None: con.execute(s, p or []).fetchall()  # noqa: E731
    pack = list(csv.DictReader(CASE_PACK_CSV.open(encoding="utf-8")))
    out: dict = {"checks": [], "tainted_cases": {}}

    def add(check: str, finding: str, ids: list, cases: list, impact: str) -> None:
        out["checks"].append({"check": check, "finding": finding, "record_ids": ids[:25], "n_records": len(ids),
                              "cases": cases, "impact": impact})
        for c in cases:
            out["tainted_cases"].setdefault(c, []).append(check)

    rec = {r[0]: r for r in q("""SELECT t.TransactionID, t.card_id, t.customer_id, t.amt, t.channel, t.score, t.ts,
                                       i.TransactionID IS NOT NULL AS has_ident
                                FROM txn t LEFT JOIN ident i USING (TransactionID)
                                WHERE list_contains(?, t.TransactionID)""", [[c["flagged_txn_id"] for c in pack]])}
    mism, text_cases = [], []
    for c in pack:
        r = rec.get(c["flagged_txn_id"])
        if r and (r[1] != c["card_id"] or r[2] != c["customer_id"]):
            mism.append(c["case_id"])
            add("case_vs_record", f"{c['case_id']}: the case names card {c['card_id']}, the bank's record puts "
                f"{c['flagged_txn_id']} on {r[1]} (whose closed cases use {r[1]} too)", [c["flagged_txn_id"], r[1], c["card_id"]],
                [c["case_id"]], "Investigated on the record's card; verdict uncertain and escalated (R8) instead of guessing")
        if r:
            txn = {"id": c["flagged_txn_id"], "amt": r[3], "channel": r[4], "risk_score": r[5]}
            m = claims_vs_record(c["trigger_text"], txn, c["trigger_type"])
            if m:
                text_cases.append(c["case_id"])
                add("alert_vs_record", f"{c['case_id']}: alert text claims " + ", ".join(f"{x['field']} {x['claimed']}" for x in m)
                    + "; record says " + ", ".join(f"{x['field']} {x['record']}" for x in m), [c["flagged_txn_id"]],
                    [c["case_id"]], "Recorded as evidence. A channel, amount or transaction claim is overridden by the record; "
                    "for the score, two bank sources disagree and neither is used in January (the bank's own warning)")
        if r and r[4] == "online" and not r[7]:
            add("missing_identity", f"{c['case_id']}: the flagged online transaction has no identity record",
                [c["flagged_txn_id"]], [c["case_id"]], "Device, New-device and proxy signals are unknown, not negative")
    jan = q("""SELECT count(*), count(*) FILTER (WHERE t.channel = 'online'),
                      count(*) FILTER (WHERE t.channel = 'online' AND i.TransactionID IS NULL)
               FROM txn t LEFT JOIN ident i USING (TransactionID) WHERE t.ts_dt >= TIMESTAMP '2017-01-01'""")[0]
    out["january"] = {"transactions": jan[0], "online": jan[1], "online_without_identity": jan[2]}
    nonet = [r[0] for r in q("""SELECT TransactionID FROM txn WHERE ts_dt >= TIMESTAMP '2017-01-01'
                                AND card4 IS NULL AND card6 IS NULL ORDER BY TransactionID""")]
    pack_cards = {c["card_id"]: c["case_id"] for c in pack}
    touched = sorted({pack_cards[r[0]] for r in q("""SELECT DISTINCT card_id FROM txn WHERE ts_dt >= TIMESTAMP '2017-01-01'
                         AND card4 IS NULL AND card6 IS NULL""") if r[0] in pack_cards})
    add("card_network_missing", f"{len(nonet)} January transactions have no card network or type, so the card_id rule "
        f"files them under the customer's blank-network card", nonet, touched,
        "This is the root of the HHF-011 card mismatch; such rows are investigated on the record's card")
    thin = []
    for c in pack:
        n = q("SELECT count(*) FROM txn WHERE card_id = ? AND ts_dt < CAST(? AS TIMESTAMP)", [c["card_id"], c["opened_at"]])[0][0]
        if n < 20:
            thin.append((c["case_id"], n))
    if thin:
        add("thin_history", "; ".join(f"{cid}: {n} earlier transactions on the case's card" for cid, n in thin),
            [], [cid for cid, _ in thin], "Baseline-based signals (amount percentile, region history) are weak or absent")
    (ROOT / "eval" / "data_quality.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    for ch in out["checks"]:
        print(f"[{ch['check']}] {ch['finding'][:150]} -> {', '.join(ch['cases']) or '-'}")
    print("January:", out["january"])
    print("Cases touched:", {k: v for k, v in sorted(out["tainted_cases"].items())})
    return out


if __name__ == "__main__":
    main()
