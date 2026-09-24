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
    }


def main(ids: list[str]) -> None:
    tg, mi = GraphClient(use_mcp=True), MirrorGraph()
    cases = [c for c in csv.DictReader((ROOT / "data" / "raw" / "case_pack.csv").open(encoding="utf-8"))
             if not ids or c["case_id"] in ids]
    bad = 0
    for c in cases:
        a, b = gather(c, tg), gather(c, mi)
        sa, sb = summary(a), summary(b)
        diffs = {k: (sa[k], sb[k]) for k in sa if sa[k] != sb[k]}
        fa = sorted(f.key for f in run_detectors(a)[0])
        fb = sorted(f.key for f in run_detectors(b)[0])
        ok = not diffs and fa == fb
        bad += 0 if ok else 1
        print(f"{c['case_id']} {'OK ' if ok else 'DIFF'} findings={fa}" + ("" if ok else f"\n    diffs={diffs}\n    mirror_findings={fb}"))
    via = {x.via for x in tg.trace.calls}
    print(f"\n{len(cases) - bad}/{len(cases)} cases identical; TigerGraph calls via {via}; "
          f"avg TG latency {sum(x.ms for x in tg.trace.calls) / max(len(tg.trace.calls), 1):.0f} ms")


if __name__ == "__main__":
    main(sys.argv[1:])
