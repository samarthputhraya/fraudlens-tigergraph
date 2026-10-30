"""Case-book consistency: read every answer as one book, the way a fraud manager reads the queue, not one case at a time.

Each case is investigated at its own open time. A card can then be cleared in one case while another case puts the
same card in a ring, plans to block it, or names it in a regulator report. One investigation can't see that; the book
can. This module links cases through the cards they touch (case -> card edges with a role, the same edges the case
writer stores in TigerGraph) and reports every card with conflicting roles.

Roles a case gives a card:
  cleared    its own card, verdict legitimate
  open       its own card, verdict uncertain (with an analyst)
  fraud      its own card, verdict fraud
  reported   named in the case's report (sar.subjects)
  block      the case's containment plan recommends blocking it
  ring       listed in connected_card_ids without being reported or blocked (monitored ring member)

Findings, worst first:
  high    a card cleared in one case is reported or planned for a block in another. `seen_at_open` says whether the
          clearing case's own evidence already flagged other charges on that card: if it did, the clearing case
          ignored evidence it had (a decision error); if not, the evidence came later and the case should be reopened
          (policy 3a: a case is updated when new evidence arrives)
  low     a card cleared in one case is only a monitored ring member in another (weak ring evidence, nothing to undo)
  linked  two reports name the same card: the later one should cite the earlier as continuing activity
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

OWN_ROLE = {"legitimate": "cleared", "uncertain": "open", "fraud": "fraud"}
SIDE_CLAIM = "Other charges on this card"      # the side-typology finding (agent/detectors.py) states this verbatim
PLAN_CLAIM = "Containment plan"


def load(answers_dir: Path, pack_csv: Path) -> tuple[dict, dict]:
    """(answers by case id, case-pack rows by case id). Files that aren't answers (attestation.json, stale/) are skipped."""
    pack = {r["case_id"]: r for r in csv.DictReader(pack_csv.open(encoding="utf-8"))}
    answers = {}
    for f in sorted(answers_dir.glob("*.json")):
        if f.stem in pack:
            answers[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    return answers, pack


def edges(answers: dict, pack: dict) -> list[dict]:
    """Every (case, card, role) edge in the book."""
    out = []
    for cid, a in answers.items():
        c, own = a["case"], pack[cid]["card_id"]
        out.append({"case": cid, "card": own, "role": OWN_ROLE.get(c["verdict"], "open")})
        subjects = set(a["sar"]["subjects"]) if a["sar"].get("file") else set()
        plan = next((e for e in c["evidence"] if e["claim"].startswith(PLAN_CLAIM)), None)
        block = set(plan["entity_ids"]) if plan else set()
        for card in sorted((subjects | block | set(c["connected_card_ids"])) - {own}):
            if "-K" not in card:
                continue                                   # customers and devices are subjects too; cards only here
            role = "reported" if card in subjects else "block" if card in block else "ring"
            out.append({"case": cid, "card": card, "role": role})
    return out


def check(answers: dict, pack: dict) -> list[dict]:
    by_card: dict[str, list[dict]] = defaultdict(list)
    for e in edges(answers, pack):
        by_card[e["card"]].append(e)
    found = []
    for card, es in sorted(by_card.items()):
        cleared = [e for e in es if e["role"] == "cleared"]
        for clr in cleared:
            a = answers[clr["case"]]
            side = [e for e in a["case"]["evidence"] if e["claim"].startswith(SIDE_CLAIM)]
            for other in es:
                if other["case"] == clr["case"] or other["role"] in ("cleared", "open"):
                    continue
                severity = "high" if other["role"] in ("reported", "block", "fraud") else "low"
                found.append({
                    "severity": severity, "card": card, "cleared_in": clr["case"], "other_case": other["case"],
                    "other_role": other["role"], "seen_at_open": bool(side),
                    "cleared_opened_at": pack[clr["case"]]["opened_at"], "other_opened_at": pack[other["case"]]["opened_at"],
                    "side_evidence": [i for e in side for i in e["entity_ids"]][:8],
                    "action": ("decision error: the clearing case's own evidence flagged other charges on this card"
                               if side and severity == "high" else
                               "reopen the cleared case: later evidence implicates its card (policy 3a)"
                               if severity == "high" else "note: monitored ring member, nothing to undo"),
                })
    reports = defaultdict(list)
    for e in edges(answers, pack):
        if e["role"] in ("reported",) or (e["role"] == "fraud" and answers[e["case"]]["sar"].get("file")):
            reports[e["card"]].append(e["case"])
    for card, cases in sorted(reports.items()):
        if len(set(cases)) > 1:
            first, *later = sorted(set(cases), key=lambda c: pack[c]["opened_at"])
            found.append({"severity": "linked", "card": card, "cases": [first, *later],
                          "action": f"continuing activity: {', '.join(later)} should cite {first}'s report"})
    order = {"high": 0, "low": 1, "linked": 2}
    return sorted(found, key=lambda f: (order[f["severity"]], f["card"]))


def summary(found: list[dict]) -> dict:
    n = defaultdict(int)
    for f in found:
        n[f["severity"]] += 1
    return {"high": n["high"], "high_seen_at_open": sum(1 for f in found if f["severity"] == "high" and f["seen_at_open"]),
            "low": n["low"], "linked_reports": n["linked"]}
