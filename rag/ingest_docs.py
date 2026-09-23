"""Build the knowledge layer for GraphRAG.

- PolicyRule vertices (sections 0-7, R1-R10, 3a, 3b) and FraudPattern vertices from the dataset README.
- DocChunk vertices from the README (patterns, policy, glossary, things-to-know) and the regulator documents the
  README lists (FinCEN, FATF, FFIEC), each linked to the rules and patterns it talks about.
Output: data/prep/knowledge.json (rules, patterns, chunks with 768-d embeddings).
"""
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import httpx
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.llm import embed  # noqa: E402

README = ROOT / "data" / "raw" / "README.md"
DOCS = ROOT / "data" / "raw" / "docs"
OUT = ROOT / "data" / "prep" / "knowledge.json"

REG_DOCS = {
    "FinCEN SAR FAQs (Oct 2025)": "https://www.fincen.gov/system/files/2025-10/SAR-FAQs-October-2025.pdf",
    "FinCEN SAR Narrative Guidance": "https://www.fincen.gov/system/files/shared/sar_guidance_narrative.pdf",
    "FinCEN Complete and Sufficient SAR Narrative": "https://www.fincen.gov/system/files/shared/sarnarrcompletguidfinal_112003.pdf",
    "FinCEN SAR Supporting Documentation FIN-2007-G003": "https://www.fincen.gov/system/files/shared/fin-2007-g003.pdf",
    "FinCEN SAR Activity Review Issue 19": "https://www.fincen.gov/sites/default/files/sar_report/sar_tti_19.pdf",
    "FinCEN Advisory on Account Takeover FIN-2011-A016": "https://www.fincen.gov/resources/advisories/fincen-advisory-fin-2011-a016",
    "FinCEN Advisory on Imposter Scams and Money Mules": "https://www.fincen.gov/system/files/advisory/2020-07-07/Advisory_%20Imposter_and_Money_Mule_COVID_19_508_FINAL.pdf",
    "FinCEN Identity-Related Suspicious Activity 2021": "https://www.fincen.gov/system/files/shared/FTA_Identity_Final508.pdf",
    "FATF Illicit Financial Flows from Cyber-Enabled Fraud": "https://www.fatf-gafi.org/content/dam/fatf-gafi/reports/Illicit-financial-flows-cyber-enabled-fraud.pdf.coredownload.inline.pdf",
    "FFIEC BSA/AML Red Flags (Appendix F)": "https://bsaaml.ffiec.gov/manual/Appendices/07",
    "FFIEC Suspicious Activity Reporting": "https://bsaaml.ffiec.gov/manual/AssessingComplianceWithBSARegulatoryRequirements/04",
}

PATTERNS = {
    "card_testing": ("Card testing", "card testing|tiny|small online authoriz|testing a stolen"),
    "card_not_present_fraud": ("Card-not-present fraud", "card-not-present|card not present|online without the card"),
    "card_not_present_new_device": ("Card-not-present fraud from a new device", "new device|device .*new|proxy"),
    "out_of_region_use": ("Out-of-region use", "out-of-region|billing region|trip|clone|card-present"),
    "account_takeover": ("Account takeover", "account takeover|takeover|stolen credentials|credential"),
    "undocumented": ("Undocumented pattern", "undocumented|fits none|coordinated|structur|threshold|money mule|mule"),
    "none": ("No fraud (cleared)", "legitimate|false alarm|cleared"),
}

RULE_HINTS = {
    "R1": r"verify before|single signal|weak signal",
    "R2": r"denies|deny|unauthori[sz]ed",
    "R3": r"confirms the transaction|confirmed the purchase",
    "R4": r"no reply|24 hours",
    "R5": r"card testing|small online authori",
    "R6": r"shared origin|same device|several cards|shared device",
    "R7": r"recurring|disputed but legitimate|subscription",
    "R8": r"uncertain|escalat|conflict",
    "R9": r"undocumented|fits none|coordinated",
    "R10": r"block_all_cards|every card|credentials .*compromised",
    "3a": r"suspicious activity report|\bSAR\b|narrative|file a report|filing",
    "6": r"stop investigating|stopping",
    "7": r"explain|cite the rule",
}


