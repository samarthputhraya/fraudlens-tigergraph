"""Run the agent on the case pack (in opened_at order so later cases can recall earlier ones) and write cases/*.json.

  python run_cases.py                   # all 20, TigerGraph via MCP, write case memory to the graph
  python run_cases.py HHG-006 HHG-014   # a subset
  python run_cases.py --mirror --no-write --no-llm --out runs/dry   # offline dry run (does not touch cases/)
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from agent.workflow import Investigator  # noqa: E402

OUT = ROOT / "cases"
TRACE = ROOT / "runs" / "traces"


def main() -> None:
    global OUT, TRACE
    if "--out" in sys.argv:
        # dry runs write somewhere else so the official answers in cases/ are never touched by accident
        OUT = ROOT / sys.argv[sys.argv.index("--out") + 1]
        TRACE = OUT / "traces"
        sys.argv.pop(sys.argv.index("--out") + 1)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    mirror = "--mirror" in sys.argv
    if mirror:
        from agent.mirror import MirrorGraph
        g = MirrorGraph()
    else:
        from agent.graph_client import GraphClient
        g = GraphClient(use_mcp="--rest" not in sys.argv)
    cases = list(csv.DictReader((ROOT / "data" / "raw" / "case_pack.csv").open(encoding="utf-8")))
    cases.sort(key=lambda c: c["opened_at"])
    OUT.mkdir(exist_ok=True)
    TRACE.mkdir(parents=True, exist_ok=True)
    events: list = []
    inv = Investigator(g, emit=lambda k, d: events.append({"t": round(time.time(), 2), "kind": k, **{x: y for x, y in d.items() if x != "answer"}}),
                       write_graph="--no-write" not in sys.argv, use_llm="--no-llm" not in sys.argv)
    summary = []
    for c in cases:
        if args and c["case_id"] not in args:
            continue
        events.clear()
        n0 = len(g.trace.calls)
        out = inv.run(c)
        ans = out["answer"]
        (OUT / f"{c['case_id']}.json").write_text(json.dumps(ans, indent=2), encoding="utf-8")
        trace = {"case_id": c["case_id"], "events": events,
                 "tool_calls": [dict(agent=x.agent, tool=x.tool, query=x.query, ref=x.ref(), params={k: v for k, v in x.params.items() if k != "qv"}, rows=x.rows, ms=round(x.ms, 1), via=x.via)
                                for x in g.trace.calls[n0:]],
                 "specialists": out.get("specialists"), "lead": out.get("lead"), "critic": out.get("critic"),
                 "problems": out.get("problems"), "written": out.get("written")}
        (TRACE / f"{c['case_id']}.json").write_text(json.dumps(trace, indent=2, default=str), encoding="utf-8")
        a = ans["case"]
        line = (f"{c['case_id']} {a['verdict']:10s} p={a['fraud_probability']:.2f} {a['pattern']:28s} "
                f"${a['exposure_usd']:>9.2f} sar={ans['sar']['file']!s:5s} calls={ans['tool_calls']:>2} tok={ans['tokens']:>6} "
                f"{ans['latency_s']:>5.1f}s graph={a['written_to_graph']} problems={out.get('problems')}")
        print(line, flush=True)
        summary.append(line)
    last = ROOT / "runs" / "last_run.txt" if OUT == ROOT / "cases" else OUT / "last_run.txt"
    last.write_text("\n".join(summary), encoding="utf-8")


if __name__ == "__main__":
    main()
