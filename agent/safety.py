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
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]+"),                       # before the key=value rule below
    re.compile(r"(?i)(secret|token|password|passwd|api[_-]?key|authorization)([\"']?\s*[:=]\s*[\"']?)(?!\[redacted\])[^\s,;\"'}]+"),
    re.compile(r"\b[A-Za-z0-9]{32,}\b"),                                        # long opaque strings: tokens, secrets
    re.compile(r"https?://[^\s\"']*tgcloud[^\s\"']*"),                          # the Savanna URL
    re.compile(r"(?i)\btg-[a-z0-9-]+(\.[a-z0-9-]+)*\.tgcloud\.io\b"),           # the Savanna host on its own
]


def redact(text: str) -> str:
    out = str(text)
    for pat in _SECRET_PATTERNS:
        out = pat.sub(lambda m: (m.group(1) + m.group(2) + "[redacted]")
                      if m.re.groups >= 2 and m.group(2) is not None and m.group(1) else "[redacted]", out)
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


# ---- append-only, tamper-evident audit log -------------------------------------------------------------------------
# Each entry carries the hash of the previous one (an edit or a removed middle entry breaks the chain), an HMAC keyed by
# FRAUDLENS_AUDIT_KEY (a forged entry can't be given a valid MAC without the server's key), and every append also
# rewrites <log>.head with the entry count and last hash (truncation or deletion of the log no longer looks clean).
# Appends hold an OS file lock, so the API and run_cases.py can write the same log at once.
_audit_lock = threading.Lock()
GENESIS = "0" * 64


def _key() -> bytes | None:
    k = os.getenv("FRAUDLENS_AUDIT_KEY", "")
    return k.encode() if len(k) >= 16 else None


def _mac(h: str) -> str | None:
    import hmac
    k = _key()
    return hmac.new(k, h.encode(), hashlib.sha256).hexdigest() if k else None


class _FileLock:
    """Cross-process exclusive lock on <path>.lock (msvcrt on Windows, fcntl elsewhere)."""

    def __init__(self, path: Path) -> None:
        self.path = path.with_suffix(path.suffix + ".lock")

    def __enter__(self):
        self.f = open(self.path, "a+b")
        if os.name == "nt":
            import msvcrt
            while True:
                try:
                    self.f.seek(0)
                    msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.01)
        else:
            import fcntl
            fcntl.flock(self.f.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc) -> None:
        if os.name == "nt":
            import msvcrt
            self.f.seek(0)
            msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.f.fileno(), fcntl.LOCK_UN)
        self.f.close()


def _paths(log: str) -> tuple[Path, Path]:
    return AUDIT_DIR / f"{log}.jsonl", AUDIT_DIR / f"{log}.head"


