"""Challenge 6, regulator's view: replay one investigation step by step from its trace, so an outsider can see what the
agent saw at each step, which tool it called, what came back, and why the decision moved.

  python eval/replay.py HHF-007 [--dir runs/llm1] [--rerun]

--rerun re-executes every recorded read query on the offline mirror and checks the row count still matches (on
TigerGraph, use the Command Center's re-prove, which replays the same reference).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(case_id: str, folder: Path, rerun: bool) -> None:
    traces = folder / "traces" if (folder / "traces").is_dir() else ROOT / "runs" / "traces"  # official runs: runs/traces
    trace = json.loads((traces / f"{case_id}.json").read_text(encoding="utf-8"))
    ans = json.loads((folder / f"{case_id}.json").read_text(encoding="utf-8"))
    print(f"REPLAY {case_id}  (graph: {ans['run']['graph']}, run at {ans['run']['started_at']}, "
          f"{'complete' if ans['run']['complete'] else 'INCOMPLETE'})\n")
    calls = list(trace["tool_calls"])
    g = None
    if rerun:
        from agent.mirror import MirrorGraph
        sys.path.insert(0, str(ROOT / "eval"))
        from attest_check import rerun as rerun_query
        g = MirrorGraph()
    step = 0
    for ev in trace["events"]:
        kind = ev.get("kind")
        if kind == "trigger":
            print(f"[alert] {ev['trigger_type']} opened {ev['opened_at']}: {ev['text'][:160]}")
        elif kind == "stage":
            print(f"\n[{ev.get('stage')}] {ev.get('msg', '')[:160]}")
        elif kind == "plan":
            print(f"[planner] hypotheses: {'; '.join(ev.get('hypotheses', []))[:200]} | extra calls: "
                  f"{[c.get('tool') for c in ev.get('calls', [])]}")
        elif kind == "finding":
            print(f"   finding {ev['key']:22s} LR {ev['lr']:>6.2f} {'(in model)' if ev.get('in_model') else ''} "
                  f"{ev['claim'][:120]}")
        elif kind == "assessment":
            print(f"\n[assessment] prior {ev['prior']:.3f} -> p {ev['p']:.2f}; verdict {ev['verdict']}, pattern {ev['pattern']}; "
                  f"initial actions {[a['action'] for a in ev['initial']]}")
        elif kind == "evidence_request":
            print(f"[evidence request] {ev['type']} -> assumed: {ev['assumed_response'][:120]}")
        elif kind == "decision":
            print(f"[decision] {ev['verdict']} p={ev['p']} final {[a['action'] for a in ev['final']]} status {ev['status']}")
        elif kind == "warning":
            print(f"[warning] {ev.get('msg', '')[:200]}")
        elif kind == "review":
            print(f"[compliance review] agree={ev.get('agree')} issues={ev.get('issues', [])[:2]}")
    print("\n[tool calls, in order]")
    for c in calls:
        step += 1
        line = f"  {step:>2}. {c['agent']:12s} {c['query']:20s} rows={c['rows']:>5} {c['ms']:>7.1f} ms via {c['via']}  {c['ref'][:110]}"
        if g is not None:
            before = len(g.trace.calls)
            if rerun_query(g, c["query"], c["params"]) is not None and len(g.trace.calls) > before:
                # the re-run is counted by the same logging code that counted the original call
                n = g.trace.calls[-1].rows
                line += f"  | re-run rows={n} {'OK' if n == c['rows'] else 'DIFFERS'}"
        print(line)
    print(f"\n[answer] {ans['case']['verdict']} p={ans['case']['fraud_probability']} pattern={ans['case']['pattern']} "
          f"exposure=${ans['case']['exposure_usd']:,.2f} report={ans['sar']['file']}")
    print(f"[stop reason] {ans['stop_reason'][:300]}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    d = sys.argv[sys.argv.index("--dir") + 1] if "--dir" in sys.argv else "cases_r2"
    if "--dir" in sys.argv:
        args = [a for a in args if a != d]
    folder = Path(d) if Path(d).is_absolute() else ROOT / d
    main(args[0], folder, "--rerun" in sys.argv)
