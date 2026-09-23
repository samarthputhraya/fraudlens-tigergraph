"""LLM roles (Gemini on Vertex AI). The LLM reasons, chooses tools and writes; it never sets numbers, IDs or routes.

- Lead Investigator: forms hypotheses and chooses up to 3 extra graph queries from the installed-query menu.
- 4 Specialists (Transaction, Identity & Device, Network & Ring, Precedent): each reads only its slice of evidence.
- Compliance Reviewer: red-teams the draft decision against the Fraud Policy (rules cited, case vs SAR, routes).
- Writer: analyst summary, "what changed", stop reason, SAR reason and a FinCEN-style SAR narrative.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor

from agent.llm import FLASH, PRO, generate_json

SYSTEM = ("You are part of a bank's fraud investigation team. You reason only from the evidence given to you, you never "
          "invent transaction, card, customer, device or case IDs, and you are honest about uncertainty. Unnamed Vesta "
          "features (V, C, D, M, id_ columns) must be described as unnamed model features, never given invented meanings. "
          "A device profile with missing model/OS/screen fields (for example ' |  | chrome 66.0 | ') is a generic browser "
          "signature shared by many unrelated people: sharing it is NOT evidence of a ring or of account takeover. Only a rare, "
          "fully specified device profile used as a New device by several customers is ring evidence.")

TOOL_MENU = {
    "device_neighbors": "Other cards/customers that used a device profile in a time window (params: days_back 7-120)",
    "card_window": "All transactions on the card over a longer window (params: days_back 7-90)",
    "region_activity": "Cards active in the flagged billing region, which are new to it, and their fraud cases (params: days_back 1-14)",
    "similar_cases_by_pattern": "Closed cases most similar to this alert restricted to one fraud pattern (params: pattern)",
    "recurring_match": "Earlier charges on the card within a tolerance of the flagged amount (params: tol_pct 0.5-5)",
}


def _compact(obj, limit: int = 3500) -> str:
    s = json.dumps(obj, default=str)
    return s if len(s) <= limit else s[:limit] + "...(truncated)"


def lead_plan(case: dict, txn: dict, first_findings: list[dict], catalog: dict | None = None) -> dict:
    schema = {"type": "object", "properties": {
        "hypotheses": {"type": "array", "items": {"type": "string"}},
        "extra_calls": {"type": "array", "items": {"type": "object", "properties": {
            "tool": {"type": "string", "enum": list(TOOL_MENU)}, "why": {"type": "string"},
            "days_back": {"type": "integer"}, "pattern": {"type": "string"}, "tol_pct": {"type": "number"}},
            "required": ["tool", "why"]}},
        "focus": {"type": "string"}}, "required": ["hypotheses", "extra_calls", "focus"]}
    prompt = (f"ALERT: {case['trigger_type']} - {case['trigger_text']}\nFLAGGED TRANSACTION: {_compact(txn, 1200)}\n"
              f"FIRST GRAPH FINDINGS: {_compact(first_findings, 2500)}\n\n"
              + (("INSTALLED QUERY CATALOG (discovered from TigerGraph via MCP):\n"
                  + "\n".join(f"- {k}: {v[:160]}" for k, v in (catalog or {}).items()) + "\n\n") if catalog else "")
              + "TOOLS YOU MAY CALL NOW (installed queries):\n"
              + "\n".join(f"- {k}: {v}" for k, v in TOOL_MENU.items()) +
              "\n\nList 2-4 competing hypotheses (fraud patterns or legitimate explanations) and choose at most 3 extra "
              "calls that would best discriminate between them. Choose none if the evidence is already decisive.")
    return generate_json(prompt, schema, system=SYSTEM, model=FLASH)


SPECIALISTS = {
    "transaction": "Transaction Analyst: velocity, bursts, amounts against the card's baseline, recurring charges, "
                   "card-testing sequences and sub-threshold structuring.",
    "identity": "Identity & Device Analyst: the device profile, New/Found flag, proxy use, match flags and the resolved "
                "cardholder account's history (entity resolution).",
    "network": "Network & Ring Analyst: what happened on OTHER cards - shared device profiles, shared regions, rings, "
               "connected cards and their cases.",
    "precedent": "Precedent Analyst: case memory - similar closed cases, prior investigations, analyst notes and the "
                 "bank's policy and typology documents.",
}


def specialist(name: str, case: dict, evidence: dict) -> dict:
    schema = {"type": "object", "properties": {
        "assessment": {"type": "string"}, "risk": {"type": "string", "enum": ["low", "medium", "high"]},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "suggested_pattern": {"type": "string"}}, "required": ["assessment", "risk", "key_points"]}
    prompt = (f"ROLE: {SPECIALISTS[name]}\nALERT: {case['trigger_type']} - {case['trigger_text']}\n"
              f"YOUR EVIDENCE (from TigerGraph queries):\n{_compact(evidence, 5000)}\n\n"
              "Give a 2-3 sentence assessment, your risk view, 2-4 key points citing the IDs in the evidence, and what is "
              "still unknown. suggested_pattern is one of card_testing, card_not_present_fraud, card_not_present_new_device, "
              "out_of_region_use, account_takeover, undocumented, none.")
    return generate_json(prompt, schema, system=SYSTEM, model=FLASH)


def run_specialists(case: dict, slices: dict) -> dict:
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {n: pool.submit(specialist, n, case, slices.get(n, {})) for n in SPECIALISTS}
        out = {}
        for n, fu in futs.items():
            try:
                out[n] = fu.result()
            except Exception as e:  # noqa: BLE001 - a specialist failure must not stop the case
                out[n] = {"assessment": f"(unavailable: {e})", "risk": "medium", "key_points": []}
    return out


def critic(draft: dict, policy_chunks: list[str]) -> dict:
    schema = {"type": "object", "properties": {
        "agree": {"type": "boolean"}, "issues": {"type": "array", "items": {"type": "string"}},
        "what_would_change_verdict": {"type": "string"}}, "required": ["agree", "issues", "what_would_change_verdict"]}
    prompt = ("You are the bank's Compliance Reviewer. Red-team this draft decision against the Fraud Policy. Check: every "
              "action cites the right rule; case vs suspicious activity report (section 3a) is decided correctly; approval "
              "routes (auto/L1/L2) are right for the exposure; R1 (verify before blocking on a weak signal) and R10 are "
              "respected; the stop rule (section 6) is applied. Flag real problems only.\n\n"
              f"POLICY EXCERPTS:\n{chr(10).join(policy_chunks)[:6000]}\n\nDRAFT:\n{_compact(draft, 6000)}")
    return generate_json(prompt, schema, system=SYSTEM, model=PRO)


def writer(draft: dict, guidance: list[str], want_sar: bool, want_desc: bool) -> dict:
    props = {"summary": {"type": "string"}}
    req = ["summary"]
    if want_sar:
        props["sar_narrative"] = {"type": "string"}
        req.append("sar_narrative")
    if want_desc:
        props["pattern_description"] = {"type": "string"}
        req.append("pattern_description")
    schema = {"type": "object", "properties": props, "required": req}
    decision = (f"verdict={draft['verdict']}, fraud_probability={draft['fraud_probability']}, pattern={draft['pattern']}, "
                f"status={draft['status']}, final actions={[a['action'] for a in draft['final_actions']]}, "
                f"suspicious activity report recommended={draft['sar_recommended_pending_L2_approval']}")
    prompt = (
        "Write the case text for this fraud investigation. The DECISION below was made by the bank's policy engine and is "
        "FINAL: describe it exactly. Do not add, remove or soften actions, do not change the verdict, do not mention a "
        "suspicious activity report unless one is filed, and do not speculate beyond the evidence list. Use ONLY facts, "
        "amounts, dates and IDs present in the DRAFT.\n"
        f"DECISION: {decision}\n"
        "- summary: 2-6 plain sentences an analyst can read: what triggered the alert, what the graph evidence showed, the "
        "verdict, and exactly the final actions.\n"
        + ("- sar_narrative: 6-12 sentences, a regulator-ready suspicious activity report that stands on its own: WHO "
           "(customer, cards, devices), WHAT happened, WHEN (dates and times), WHERE (channel, billing region), HOW it was "
           "carried out, WHY it is suspicious, and the total amount. Follow the FinCEN narrative guidance below.\n" if want_sar else "")
        + ("- pattern_description: 2-3 sentences on what the undocumented pattern is, who it affects and how it was found.\n" if want_desc else "")
        + f"\nFINCEN / POLICY GUIDANCE:\n{chr(10).join(guidance)[:4000]}\n\nDRAFT:\n{_compact(draft, 9000)}")
    return generate_json(prompt, schema, system=SYSTEM, model=PRO, temperature=0.2)


ID_RE = re.compile(r"\b(CC-\d{4}|C\d{5}-K\d|C\d{5}|3\d{6})\b")


def unknown_ids(text: str, allowed: set[str]) -> list[str]:
    return sorted({m for m in ID_RE.findall(text or "") if m not in allowed})
