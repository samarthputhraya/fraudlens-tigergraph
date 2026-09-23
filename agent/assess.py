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
    prior = prior_for(trigger, score)
    fam = defaultdict(float)
    for f in findings:
        fam[f.family] += f.weight
    total = logit(prior)
    contrib = []
    for fname, w in fam.items():
        w = max(-FAMILY_CAP, min(FAMILY_CAP, w))
        total += w
    for f in findings:
        contrib.append({"key": f.key, "family": f.family, "lr": round(f.lr, 2), "delta_logodds": round(f.weight, 3)})
    p = min(0.97, max(0.03, sigmoid(total)))
    fraud_fams = sorted(k for k, w in fam.items() if w >= math.log(1.5))
    legit_fams = sorted(k for k, w in fam.items() if w <= -math.log(1.4))
    return {"prior": prior, "p": round(p, 2), "fraud_families": fraud_fams, "legit_families": legit_fams,
            "contributions": contrib, "strong": sorted({f.key for f in findings if f.key in STRONG})}


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
