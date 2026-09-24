"""Temporal backtest of the deterministic investigation core on the bank's closed cases.

For each sampled closed case we replay the alert as it looked when it fired: the flagged transaction is the case's
last transaction, `opened_at` = flagged time + 6 h, and memory only contains closed cases opened BEFORE the alert
(the case's own labels are masked). All cases are presented as model alerts (risk_score trigger, real score), so the
engine sees no customer statement. We score:
  verdict accuracy (fraud vs cleared), Brier score + reliability of the calibrated probability, pattern accuracy,
  episode Jaccard vs the case's txn_ids, exposure MAE and SAR agreement (for confirmed cases).
Writes eval/report.json and eval/report.md.
"""
from __future__ import annotations

import json
import random
import sys
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.assess import ledger, pattern_of, verdict_of  # noqa: E402
from agent.core import amount_of, situation  # noqa: E402
from agent.detectors import run_detectors  # noqa: E402
from agent.evidence import P, gather  # noqa: E402
from agent.mirror import MirrorGraph  # noqa: E402
from agent.policy import sar_required  # noqa: E402


def main(n_fraud: int = 350, month: str = "2016-10") -> None:
    g = MirrorGraph()
    closed = g._rows(f"SELECT * FROM closed WHERE opened_at LIKE '{month}%'")
    fraud = [c for c in closed if c["outcome"] == "confirmed_fraud"]
    cleared = [c for c in closed if c["outcome"] == "cleared"]
    random.seed(7)
    sample = random.sample(fraud, min(n_fraud, len(fraud))) + cleared
    # keep the rare patterns in the sample
    for c in closed:
        if c["pattern"] in ("card_testing", "undocumented") and c not in sample:
            sample.append(c)
    rows, t0 = [], time.time()
    for i, c in enumerate(sample):
        txns = [t for t in c["txn_ids"].split("|") if t]
        info = g._rows("SELECT TransactionID id, strftime(ts_dt, '%Y-%m-%d %H:%M:%S') ts, score FROM txn WHERE TransactionID IN (SELECT unnest(?))", [txns])
        info.sort(key=lambda r: r["ts"])
        flagged = info[-1]
        opened = (P(flagged["ts"]) + timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
        g.cutoff = min(opened, c["opened_at"])
        g.exclude = {c["case_id"]}
        case = {"case_id": c["case_id"], "opened_at": opened, "trigger_type": "risk_score", "trigger_text": "",
                "flagged_txn_id": flagged["id"], "card_id": c["card_id"], "customer_id": c["customer_id"],
                "risk_score": str(flagged["score"])}
        try:
            ep = gather(case, g)
            findings, facts = run_detectors(ep)
            led = ledger("risk_score", findings, float(flagged["score"]))
            v = verdict_of(led["p"], led, "risk_score")
            pat, _ = pattern_of("fraud", facts, ep.txn)
            ep_ids = facts["episode"]
            exp, _ = amount_of(ep, ep_ids)
            sit = situation(ep, findings, facts, led, "fraud", pat, exp)
            sar = sar_required(sit, "fraud")
        except Exception as e:  # noqa: BLE001
            print("skip", c["case_id"], e)
            continue
        truth = [t for t in txns if t <= flagged["id"] or True]
        inter = len(set(ep_ids) & set(txns))
        rows.append({"case_id": c["case_id"], "outcome": c["outcome"], "pattern": c["pattern"], "p": led["p"], "verdict": v,
                     "pred_pattern": pat, "jaccard": inter / len(set(ep_ids) | set(txns)), "exposure": exp,
                     "true_exposure": float(c["exposure_usd"]), "sar_pred": sar, "sar_true": c["report_filed"] == "Yes",
                     "strong": led["strong"], "score": float(flagged["score"]),
                     "model_p": facts.get("model_p"),
                     "evidence_logodds": round(sum(x["delta_logodds"] for x in led["contributions"]), 3)})
        if i % 50 == 0:
            print(f"{i}/{len(sample)} {time.time() - t0:.0f}s", flush=True)
    rep = score(rows)
    (ROOT / "eval" / "report.json").write_text(json.dumps(rep, indent=1))
    (ROOT / "eval" / "backtest_rows.json").write_text(json.dumps(rows))
    print(json.dumps({k: v for k, v in rep.items() if k != "reliability"}, indent=1))


def score(rows: list[dict]) -> dict:
    fr = [r for r in rows if r["outcome"] == "confirmed_fraud"]
    cl = [r for r in rows if r["outcome"] == "cleared"]
    y = lambda r: 1.0 if r["outcome"] == "confirmed_fraud" else 0.0  # noqa: E731
    # verdict accuracy on decided cases, uncertain counted separately
    decided = [r for r in rows if r["verdict"] != "uncertain"]
    acc = sum(1 for r in decided if (r["verdict"] == "fraud") == (y(r) == 1)) / max(len(decided), 1)
    # balanced Brier (weight classes equally)
    brier_f = sum((r["p"] - 1) ** 2 for r in fr) / max(len(fr), 1)
    brier_c = sum((r["p"] - 0) ** 2 for r in cl) / max(len(cl), 1)
    rel = []
    for lo in [i / 10 for i in range(10)]:
        b = [r for r in rows if lo <= r["p"] < lo + 0.1 or (lo == 0.9 and r["p"] == 1.0)]
        if b:
            rel.append({"bin": f"{lo:.1f}-{lo + 0.1:.1f}", "predicted": round(sum(r["p"] for r in b) / len(b), 3),
                        "observed": round(sum(y(r) for r in b) / len(b), 3), "n": len(b)})
    pat_ok = [r for r in fr if r["pred_pattern"] == r["pattern"]]

    def auc(rs):
        pos = [r["evidence_logodds"] for r in rs if y(r) == 1]
        neg = [r["evidence_logodds"] for r in rs if y(r) == 0]
        if not pos or not neg:
            return None
        wins = sum((1.0 if a > b else 0.5 if a == b else 0.0) for a in pos for b in neg)
        return round(wins / (len(pos) * len(neg)), 3)
    band = [r for r in rows if r.get("score", 0) >= 0.5]

    def auc_p(rs, key="p"):
        pos = [r[key] for r in rs if y(r) == 1 and r.get(key) is not None]
        neg = [r[key] for r in rs if y(r) == 0 and r.get(key) is not None]
        if not pos or not neg:
            return None
        wins = sum((1.0 if a > b else 0.5 if a == b else 0.0) for a in pos for b in neg)
        return round(wins / (len(pos) * len(neg)), 3)
    return {
        "auc_final_probability": auc_p(rows), "auc_final_probability_score_ge_0_5": auc_p(band),
        "auc_model_only": auc_p(rows, "model_p"),
        "n_cases": len(rows), "n_confirmed": len(fr), "n_cleared": len(cl),
        "verdict_accuracy": round(acc, 3), "uncertain_share": round(1 - len(decided) / max(len(rows), 1), 3),
        "fraud_recall": round(sum(1 for r in fr if r["verdict"] == "fraud") / max(len(fr), 1), 3),
        "cleared_specificity": round(sum(1 for r in cl if r["verdict"] == "legitimate") / max(len(cl), 1), 3),
        "brier_balanced": round((brier_f + brier_c) / 2, 3),
        "pattern_accuracy": round(len(pat_ok) / max(len(fr), 1), 3),
        "pattern_confusion": Counter(f"{r['pattern']}->{r['pred_pattern']}" for r in fr).most_common(12),
        "episode_jaccard": round(sum(r["jaccard"] for r in fr) / max(len(fr), 1), 3),
        "exposure_mae": round(sum(abs(r["exposure"] - r["true_exposure"]) for r in fr) / max(len(fr), 1), 2),
        "sar_agreement": round(sum(1 for r in fr if r["sar_pred"] == r["sar_true"]) / max(len(fr), 1), 3),
        "reliability": rel,
        "evidence_auc_all": auc(rows),
        "evidence_auc_score_ge_0_5": auc(band), "n_score_ge_0_5": len(band),
        "note": ("Closed history is selection-biased: every cleared case is a high-score model alert and most confirmed "
                 "cases came from low-score customer reports, so raw verdict accuracy/Brier here are not meaningful. "
                 "evidence_auc_* measures how well graph evidence alone (excluding the score prior) separates fraud "
                 "from false alarms."),
    }


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 350)
