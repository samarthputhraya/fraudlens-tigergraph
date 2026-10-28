"""Approvals are enforced on the server: the role comes from the token, one decision per action even under concurrency,
the route is recomputed from policy, decisions are refused on incomplete or edited answers, and the approval log is
tamper-evident (edits, forgeries, truncation, deletion). Also: the SPA route can't read files outside api/static, and
re-prove never runs a write query."""
from __future__ import annotations

import hashlib
import json
import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import safety  # noqa: E402

TL, FM = "team-lead-token-0123456789", "fraud-manager-token-0123456789"
L1, L2 = "INV-TEST-009-F1-BLOCK_CARD", "INV-TEST-009-F3-FILE_REPORT"


def write_answer(cases: Path, answer: dict, record: bool = True) -> None:
    text = json.dumps(answer, indent=2)
    (cases / "HHF-009.json").write_bytes(text.encode("utf-8"))
    if record:  # what run_cases.py records when it writes an answer
        safety.audit("case_answered", {"case_id": "HHF-009", "answer_sha256": hashlib.sha256(text.encode()).hexdigest()})


def base_answer(**over) -> dict:
    ans = {"case_id": "HHF-009", "case": {"graph_case_id": "INV-TEST-009", "exposure_usd": 228.01},
           "next_best_actions": {"final": [
               {"action": "BLOCK_CARD", "route": "L1", "reason": "R2"},
               {"action": "CREATE_CASE", "route": "auto", "reason": "3a"},
               {"action": "FILE_REPORT", "route": "L2", "reason": "R6"}]},
           "run": {"complete": True}}
    ans.update(over)
    return ans


@pytest.fixture()
def env(tmp_path, monkeypatch):
    import api.main as main
    cases = tmp_path / "cases"
    cases.mkdir()
    monkeypatch.setattr(main, "CASES", cases)
    monkeypatch.setattr(main, "AUTO", tmp_path / "none")
    monkeypatch.setattr(main, "ADHOC", tmp_path / "adhoc")
    (tmp_path / "adhoc").mkdir()
    monkeypatch.setattr(safety, "AUDIT_DIR", tmp_path / "audit")
    monkeypatch.setenv("FRAUDLENS_APPROVER_TOKENS", f"team_lead:{TL},fraud_manager:{FM}")
    monkeypatch.setenv("FRAUDLENS_AUDIT_KEY", "test-audit-key-0123456789")
    monkeypatch.setenv("FRAUDLENS_MIRROR", "1")
    write_answer(cases, base_answer())
    return {"client": TestClient(main.app), "cases": cases, "main": main}


@pytest.fixture()
def client(env):
    return env["client"]


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def status(client) -> dict:
    return {i["action_id"]: i["status"] for i in client.get("/api/approvals").json()}


# ---- roles and single decisions ------------------------------------------------------------------------------------

def test_inbox_lists_only_human_routed_actions(client):
    items = {i["action_id"]: i for i in client.get("/api/approvals").json()}
    assert set(items) == {L1, L2}
    assert items[L1]["status"] == "pending_approval_team_lead"
    assert items[L2]["status"] == "pending_approval_fraud_manager"


def test_no_token_and_bad_token_are_401(client):
    assert client.post(f"/api/approvals/{L1}", json={"approve": True}).status_code == 401
    assert client.post(f"/api/approvals/{L1}", json={"approve": True}, headers=bearer("nope-nope-nope-nope")).status_code == 401


def test_role_in_body_is_ignored(client):
    resp = client.post(f"/api/approvals/{L2}", json={"approve": True, "role": "fraud_manager"}, headers=bearer(TL))
    assert resp.status_code == 403
    assert any(e["event"] == "approval_refused" for e in safety.read_audit("approvals"))


def test_right_role_decides_once(client):
    ok = client.post(f"/api/approvals/{L2}", json={"approve": True}, headers=bearer(FM))
    assert ok.status_code == 200 and ok.json()["status"] == "approved_by_fraud_manager"
    assert client.post(f"/api/approvals/{L2}", json={"approve": False}, headers=bearer(FM)).status_code == 409
    assert status(client)[L2] == "approved_by_fraud_manager"


def test_team_lead_can_decide_l1(client):
    resp = client.post(f"/api/approvals/{L1}", json={"approve": False}, headers=bearer(TL))
    assert resp.status_code == 200 and resp.json()["status"] == "rejected_by_team_lead"


def test_unconfigured_approvals_fail_closed(client, monkeypatch):
    monkeypatch.delenv("FRAUDLENS_APPROVER_TOKENS")
    assert client.post(f"/api/approvals/{L1}", json={"approve": True}, headers=bearer(TL)).status_code == 503


