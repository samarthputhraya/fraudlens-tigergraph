"""Fraud Policy v1.0 as code: actions, approval routes, rules R1-R10, section 3a (case vs SAR), section 6 (stop).

`plan()` returns the initial recommendation, the evidence request (if any), all three counterfactual branches
(customer confirms / denies / no reply) and, given the assumed reply, the final recommendation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

AUTO = {"ALLOW_TRANSACTION", "MONITOR_CARD", "MONITOR_CONNECTED_CARDS", "WARN_CUSTOMER", "VERIFY_WITH_CUSTOMER",
        "STEP_UP_AUTH", "GENERATE_REPORT", "CREATE_CASE", "ESCALATE_TO_ANALYST", "CLOSE_NO_FRAUD"}


def route(action: str, exposure: float) -> str:
    if action in AUTO:
        return "auto"
    if action == "DECLINE_TRANSACTION":
        return "L1"
    if action == "BLOCK_CARD":
        return "L1" if exposure <= 2500 else "L2"
    if action in ("BLOCK_ALL_CARDS", "FILE_REPORT"):
        return "L2"
    raise ValueError(action)


def act(action: str, reason: str, exposure: float) -> dict:
    return {"action": action, "route": route(action, exposure), "reason": reason}


@dataclass
class Situation:
    trigger: str
    p: float
    verdict: str
    pattern: str
    exposure: float
    online: bool
    shared: bool                   # shared device / region cluster / another customer's fraud (R6, 3a)
    connected_cards: list = field(default_factory=list)
    shared_desc: str = ""
    recurring: bool = False        # R7
    card_testing: bool = False     # R5
    ct_cleared_over_100: bool = False
    strong_families: int = 0
    legit_families: int = 0
    single_signal: bool = False
    conflict: bool = False
    legit_explanation: str = ""
    integrity_conflict: bool = False   # the case record and the bank's own record disagree (data quality)
    side_concern: str = ""             # other charges on the card match a fraud typology (not the flagged one)
    signature: str = ""                # connected cards show the same typology signature but share nothing (R9, not R6)


def sar_required(s: Situation, verdict: str) -> bool:
    return verdict == "fraud" and (s.exposure > 1000 or s.shared or s.pattern == "undocumented")


def sar_reason(s: Situation) -> str:
    parts = []
    if s.exposure > 1000:
        parts.append(f"exposure ${s.exposure:,.2f} exceeds $1,000")
    if s.shared:
        parts.append(f"activity connects to {s.shared_desc or 'a shared device profile / another customer'}")
    if s.pattern == "undocumented":
        parts.append(f"the pattern is undocumented{' and coordinated across ' + str(len(s.connected_cards) + 1) + ' cards' if s.connected_cards else ''} (R9)")
    return "; ".join(parts)


def fraud_actions(s: Situation, basis: str) -> list[dict]:
    """Actions once fraud is confirmed/strongly suspected (after a denial, or on strong multi-signal evidence)."""
    e = s.exposure
    out = []
    if s.card_testing and not s.ct_cleared_over_100:
        out.append(act("DECLINE_TRANSACTION", "R5: card-testing sequence; decline the pending authorisation", e))
        out.append(act("STEP_UP_AUTH", "R5: require a one-time passcode before further activity", e))
    else:
        why = f"{basis}; exposure ${e:,.2f} is {'under' if e <= 2500 else 'over'} $2,500"
        if s.card_testing:
            why = "R5: a purchase over $100 already cleared after the testing sequence; " + why
        out.append(act("BLOCK_CARD", why, e))
    out.append(act("CREATE_CASE", "Section 3a: fraud confirmed or strongly suspected; record the investigation and write it to the graph", e))
    if sar_required(s, "fraud"):
        rule = "R6" if s.shared else ("R9" if s.pattern == "undocumented" else "R2")
        out.append(act("FILE_REPORT", f"{rule} / section 3a: {sar_reason(s)}", e))
    if s.connected_cards:
        why = (f"R6: {len(s.connected_cards)} other card(s) share {s.shared_desc or 'a link with this card'}" if s.shared else
               f"R9: {len(s.connected_cards)} other card(s) show the same {s.signature or 'signature'} in the same 30 days")
        out.append(act("MONITOR_CONNECTED_CARDS", why, e))
    if s.pattern == "undocumented":
        out.append(act("ESCALATE_TO_ANALYST", f"R9: {'coordinated ' if s.connected_cards else ''}activity that fits no "
                                              f"documented pattern; hand to an analyst with the evidence", e))
    return out


def with_side_concern(actions: list[dict], s: Situation) -> list[dict]:
    """Other charges on the card look like a known typology: protect the card and hand them to an analyst. Both actions
    cost a legitimate customer nothing; a block is never added for charges the case isn't about."""
    if not s.side_concern or any(a["action"] in ("BLOCK_CARD", "BLOCK_ALL_CARDS") for a in actions):
        return actions
    out = list(actions)
    if not any(a["action"] == "MONITOR_CARD" for a in out):
        out.append(act("MONITOR_CARD", f"R6: other charges on this card share an element with a fraud ring ({s.side_concern}); "
                                       f"raise monitoring for 72 hours", s.exposure))
    if not any(a["action"] == "ESCALATE_TO_ANALYST" for a in out):
        out.append(act("ESCALATE_TO_ANALYST", "R8: the evidence conflicts - the flagged purchase is clean but other charges "
                                              "on the card are suspicious; hand those to an analyst with the evidence", s.exposure))
    return out


