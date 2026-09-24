"""v2: learned model as the starting point, the bank's pattern labelling rule, and the probabilistic episode chain."""
from datetime import datetime

from agent.assess import DISPUTE_PRIOR, ledger, logit, pattern_of, sigmoid
from agent.detectors import MODEL_BASE_RATE, Finding, episode_chain
from agent.evidence import EvidencePack


def _model(p: float) -> Finding:
    lr = (p / (1 - p)) / (MODEL_BASE_RATE / (1 - MODEL_BASE_RATE))
    return Finding("model_score", "model", lr, "model", data={"model_p": p})


def test_model_score_is_the_starting_point_for_alerts():
    led = ledger("risk_score", [_model(0.006)], 0.9)
    assert led["prior"] == 0.006 and led["p"] == 0.03          # floor of the ledger
    assert "model" in led["legit_families"]


def test_signals_the_model_already_sees_are_not_counted_twice():
    seen = Finding("new_device", "new device", 1.4, "device", in_model=True)
    proxy = Finding("proxy", "anonymous proxy", 3.0, "device", in_model=True)
    a = ledger("risk_score", [_model(0.2)], 0.8)
    b = ledger("risk_score", [_model(0.2), seen, proxy], 0.8)
    assert a["p"] == b["p"]


def test_graph_only_evidence_still_moves_the_probability():
    ring = Finding("shared_device", "ring", 20.0, "network")
    assert ledger("risk_score", [_model(0.2), ring], 0.8)["p"] > 0.8


def test_customer_dispute_combines_the_dispute_prior_with_the_model_view():
    led = ledger("customer_report", [_model(0.0132)], 0.5)
    want = sigmoid(logit(DISPUTE_PRIOR) + logit(0.0132) - logit(MODEL_BASE_RATE))
    assert abs(led["prior"] - want) < 1e-9 and 0.6 < led["p"] < 0.85   # a dispute the model doubts is still likely fraud


def _rows(*specs):
    return [{"id": str(i), "channel": ch, "is_new": new, "addr1": reg} for i, (ch, new, reg) in enumerate(specs)]


def test_pattern_rule_matches_the_bank_labelling():
    online_new = {"episode_rows": _rows(("online", "Found", ""), ("online", "New", ""))}
    online = {"episode_rows": _rows(("online", "Found", ""))}
    mixed = {"episode_rows": _rows(("online", "New", ""), ("in_person", "", "264.0"))}
    home = {"episode_rows": _rows(("in_person", "", "264.0"), ("in_person", "", "264.0")), "home_region": "264.0"}
    away = {"episode_rows": _rows(("in_person", "", "330.0")), "home_region": "299.0"}
    spread = {"episode_rows": _rows(("in_person", "", "264.0"), ("in_person", "", "310.0")), "home_region": "264.0"}
    assert pattern_of("fraud", online_new, {})[0] == "card_not_present_new_device"
    assert pattern_of("fraud", online, {})[0] == "card_not_present_fraud"
    assert pattern_of("fraud", mixed, {})[0] == "account_takeover"
    assert pattern_of("fraud", home, {})[0] == "account_takeover"
    assert pattern_of("fraud", away, {})[0] == "out_of_region_use"
    assert pattern_of("fraud", spread, {})[0] == "out_of_region_use"
    assert pattern_of("legitimate", home, {})[0] == "none"


def _pack(rows, flagged_id, opened):
    ep = EvidencePack(case={"card_id": "C1-K1"}, opened_at=datetime.fromisoformat(opened))
    ep.window = rows
    ep.txn = next(r for r in rows if r["id"] == flagged_id)
    return ep


def _t(i, ts, p, amt=10.0):
    return {"id": str(i), "ts": ts, "amt": amt, "model_p": p}


def test_episode_chain_follows_48h_gaps_over_fraud_scored_transactions():
    rows = [_t(1, "2016-11-01 10:00:00", 0.95), _t(2, "2016-11-02 09:00:00", 0.01), _t(3, "2016-11-02 12:00:00", 0.9),
            _t(4, "2016-11-03 12:00:00", 0.1), _t(5, "2016-11-06 12:00:00", 0.95)]
    ids = [w["id"] for w in episode_chain(_pack(rows, "3", "2016-11-03 18:00:00"), samples=2000)]
    assert ids == ["1", "3"]      # 2 and 4 look legitimate; 5 is more than 48 h after the last fraud and after opened_at


def test_episode_chain_never_reads_past_opened_at():
    rows = [_t(1, "2016-11-01 10:00:00", 0.9), _t(2, "2016-11-01 12:00:00", 0.99)]
    ids = [w["id"] for w in episode_chain(_pack(rows, "1", "2016-11-01 11:00:00"), samples=500)]
    assert ids == ["1"]
