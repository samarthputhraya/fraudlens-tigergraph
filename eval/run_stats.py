"""Challenge 9, speed and cost: per-case latency, tool calls and model tokens from a run's answer files.

  python eval/run_stats.py runs/llm1      ->  prints p50 / p95 latency, mean tool calls and tokens
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def main(folder: Path) -> dict:
    rows = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(folder.glob("HHF-*.json"))]
    lat = [r["latency_s"] for r in rows]
    tok = [r["tokens"] for r in rows]
    calls = [r["tool_calls"] for r in rows]
    out = {"cases": len(rows), "latency_p50_s": pct(lat, 0.5), "latency_p95_s": pct(lat, 0.95),
           "latency_max_s": max(lat), "tool_calls_mean": round(statistics.mean(calls), 1),
           "tokens_mean": round(statistics.mean(tok)), "tokens_total": sum(tok),
           "complete": sum(1 for r in rows if r.get("run", {}).get("complete", True)),
           "graph": rows[0].get("run", {}).get("graph") if rows else None}
    print(json.dumps(out))
    return out


if __name__ == "__main__":
    main(ROOT / (sys.argv[1] if len(sys.argv) > 1 else "cases_r2"))
