"""Embed closed-case narratives (the bank's labelled memory) for TigerVector similarity search."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.llm import embed  # noqa: E402

OUT = ROOT / "data" / "prep" / "closed_emb.json"


def case_text(r: dict) -> str:
    return (f"Outcome: {r['outcome']}. Pattern: {r['pattern']}. Exposure ${r['exposure_usd']} over {r['n_txns']} "
            f"transaction(s). Actions: {r['actions_taken']}. SAR filed: {r['report_filed']}. {r['analyst_notes']}")


def main() -> None:
    rows = list(csv.DictReader((ROOT / "data" / "raw" / "closed_cases_history.csv").open(encoding="utf-8")))
    embs = embed([case_text(r) for r in rows])
    OUT.write_text(json.dumps({r["case_id"]: e for r, e in zip(rows, embs)}), encoding="utf-8")
    print(f"embedded {len(rows)} closed cases -> {OUT}")


if __name__ == "__main__":
    main()
