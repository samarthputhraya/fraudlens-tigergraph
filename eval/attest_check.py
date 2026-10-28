"""Attestation self-check: re-run the query behind every evidence claim and confirm every ID the claim cites is in
the result. This is what the judges do ("We re-run the query. If the result differs from the claim, the claim scores
zero"), done by us first, on every answer.

  python eval/attest_check.py runs/v3            # answers + traces written by run_cases.py --out runs/v3 (mirror)
  python eval/attest_check.py cases_r2 --graph   # the official answers, re-run on TigerGraph

A claim is: attested (its query re-runs and returns every cited ID), mismatched (an ID is missing: a failure),
or not a query (a customer response, the policy document, the alert text itself: checked by other means).
Writes <dir>/attestation.json.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.attest import ids_in  # noqa: E402


def rerun(g, name: str, p: dict):
    """Re-run one recorded tool call by name and parameters. Returns the raw result, or None if not re-runnable."""
    if hasattr(g, "run") and not hasattr(g, "QUERIES"):          # TigerGraph: the installed query itself
        return g.run(name, p, agent="attest")
    fns = {
        "txn_context": lambda: g.txn_context(p["txn"]),
        "card_window": lambda: g.card_window(p["card"], p["start_ts"], p["end_ts"]),
        "card_profile": lambda: g.card_profile(p["card"], p["before_ts"], int(p.get("recent_days", 30))),
        "recurring_match": lambda: g.recurring_match(p["card"], float(p["amt"]), float(p["tol"]), p["before_ts"]),
        "device_neighbors": lambda: g.device_neighbors(p["dev"], p["start_ts"], p["end_ts"]),
        "region_activity": lambda: g.region_activity(p["region"], p["start_ts"], p["end_ts"], int(p.get("max_cards", 200))),
        "prior_cases": lambda: g.prior_cases(p["card"], p.get("before_ts")),
        "account_history": lambda: g.account_history(p["txn"], int(p.get("lookback_days", 200))),
        "typology_scan": lambda: g.typology_scan(p["start_ts"], p["end_ts"], p["base_start"], float(p.get("micro_max", 10)),
                                                 int(p.get("min_micro", 4)), float(p.get("ramp_min", 500))),
        "recipient_activity": lambda: g.recipient_activity(p["dom"], p["start_ts"], p["end_ts"], p["base_start"],
                                                           int(p.get("max_detail", 200))),
    }
    return fns[name]() if name in fns else None


def main(folder: Path, official: bool) -> dict:
    if official:
        from agent.graph_client import GraphClient
        g = GraphClient()
    else:
        from agent.mirror import MirrorGraph
        g = MirrorGraph()
    totals = {"claims": 0, "attested": 0, "mismatched": 0, "not_a_query": 0, "not_rerunnable": 0}
    per_case, failures = {}, []
    for f in sorted(folder.glob("HHF-*.json")):
        ans = json.loads(f.read_text(encoding="utf-8"))
        trace_p = folder / "traces" / f.name
        calls = {c["ref"]: c for c in json.loads(trace_p.read_text(encoding="utf-8"))["tool_calls"]} if trace_p.exists() else {}
        counts = {k: 0 for k in totals}
        for ev in ans["case"]["evidence"]:
            counts["claims"] += 1
            ref = ev.get("ref", "")
            m = re.match(r"^query:(\w+)\(", ref)
            if not m:
                counts["not_a_query"] += 1
                continue
            call = calls.get(ref)
            result = rerun(g, m.group(1), call["params"]) if call else None
            if result is None:
                counts["not_rerunnable"] += 1
                continue
            found = ids_in(result)
            missing = [e for e in ev.get("entity_ids", []) if str(e) not in found]
            if missing:
                counts["mismatched"] += 1
                failures.append({"case": f.stem, "ref": ref, "missing": missing[:8], "claim": ev["claim"][:160]})
            else:
                counts["attested"] += 1
        per_case[f.stem] = counts
        for k in totals:
            totals[k] += counts[k]
    queries = totals["attested"] + totals["mismatched"] + totals["not_rerunnable"]
    out = {"graph": getattr(g, "source", "?"), "totals": totals,
           "attested_share_of_query_claims": round(totals["attested"] / queries, 3) if queries else None,
           "per_case": per_case, "failures": failures}
    (folder / "attestation.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({"graph": out["graph"], **totals, "attested_share": out["attested_share_of_query_claims"]}))
    for x in failures[:10]:
        print("MISMATCH", x)
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(ROOT / (args[0] if args else "cases_r2"), "--graph" in sys.argv)
