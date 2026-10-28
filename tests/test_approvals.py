"""Approvals are enforced on the server: the role comes from the token, one decision per action, an append-only
hash-chained log, and a failed graph write is an error, never `ok`."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import safety  # noqa: E402

TL, FM = "team-lead-token-0123456789", "fraud-manager-token-0123456789"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import api.main as main
    cases = tmp_path / "cases"
    cases.mkdir()
    answer = {"case_id": "HHF-009", "case": {"graph_case_id": "INV-TEST-009", "exposure_usd": 228.01},
              "next_best_actions": {"final": [
                  {"action": "BLOCK_CARD", "route": "L1", "reason": "R2"},
                  {"action": "CREATE_CASE", "route": "auto", "reason": "3a"},
                  {"action": "FILE_REPORT", "route": "L2", "reason": "R6"}]}}
    (cases / "HHF-009.json").write_text(json.dumps(answer), encoding="utf-8")
    monkeypatch.setattr(main, "CASES", cases)
    monkeypatch.setattr(main, "AUTO", tmp_path / "none")
    monkeypatch.setattr(main, "ADHOC", tmp_path / "adhoc")
    (tmp_path / "adhoc").mkdir()
    monkeypatch.setattr(safety, "AUDIT_DIR", tmp_path / "audit")
    monkeypatch.setenv("FRAUDLENS_APPROVER_TOKENS", f"team_lead:{TL},fraud_manager:{FM}")
    monkeypatch.setenv("FRAUDLENS_MIRROR", "1")
    return TestClient(main.app)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


L1, L2 = "INV-TEST-009-F1", "INV-TEST-009-F3"


def test_inbox_lists_only_human_routed_actions(client):
    items = {i["action_id"]: i for i in client.get("/api/approvals").json()}
    assert set(items) == {L1, L2}
    assert items[L1]["status"] == "pending_approval_team_lead"
    assert items[L2]["status"] == "pending_approval_fraud_manager"


def test_no_token_is_401(client):
    assert client.post(f"/api/approvals/{L1}", json={"approve": True}).status_code == 401


def test_bad_token_is_401(client):
    assert client.post(f"/api/approvals/{L1}", json={"approve": True}, headers=bearer("nope-nope-nope-nope")).status_code == 401


def test_role_in_body_is_ignored(client):
    # a team lead claiming to be a fraud manager in the body still can't decide an L2 action
    resp = client.post(f"/api/approvals/{L2}", json={"approve": True, "role": "fraud_manager"}, headers=bearer(TL))
    assert resp.status_code == 403
    assert any(e["event"] == "approval_refused" for e in safety.read_audit("approvals"))


def test_right_role_decides_once(client):
    ok = client.post(f"/api/approvals/{L2}", json={"approve": True}, headers=bearer(FM))
    assert ok.status_code == 200 and ok.json()["status"] == "approved_by_fraud_manager"
    again = client.post(f"/api/approvals/{L2}", json={"approve": False}, headers=bearer(FM))
    assert again.status_code == 409
    status = {i["action_id"]: i["status"] for i in client.get("/api/approvals").json()}
    assert status[L2] == "approved_by_fraud_manager"


def test_team_lead_can_decide_l1(client):
    resp = client.post(f"/api/approvals/{L1}", json={"approve": False}, headers=bearer(TL))
    assert resp.status_code == 200 and resp.json()["status"] == "rejected_by_team_lead"


def test_unconfigured_approvals_fail_closed(client, monkeypatch):
    monkeypatch.delenv("FRAUDLENS_APPROVER_TOKENS")
    assert client.post(f"/api/approvals/{L1}", json={"approve": True}, headers=bearer(TL)).status_code == 503


def test_graph_write_failure_is_an_error_and_records_no_decision(client, monkeypatch):
    import agent.case_writer as cw
    monkeypatch.setenv("FRAUDLENS_MIRROR", "0")
    monkeypatch.setenv("TG_HOST", "https://example.invalid")

    def boom(*_a, **_k):
        raise RuntimeError("graph unreachable")
    monkeypatch.setattr(cw, "decide_action", boom)
    resp = client.post(f"/api/approvals/{L1}", json={"approve": True}, headers=bearer(TL))
    assert resp.status_code == 502
    assert "NOT recorded" in resp.json()["detail"]
    monkeypatch.setenv("FRAUDLENS_MIRROR", "1")
    status = {i["action_id"]: i["status"] for i in client.get("/api/approvals").json()}
    assert status[L1] == "pending_approval_team_lead"


def test_tampering_with_the_approval_log_is_detected(client):
    client.post(f"/api/approvals/{L1}", json={"approve": True}, headers=bearer(TL))
    client.post(f"/api/approvals/{L2}", json={"approve": True}, headers=bearer(FM))
    path = safety.AUDIT_DIR / "approvals.jsonl"
    text = path.read_text(encoding="utf-8").replace("approved_by_team_lead", "rejected_by_team_lead")
    path.write_text(text, encoding="utf-8")
    assert client.get("/api/audit/verify").json()["approvals"]["ok"] is False
