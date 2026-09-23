"""Build the Fraud graph on TigerGraph Savanna: schema, vector attributes, loading jobs, data, queries.

Usage:
  python graph/setup.py schema        # create graph + schema + vector attrs + loading jobs
  python graph/setup.py load          # load all CSVs from data/prep/load (chunked, resumable)
  python graph/setup.py queries       # create + install all queries in graph/queries/
  python graph/setup.py stats         # vertex/edge counts
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tg import GRAPH, ROOT, conn, gsql, retry  # noqa: E402

LOAD_DIR = ROOT / "data" / "prep" / "load"
CHUNK_DIR = ROOT / "data" / "prep" / "chunks"
DONE_FILE = ROOT / "data" / "prep" / "loaded.json"
CHUNK_BYTES = 8_000_000

# (csv name, loading job) in dependency order
LOAD_PLAN = [
    ("customers", "load_customers"),
    ("cards", "load_cards"),
    ("devices", "load_devices"),
    ("transactions", "load_transactions"),
    ("accounts", "load_accounts"),
    ("account_edges", "load_account_edges"),
    ("next_edges", "load_next"),
    ("device_edges", "load_device_edges"),
    ("card_device", "load_card_device"),
    ("card_region", "load_card_region"),
    ("closed_cases", "load_closed_cases"),
    ("closed_involves", "load_closed_involves"),
    ("closed_connected", "load_closed_connected"),
]


def show(out) -> None:
    text = out if isinstance(out, str) else json.dumps(out)
    print("\n".join(line for line in text.splitlines() if line.strip())[-3000:])


def cmd_schema() -> None:
    graphs = gsql("SHOW GRAPH *")
    if f"Graph {GRAPH}(" in graphs or f"- Graph {GRAPH}" in graphs:
        print(f"Graph {GRAPH} already exists; skipping schema creation")
    else:
        show(gsql((ROOT / "graph" / "schema.gsql").read_text()))
        show(gsql((ROOT / "graph" / "vectors.gsql").read_text()))
    show(gsql((ROOT / "graph" / "loading_jobs_positional.gsql").read_text()))


def split_csv(path: Path) -> list[Path]:
    """Split a CSV into ~16 MB header-less chunks (posted data ignores header="true", so the header must go)."""
    CHUNK_DIR.mkdir(parents=True, exist_ok=True)
    chunks: list[Path] = []
    with path.open("rb") as f:
        f.readline()  # drop header
        idx, buf, size = 0, [], 0
        for line in f:
            buf.append(line)
            size += len(line)
            if size >= CHUNK_BYTES:
                out = CHUNK_DIR / f"{path.stem}.{idx:03d}.csv"
                out.write_bytes(b"".join(buf))
                chunks.append(out)
                idx, buf, size = idx + 1, [], 0
        if buf:
            out = CHUNK_DIR / f"{path.stem}.{idx:03d}.csv"
            out.write_bytes(b"".join(buf))
            chunks.append(out)
    return chunks


def cmd_load(only: list[str] | None = None) -> None:
    done = set(json.loads(DONE_FILE.read_text())) if DONE_FILE.exists() else set()
    c = conn()
    for name, job in LOAD_PLAN:
        if only and name not in only:
            continue
        for chunk in split_csv(LOAD_DIR / f"{name}.csv"):
            key = chunk.name
            if key in done:
                continue
            t0 = time.time()
            res = retry(lambda: c.runLoadingJobWithFile(str(chunk), "f", job, sep=",", timeout=600000))
            stats = json.dumps(res)[:300] if res else "no response"
            print(f"{key:28s} {time.time() - t0:6.1f}s  {stats}")
            done.add(key)
            DONE_FILE.write_text(json.dumps(sorted(done)))


def cmd_queries(names: list[str] | None = None) -> None:
    qdir = ROOT / "graph" / "queries"
    files = sorted(qdir.glob("*.gsql"))
    if names:
        files = [f for f in files if f.stem in names]
    for f in files:
        print(f"-- create {f.stem}")
        show(gsql(f"USE GRAPH {GRAPH}\n" + f.read_text()))
    t0 = time.time()
    print("-- INSTALL QUERY ALL (a few minutes)...")
    show(gsql(f"USE GRAPH {GRAPH}\nINSTALL QUERY ALL"))
    print(f"installed in {time.time() - t0:.0f}s")


def cmd_vectors() -> None:
    """Knowledge layer + TigerVector embeddings: PolicyRule, FraudPattern, DocChunk (+emb, DOC_RULE, DOC_PATTERN)
    and ClosedCase.emb. Run after `python rag/ingest_docs.py` and `python rag/embed_cases.py`."""
    c = conn()
    kn = json.loads((ROOT / "data" / "prep" / "knowledge.json").read_text(encoding="utf-8"))
    print("rules", retry(lambda: c.upsertVertices("PolicyRule", [(r["id"], {"title": r["title"], "body": r["body"][:4000]}) for r in kn["rules"]])))
    print("patterns", retry(lambda: c.upsertVertices("FraudPattern", [(p["id"], {"name": p["name"], "description": p["description"][:2000]}) for p in kn["patterns"]])))
    chunks = kn["chunks"]
    for i in range(0, len(chunks), 50):
        part = chunks[i:i + 50]
        retry(lambda: c.upsertVertices("DocChunk", [(ch["id"], {"source": ch["source"], "section": ch["section"][:200],
                                                                  "body": ch["body"], "emb": ch["emb"]}) for ch in part]))
    rule_ids = {r["id"] for r in kn["rules"]}
    pat_ids = {p["id"] for p in kn["patterns"]}
    dr = [(ch["id"], r, {}) for ch in chunks for r in ch.get("rules", []) if r in rule_ids]
    dp = [(ch["id"], p, {}) for ch in chunks for p in ch.get("patterns", []) if p in pat_ids]
    print("doc chunks", len(chunks), "DOC_RULE", retry(lambda: c.upsertEdges("DocChunk", "DOC_RULE", "PolicyRule", dr)),
          "DOC_PATTERN", retry(lambda: c.upsertEdges("DocChunk", "DOC_PATTERN", "FraudPattern", dp)))
    embs = json.loads((ROOT / "data" / "prep" / "closed_emb.json").read_text())
    items = list(embs.items())
    for i in range(0, len(items), 250):
        part = items[i:i + 250]
        retry(lambda: c.upsertVertices("ClosedCase", [(cid, {"emb": e}) for cid, e in part]))
        if i % 1000 == 0:
            print(f"  closed-case embeddings {i + len(part)}/{len(items)}")
    print("vector index status:", retry(lambda: c.getVectorIndexStatus(GRAPH)))


def cmd_describe() -> None:
    """Publish each installed query's description (from its /* comment */) so agents can discover tools via MCP."""
    import re as _re
    for f in sorted((ROOT / "graph" / "queries").glob("*.gsql")):
        text = f.read_text(encoding="utf-8")
        name = _re.search(r"QUERY (\w+)\(", text).group(1)
        m = _re.search(r"/\*(.*?)\*/", text, _re.S)
        if not m:
            continue
        desc = " ".join(m.group(1).split()).replace('"', "'")
        try:
            show(gsql(f'USE GRAPH {GRAPH}\nUPDATE DESCRIPTION OF QUERY {name} "{desc}"'))
        except Exception as e:  # noqa: BLE001 - older servers lack query descriptions
            print(f"  description for {name} not set: {e}")


def cmd_stats() -> None:
    c = conn()
    print("vertices:", json.dumps(retry(lambda: c.getVertexCount("*")), indent=1))
    print("edges:", json.dumps(retry(lambda: c.getEdgeCount("*")), indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    rest = sys.argv[2:] or None
    {"schema": cmd_schema, "load": lambda: cmd_load(rest), "queries": lambda: cmd_queries(rest),
     "vectors": cmd_vectors, "describe": cmd_describe, "stats": cmd_stats}[cmd]()
