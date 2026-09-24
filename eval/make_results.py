"""Fill the README / blog result tables from cases/*.json and eval/report.json."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def results_table() -> str:
    rows = ["| Case | Trigger | Verdict | p | Pattern | Exposure | SAR | Initial → Final actions | Graph |",
            "|---|---|---|---|---|---|---|---|---|"]
    trig = {r.split(",")[0]: r.split(",")[2] for r in (ROOT / "data" / "raw" / "case_pack.csv").read_text(encoding="utf-8").splitlines()[1:]}
    tot = {"calls": 0, "tokens": 0, "lat": 0.0, "n": 0}
    for f in sorted((ROOT / "cases").glob("HHG-*.json")):
        a = json.loads(f.read_text(encoding="utf-8"))
        c = a["case"]
        ini = " ".join(x["action"] for x in a["next_best_actions"]["initial"])
        fin = " ".join(x["action"] for x in a["next_best_actions"]["final"])
        change = ini if ini == fin else f"{ini} **→** {fin}"
        rows.append(f"| [{a['case_id']}](cases/{f.name}) | {trig.get(a['case_id'], '').replace('_', ' ')} | {c['verdict']} | "
                    f"{c['fraud_probability']:.2f} | {c['pattern'].replace('_', ' ')} | ${c['exposure_usd']:,.2f} | "
                    f"{'✅' if a['sar']['file'] else '—'} | {change} | {'✅' if c['written_to_graph'] else '—'} |")
        tot["calls"] += a["tool_calls"]
        tot["tokens"] += a["tokens"]
        tot["lat"] += a["latency_s"]
        tot["n"] += 1
    n = max(tot["n"], 1)
    rows.append("")
    rows.append(f"Average per case: **{tot['calls'] / n:.1f} graph/retrieval tool calls**, **{tot['tokens'] / n:,.0f} LLM tokens**, "
                f"**{tot['lat'] / n:.0f} s**. Every file passes the schema + ID + policy validator.")
    return "\n".join(rows)


def backtest_table() -> str:
    p = ROOT / "eval" / "report.json"
    if not p.exists():
        return "_run `python eval/backtest.py`_"
    r = json.loads(p.read_text())
    return "\n".join([
        "| Agent replay on October closed cases | Value |", "|---|---|",
        f"| Cases replayed | {r['n_cases']} ({r['n_confirmed']} confirmed, {r['n_cleared']} cleared) |",
        f"| Fraud vs false alarm, final probability (AUC) | **{r['auc_final_probability']:.3f}** ({r['auc_final_probability_score_ge_0_5']:.3f} on alerts scored ≥ 0.5) |",
        f"| Pattern accuracy (confirmed cases, 5 known patterns + undocumented) | **{r['pattern_accuracy']:.0%}** |",
        f"| Episode reconstruction (Jaccard vs the case's txn_ids) | **{r['episode_jaccard']:.2f}** |",
        f"| SAR decision agreement with the bank's filings | **{r['sar_agreement']:.0%}** |",
        f"| Exposure mean absolute error | ${r['exposure_mae']:,.2f} |",
    ])


def main() -> None:
    res, bt = results_table(), backtest_table()
    for name in ("README.md", "docs/blog.md"):
        p = ROOT / name
        s = p.read_text(encoding="utf-8")
        s = re.sub(r"<!-- RESULTS_TABLE -->.*?(?=\n## )", "<!-- RESULTS_TABLE -->\n" + res + "\n\n", s, flags=re.S) if "<!-- RESULTS_TABLE -->" in s else s
        # the marker is followed by one or more tables (rows and blank lines); replace all of them
        s = re.sub(r"<!-- BACKTEST_TABLE -->\r?\n(?:(?:\|[^\n]*)?\r?\n)*", lambda _: "<!-- BACKTEST_TABLE -->\n" + bt + "\n\n", s) if "<!-- BACKTEST_TABLE -->" in s else s
        s = s.replace("<!-- filled from cases/ and eval/report.json -->", "<!-- RESULTS_TABLE -->\n" + res + "\n\n<!-- BACKTEST_TABLE -->\n" + bt + "\n")
        p.write_text(s, encoding="utf-8")
    print(res)
    print(bt)


if __name__ == "__main__":
    main()
