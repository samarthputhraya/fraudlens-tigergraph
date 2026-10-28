"""Fail-closed plumbing shared by every component: dependency failures, fault drills, redaction and the audit log.

Banking rule (Final Round brief): if the graph, the tool layer or the model fails, stop and report it; never fall back
silently to other data and present the result as complete. Every tool call and decision is recorded in an append-only,
hash-chained audit log, so an entry can't be edited later without breaking the chain.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = Path(os.getenv("FRAUDLENS_AUDIT_DIR", str(ROOT / "runs" / "audit")))


class DependencyFailure(RuntimeError):
    """A dependency (graph, mcp, llm, embedding) failed. The investigation stops; nothing is presented as complete."""

    def __init__(self, dependency: str, step: str, detail: str) -> None:
        self.dependency = dependency
        self.step = step
        self.detail = redact(detail)[:300]
        super().__init__(f"{dependency} failed during {step}: {self.detail}")

    def as_dict(self) -> dict:
        return {"dependency": self.dependency, "step": self.step, "detail": self.detail}


class InvalidInput(DependencyFailure):
    """The case itself can't be investigated (e.g. its flagged transaction doesn't exist). Same handling: stop, say why."""

    def __init__(self, step: str, detail: str) -> None:
        super().__init__("input", step, detail)


# ---- fault drills -------------------------------------------------------------------------------------------------
# FRAUDLENS_FAULT="graph:card_window,llm:writer" makes those steps fail on purpose, so the fail-closed behaviour can be
# shown live and tested. Forms: "graph:<query>", "graph:*", "llm:<role>", "llm:*", "llm_garbage:<role>", "llm_timeout:<role>".

def _faults() -> set[str]:
    return {f.strip() for f in os.getenv("FRAUDLENS_FAULT", "").split(",") if f.strip()}


def fault(kind: str, step: str) -> bool:
    active = _faults()
    return f"{kind}:{step}" in active or f"{kind}:*" in active


# ---- redaction ----------------------------------------------------------------------------------------------------
_SECRET_PATTERNS = [
    re.compile(r"(?i)(secret|token|password|api[_-]?key|authorization)(\W{1,3})[^\s,;\"']+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"\b[A-Za-z0-9]{32,}\b"),  # long opaque strings: tokens, secrets
    re.compile(r"https?://[^\s\"']*tgcloud[^\s\"']*"),  # the Savanna host
]


def redact(text: str) -> str:
    out = str(text)
    for pat in _SECRET_PATTERNS:
        out = pat.sub(lambda m: (m.group(1) + m.group(2) + "[redacted]") if m.lastindex and m.lastindex >= 2 else "[redacted]", out)
    return out


def redact_obj(obj: Any) -> Any:
    """Redact every string in a JSON-like object. Keys ending in `sha256` are digests we wrote, so they're kept."""
    if isinstance(obj, dict):
        return {k: (v if str(k).endswith("sha256") else redact_obj(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact_obj(v) for v in obj]
    if isinstance(obj, str):
        return redact(obj)
    return obj


# ---- append-only, hash-chained audit log ---------------------------------------------------------------------------
_audit_lock = threading.Lock()


def _last_hash(path: Path) -> str:
    if not path.exists() or path.stat().st_size == 0:
        return "0" * 64
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - 65536))
        lines = f.read().splitlines()
    return json.loads(lines[-1])["hash"]


def audit(event: str, data: dict[str, Any], log: str = "audit") -> dict:
    """Append one entry. Each entry carries the hash of the previous one; `verify_audit` detects any edit."""
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    path = AUDIT_DIR / f"{log}.jsonl"
    with _audit_lock:
        prev = _last_hash(path)
        body = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event,
                "data": redact_obj(json.loads(json.dumps(data, default=str))), "prev": prev}
        body["hash"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(body, sort_keys=True) + "\n")
    return body


def read_audit(log: str = "audit") -> list[dict]:
    path = AUDIT_DIR / f"{log}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def verify_audit(log: str = "audit") -> tuple[bool, str]:
    """Recompute the chain. Returns (ok, message naming the first broken entry)."""
    prev = "0" * 64
    for i, entry in enumerate(read_audit(log)):
        claimed = entry.get("hash")
        body = {k: v for k, v in entry.items() if k != "hash"}
        if body.get("prev") != prev:
            return False, f"entry {i} does not follow entry {i - 1}"
        if hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest() != claimed:
            return False, f"entry {i} was modified after it was written"
        prev = claimed
    return True, "chain intact"
