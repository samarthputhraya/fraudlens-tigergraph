"""Train the transaction fraud model on the bank's own closed cases and score every transaction.

Label: the transaction belongs to a confirmed-fraud closed case (July-October). Everything else, including the
transactions of cleared alerts, is 0. The public IEEE-CIS files are never used.

Temporal protocol (no leakage):
- validation model: trained on July-September, evaluated on October -> the honest numbers in eval/model_report.json,
  the isotonic calibration map, and the October scores used by the backtest (eval/backtest.py);
- production model: trained on July-October with the same number of rounds, scores November-December (the 20 cases).

Outputs: data/prep/model_scores.parquet (TransactionID, p_raw, p_cal, model), eval/model_report.json.
Usage:  python -m ml.train
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, roc_auc_score

from ml.features import PREP, ROOT, build, encode

PARAMS = dict(objective="binary", learning_rate=0.03, num_leaves=256, min_child_samples=50, feature_fraction=0.4,
              bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1, n_jobs=16, seed=7)


def _auc(y, p) -> float:
    return round(float(roc_auc_score(y, p)), 4) if len(set(y)) > 1 else float("nan")


def _reliability(y: np.ndarray, p: np.ndarray) -> list[dict]:
    bins = [0, .01, .02, .05, .1, .2, .3, .5, .7, .9, 1.0]
    out = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (p > lo) & (p <= hi) if lo > 0 else (p <= hi)
        if m.sum():
            out.append({"bin": f"{lo:.2f}-{hi:.2f}", "n": int(m.sum()), "predicted": round(float(p[m].mean()), 4),
                        "observed": round(float(y[m].mean()), 4)})
    return out


def fit_validate(df: pd.DataFrame, feats: list[str], tag: str) -> tuple[lgb.Booster, np.ndarray, dict]:
    tr, va = df.month.isin([7, 8, 9]), df.month == 10
    X = df[feats].astype(np.float32)
    m = lgb.train(PARAMS, lgb.Dataset(X[tr], df.y[tr]), 3000,
                  valid_sets=[lgb.Dataset(X[va], df.y[va])], callbacks=[lgb.early_stopping(150, verbose=False)])
    p = m.predict(X[va], num_iteration=m.best_iteration)
    v = df.loc[va, ["TransactionID", "y", "cleared", "risk_score"]].assign(p=p)
    cases = v[(v.y == 1) | (v.cleared == 1)]
    hs = v[v.risk_score >= 0.5]
    stats = {"model": tag, "best_iteration": m.best_iteration, "n_train": int(tr.sum()), "n_valid": int(va.sum()),
             "fraud_rate_valid": round(float(v.y.mean()), 4),
             "auc_october_all": _auc(v.y, v.p),
             "auc_october_alerts_score_ge_0_5": _auc(hs.y, hs.p), "n_alerts_score_ge_0_5": int(len(hs)),
             "auc_october_confirmed_vs_cleared": _auc(cases.y, cases.p), "n_closed_case_txns": int(len(cases))}
    return m, v, stats


def main() -> None:
    t0 = time.time()
    df = build()
    df, feats = encode(df)
    print(f"features: {len(feats)} on {len(df):,} transactions ({time.time() - t0:.0f}s)", flush=True)
    no_score = [f for f in feats if f != "risk_score"]

    m_ws, v_ws, s_ws = fit_validate(df, feats, "with the bank's risk score")
    print(s_ws, flush=True)
    _, _, s_ns = fit_validate(df, no_score, "without the bank's risk score")
    print(s_ns, flush=True)

    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(v_ws.p, v_ws.y)
    v_ws["p_cal"] = iso.predict(v_ws.p)
    s_ws["brier_october_raw"] = round(float(brier_score_loss(v_ws.y, v_ws.p)), 5)
    s_ws["brier_october_calibrated_in_sample"] = round(float(brier_score_loss(v_ws.y, v_ws.p_cal)), 5)
    imp = pd.Series(m_ws.feature_importance("gain"), index=feats).sort_values(ascending=False)

    # production model: July-October, same number of rounds (+10% for the extra month)
    tr = df.month <= 10
    X = df[feats].astype(np.float32)
    m_prod = lgb.train(PARAMS, lgb.Dataset(X[tr], df.y[tr]), int(m_ws.best_iteration * 1.1))
    te = df.month >= 11
    p_te = m_prod.predict(X[te])
    m_prod.save_model(str(PREP / "txn_model.txt"))
    m_ws.save_model(str(PREP / "txn_model_julsep.txt"))

    scores = pd.concat([
        pd.DataFrame({"TransactionID": v_ws.TransactionID.values, "p_raw": v_ws.p.values, "p_cal": v_ws.p_cal.values,
                      "model": "jul-sep"}),
        pd.DataFrame({"TransactionID": df.loc[te, "TransactionID"].values, "p_raw": p_te, "p_cal": iso.predict(p_te),
                      "model": "jul-oct"}),
    ])
    scores.to_parquet(PREP / "model_scores.parquet", index=False)

    hs = v_ws[v_ws.risk_score >= 0.5]
    bank = {"auc_october_all": _auc(v_ws.y, v_ws.risk_score), "auc_october_alerts_score_ge_0_5": _auc(hs.y, hs.risk_score),
            "note": "the bank's risk_score column alone, same October transactions and labels"}
    report = {
        "bank_score": bank,
        "label": "transaction belongs to a confirmed-fraud closed case (closed_cases_history.csv)",
        "protocol": "train July-September, validate October; production model trained July-October scores Nov-Dec",
        "n_features": len(feats), "validation": s_ws, "validation_without_risk_score": s_ns,
        "reliability_october_raw": _reliability(v_ws.y.values, v_ws.p.values),
        "top_features": [{"feature": k, "gain_share": round(float(g / imp.sum()), 4)} for k, g in imp.head(20).items()],
        "novdec_mean_p_cal": round(float(np.mean(iso.predict(p_te))), 4),
        "seconds": round(time.time() - t0, 1),
    }
    (ROOT / "eval" / "model_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("validation", "validation_without_risk_score", "top_features")}, indent=1))


if __name__ == "__main__":
    main()