def _read_head(head: Path) -> dict | None:
    try:
        return json.loads(head.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def audit(event: str, data: dict[str, Any], log: str = "audit") -> dict:
    """Append one entry under a process-wide and an OS file lock.

    A log that can't be extended (no head anchor, or a chain written entirely without a key now that
    FRAUDLENS_AUDIT_KEY is set) is archived untouched and a new chain starts. The old chain is verified first and the
    result is recorded in the new chain's first entry, so rotation never launders tampering: if the archived log did
    not verify, or the archive is later changed or removed, verify_audit keeps failing."""
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    path, head = _paths(log)
    with _audit_lock, _FileLock(path):
        h = _read_head(head)
        rotated = None
        reason = tag = ""
        if path.exists() and path.stat().st_size > 0:
            old = read_audit(log)
            if h is None:
                reason, tag = "the log had no head anchor", "unanchored"
            elif _key() and old and all("mac" not in e and "unreadable" not in e for e in old):
                reason, tag = "the log was written without FRAUDLENS_AUDIT_KEY; a keyed chain starts here", "unkeyed"
            # anything else (including one MAC stripped from a keyed chain) is appended to and fails verification
        if reason:
            ok, problem, _ = _verify_entries(old, h, require_mac=False)
            if h is None and any("mac" in e for e in old):
                ok, problem = False, "the head anchor of a keyed log was missing"
            raw = path.read_bytes()
            archive = path.with_name(f"{log}.{tag}-{time.strftime('%Y%m%d-%H%M%S')}.jsonl")
            _replace(path, archive)
            rotated = {"archived_as": archive.name, "archive_sha256": hashlib.sha256(raw).hexdigest(),
                       "lines": raw.count(b"\n"), "reason": reason, "archive_verified": ok,
                       "archive_problem": "" if ok else problem}
            h = None
        prev, count = (h["hash"], int(h["count"])) if h else (GENESIS, 0)
        if rotated:
            first = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": "log_rotated", "data": rotated,
                     "prev": GENESIS, "seq": 0}
            first["hash"] = hashlib.sha256(json.dumps(first, sort_keys=True).encode()).hexdigest()
            if _mac(first["hash"]):
                first["mac"] = _mac(first["hash"])
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(first, sort_keys=True) + "\n")
            prev, count = first["hash"], 1
        body = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event,
                "data": redact_obj(json.loads(json.dumps(data, default=str))), "prev": prev, "seq": count}
        body["hash"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        mac = _mac(body["hash"])
        if mac:
            body["mac"] = mac
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(body, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        tmp = head.with_suffix(".head.tmp")
        tmp.write_text(json.dumps({"count": count + 1, "hash": body["hash"]}), encoding="utf-8")
        _replace(tmp, head)
    return body


def _replace(src: Path, dst: Path, tries: int = 20) -> None:
    """os.replace, retried briefly: on Windows a sync client, indexer or virus scanner can hold the target open for a
    moment (seen 30 Oct: OneDrive locked audit.head mid-run and the whole run stopped). Gives up after about 2 s."""
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.1)


def read_audit(log: str = "audit") -> list[dict]:
    """Parsed entries; an unreadable line becomes {"unreadable": n} so verify_audit can report it."""
    path, _ = _paths(log)
    if not path.exists():
        return []
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            entry = None
        out.append(entry if isinstance(entry, dict) else {"unreadable": n})
    return out


def _verify_entries(entries: list[dict], h: dict | None, require_mac: bool) -> tuple[bool, str, str]:
    """Chain, hashes, MACs (when required) and, if a head is given, the head anchor. Returns (ok, problem, last hash)."""
    prev = GENESIS
    for i, entry in enumerate(entries):
        if "unreadable" in entry:
            return False, f"entry {i} is unreadable", prev
        claimed = entry.get("hash")
        body = {k: v for k, v in entry.items() if k not in ("hash", "mac")}
        if body.get("prev") != prev or body.get("seq", i) != i:
            return False, f"entry {i} does not follow entry {i - 1}", prev
        if hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest() != claimed:
            return False, f"entry {i} was modified after it was written", prev
        if require_mac and entry.get("mac") != _mac(claimed):
            return False, f"entry {i} has no valid MAC: it was not written by this server", prev
        prev = claimed
    if h is not None and (int(h.get("count", -1)) != len(entries) or h.get("hash") != prev):
        return False, (f"the log has {len(entries)} entries but its head records {h.get('count')}: entries were removed "
                       f"or added"), prev
    return True, "", prev


def verify_audit(log: str = "audit") -> tuple[bool, str]:
    """Recompute the chain, the MACs and the head anchor, and check every log this chain archived. Returns (ok, message
    naming the first problem)."""
    path, head = _paths(log)
    entries = read_audit(log)
    h = _read_head(head)
    if not entries:
        if h and int(h.get("count", 0)) > 0:
            return False, f"the log is empty or missing but its head records {h['count']} entries"
        return True, "empty"
    if h is None:
        return False, "the head anchor is missing"
    ok, problem, _ = _verify_entries(entries, h, require_mac=bool(_key()))
    if not ok:
        return False, problem
    for i, entry in enumerate(entries):
        if entry.get("event") != "log_rotated":
            continue
        d = entry.get("data") or {}
        if d.get("archive_verified") is False:
            return False, (f"entry {i} archived a log that failed verification ({d.get('archive_problem')}); it is kept "
                           f"as {d.get('archived_as')} for review")
        arch = AUDIT_DIR / str(d.get("archived_as") or "")
        if not d.get("archived_as") or not arch.is_file() or hashlib.sha256(arch.read_bytes()).hexdigest() != d.get("archive_sha256"):
            return False, f"entry {i} archived {d.get('archived_as')}, which has since been changed or removed"
    return True, "chain intact" + ("" if _key() else " (unkeyed: set FRAUDLENS_AUDIT_KEY to make forgery detectable)")
