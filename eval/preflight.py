"""Preflight before the official run: is everything in place? Prints OK / WARN / FAIL per item and never prints a
secret (only whether it is set and long enough).

  python eval/preflight.py           # local checks: .env, data files, git state, existing answers
  python eval/preflight.py --live    # also: TigerGraph answers (graph/setup.py stats) and one tiny Gemini call

Exit status 0 when nothing FAILs.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from agent.paths import CASE_PACK_CSV, CASES_OUT, CLOSED_EMB, DB, GRADER, LOAD_DIR, MODEL_SCORES, POLICY_MD  # noqa: E402

results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, detail: str = "", warn_only: bool = False) -> None:
    results.append(("OK" if ok else ("WARN" if warn_only else "FAIL"), name, detail))


def env_checks() -> None:
    check(".env exists", (ROOT / ".env").exists(), "copy .env.example and fill it in")
    for k in ("TG_HOST", "TG_GRAPHNAME", "TG_SECRET", "GOOGLE_CLOUD_PROJECT"):
        check(f"{k} is set", bool(os.getenv(k)), "needed for the official run")
    tokens = {}
    for part in os.getenv("FRAUDLENS_APPROVER_TOKENS", "").split(","):
        role, _, tok = part.strip().partition(":")
        if role:
            tokens[role] = tok
    for role in ("team_lead", "fraud_manager"):
        n = len(tokens.get(role, ""))
        check(f"approver token for {role}", n >= 24, f"{'missing' if not n else f'only {n} characters'}; "
                                                    f"format team_lead:<24+ chars>,fraud_manager:<24+ chars>")
    if tokens.get("team_lead") and tokens.get("team_lead") == tokens.get("fraud_manager"):
        check("approver tokens differ", False, "the two roles must have different tokens")
    n = len(os.getenv("FRAUDLENS_AUDIT_KEY", ""))
    check("FRAUDLENS_AUDIT_KEY (32+ characters)", n >= 32,
          "missing: the audit log can't prove who wrote it" if not n else f"only {n} characters")
    check("not in mirror mode", os.getenv("FRAUDLENS_MIRROR", "") != "1", "unset FRAUDLENS_MIRROR for the official run")
    check("no fault drill armed", not os.getenv("FRAUDLENS_FAULT"), "unset FRAUDLENS_FAULT before the official run")
    check("model text fenced", os.getenv("FRAUDLENS_UNFENCED", "") != "1", "unset FRAUDLENS_UNFENCED")


def file_checks() -> None:
    for name, p in (("case pack", CASE_PACK_CSV), ("bank policy", POLICY_MD), ("organisers' grader", GRADER),
                    ("DuckDB (backtests, parity)", DB), ("January model scores", MODEL_SCORES),
                    ("closed-case embeddings", CLOSED_EMB)):
        check(f"{name}: {p.relative_to(ROOT)}", p.exists(), "missing")
    csvs = list(LOAD_DIR.glob("*.csv")) if LOAD_DIR.exists() else []
    check(f"January load files in {LOAD_DIR.relative_to(ROOT)}", bool(csvs), f"{len(csvs)} CSV files")
    queries = ROOT / "graph" / "queries"
    for q in ("03_card_profile", "19_typology_scan", "20_recipient_activity"):
        check(f"query file {q}.gsql", (queries / f"{q}.gsql").exists(), "missing")


def git_checks() -> None:
    def git(*a: str) -> str:
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    check(f"on branch round2 (now {branch})", branch == "round2", "git checkout round2")
    dirty = [x for x in git("status", "--porcelain").splitlines() if not x.endswith(".env")]
    check("working tree clean", not dirty, f"{len(dirty)} uncommitted change(s): commit them before the freeze",
          warn_only=True)
    existing = sorted(CASES_OUT.glob("HHF-*.json"))
    check(f"{CASES_OUT.name}/ answers", True,
          f"{len(existing)} existing answer(s); the official run replaces them" if existing else "empty, ready")


def live_checks() -> None:
    try:
        p = subprocess.run([sys.executable, str(ROOT / "graph" / "setup.py"), "stats"], cwd=ROOT, capture_output=True,
                           text=True, timeout=120)
        out = (p.stdout + p.stderr).strip().splitlines()
        check("TigerGraph answers (graph/setup.py stats)", p.returncode == 0 and "Transaction" in (p.stdout or ""),
              (out[-1] if out else "no output")[:120])
    except subprocess.TimeoutExpired:
        check("TigerGraph answers (graph/setup.py stats)", False, "timed out after 120 s: is the workspace resumed?")
    try:
        from agent.llm import FLASH, generate
        txt = generate("Reply with the single word OK.", model=FLASH, cache=False, role="preflight")
        check(f"Gemini on Vertex ({FLASH})", "ok" in txt.lower(), txt.strip()[:40])
    except Exception as e:  # noqa: BLE001
        check("Gemini on Vertex", False, f"{type(e).__name__}: {str(e)[:120]}")


def main(live: bool) -> int:
    env_checks()
    file_checks()
    git_checks()
    if live:
        live_checks()
    for status, name, detail in results:
        print(f"{status:4s}  {name}" + (f"  ({detail})" if detail and status != "OK" or name.endswith("answers") else ""))
    fails = sum(1 for s, _, _ in results if s == "FAIL")
    print(f"\n{len(results) - fails}/{len(results)} checks pass" + ("" if live else "; add --live to test TigerGraph and Gemini"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main("--live" in sys.argv))