def test_concurrent_decisions_record_exactly_one(env, monkeypatch):
    import agent.case_writer as cw
    monkeypatch.setenv("FRAUDLENS_MIRROR", "0")
    monkeypatch.setenv("TG_HOST", "https://example.invalid")
    calls = []

    def slow(action_id, approve, role):
        calls.append(role)
        threading.Event().wait(0.2)
        return {"ok": True}
    monkeypatch.setattr(cw, "decide_action", slow)
    codes = []

    def go(token, approve):
        codes.append(env["client"].post(f"/api/approvals/{L1}", json={"approve": approve}, headers=bearer(token)).status_code)
    ts = [threading.Thread(target=go, args=(TL, True)), threading.Thread(target=go, args=(FM, False))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(codes) == [200, 409]
    assert len(calls) == 1
    assert len([e for e in safety.read_audit("approvals") if e["event"] == "approval_decision"]) == 1


# ---- the answer behind a decision ------------------------------------------------------------------------------------

def test_route_is_recomputed_from_policy(env):
    # an answer claiming FILE_REPORT needs only a team lead: policy says L2, so nobody may decide it
    ans = base_answer()
    ans["next_best_actions"]["final"][2]["route"] = "L1"
    write_answer(env["cases"], ans)
    resp = env["client"].post(f"/api/approvals/{L2}", json={"approve": True}, headers=bearer(FM))
    assert resp.status_code == 409 and "policy section 2" in resp.json()["detail"]


def test_incomplete_answer_cannot_be_decided(env):
    write_answer(env["cases"], base_answer(run={"complete": False}))
    assert env["client"].post(f"/api/approvals/{L1}", json={"approve": True}, headers=bearer(TL)).status_code == 409


def test_edited_answer_cannot_be_decided(env):
    path = env["cases"] / "HHF-009.json"
    path.write_text(path.read_text(encoding="utf-8").replace("228.01", "228.02"), encoding="utf-8")
    resp = env["client"].post(f"/api/approvals/{L1}", json={"approve": True}, headers=bearer(TL))
    assert resp.status_code == 409 and "differs" in resp.json()["detail"]


def test_reordered_answer_does_not_move_a_decision(env):
    env["client"].post(f"/api/approvals/{L2}", json={"approve": True}, headers=bearer(FM))
    ans = base_answer()
    acts = ans["next_best_actions"]["final"]
    ans["next_best_actions"]["final"] = [acts[2], acts[1], acts[0]]
    write_answer(env["cases"], ans)
    st = status(env["client"])
    assert all(v.startswith("pending") for v in st.values())  # nothing inherited a decision by position


def test_graph_write_failure_is_an_error_and_records_no_decision(env, monkeypatch):
    import agent.case_writer as cw
    monkeypatch.setenv("FRAUDLENS_MIRROR", "0")
    monkeypatch.setenv("TG_HOST", "https://example.invalid")

    def boom(*_a, **_k):
        raise RuntimeError("graph unreachable")
    monkeypatch.setattr(cw, "decide_action", boom)
    resp = env["client"].post(f"/api/approvals/{L1}", json={"approve": True}, headers=bearer(TL))
    assert resp.status_code == 502 and "NOT recorded" in resp.json()["detail"]
    monkeypatch.setenv("FRAUDLENS_MIRROR", "1")
    assert status(env["client"])[L1] == "pending_approval_team_lead"


# ---- tamper evidence --------------------------------------------------------------------------------------------------

def decide_both(client):
    client.post(f"/api/approvals/{L1}", json={"approve": True}, headers=bearer(TL))
    client.post(f"/api/approvals/{L2}", json={"approve": True}, headers=bearer(FM))


def test_edit_is_detected_and_suspends_approvals(client):
    decide_both(client)
    path = safety.AUDIT_DIR / "approvals.jsonl"
    path.write_text(path.read_text(encoding="utf-8").replace("approved_by_team_lead", "rejected_by_team_lead"), encoding="utf-8")
    assert client.get("/api/audit/verify").json()["approvals"]["ok"] is False
    assert client.get("/api/approvals").status_code == 503


def test_forged_entry_with_a_valid_chain_hash_is_detected(client):
    decide_both(client)
    path = safety.AUDIT_DIR / "approvals.jsonl"
    last = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    forged = {"ts": last["ts"], "event": "approval_decision", "prev": last["hash"], "seq": last["seq"] + 1,
              "data": {"action_id": "X", "status": "approved_by_fraud_manager"}}
    forged["hash"] = hashlib.sha256(json.dumps(forged, sort_keys=True).encode()).hexdigest()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(forged, sort_keys=True) + "\n")
    ok, msg = safety.verify_audit("approvals")
    assert not ok


@pytest.mark.parametrize("damage", ["truncate", "empty", "delete"])
def test_removed_entries_are_detected(client, damage):
    decide_both(client)
    path = safety.AUDIT_DIR / "approvals.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    if damage == "truncate":
        path.write_text(lines[0] + "\n", encoding="utf-8")
    elif damage == "empty":
        path.write_text("", encoding="utf-8")
    else:
        path.unlink()
    assert safety.verify_audit("approvals")[0] is False
    assert client.post(f"/api/approvals/{L1}", json={"approve": False}, headers=bearer(TL)).status_code == 503


def test_unreadable_line_is_reported_not_a_crash(client):
    decide_both(client)
    with (safety.AUDIT_DIR / "approvals.jsonl").open("a", encoding="utf-8") as f:
        f.write("{not json\n")
    resp = client.get("/api/audit/verify")
    assert resp.status_code == 200 and resp.json()["approvals"]["ok"] is False


# ---- API surface -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/..%2F..%2FREADME.md", "/%2e%2e/%2e%2e/CLAUDE.md", "/..%2F..%2F.env"])
def test_spa_route_never_serves_files_outside_static(client, path):
    import api.main as main
    if not main.STATIC.exists():
        pytest.skip("no built UI")
    resp = client.get(path)
    assert "FraudLens" not in resp.text[:200] or "<html" in resp.text[:500].lower()
    assert "TG_SECRET" not in resp.text and "# FraudLens" not in resp.text


def test_reprove_refuses_write_queries(client):
    resp = client.post("/api/reprove", json={"ref": "query:build_ring_links(start_ts=2017-01-01, end_ts=2017-01-31)"})
    assert resp.json()["ok"] is False and "read-only" in resp.json()["error"]


def test_graph_client_refuses_write_queries_without_permission():
    from agent.graph_client import GraphClient
    from agent.safety import DependencyFailure
    g = GraphClient.__new__(GraphClient)  # no connection needed: the check runs before any I/O
    g.allow_write, g.agent, g._mcp = False, "lead", None
    from agent.graph_client import Trace
    g.trace = Trace()
    with pytest.raises(DependencyFailure):
        g.run("build_ring_links", {})
