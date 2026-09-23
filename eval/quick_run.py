"""Run the deterministic core over the 20 benchmark cases (mirror backend) and print a one-line verdict per case."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.core import investigate  # noqa: E402
from agent.mirror import MirrorGraph  # noqa: E402


def main(ids: list[str], verbose: bool) -> None:
    g = MirrorGraph()
    cases = list(csv.DictReader((ROOT / "data" / "raw" / "case_pack.csv").open(encoding="utf-8")))
    for c in cases:
        if ids and c["case_id"] not in ids:
            continue
        r = investigate(c, g)
        acts0 = ",".join(a["action"] for a in r["initial"])
        acts1 = ",".join(a["action"] for a in r["final"])
        print(f"{c['case_id']} {c['trigger_type'][:8]:8s} p0={r['ledger']['p']:.2f} v0={r['verdict0'][:5]:5s} -> "
              f"{r['verdict'][:5]:5s} p={r['p_final']:.2f} {r['pattern'][:22]:22s} exp=${r['exposure']:>8.2f} n={len(r['episode'])} "
              f"sar={int(r['sar_file'])} reply={r['reply']} | I: {acts0} | F: {acts1}")
        if verbose:
            for f in r["findings"]:
                print(f"      [{f.lr:>5.1f} {f.family:9s}] {f.claim[:170]}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    main(args, "-v" in sys.argv)