def chunk_text(text: str, size: int = 1400, overlap: int = 200) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    parts, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        cut = text.rfind("\n", start + size // 2, end)
        if cut == -1 or end == len(text):
            cut = end
        parts.append(text[start:cut].strip())
        if cut >= len(text):
            break
        start = max(cut - overlap, start + 1)
    return [p for p in parts if len(p) > 80]


def links(text: str) -> tuple[list[str], list[str]]:
    low = text.lower()
    rules = [r for r, pat in RULE_HINTS.items() if re.search(pat, low)]
    pats = [p for p, (_, pat) in PATTERNS.items() if re.search(pat, low)]
    return rules, pats


def readme_sections(md: str) -> dict[str, str]:
    """Split the README on markdown headings into {heading: body}."""
    out, cur, buf = {}, "Intro", []
    for line in md.splitlines():
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            if buf:
                out[cur] = "\n".join(buf).strip()
            cur, buf = m.group(2).strip(), []
        else:
            buf.append(line)
    if buf:
        out[cur] = "\n".join(buf).strip()
    return out


def policy_rules(md: str) -> list[dict]:
    rules = []
    for m in re.finditer(r"\*\*(R\d+)\. ([^*]+)\*\*(.*?)(?=\n\*\*R\d+\.|\n### |\Z)", md, re.S):
        rules.append({"id": m.group(1), "title": m.group(2).strip().rstrip("."), "body": m.group(3).strip()})
    secs = readme_sections(md)
    for sid, title in [("0", "0. What the agent starts with"), ("1", "1. Actions"), ("2", "2. Approval routing"),
                       ("3a", "3a. A case is not a report"), ("3b", "3b. The next best action can change"),
                       ("4", "4. Exposure"), ("5", "5. Gathering more evidence"), ("6", "6. Stopping"),
                       ("7", "7. Explaining")]:
        if title in secs:
            rules.append({"id": sid, "title": title.split(". ", 1)[1], "body": secs[title]})
    return rules


def fraud_patterns(md: str) -> list[dict]:
    pats = []
    for m in re.finditer(r"\*\*(\d)\. ([^*]+)\*\*(.*?)(?=\n\*\*\d\. |\n## |\Z)", md, re.S):
        name = m.group(2).strip().rstrip(".")
        pid = {"Card testing": "card_testing", "Card-not-present fraud": "card_not_present_fraud",
               "Card-not-present fraud from a new device": "card_not_present_new_device",
               "Out-of-region use": "out_of_region_use", "Account takeover": "account_takeover"}.get(name)
        if pid:
            pats.append({"id": pid, "name": name, "description": m.group(3).strip()})
    pats.append({"id": "undocumented", "name": "Undocumented pattern",
                 "description": "Activity that fits none of the five known patterns but shows coordinated or repeated "
                                "abuse across customers. Describe it in your own words (policy R9)."})
    pats.append({"id": "none", "name": "No fraud", "description": "Alert cleared as legitimate activity."})
    return pats


def fetch_doc(name: str, url: str) -> str:
    DOCS.mkdir(parents=True, exist_ok=True)
    cache = DOCS / (re.sub(r"[^A-Za-z0-9]+", "_", name) + ".txt")
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    try:
        r = httpx.get(url, follow_redirects=True, timeout=90, headers={"User-Agent": "Mozilla/5.0 (research)"})
        r.raise_for_status()
        if url.lower().endswith(".pdf") or r.headers.get("content-type", "").startswith("application/pdf") or r.content[:4] == b"%PDF":
            reader = PdfReader(io.BytesIO(r.content))
            text = "\n".join((p.extract_text() or "") for p in reader.pages[:60])
        else:
            html = re.sub(r"(?is)<(script|style|nav|header|footer).*?</\1>", " ", r.text)
            text = re.sub(r"(?s)<[^>]+>", " ", html)
            text = re.sub(r"&nbsp;|&#160;", " ", text)
            text = re.sub(r"\s{2,}", "\n", text)
    except Exception as e:  # noqa: BLE001
        print(f"  ! could not fetch {name}: {e}")
        return ""
    cache.write_text(text, encoding="utf-8")
    return text


def main() -> None:
    md = README.read_text(encoding="utf-8")
    rules = policy_rules(md)
    patterns = fraud_patterns(md)
    chunks = []

    secs = readme_sections(md)
    keep = ["The five known fraud patterns", "Things to know", "Glossary", "The task", "Answer Format",
            "Part 2: `sar`", "Part 3: `next_best_actions`", "Notes"]
    for sec in keep:
        if sec in secs:
            for i, body in enumerate(chunk_text(secs[sec], 1200, 150)):
                chunks.append({"source": "Dataset README", "section": sec, "body": body})
    for r in rules:
        chunks.append({"source": "Bank Fraud Policy v1.0", "section": f"{r['id']} {r['title']}",
                       "body": f"Policy {r['id']} - {r['title']}. {r['body']}", "rules": [r["id"]]})
    for p in patterns:
        chunks.append({"source": "Known fraud patterns", "section": p["name"],
                       "body": f"Fraud pattern {p['id']} ({p['name']}): {p['description']}", "patterns": [p["id"]]})

    for name, url in REG_DOCS.items():
        text = fetch_doc(name, url)
        parts = chunk_text(text)[:40]
        print(f"{name[:60]:60s} {len(text):>8,} chars -> {len(parts)} chunks")
        for body in parts:
            chunks.append({"source": name, "section": name, "body": body})

    for i, c in enumerate(chunks):
        c["id"] = f"DOC-{i:04d}"
        r, p = links(c["body"])
        c["rules"] = sorted(set(c.get("rules", []) + r))
        c["patterns"] = sorted(set(c.get("patterns", []) + p))
    embs = embed([f"{c['source']} | {c['section']}\n{c['body']}" for c in chunks])
    for c, e in zip(chunks, embs):
        c["emb"] = e
    OUT.write_text(json.dumps({"rules": rules, "patterns": patterns, "chunks": chunks}), encoding="utf-8")
    print(f"rules={len(rules)} patterns={len(patterns)} chunks={len(chunks)} -> {OUT}")


if __name__ == "__main__":
    main()
