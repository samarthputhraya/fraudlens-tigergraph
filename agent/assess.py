"""Calibrated assessment: Bayesian log-odds ledger over detector findings -> probability, verdict and pattern."""
from __future__ import annotations

import math
from collections import defaultdict

from agent.detectors import Finding

# Prior fraud probability by trigger, before any graph evidence.
# risk_score alerts: base fraud rate (3.4% of Jul-Oct transactions are in confirmed cases) times the score-bin
# likelihood ratio measured on 14,055 fraud vs 402,449 background transactions (eval/likelihoods.md). This reproduces
# the README's warning: even at >= 0.85 fewer than half of alerts are fraud.
BASE_RATE = 0.034
SCORE_LR = [(0.10, 0.14), (0.30, 0.60), (0.50, 2.52), (0.70, 6.04), (0.85, 9.59), (1.01, 24.99)]
PRIORS = {"customer_report": 0.60, "analyst_request": 0.45}
# A customer dispute is strong evidence on its own: every confirmed case in the bank's history began as a customer
# report. We keep a margin for disputed-but-legitimate recurring charges (R7): prior 0.86 before the model's view.
DISPUTE_PRIOR = 0.86
TRIGGER_PRIOR = {"customer_report": DISPUTE_PRIOR, "analyst_request": PRIORS["analyst_request"]}
FAMILY_CAP = math.log(60.0)
STRONG = {"structuring", "card_testing", "shared_device", "account_prior_fraud"}


def logit(p: float) -> float:
    return math.log(p / (1 - p))


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def score_lr(score: float) -> float:
    for hi, lr in SCORE_LR:
        if score < hi:
            return lr
    return SCORE_LR[-1][1]


def prior_for(trigger: str, score: float) -> float:
    if trigger == "risk_score":
        return sigmoid(logit(BASE_RATE) + math.log(score_lr(score)))
    return PRIORS.get(trigger, 0.4)


def ledger(trigger: str, findings: list[Finding], score: float = 0.5) -> dict:
    """Log-odds ledger. With the learned model available, the model's calibrated probability for the flagged
    transaction is the starting point (it already includes the risk score, the identity record and account memory);
    only graph evidence the model cannot see (other cards, rings, structuring, testing sequences, recurrence, the
    customer's own report) moves it further. Without the model, the fitted score-bin prior and single-signal LRs apply."""
    model = next((f for f in findings if f.key == "model_score"), None)
    if model is not None:
        mp = min(0.999, max(0.001, float(model.data["model_p"])))
        prior = mp
        if trigger in TRIGGER_PRIOR:
            # a person already saw something (the customer's own denial, an analyst's lead): start from that prior and
            # move it by the model's likelihood ratio, instead of the population base rate the model is calibrated to
            from agent.detectors import MODEL_BASE_RATE
            prior = sigmoid(logit(TRIGGER_PRIOR[trigger]) + logit(mp) - logit(MODEL_BASE_RATE))
    else:
        prior = prior_for(trigger, score)
    fam = defaultdict(float)
    for f in findings:
        if f.key == "model_score" or f.in_model:
            continue
        fam[f.family] += f.weight
    total = logit(prior)
    contrib = []
    for fname, w in fam.items():
        w = max(-FAMILY_CAP, min(FAMILY_CAP, w))
        total += w
    for f in findings:
        counted = not (f.in_model or f.key == "model_score")
        contrib.append({"key": f.key, "family": f.family, "lr": round(f.lr, 2),
                        "delta_logodds": round(f.weight, 3) if counted else 0.0,
                        "note": "in model score" if f.in_model else ("starting point" if f.key == "model_score" else "")})
    p = min(0.97, max(0.03, sigmoid(total)))
    fraud_fams = sorted(k for k, w in fam.items() if w >= math.log(1.5))
    legit_fams = sorted(k for k, w in fam.items() if w <= -math.log(1.4))
    if model is not None:
        # the model is one independent family of evidence (fraud-leaning or legitimate-leaning)
        if model.lr >= 1.5:
            fraud_fams = sorted(set(fraud_fams) | {"model"})
        elif model.lr <= 1 / 1.4:
            legit_fams = sorted(set(legit_fams) | {"model"})
    return {"prior": prior, "p": round(p, 2), "fraud_families": fraud_fams, "legit_families": legit_fams,
            "contributions": contrib, "strong": sorted({f.key for f in findings if f.key in STRONG and not f.in_model})}


def verdict_of(p: float, led: dict, trigger: str) -> str:
    n_f = len(led["fraud_families"]) + (1 if trigger == "customer_report" else 0)
    if p >= 0.70 and (n_f >= 2 or led["strong"]):
        return "fraud"
    if p <= 0.30:
        return "legitimate"
    return "uncertain"


def pattern_of(verdict: str, facts: dict, txn: dict) -> tuple[str, str]:
    """Returns (pattern, pattern_description)."""
    if verdict == "legitimate":
        return "none", ""
    sig = facts.get("pattern_signals", {})
    if facts.get("structuring"):
        n = len(facts["structuring"])
        return "undocumented", (
            f"Sub-threshold structuring: {n} online purchases on one card within an hour, each priced just under a $500 "
            f"authorisation threshold, apparently to avoid step-up checks on larger amounts. It matches none of the five known "
            f"patterns; the agent found it by scanning the card's transaction window for clustered same-band purchases and "
            f"matched it to earlier confirmed cases with the same signature.")
    if facts.get("ring_size", 0) >= 4:
        return "undocumented", (
            f"Shared-device ring: one rare device profile was used as a new device on the cards of {facts['ring_size'] + 1} "
            f"different customers within weeks, often behind an anonymising proxy, pointing to a single actor cycling through "
            f"compromised cards. It is broader than card-not-present fraud on one card; the agent found it by traversing "
            f"device -> transactions -> cards in the graph.")
    if facts.get("card_testing"):
        return "card_testing", ""
    rows = facts.get("episode_rows")
    if rows:
        # The bank's own labelling of its closed cases (read off all 4,665 confirmed cases): an all-online episode is
        # card-not-present fraud, "new device" when any purchase came from a device marked New for the account; a
        # mixed-channel episode is account takeover; a card-present episode is account takeover when it stays in the
        # card's home billing region, and out-of-region use when it happens elsewhere or spans several regions.
        chans = {r.get("channel") for r in rows}
        if chans == {"online"}:
            return ("card_not_present_new_device" if any(r.get("is_new") == "New" for r in rows)
                    else "card_not_present_fraud"), ""
        if chans == {"in_person"}:
            regions = {r.get("addr1") for r in rows if r.get("addr1")}
            home = facts.get("home_region")
            return ("account_takeover" if len(regions) == 1 and home and regions == {home} else "out_of_region_use"), ""
        return "account_takeover", ""
    if facts.get("online"):
        if facts.get("new_device") or sig.get("card_not_present_new_device"):
            return "card_not_present_new_device", ""
        return "card_not_present_fraud", ""
    if facts.get("new_region") or sig.get("out_of_region_use"):
        return "out_of_region_use", ""
    for key in ("account_prior_patterns", "card_prior_patterns"):
        prior_pats = facts.get(key)
        if prior_pats:
            inperson = {k: v for k, v in prior_pats.items() if k in ("account_takeover", "out_of_region_use")}
            if inperson:
                return max(inperson.items(), key=lambda kv: kv[1])[0], ""
    return "account_takeover", ""
