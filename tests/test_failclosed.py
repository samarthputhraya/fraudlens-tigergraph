"""Fail-closed behaviour (Final Round drills): graph down mid-run, model down / timing out / returning garbage, the
same case run twice, the audit chain, and redaction.

Investigation tests run on the offline mirror with the Round 2 data and skip when it isn't built
(python graph/prep.py && python graph/export.py)."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import safety  # noqa: E402
from agent.paths import CASE_PACK_CSV, DB  # noqa: E402
from agent.safety import DependencyFailure  # noqa: E402

needs_data = pytest.mark.skipif(not DB.exists(), reason="Round 2 DuckDB not built")
CASE = "HHF-009"


@pytest.fixture(autouse=True)
def isolated_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(safety, "AUDIT_DIR", tmp_path / "audit")
    monkeypatch.delenv("FRAUDLENS_FAULT", raising=False)


def pack_row(case_id: str) -> dict:
    return next(r for r in csv.DictReader(CASE_PACK_CSV.open(encoding="utf-8")) if r["case_id"] == case_id)


def investigate(case_id: str = CASE, use_llm: bool = False) -> dict:
    from agent.mirror import MirrorGraph
    from agent.workflow import Investigator
    return Investigator(MirrorGraph(), write_graph=False, use_llm=use_llm).run(pack_row(case_id))["answer"]


# ---- audit log, redaction ------------------------------------------------------------------------------------------

def test_audit_chain_detects_edits():
    for i in range(3):
        safety.audit("event", {"i": i}, log="t")
    assert safety.verify_audit("t")[0] is True
    path = safety.AUDIT_DIR / "t.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[1])
    entry["data"]["i"] = 99
    lines[1] = json.dumps(entry, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, msg = safety.verify_audit("t")
    assert not ok and "entry 1" in msg


def test_audit_chain_detects_a_removed_entry():
    for i in range(3):
        safety.audit("event", {"i": i}, log="t")
    path = safety.AUDIT_DIR / "t.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    assert not safety.verify_audit("t")[0]


def test_redaction():
    text = safety.redact("TG_SECRET=abcd1234efgh5678 token: zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz https://tg-1.i.tgcloud.io/x")
    assert "abcd1234efgh5678" not in text and "zzzz" not in text and "tgcloud" not in text


def test_audit_entries_are_redacted():
    e = safety.audit("dependency_failure", {"detail": "401 bad secret=supersecretvalue123"}, log="t")
    assert "supersecretvalue123" not in json.dumps(e)


# ---- graph failure: stop ------------------------------------------------------------------------------------------

@needs_data
def test_mirror_query_failure_raises_and_is_logged(monkeypatch):
    from agent.mirror import MirrorGraph
    monkeypatch.setenv("FRAUDLENS_FAULT", "graph:card_window")
    g = MirrorGraph()
    with pytest.raises(DependencyFailure) as err:
        g.card_window("C09177-K1", "2017-01-01 00:00:00", "2017-01-31 00:00:00")
    assert err.value.dependency == "graph"
    assert g.trace.calls[-1].ok is False
    assert any(e["event"] == "dependency_failure" for e in safety.read_audit())


@needs_data
@pytest.mark.parametrize("query", ["txn_context", "card_window", "account_history", "prior_cases"])
def test_graph_down_mid_investigation_stops_the_case(monkeypatch, query):
    monkeypatch.setenv("FRAUDLENS_FAULT", f"graph:{query}")
    with pytest.raises(DependencyFailure) as err:
        investigate()
    assert err.value.step == query


@needs_data
def test_runner_writes_no_answer_and_exits_2_when_the_graph_fails(tmp_path):
    out = tmp_path / "out"
    env = {**__import__("os").environ, "FRAUDLENS_FAULT": "graph:card_window",
           "FRAUDLENS_AUDIT_DIR": str(tmp_path / "audit")}
    proc = subprocess.run([sys.executable, "run_cases.py", "--mirror", "--no-write", "--no-llm", "--out",
                           str(out.relative_to(tmp_path)) if False else str(out), CASE],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "STOPPED" in proc.stdout
    assert not (out / f"{CASE}.json").exists()
    assert list((out / "traces").glob(f"{CASE}.FAILED.*.json"))


# ---- model failure: decision stands, case escalated, nothing hidden -------------------------------------------------

@needs_data
@pytest.mark.parametrize("fault", ["llm:*", "llm_timeout:*", "llm_garbage:*"])
def test_model_failure_marks_the_answer_incomplete(monkeypatch, fault):
    monkeypatch.setenv("FRAUDLENS_FAULT", fault + ",llm:embed")
    ans = investigate(use_llm=True)
    assert ans["run"]["complete"] is False
    assert ans["run"]["failures"]
    assert ans["case"]["status"] == "escalated"
    assert any(a["action"] == "ESCALATE_TO_ANALYST" for a in ans["next_best_actions"]["final"])
    assert "Escalated to an analyst" in ans["next_best_actions"]["what_changed"]
    assert ans["stop_reason"].startswith("Stopped incomplete")
    assert ans["case"]["summary"].startswith("[Template text")


@needs_data
def test_model_failure_does_not_change_the_decision(monkeypatch):
    baseline = investigate(use_llm=False)
    monkeypatch.setenv("FRAUDLENS_FAULT", "llm:*,llm:embed")
    failed = investigate(use_llm=True)
    for key in ("verdict", "fraud_probability", "pattern", "affected_txn_ids", "exposure_usd"):
        assert failed["case"][key] == baseline["case"][key], key


# ---- same case twice ----------------------------------------------------------------------------------------------

VOLATILE = {"latency_s", "tokens", "run"}


@needs_data
def test_same_case_twice_gives_the_same_answer():
    a, b = investigate(), investigate()
    strip = lambda x: {k: v for k, v in x.items() if k not in VOLATILE}  # noqa: E731
    assert json.dumps(strip(a), sort_keys=True) == json.dumps(strip(b), sort_keys=True)


# ---- invalid input, stale answers, garbage text (second review) ---------------------------------------------------------

def test_check_row_rejects_malformed_rows():
    import run_cases
    from agent.safety import InvalidInput
    row = pack_row(CASE)
    for bad in ({"opened_at": "yesterday"}, {"trigger_type": "rumour"}, {"flagged_txn_id": ""}):
        with pytest.raises(InvalidInput):
            run_cases.check_row({**row, **bad})


@needs_data
@pytest.mark.parametrize("bad", [{"flagged_txn_id": "9999999"}, {"opened_at": "2016-12-01 00:00:00"}])
def test_invalid_case_stops_with_a_clear_error(bad):
    from agent.mirror import MirrorGraph
    from agent.safety import InvalidInput
    from agent.workflow import Investigator
    with pytest.raises(InvalidInput):
        Investigator(MirrorGraph(), write_graph=False, use_llm=False).run({**pack_row(CASE), **bad})


@needs_data
def test_another_customers_card_is_flagged_and_reconciled():
    from agent.mirror import MirrorGraph
    from agent.workflow import Investigator
    row = {**pack_row(CASE), "card_id": "C07196-K2", "customer_id": "C07196"}
    ans = Investigator(MirrorGraph(), write_graph=False, use_llm=False).run(row)["answer"]
    assert ans["case"]["verdict"] == "uncertain"
    assert any(a["action"] == "ESCALATE_TO_ANALYST" for a in ans["next_best_actions"]["final"])
    assert any("case record names card C07196-K2" in e["claim"] for e in ans["case"]["evidence"])


@needs_data
def test_stopped_rerun_moves_the_old_answer_aside(tmp_path):
    import os
    out = tmp_path / "out"
    env = {**os.environ, "FRAUDLENS_AUDIT_DIR": str(tmp_path / "audit")}
    cmd = [sys.executable, "run_cases.py", "--mirror", "--no-write", "--no-llm", "--out", str(out), CASE]
    assert subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=600).returncode == 0
    assert (out / f"{CASE}.json").exists()
    proc = subprocess.run(cmd, cwd=ROOT, env={**env, "FRAUDLENS_FAULT": "graph:card_window"}, capture_output=True,
                          text=True, timeout=600)
    assert proc.returncode == 2
    assert not (out / f"{CASE}.json").exists()
    assert list((out / "stale").glob(f"*{CASE}*.json"))


@needs_data
def test_garbage_writer_text_is_a_model_failure(monkeypatch):
    import random
    from agent import evidence, llm, roles
    from agent.mirror import MirrorGraph
    from agent.workflow import Investigator
    rng = random.Random(7)
    vec = [rng.random() for _ in range(768)]
    monkeypatch.setattr(evidence, "embed_query", lambda *_a, **_k: vec)
    monkeypatch.setattr(llm, "embed_query", lambda *_a, **_k: vec)
    monkeypatch.setattr(roles, "lead_plan", lambda *a, **k: {"hypotheses": [], "extra_calls": [], "focus": ""})
    monkeypatch.setattr(roles, "run_specialists", lambda *a, **k: {})
    monkeypatch.setattr(roles, "critic", lambda *a, **k: {"agree": True, "issues": [], "what_would_change_verdict": ""})
    monkeypatch.setattr(roles, "writer", lambda *a, **k: {"summary": "asdf qwer zxcv lorem ipsum",
                                                          "sar_narrative": "fine", "pattern_description": "x"})
    ans = Investigator(MirrorGraph(), write_graph=False, use_llm=True).run(pack_row("HHF-007"))["answer"]
    assert ans["run"]["complete"] is False
    assert any(f["step"] == "writer" for f in ans["run"]["failures"])
    assert ans["case"]["summary"].startswith("[Template text")
