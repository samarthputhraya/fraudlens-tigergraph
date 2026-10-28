"""Run the agent on the case pack (in opened_at order so later cases can recall earlier ones) and write one answer
file per case.

  python run_cases.py HHF-007            # one case: TigerGraph via MCP (official), case memory written to the graph
  python run_cases.py                    # every case in the pack
  python run_cases.py --mirror --no-write --out runs/dev   # offline DuckDB mirror, labelled not official
  python run_cases.py --rest HHF-007     # TigerGraph over REST instead of MCP: an explicit, recorded choice
  python run_cases.py --pack drills.csv  # a different case pack, e.g. the resilience drills (eval/drills.py)

Fail closed: if the graph, the tool layer or the case itself fails, that case stops, no answer is presented for it
(an earlier answer for the same case is moved to <out>/stale/), the failure is printed, recorded and audited, and the
run carries on with the next case. Exit status: 0 all answered and complete; 3 some answers are marked incomplete (a
model step failed; the decision stands but is escalated); 2 some cases stopped; 1 bad command line.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from agent.paths import CASE_PACK_CSV, CASES_OUT  # noqa: E402
from agent.safety import DependencyFailure, InvalidInput, audit, redact, redact_obj  # noqa: E402

OUT = CASES_OUT
TRACE = ROOT / "runs" / "traces"
REQUIRED = ("case_id", "opened_at", "trigger_type", "trigger_text", "flagged_txn_id", "card_id", "customer_id")
TRIGGERS = {"risk_score", "customer_report", "analyst_request"}


def check_row(c: dict) -> None:
    """Reject a malformed case row before anything is investigated."""
    missing = [k for k in REQUIRED if not str(c.get(k) or "").strip() and k != "trigger_text"]
    if missing:
        raise InvalidInput("case_row", f"missing field(s): {', '.join(missing)}")
    try:
        datetime.fromisoformat(c["opened_at"].strip())
    except ValueError:
        raise InvalidInput("case_row", f"opened_at {c['opened_at']!r} is not a timestamp") from None
    if c["trigger_type"] not in TRIGGERS:
        raise InvalidInput("case_row", f"trigger_type {c['trigger_type']!r} is not one of {sorted(TRIGGERS)}")


def set_aside(case_id: str) -> list[str]:
    """A stopped case must not leave an older answer that looks current: move it (and its trace) to <out>/stale/."""
    moved = []
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for src in (OUT / f"{case_id}.json", TRACE / f"{case_id}.json"):
        if src.exists():
            dest = OUT / "stale" / f"{src.parent.name}-{case_id}.{stamp}.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), dest)
            moved.append(str(dest.relative_to(ROOT)) if dest.is_relative_to(ROOT) else str(dest))
    return moved


def main() -> int:
    global OUT, TRACE
    if "--out" in sys.argv:
        # dev runs write somewhere else so the official answers are never touched by accident
        OUT = Path(sys.argv[sys.argv.index("--out") + 1])
        OUT = OUT if OUT.is_absolute() else ROOT / OUT
        TRACE = OUT / "traces"
        sys.argv.pop(sys.argv.index("--out") + 1)
    pack = CASE_PACK_CSV
    if "--pack" in sys.argv:
        pack = Path(sys.argv[sys.argv.index("--pack") + 1])
        sys.argv.pop(sys.argv.index("--pack") + 1)
        if not pack.is_file():
            print(f"error: no case pack at {pack}", file=sys.stderr)
            return 1
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    cases = list(csv.DictReader(pack.open(encoding="utf-8")))
    unknown = [a for a in args if a not in {c["case_id"] for c in cases}]
    if unknown:
        print(f"error: not in {pack.name}: {', '.join(unknown)}", file=sys.stderr)
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
    summary, failed, incomplete = [], [], []
    for c in cases:
        if args and c["case_id"] not in args:
            continue
        events.clear()
        n0 = len(g.trace.calls)
        try:
            check_row(c)
            out = inv.run(c)
        except Exception as e:  # noqa: BLE001 - every failure stops this case only, loudly, with a record
            err = e if isinstance(e, DependencyFailure) else DependencyFailure("agent", "unexpected", f"{type(e).__name__}: {e}")
            record = {"case_id": c["case_id"], "stopped": True, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **err.as_dict(),
                      "moved_aside": set_aside(c["case_id"]),
                      "tool_calls_before_failure": [dict(query=x.query, params=redact_obj(x.params), ok=x.ok, via=x.via)
                                                    for x in g.trace.calls[n0:]]}
            stamp = time.strftime("%Y%m%d-%H%M%S")
            (TRACE / f"{c['case_id']}.FAILED.{stamp}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
            audit("case_stopped", record)
            line = f"{c['case_id']} STOPPED: {redact(str(err))}. No answer written for this case."
            print(line, flush=True)
            summary.append(line)
            failed.append(c["case_id"])
            continue
        ans = out["answer"]
        text = json.dumps(ans, indent=2)
        (OUT / f"{c['case_id']}.json").write_bytes(text.encode("utf-8"))  # exact bytes: the audit records their hash
        trace = {"case_id": c["case_id"], "events": events,
                 "tool_calls": [dict(agent=x.agent, tool=x.tool, query=x.query, ref=x.ref(), params={k: v for k, v in x.params.items() if k != "qv"}, rows=x.rows, ms=round(x.ms, 1), via=x.via, ok=x.ok)
                                for x in g.trace.calls[n0:]],
                 "specialists": out.get("specialists"), "lead": out.get("lead"), "critic": out.get("critic"),
                 "problems": out.get("problems"), "written": out.get("written")}
        trace_text = json.dumps(redact_obj(json.loads(json.dumps(trace, default=str))), indent=2)
        (TRACE / f"{c['case_id']}.json").write_text(trace_text, encoding="utf-8")
        a = ans["case"]
        audit("case_answered", {"case_id": c["case_id"], "verdict": a["verdict"], "probability": a["fraud_probability"],
                                "final": [x["action"] for x in ans["next_best_actions"]["final"]],
                                "graph": ans["run"]["graph"], "complete": ans["run"]["complete"],
                                "answer_sha256": hashlib.sha256(text.encode()).hexdigest(),
                                "trace_sha256": hashlib.sha256(trace_text.encode()).hexdigest()})
        if not ans["run"]["complete"]:
            incomplete.append(c["case_id"])
        line = (f"{c['case_id']} {a['verdict']:10s} p={a['fraud_probability']:.2f} {a['pattern']:28s} "
                f"${a['exposure_usd']:>9.2f} sar={ans['sar']['file']!s:5s} calls={ans['tool_calls']:>2} tok={ans['tokens']:>6} "
                f"{ans['latency_s']:>5.1f}s graph={a['written_to_graph']} "
                f"{'complete' if ans['run']['complete'] else 'INCOMPLETE (escalated)'} problems={out.get('problems')}")
        print(line, flush=True)
        summary.append(line)
    (OUT / "last_run.txt").write_text("\n".join(summary), encoding="utf-8")
    if failed:
        print(f"\n{len(failed)} case(s) stopped: {', '.join(failed)}", file=sys.stderr)
        return 2
    if incomplete:
        print(f"\n{len(incomplete)} answer(s) are marked incomplete and escalated: {', '.join(incomplete)}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
