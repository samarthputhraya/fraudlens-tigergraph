"""Answer-file tests: every submitted case file passes the schema + policy validator and is internally consistent."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.answer import validate  # noqa: E402

FILES = sorted((ROOT / "cases").glob("HHG-*.json"))


@pytest.mark.parametrize("path", FILES, ids=[p.stem for p in FILES])
def test_answer_file_valid(path):
    ans = json.loads(path.read_text(encoding="utf-8"))
    assert ans["case_id"] == path.stem
    assert validate(ans) == []


@pytest.mark.parametrize("path", FILES, ids=[p.stem for p in FILES])
def test_exposure_and_dates(path):
    ans = json.loads(path.read_text(encoding="utf-8"))
    c = ans["case"]
    if c["verdict"] == "legitimate":
        assert c["exposure_usd"] == 0 and not c["affected_txn_ids"] and not ans["sar"]["file"]
    if ans["sar"]["file"]:
        assert ans["sar"]["total_amount_usd"] == c["exposure_usd"]
        assert ans["sar"]["activity_dates"][0] <= ans["sar"]["activity_dates"][1]
        assert 5 <= ans["sar"]["narrative"].count(". ") + 1 <= 16


def test_all_twenty_present():
    assert len(FILES) == 20
