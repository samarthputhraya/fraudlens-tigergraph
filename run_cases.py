"""Run the agent on the case pack (in opened_at order so later cases can recall earlier ones) and write one answer
file per case.

  python run_cases.py HHF-007            # one case: TigerGraph via MCP (official), case memory written to the graph
  python run_cases.py                    # every case in the pack
  python run_cases.py --mirror --no-write --out runs/dev   # offline DuckDB mirror, labelled not official
  python run_cases.py --rest HHF-007     # TigerGraph over REST instead of MCP: an explicit, recorded choice

Fail closed: if the graph or the tool layer fails mid-investigation, that case stops, no answer is written for it,
the failure is printed and audited, and the command exits with status 2. A model failure doesn't change the
decision (it is code), but the answer is marked incomplete and escalated to an analyst.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from agent.paths import CASE_PACK_CSV, CASES_OUT  # noqa: E402
from agent.safety import DependencyFailure, audit  # noqa: E402

OUT = CASES_OUT
TRACE = ROOT / "runs" / "traces"


def main() -> int:
    global OUT, TRACE
    if "--out" in sys.argv:
        # dev runs write somewhere else so the official answers are never touched by accident
        OUT = ROOT / sys.argv[sys.argv.index("--out") + 1]
        TRACE = OUT / "traces"
        sys.argv.pop(sys.argv.index("--out") + 1)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    cases = list(csv.DictReader(CASE_PACK_CSV.open(encoding="utf-8")))
    unknown = [a for a in args if a not in {c["case_id"] for c in cases}]
    if unknown:
        print(f"error: not in {CASE_PACK_CSV.name}: {', '.join(unknown)}", file=sys.stderr)
        return 1

    try:
        if "--mirror" in sys.argv:
            from agent.mirror import MirrorGraph
            g = MirrorGraph()
            print("NOTE: offline DuckDB mirror. These answers are for development and are not official.", flush=True)
        else:
            from agent.graph_client import GraphClient
            g = GraphClient(use_mcp="--rest" not in sys.argv)
    except DependencyFailure as e:
        print(f"STOPPED: {e}. No case was investigated.", file=sys.stderr)
        return 2
    from agent.workflow import Investigator

    cases.sort(key=lambda c: c["opened_at"])
    OUT.mkdir(parents=True, exist_ok=True)
    TRACE.mkdir(parents=True, exist_ok=True)
    events: list = []
    inv = Investigator(g, emit=lambda k, d: events.append({"t": round(time.time(), 2), "kind": k, **{x: y for x, y in d.items() if x != "answer"}}),
                       write_graph="--no-write" not in sys.argv, use_llm="--no-llm" not in sys.argv)
    summary, failed = [], []
    for c in cases:
        if args and c["case_id"] not in args:
            continue
        events.clear()
        n0 = len(g.trace.calls)
        try:
            out = inv.run(c)
        except DependencyFailure as e:
            # fail closed: no answer for this case, a clear message, and a record of what failed
            record = {"case_id": c["case_id"], "stopped": True, **e.as_dict(),
                      "tool_calls_before_failure": [dict(query=x.query, ok=x.ok, via=x.via) for x in g.trace.calls[n0:]]}
            (TRACE / f"{c['case_id']}.FAILED.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
            audit("case_stopped", record)
            line = f"{c['case_id']} STOPPED: {e}. No answer written for this case."
            print(line, flush=True)
            summary.append(line)
            failed.append(c["case_id"])
            continue
        ans = out["answer"]
        text = json.dumps(ans, indent=2)
        (OUT / f"{c['case_id']}.json").write_text(text, encoding="utf-8")
        stale = TRACE / f"{c['case_id']}.FAILED.json"
        if stale.exists():
            stale.unlink()
        trace = {"case_id": c["case_id"], "events": events,
                 "tool_calls": [dict(agent=x.agent, tool=x.tool, query=x.query, ref=x.ref(), params={k: v for k, v in x.params.items() if k != "qv"}, rows=x.rows, ms=round(x.ms, 1), via=x.via, ok=x.ok)
                                for x in g.trace.calls[n0:]],
                 "specialists": out.get("specialists"), "lead": out.get("lead"), "critic": out.get("critic"),
                 "problems": out.get("problems"), "written": out.get("written")}
        (TRACE / f"{c['case_id']}.json").write_text(json.dumps(trace, indent=2, default=str), encoding="utf-8")
        a = ans["case"]
        audit("case_answered", {"case_id": c["case_id"], "verdict": a["verdict"], "probability": a["fraud_probability"],
                                "final": [x["action"] for x in ans["next_best_actions"]["final"]],
                                "graph": ans["run"]["graph"], "complete": ans["run"]["complete"],
                                "answer_sha256": hashlib.sha256(text.encode()).hexdigest()})
        line = (f"{c['case_id']} {a['verdict']:10s} p={a['fraud_probability']:.2f} {a['pattern']:28s} "
                f"${a['exposure_usd']:>9.2f} sar={ans['sar']['file']!s:5s} calls={ans['tool_calls']:>2} tok={ans['tokens']:>6} "
                f"{ans['latency_s']:>5.1f}s graph={a['written_to_graph']} complete={ans['run']['complete']} problems={out.get('problems')}")
        print(line, flush=True)
        summary.append(line)
    (OUT / "last_run.txt").write_text("\n".join(summary), encoding="utf-8")
    if failed:
        print(f"\n{len(failed)} case(s) stopped on a dependency failure: {', '.join(failed)}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
