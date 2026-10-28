"""Where each round's data lives.

FRAUDLENS_ROUND=r2 (the default) is the TigerGraph Final Round: Round 1's July-December files plus January 2017,
the replaced closed-case history (5,585 cases) and the 18-case final pack. FRAUDLENS_ROUND=r1 reproduces the
Round 1 submission exactly.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREP = ROOT / "data" / "prep"
RAW_R1 = ROOT / "data" / "raw"
RAW_R2 = ROOT / "data" / "raw_r2" / "share"

ROUND = os.getenv("FRAUDLENS_ROUND", "r2").lower()
if ROUND not in ("r1", "r2"):
    raise SystemExit(f"FRAUDLENS_ROUND must be r1 or r2, not {ROUND!r}")
R2 = ROUND == "r2"

TXN_CSVS = [RAW_R1 / "transactions.csv"] + ([RAW_R2 / "transactions_2017q1.csv"] if R2 else [])
IDENT_CSVS = [RAW_R1 / "identity.csv"] + ([RAW_R2 / "identity_2017q1.csv"] if R2 else [])
CLOSED_CSV = (RAW_R2 if R2 else RAW_R1) / "closed_cases_history.csv"
CASE_PACK_CSV = RAW_R2 / "cases" / "case_pack_final.csv" if R2 else RAW_R1 / "case_pack.csv"
POLICY_MD = RAW_R2 / "policy" / "fraud_policy.md"
GRADER = RAW_R2 / "grader" / "grade.py"

DB = PREP / ("hhgoa_r2.duckdb" if R2 else "hhgoa.duckdb")
MODEL_SCORES = PREP / ("model_scores_r2.parquet" if R2 else "model_scores.parquet")
LOAD_DIR = PREP / ("load_r2" if R2 else "load")
CASES_OUT = ROOT / ("cases_r2" if R2 else "cases")