def plan(s: Situation) -> dict:
    res = _plan(s)
    if s.side_concern:
        res["initial"] = with_side_concern(res["initial"], s)
        res["branches"] = {k: with_side_concern(v, s) for k, v in res["branches"].items()}
    return res


def _plan(s: Situation) -> dict:
    e = s.exposure
    res: dict = {"evidence_request": None, "branches": {}}

    # ------------------------------------------------------------------ the records disagree about the case itself
    if s.integrity_conflict and not (s.p >= 0.85 and s.strong_families >= 2):
        initial = [act("CREATE_CASE", "Section 3a: keep a record while the data discrepancy is resolved", e),
                   act("MONITOR_CARD", "R8: raise monitoring for 72 hours while the card record is reconciled", e),
                   act("VERIFY_WITH_CUSTOMER", "R1: confirm the purchase with the cardholder before any block", e),
                   act("ESCALATE_TO_ANALYST", "R8: the evidence conflicts - the case record and the bank's transaction "
                                              "record name different cards; an analyst must reconcile them", e)]
        res.update(initial=initial, verdict_override="uncertain",
                   evidence_request=("analyst_info", "Analyst asked to reconcile the case record's card with the bank's "
                                                     "transaction record; no answer yet, so the case stays with the analyst"))
        res["branches"] = {"confirm": initial, "deny": initial, "no_reply": initial}
        return res

    # ------------------------------------------------------------------ customer already disputed the charge
    if s.trigger == "customer_report":
        if s.recurring and s.p < 0.5:
            initial = [act("CREATE_CASE", "Section 3a: the customer disputes a charge", e),
                       act("VERIFY_WITH_CUSTOMER", "R7: the disputed charge matches the card's own recurring pattern (same amount, monthly); confirm before any block", e),
                       act("WARN_CUSTOMER", "R7: send a recurring-charge reminder showing the earlier matching charges", e)]
            res["evidence_request"] = ("customer_validation",
                                       "Customer reviews the earlier matching charges and recognises the payment as their own recurring charge")
            res["branches"] = {
                "confirm": [act("CREATE_CASE", "Section 3a: keep the case record; customer confirmation noted", e),
                            act("WARN_CUSTOMER", "R7: recurring-charge reminder sent", e),
                            act("CLOSE_NO_FRAUD", "R3: the customer recognised the recurring charge", e)],
                "deny": fraud_actions(s, "R2: customer maintains the charge is unauthorised after seeing the recurring history"),
                "no_reply": [act("MONITOR_CARD", "R4: no reply within 24 hours; raise monitoring for 72 hours", e),
                             act("CREATE_CASE", "Section 3a: dispute on record", e)],
            }
            res["initial"] = initial
            return res
        if s.conflict and s.p < 0.5:
            # The denial conflicts with the evidence (the purchase fits the cardholder's own pattern). Blocking an
            # innocent customer is the costliest mistake, so verify and escalate under R8 instead of blocking.
            initial = [act("CREATE_CASE", "Section 3a: the customer disputes a charge", e),
                       act("VERIFY_WITH_CUSTOMER", "R1 / R8: the graph evidence does not support the denial; confirm the "
                                                   "details with the cardholder before any block", e),
                       act("MONITOR_CARD", "R4 / R8: raise monitoring for 72 hours while the dispute is reviewed", e),
                       act("ESCALATE_TO_ANALYST", "R8: the graph evidence conflicts with the customer's report", e)]
            res["initial"] = initial
            res["branches"] = {"confirm": initial, "deny": initial, "no_reply": initial}
            return res
        initial = fraud_actions(s, "R2: the customer denies making the transaction")
        res["initial"] = initial
        res["branches"] = {"confirm": initial, "deny": initial, "no_reply": initial}
        return res

    # ------------------------------------------------------------------ model alert or analyst request
    strong_stop = s.p >= 0.85 and s.strong_families >= 2
    if strong_stop:
        initial = fraud_actions(s, "Section 6: probability >= 0.85 on two or more independent pieces of evidence")
        res["initial"] = initial
        res["branches"] = {"confirm": initial, "deny": initial, "no_reply": initial}
        return res
    if s.p <= 0.15 and s.legit_families >= 2:
        initial = [act("ALLOW_TRANSACTION", "Section 6: probability <= 0.15 on two or more independent legitimate signals", e),
                   act("CLOSE_NO_FRAUD", "Section 6: the evidence settles the alert as legitimate; further steps would not change the decision", e)]
        res["initial"] = initial
        res["branches"] = {"confirm": initial, "deny": initial, "no_reply": initial}
        return res

    verify = "STEP_UP_AUTH" if s.online and s.p >= 0.5 else "VERIFY_WITH_CUSTOMER"
    initial = [act("CREATE_CASE", "Section 3a: evidence is being requested" + (" and probability >= 0.30" if s.p >= 0.3 else ""), e)]
    initial.append(act(verify, f"R1: {'single signal' if s.single_signal else 'evidence not yet conclusive'} "
                               f"(probability {s.p:.2f} < 0.70); verify before any block", e))
    if s.connected_cards:
        initial.append(act("MONITOR_CONNECTED_CARDS", f"R6: {len(s.connected_cards)} card(s) share {s.shared_desc}", e))
    res["initial"] = initial
    res["evidence_request"] = ("step_up_auth" if verify == "STEP_UP_AUTH" else "customer_validation", "")
    no_reply = [act("MONITOR_CARD", "R4: no reply within 24 hours; raise monitoring for 72 hours", e),
                act("DECLINE_TRANSACTION", "R4: decline the pending authorisation", e)]
    if e > 500:
        no_reply.append(act("ESCALATE_TO_ANALYST", f"R4 / R8: verdict still uncertain and exposure ${e:,.2f} exceeds $500", e))
    res["branches"] = {
        "confirm": [act("ALLOW_TRANSACTION", "R3: the cardholder confirmed the transaction", e),
                    act("CLOSE_NO_FRAUD", f"R3: {s.legit_explanation or 'cardholder confirmed'}; confirmation noted in the case file", e)],
        "deny": fraud_actions(s, "R2: the cardholder denied the transaction"),
        "no_reply": no_reply,
    }
    return res


def status_of(final: list[dict], verdict: str) -> str:
    acts = {a["action"] for a in final}
    if "ESCALATE_TO_ANALYST" in acts:
        return "escalated"
    if verdict == "fraud":
        return "closed_fraud"
    if verdict == "legitimate":
        return "closed_legitimate"
    return "open"
