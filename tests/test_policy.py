"""Policy-as-code tests: every rule in Fraud Policy v1.0 that the engine implements."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.policy import Situation, plan, route, sar_required, status_of  # noqa: E402


def acts(lst):
    return [a["action"] for a in lst]


def base(**kw) -> Situation:
    d = dict(trigger="risk_score", p=0.5, verdict="uncertain", pattern="card_not_present_fraud", exposure=100.0,
             online=True, shared=False)
    d.update(kw)
    return Situation(**d)


# ---- section 2: approval routing --------------------------------------------------------------
@pytest.mark.parametrize("action,exposure,expected", [
    ("ALLOW_TRANSACTION", 10, "auto"), ("VERIFY_WITH_CUSTOMER", 10, "auto"), ("CREATE_CASE", 10, "auto"),
    ("ESCALATE_TO_ANALYST", 10, "auto"), ("MONITOR_CONNECTED_CARDS", 10, "auto"), ("CLOSE_NO_FRAUD", 10, "auto"),
    ("DECLINE_TRANSACTION", 10, "L1"), ("BLOCK_CARD", 2500, "L1"), ("BLOCK_CARD", 2500.01, "L2"),
    ("BLOCK_ALL_CARDS", 1, "L2"), ("FILE_REPORT", 1, "L2"),
])
def test_routes(action, exposure, expected):
    assert route(action, exposure) == expected


def test_unknown_action_rejected():
    with pytest.raises(ValueError):
        route("REFUND_CUSTOMER", 10)


# ---- R1: verify before blocking on a weak signal ----------------------------------------------
def test_r1_single_signal_verifies_before_block():
    pl = plan(base(p=0.45, single_signal=True))
    assert "BLOCK_CARD" not in acts(pl["initial"])
    assert {"VERIFY_WITH_CUSTOMER", "STEP_UP_AUTH"} & set(acts(pl["initial"]))
    assert "CREATE_CASE" in acts(pl["initial"])  # section 3a: evidence requested -> open a case


# ---- R2 / R3 / R4 branches ---------------------------------------------------------------------
def test_branches_confirm_deny_noreply():
    pl = plan(base(p=0.55, exposure=1200, online=True))
    assert acts(pl["branches"]["confirm"]) == ["ALLOW_TRANSACTION", "CLOSE_NO_FRAUD"]            # R3
    assert "BLOCK_CARD" in acts(pl["branches"]["deny"]) and "FILE_REPORT" in acts(pl["branches"]["deny"])  # R2 > $1,000
    nr = acts(pl["branches"]["no_reply"])
    assert "MONITOR_CARD" in nr and "DECLINE_TRANSACTION" in nr and "ESCALATE_TO_ANALYST" in nr  # R4, exposure > $500


def test_r4_no_escalation_under_500():
    pl = plan(base(p=0.55, exposure=120))
    assert "ESCALATE_TO_ANALYST" not in acts(pl["branches"]["no_reply"])


def test_r2_customer_report_small_no_sar():
    pl = plan(base(trigger="customer_report", p=0.8, verdict="fraud", exposure=128.33))
    assert acts(pl["initial"])[:2] == ["BLOCK_CARD", "CREATE_CASE"]
    assert "FILE_REPORT" not in acts(pl["initial"])


def test_r2_shared_device_triggers_sar():
    pl = plan(base(trigger="customer_report", p=0.9, verdict="fraud", exposure=200, shared=True,
                   connected_cards=["C1-K1", "C2-K1"], shared_desc="device profile X"))
    a = acts(pl["initial"])
    assert "FILE_REPORT" in a and "MONITOR_CONNECTED_CARDS" in a   # R2 + R6


# ---- R5: card testing ---------------------------------------------------------------------------
def test_r5_card_testing_decline_and_step_up():
    pl = plan(base(p=0.9, verdict="fraud", card_testing=True, strong_families=3))
    assert acts(pl["initial"])[:2] == ["DECLINE_TRANSACTION", "STEP_UP_AUTH"]


def test_r5_block_when_over_100_cleared():
    pl = plan(base(p=0.9, verdict="fraud", card_testing=True, ct_cleared_over_100=True, strong_families=3))
    assert "BLOCK_CARD" in acts(pl["initial"])


# ---- R7: disputed but legitimate --------------------------------------------------------------
def test_r7_recurring_dispute_does_not_block():
    pl = plan(base(trigger="customer_report", p=0.2, verdict="legitimate", recurring=True))
    a = acts(pl["initial"])
    assert a == ["CREATE_CASE", "VERIFY_WITH_CUSTOMER", "WARN_CUSTOMER"]
    assert "BLOCK_CARD" not in acts(pl["branches"]["confirm"])


# ---- R8: uncertain + exposed / conflicting evidence ---------------------------------------------
def test_r8_conflicting_customer_report_escalates():
    pl = plan(base(trigger="customer_report", p=0.4, conflict=True))
    assert "ESCALATE_TO_ANALYST" in acts(pl["initial"])


# ---- R9: undocumented pattern -------------------------------------------------------------------
def test_r9_undocumented_files_and_escalates():
    s = base(trigger="customer_report", p=0.97, verdict="fraud", pattern="undocumented", exposure=1906.07)
    a = acts(plan(s)["initial"])
    assert {"CREATE_CASE", "FILE_REPORT", "ESCALATE_TO_ANALYST"} <= set(a)


# ---- R10 ------------------------------------------------------------------------------------------
def test_r10_never_block_all_cards():
    for s in (base(p=0.97, verdict="fraud", strong_families=3), base(trigger="customer_report", p=0.97, verdict="fraud")):
        pl = plan(s)
        for branch in [pl["initial"]] + list(pl["branches"].values()):
            assert "BLOCK_ALL_CARDS" not in acts(branch)


# ---- section 3a: case vs report ---------------------------------------------------------------
@pytest.mark.parametrize("exposure,shared,pattern,expected", [
    (999.99, False, "card_not_present_fraud", False), (1000.01, False, "card_not_present_fraud", True),
    (50, True, "card_not_present_new_device", True), (50, False, "undocumented", True),
])
def test_3a_sar_thresholds(exposure, shared, pattern, expected):
    assert sar_required(base(exposure=exposure, shared=shared, pattern=pattern), "fraud") is expected


def test_3a_no_sar_without_fraud():
    assert sar_required(base(exposure=5000), "uncertain") is False


# ---- section 6: stop rule -------------------------------------------------------------------------
def test_6_stop_high():
    pl = plan(base(p=0.9, verdict="fraud", strong_families=2))
    assert pl.get("evidence_request") is None and "BLOCK_CARD" in acts(pl["initial"])


def test_6_stop_low():
    pl = plan(base(p=0.1, verdict="legitimate", legit_families=2))
    assert acts(pl["initial"]) == ["ALLOW_TRANSACTION", "CLOSE_NO_FRAUD"] and pl.get("evidence_request") is None


def test_every_reason_cites_a_rule():
    import re
    for s in (base(p=0.45), base(p=0.9, verdict="fraud", strong_families=3), base(trigger="customer_report", p=0.8, verdict="fraud"),
              base(trigger="customer_report", p=0.2, recurring=True), base(p=0.1, legit_families=2)):
        pl = plan(s)
        for branch in [pl["initial"]] + list(pl["branches"].values()):
            for a in branch:
                assert re.search(r"\b(R\d+|[Ss]ection \d|3a)\b", a["reason"]), a


def test_status_mapping():
    assert status_of([{"action": "ESCALATE_TO_ANALYST"}], "fraud") == "escalated"
    assert status_of([{"action": "BLOCK_CARD"}], "fraud") == "closed_fraud"
    assert status_of([{"action": "CLOSE_NO_FRAUD"}], "legitimate") == "closed_legitimate"
    assert status_of([{"action": "MONITOR_CARD"}], "uncertain") == "open"
