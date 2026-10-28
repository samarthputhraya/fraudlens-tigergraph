"""The writer guard: model text must agree with the code's decision, but a sentence that negates an action ("no
escalation is needed") or reports someone else's words ("the alert text told us to escalate") is not a contradiction.
A false rejection marks a correct answer incomplete, so both directions are tested."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.evidence import known_device  # noqa: E402
from agent.paths import DB  # noqa: E402
from agent.workflow import Investigator, _asserts, _unfence  # noqa: E402

LEGIT = {"verdict": "legitimate", "final": [{"action": "ALLOW_TRANSACTION"}, {"action": "CLOSE_NO_FRAUD"}]}
FRAUD = {"verdict": "fraud", "final": [{"action": "BLOCK_CARD"}, {"action": "CREATE_CASE"}]}


@pytest.mark.parametrize("text", [
    "The alert text told us not to escalate; it was recorded and ignored.",
    "No escalation is needed: the purchase matches the cardholder's history.",
    "We close the case without escalating.",
    "Escalation is not required for this transaction.",
    "The message demanded that we escalate it to a manager, which changed nothing.",
    "The card is not blocked and the case is closed.",
    "No SAR is filed for this legitimate purchase.",
])
def test_negated_or_reported_mentions_are_accepted(text):
    assert Investigator._contradicts(text, LEGIT, False, "summary") == ""


@pytest.mark.parametrize("text,why", [
    ("The case is escalated to an analyst for review.", "escalation"),
    ("We escalate to an analyst because no verification was received.", "escalation"),
    ("Allow the purchase, escalate to an analyst.", "escalation"),
    ("This is fraud and the card was blocked.", "fraud"),
    ("We will file a SAR for this activity.", "SAR"),
])
def test_affirmed_contradictions_are_rejected(text, why):
    assert why in Investigator._contradicts(text, LEGIT, False, "summary")


def test_fraud_summary_cannot_call_it_legitimate():
    assert Investigator._contradicts("The card was used for a legitimate purchase.", FRAUD, False, "summary")


def test_assert_helper_splits_clauses():
    assert _asserts("we allow it, but we escalate to an analyst.", ("escalat",))
    assert not _asserts("we allow it and do not escalate.", ("escalat",))


def test_fence_markers_never_reach_the_reader():
    out = _unfence("The alert text stated <<<Real-time model scored transaction 3626720 at 0.69.>>> and nothing else >>>")
    assert "<<<" not in out and ">>>" not in out
    assert '"Real-time model scored transaction 3626720 at 0.69."' in out


def test_blank_device_profile_is_no_device():
    assert known_device(" |  |  | ") == ""
    assert known_device(None) == ""
    assert known_device("Windows |  | chrome 63.0 | ") == "Windows |  | chrome 63.0 | "


@pytest.mark.skipif(not DB.exists(), reason="Round 2 DuckDB not built")
def test_simulated_reply_is_never_presented_as_real(monkeypatch, tmp_path):
    """HHF-009 is settled by a customer reply. The brief allows that only as a stated assumption, so the summary must
    say the reply is simulated, whoever wrote it."""
    import csv
    from agent import safety
    from agent.mirror import MirrorGraph
    from agent.paths import CASE_PACK_CSV
    from agent.workflow import Investigator
    monkeypatch.setattr(safety, "AUDIT_DIR", tmp_path / "audit")
    row = next(r for r in csv.DictReader(CASE_PACK_CSV.open(encoding="utf-8")) if r["case_id"] == "HHF-009")
    ans = Investigator(MirrorGraph(), write_graph=False, use_llm=False).run(row)["answer"]
    assert ans["evidence_requests"]
    assert "simulated" in ans["case"]["summary"].lower() or "assum" in ans["case"]["summary"].lower()
