"""R8 conflicts (a clean purchase on a card that carries a ring signature) and the case-book consistency gate."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import casebook  # noqa: E402
from agent.policy import CONFLICT_P, Situation, plan  # noqa: E402
from agent.safety import _replace  # noqa: E402


def acts(lst):
    return [a["action"] for a in lst]


def side(**kw) -> Situation:
    d = dict(trigger="risk_score", p=0.03, verdict="legitimate", pattern="none", exposure=0.0, online=False, shared=False,
             legit_families=2, side_concern="recipient surge on 3660311, 3660312", side_shared="recipient email sc.rr.com",
             side_conflict=True, side_txns=["3660311", "3660312"], side_ring=["C01727-K2", "C04146-K1"])
    d.update(kw)
    return Situation(**d)


# ---- R8: the evidence conflicts -----------------------------------------------------------------------------------
def test_clean_purchase_on_a_ring_card_is_uncertain_and_escalated_not_cleared():
    res = plan(side())
    assert res["verdict_override"] == "uncertain" and res["p_override"] == CONFLICT_P == 0.5
    final = acts(res["branches"]["no_reply"])
    assert {"CREATE_CASE", "VERIFY_WITH_CUSTOMER", "MONITOR_CARD", "MONITOR_CONNECTED_CARDS", "ESCALATE_TO_ANALYST"} == set(final)
    # never clears the card, never acts against the customer on charges the case isn't about
    assert not {"CLOSE_NO_FRAUD", "ALLOW_TRANSACTION", "BLOCK_CARD", "BLOCK_ALL_CARDS", "FILE_REPORT"} & set(final)
    assert all(a["route"] == "auto" for a in res["initial"])
    assert res["episode_override"] == ["3660311", "3660312"] and res["connected_override"] == ["C01727-K2", "C04146-K1"]
    # the open request must not tip the customer off about a report
    assert not any(w in res["evidence_request"][1].lower() for w in ("report", "regulator", "sar"))


def test_without_a_side_conflict_the_clean_purchase_still_closes():
    res = plan(side(side_conflict=False, side_concern="", side_shared="", side_txns=[], side_ring=[]))
    assert "verdict_override" not in res
    assert acts(res["initial"]) == ["ALLOW_TRANSACTION", "CLOSE_NO_FRAUD"]


def test_a_data_conflict_also_reports_the_point_of_no_knowledge():
    res = plan(side(side_conflict=False, side_concern="", integrity_conflict=True))
    assert res["verdict_override"] == "uncertain" and res["p_override"] == 0.5


# ---- case-book gate -------------------------------------------------------------------------------------------------
def answer(cid, verdict, card_conn=(), subjects=(), side_ids=(), plan_ids=()):
    evidence = []
    if side_ids:
        evidence.append({"claim": "Other charges on this card, not the flagged transaction, match ...", "source": "graph",
                         "ref": "query:recipient_activity(...)", "entity_ids": list(side_ids)})
    if plan_ids:
        evidence.append({"claim": "Containment plan for the analyst ...", "source": "graph", "ref": "query:x",
                         "entity_ids": list(plan_ids)})
    return {"case_id": cid, "case": {"verdict": verdict, "connected_card_ids": list(card_conn), "evidence": evidence},
            "sar": {"file": bool(subjects), "subjects": list(subjects)}}


PACK = {"A": {"card_id": "C1-K1", "opened_at": "2017-01-26 20:40:00"},
        "B": {"card_id": "C2-K1", "opened_at": "2017-01-28 10:59:42"},
        "C": {"card_id": "C3-K1", "opened_at": "2017-01-31 20:31:28"},
        "D": {"card_id": "C4-K1", "opened_at": "2017-01-01 03:07:47"}}


def test_gate_finds_a_card_cleared_here_and_reported_there():
    answers = {"A": answer("A", "legitimate", side_ids=["t1", "t2"]),
               "B": answer("B", "fraud", card_conn=["C1-K1"], subjects=["C2", "C2-K1", "C1-K1"], plan_ids=["C1-K1"])}
    found = casebook.check(answers, PACK)
    high = [f for f in found if f["severity"] == "high"]
    assert len(high) == 1 and high[0]["card"] == "C1-K1" and high[0]["seen_at_open"] is True
    assert casebook.summary(found)["high_seen_at_open"] == 1
    # the fix: the clearing case becomes uncertain and goes to an analyst, and the conflict disappears
    answers["A"]["case"]["verdict"] = "uncertain"
    assert casebook.summary(casebook.check(answers, PACK))["high"] == 0


def test_gate_tells_a_later_finding_from_a_missed_one_and_notes_weak_ring_members():
    answers = {"D": answer("D", "legitimate"),
               "C": answer("C", "fraud", card_conn=["C4-K1"], subjects=["C3", "C3-K1"]),
               "A": answer("A", "legitimate"),
               "B": answer("B", "fraud", subjects=["C2", "C2-K1", "C1-K1"])}
    found = {f["card"]: f for f in casebook.check(answers, PACK) if f["severity"] != "linked"}
    assert found["C4-K1"]["severity"] == "low"                       # a monitored ring member: nothing to undo
    assert found["C1-K1"]["severity"] == "high" and not found["C1-K1"]["seen_at_open"]   # reopen, not an error


def test_gate_links_reports_that_name_the_same_card():
    answers = {"A": answer("A", "fraud", subjects=["C1", "C1-K1"]),
               "B": answer("B", "fraud", card_conn=["C1-K1"], subjects=["C2", "C2-K1", "C1-K1"])}
    linked = [f for f in casebook.check(answers, PACK) if f["severity"] == "linked"]
    assert linked == [{"severity": "linked", "card": "C1-K1", "cases": ["A", "B"],
                       "action": "continuing activity: B should cite A's report"}]


def test_frozen_answers_carry_exactly_one_decision_error():
    root = Path(__file__).resolve().parents[1]
    from agent.paths import CASE_PACK_CSV
    answers, pack = casebook.load(root / "cases_r2", CASE_PACK_CSV)
    if len(answers) != 18 or answers["HHF-013"]["case"]["verdict"] != "legitimate":
        pytest.skip("cases_r2 no longer holds the 29 Oct freeze")
    s = casebook.summary(casebook.check(answers, pack))
    assert s["high_seen_at_open"] == 1


# ---- audit writes survive a briefly locked file (Windows sync clients) -----------------------------------------------
def test_replace_retries_a_locked_target(tmp_path, monkeypatch):
    import os
    src, dst = tmp_path / "a.tmp", tmp_path / "a"
    src.write_text(json.dumps({"n": 1}))
    calls = {"n": 0}
    real = os.replace

    def flaky(a, b):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("locked")
        real(a, b)

    monkeypatch.setattr(os, "replace", flaky)
    _replace(src, dst)
    assert calls["n"] == 3 and json.loads(dst.read_text()) == {"n": 1}
