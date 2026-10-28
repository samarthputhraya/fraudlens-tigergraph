"""Parity check: the installed GSQL queries on TigerGraph (via MCP) vs the offline mirror, on real benchmark cases.

For each case we gather the evidence pack both ways and compare what the detectors depend on, then run the
detectors on both packs and compare verdict inputs. Any mismatch points at a query bug before the official run.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.detectors import run_detectors  # noqa: E402
from agent.evidence import gather  # noqa: E402
from agent.graph_client import GraphClient  # noqa: E402
from agent.mirror import MirrorGraph  # noqa: E402
from agent.paths import CASE_PACK_CSV  # noqa: E402


def summary(ep) -> dict:
    return {
        "txn.device": ep.txn.get("device", ""), "txn.is_new": ep.txn.get("is_new", ""), "txn.proxy": ep.txn.get("proxy", ""),
        "window": len(ep.window), "window_ids": sorted(w["id"] for w in ep.window)[:5],
        "profile.n": ep.profile.get("n_txn"), "profile.region_here": ep.profile.get("region_n", {}).get(ep.txn.get("addr1", ""), 0),
        "profile.device_here": ep.profile.get("device_n", {}).get(ep.txn.get("device", ""), 0),
        "recurring": len(ep.recurring), "account.hist": len(ep.account.get("history", [])),
        "account.fraud": sum(1 for h in ep.account.get("history", []) if "confirmed_fraud" in (h.get("outcomes") or [])),
        "device.txns": len((ep.device or {}).get("txns", [])), "device.cards_all": (ep.device or {}).get("n_cards_all_time"),
        "prior.closed": len((ep.prior or {}).get("closed_cases", [])),
        # v2: the transaction model's score must come back from the graph exactly as the mirror serves it
        "txn.model_p": round(float(ep.txn.get("model_p", -1) or -1), 4),
        "window.model_p_sum": round(sum(float(w.get("model_p", -1) or -1) for w in ep.window), 3),
        # Round 2: the new-typology queries (19_typology_scan, 20_recipient_activity) and the 30-day window
        "window_30d": len(ep.extra.get("window_30d") or []), "micro_prior_n": ep.extra.get("micro_prior_n"),
        "recipient": {d: (len(st["cards_window"]), len(st.get("window_txns") or []))
                      for d, st in (ep.extra.get("recipient") or {}).items()},
        "typology_scan": {k: len(v) for k, v in (ep.extra.get("typology_scan") or {}).items()},
    }


def _ring(facts: dict) -> dict:
    plan = facts.get("containment") or {}
    return {"connected": sorted(facts.get("connected_cards") or []), "weak": sorted(facts.get("weak_ring_cards") or []),
            "block": sorted(m["card"] for m in plan.get("block", []))}


def main(ids: list[str]) -> None:
    tg, mi = GraphClient(use_mcp=True), MirrorGraph()
    cases = [c for c in csv.DictReader(CASE_PACK_CSV.open(encoding="utf-8"))
             if not ids or c["case_id"] in ids]
    bad = 0
    for c in cases:
        a, b = gather(c, tg), gather(c, mi)
        sa, sb = summary(a), summary(b)
        diffs = {k: (sa[k], sb[k]) for k in sa if sa[k] != sb[k]}
        (fa_list, xa), (fb_list, xb) = run_detectors(a), run_detectors(b)
        fa, fb = sorted(f.key for f in fa_list), sorted(f.key for f in fb_list)
        # the ring and the containment plan, not just list sizes: who is connected, who would be blocked
        ra, rb = _ring(xa), _ring(xb)
        if ra != rb:
            diffs["ring/containment"] = (ra, rb)
        ok = not diffs and fa == fb
        bad += 0 if ok else 1
        print(f"{c['case_id']} {'OK ' if ok else 'DIFF'} findings={fa}" + ("" if ok else f"\n    diffs={diffs}\n    mirror_findings={fb}"))
    via = {x.via for x in tg.trace.calls}
    print(f"\n{len(cases) - bad}/{len(cases)} cases identical; TigerGraph calls via {via}; "
          f"avg TG latency {sum(x.ms for x in tg.trace.calls) / max(len(tg.trace.calls), 1):.0f} ms")
    # typology_scan returns thousands of rows: watch it against the 60 s MCP call timeout
    for q in ("typology_scan", "recipient_activity"):
        ms = [x.ms for x in tg.trace.calls if x.query == q]
        if ms:
            print(f"{q}: {len(ms)} calls, max {max(ms) / 1000:.1f} s, max rows {max(x.rows for x in tg.trace.calls if x.query == q)}")


if __name__ == "__main__":
    main(sys.argv[1:])
