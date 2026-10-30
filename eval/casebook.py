"""Case-book consistency gate (agent/casebook.py): run it over a folder of answers before freezing them.

  python eval/casebook.py                      # the official answers in cases_r2/
  python eval/casebook.py runs/dev_all         # any other folder of answers
  python eval/casebook.py --compare cases_r2 runs/dev_all

Exit status 1 when a card is cleared in one case although that case's own evidence flagged other charges on it and
another case reports it or plans to block it (a decision error). Everything else is printed for the analyst.
Writes eval/casebook.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import casebook  # noqa: E402
from agent.paths import CASE_PACK_CSV, CASES_OUT  # noqa: E402


def run(folder: Path) -> tuple[list[dict], dict]:
    answers, pack = casebook.load(folder, CASE_PACK_CSV)
    found = casebook.check(answers, pack)
    return found, casebook.summary(found)


def show(folder: Path, found: list[dict], s: dict) -> None:
    print(f"{folder}: {s['high']} high ({s['high_seen_at_open']} decision error(s)), {s['low']} low, "
          f"{s['linked_reports']} report(s) to cross-reference")
    for f in found:
        if f["severity"] == "linked":
            print(f"  linked  {f['card']}: {f['action']}")
        else:
            print(f"  {f['severity']:<6}  {f['card']}: cleared in {f['cleared_in']} ({f['cleared_opened_at'][:10]}), "
                  f"{f['other_role']} in {f['other_case']} ({f['other_opened_at'][:10]}) -> {f['action']}")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    folders = [Path(a) if Path(a).is_absolute() else ROOT / a for a in args] or [CASES_OUT]
    out = {}
    for folder in folders:
        found, s = run(folder)
        show(folder, found, s)
        out[str(folder.relative_to(ROOT)) if folder.is_relative_to(ROOT) else str(folder)] = {"summary": s, "findings": found}
    (ROOT / "eval" / "casebook.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    last = out[list(out)[-1]]["summary"]
    return 1 if last["high_seen_at_open"] else 0


if __name__ == "__main__":
    sys.exit(main())
