"""Ablation for the innovation claim: run the 18 final-round cases with each contribution switched off and compare.

  full          everything on
  -typologies   the new-typology detectors and ring scans off (agent/typologies.py)
  -drift        the model is the starting point again, as in Round 1, even for January
  -both         roughly the Round 1 agent on Round 2 data

Decisions only (no model calls), offline mirror. Writes eval/ablation.json.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.paths import CASE_PACK_CSV  # noqa: E402

VARIANTS = {"full": "", "-typologies": "typologies", "-drift": "drift", "-both": "typologies,drift"}


def main() -> None:
    from agent.mirror import MirrorGraph
    from agent.workflow import Investigator
    pack = sorted(csv.DictReader(CASE_PACK_CSV.open(encoding="utf-8")), key=lambda c: c["opened_at"])
    g = MirrorGraph()
    out: dict = {}
    for name, ablate in VARIANTS.items():
        os.environ["FRAUDLENS_ABLATE"] = ablate
        rows = {}
        for c in pack:
            a = Investigator(g, write_graph=False, use_llm=False).run(c)["answer"]
            fin = [x["action"] for x in a["next_best_actions"]["final"]]
            rows[c["case_id"]] = {"verdict": a["case"]["verdict"], "p": a["case"]["fraud_probability"],
                                  "pattern": a["case"]["pattern"], "block": "BLOCK_CARD" in fin, "sar": a["sar"]["file"]}
        out[name] = {"cases": rows, "verdicts": dict(Counter(r["verdict"] for r in rows.values())),
                     "blocks": sum(r["block"] for r in rows.values()), "sars": sum(r["sar"] for r in rows.values())}
        print(f"{name:12s} verdicts={out[name]['verdicts']} blocks={out[name]['blocks']} sars={out[name]['sars']}", flush=True)
    os.environ.pop("FRAUDLENS_ABLATE", None)
    full = out["full"]["cases"]
    for name in list(VARIANTS)[1:]:
        diff = {cid: f"{out[name]['cases'][cid]['verdict']} -> {full[cid]['verdict']}" for cid in full
                if out[name]["cases"][cid]["verdict"] != full[cid]["verdict"]}
        out[name]["changed_vs_full"] = diff
        print(f"{name:12s} differs from full on {len(diff)} case(s): {diff}")
    (ROOT / "eval" / "ablation.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
