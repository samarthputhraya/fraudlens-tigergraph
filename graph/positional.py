"""Rewrite loading_jobs.gsql column references $"name" -> $<index> using each job's CSV header (TG 4.x needs a bound
file to resolve header names, and our files are posted at run time)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOB_FILE = {"load_customers": "customers", "load_cards": "cards", "load_transactions": "transactions",
            "load_accounts": "accounts", "load_account_edges": "account_edges", "load_next": "next_edges",
            "load_devices": "devices", "load_device_edges": "device_edges", "load_card_device": "card_device",
            "load_card_region": "card_region", "load_closed_cases": "closed_cases",
            "load_closed_involves": "closed_involves", "load_closed_connected": "closed_connected"}


def main() -> None:
    src = (ROOT / "graph" / "loading_jobs.gsql").read_text(encoding="utf-8")
    out = []
    for block in re.split(r"(?=CREATE LOADING JOB )", src):
        m = re.match(r"CREATE LOADING JOB (\w+)", block)
        if m:
            header = (ROOT / "data" / "prep" / "load" / f"{JOB_FILE[m.group(1)]}.csv").open(encoding="utf-8").readline().strip().split(",")
            idx = {h: i for i, h in enumerate(header)}
            block = re.sub(r'\$"(\w+)"', lambda mm: f"${idx[mm.group(1)]}", block)
        out.append(block)
    (ROOT / "graph" / "loading_jobs_positional.gsql").write_text("".join(out), encoding="utf-8")
    print("written graph/loading_jobs_positional.gsql")


if __name__ == "__main__":
    main()
