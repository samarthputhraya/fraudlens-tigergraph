"""Gemini on Vertex AI: text generation, JSON generation and embeddings, with token accounting and disk caching.

Bounded and fail-closed: each call has a timeout and one retry on the same model (no silent switch to another model),
then raises DependencyFailure("llm", <role>, ...). Unparseable JSON is a failure too. The disk cache makes a re-run of
the same case return the same text, which keeps answers reproducible.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from agent.safety import DependencyFailure, fault

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

PRO = os.getenv("LLM_MODEL_PRO", "gemini-3.1-pro-preview")
FLASH = os.getenv("LLM_MODEL_FLASH", "gemini-3.5-flash")
EMBED = os.getenv("EMBED_MODEL", "text-embedding-005")
CACHE = ROOT / "runs" / "llm_cache"
CACHE.mkdir(parents=True, exist_ok=True)

TIMEOUT_MS = {"flash": int(os.getenv("LLM_TIMEOUT_FLASH_MS", "45000")), "pro": int(os.getenv("LLM_TIMEOUT_PRO_MS", "90000"))}
ATTEMPTS = 2  # one try plus one retry, then fail closed

_client = None
_lock = threading.Lock()


class Usage:
    """Per-investigation token counter (thread-local so parallel specialists don't collide)."""

    _local = threading.local()

    @classmethod
    def reset(cls) -> None:
        cls._local.tokens = 0
        cls._local.calls = 0
        Breaker.reset()

    @classmethod
    def add(cls, n: int) -> None:
        cls._local.tokens = getattr(cls._local, "tokens", 0) + int(n or 0)
        cls._local.calls = getattr(cls._local, "calls", 0) + 1

    @classmethod
    def tokens(cls) -> int:
        return getattr(cls._local, "tokens", 0)


class Breaker:
    """Per investigation: after one model failure, later model calls fail at once instead of each waiting out its own
    timeout twice (a hung endpoint would otherwise cost minutes per case). Reset when a new investigation starts."""

    _open = threading.local()

    @classmethod
    def reset(cls) -> None:
        cls._open.reason = None

    @classmethod
    def trip(cls, reason: str) -> None:
        cls._open.reason = reason

    @classmethod
    def check(cls, role: str) -> None:
        reason = getattr(cls._open, "reason", None)
        if reason:
            raise DependencyFailure("llm", role, f"not attempted: the model already failed in this investigation ({reason})")


def _valid_json(text: str, schema: dict | None) -> dict | None:
    if not schema:
        return None
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        try:
            out = json.loads(text[start:end + 1]) if start >= 0 and end > start else None
        except json.JSONDecodeError:
            out = None
    if not isinstance(out, dict) or any(k not in out for k in schema.get("required", [])):
        return None
    return out


def client() -> genai.Client:
    global _client
    with _lock:
        if _client is None:
            _client = genai.Client(vertexai=True, project=os.environ["GOOGLE_CLOUD_PROJECT"],
                                   location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
                                   http_options=types.HttpOptions(timeout=TIMEOUT_MS["pro"]))
    return _client


def _key(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:24]


def generate(prompt: str, system: str = "", model: str | None = None, json_schema: dict | None = None,
             temperature: float = 0.2, cache: bool = True, usage_sink: list | None = None, role: str = "llm") -> str:
    """Generate text (or JSON when json_schema is given). Cached on disk by (model, system, prompt, schema)."""
    model = model or PRO
    Breaker.check(role)
    if fault("llm", role) or fault("llm_timeout", role):
        Breaker.trip(f"{role} failed")
        raise DependencyFailure("llm", role, "fault drill: the model call timed out" if fault("llm_timeout", role)
                                else "fault drill: the model is unavailable")
    if fault("llm_garbage", role):
        return "}{ this is not the JSON you asked for"
    key = _key(model, system, prompt, json_schema, temperature)
    path = CACHE / f"{key}.json"
    if cache and path.exists():
        rec = json.loads(path.read_text(encoding="utf-8"))
        Usage.add(rec.get("tokens", 0))
        if usage_sink is not None:
            usage_sink.append(rec.get("tokens", 0))
        return rec["text"]
    last = None
    for attempt in range(ATTEMPTS):
        cfg = types.GenerateContentConfig(
            temperature=temperature, system_instruction=system or None,
            thinking_config=types.ThinkingConfig(thinking_level="low" if model == FLASH else "medium"),
            http_options=types.HttpOptions(timeout=TIMEOUT_MS["flash" if model == FLASH else "pro"]))
        if json_schema:
            cfg.response_mime_type = "application/json"
            cfg.response_json_schema = json_schema
        try:
            resp = client().models.generate_content(model=model, contents=prompt, config=cfg)
            text = resp.text or ""
            tokens = getattr(resp.usage_metadata, "total_token_count", 0) or 0
            Usage.add(tokens)
            if usage_sink is not None:
                usage_sink.append(tokens)
            if json_schema and _valid_json(text, json_schema) is None:
                raise ValueError("output does not match the requested JSON schema")  # retried, and never cached
            path.write_text(json.dumps({"text": text, "tokens": tokens, "model": model}), encoding="utf-8")
            return text
        except Exception as e:  # noqa: BLE001 - one retry on transient API errors, then fail closed
            last = e
            if attempt + 1 < ATTEMPTS:
                time.sleep(2)
    Breaker.trip(f"{role}: {type(last).__name__}")
    raise DependencyFailure("llm", role, f"{type(last).__name__}: {last}")


def generate_json(prompt: str, schema: dict, system: str = "", model: str | None = None, role: str = "llm", **kw) -> dict:
    text = generate(prompt, system=system, model=model, json_schema=schema, role=role, **kw)
    out = _valid_json(text, schema)
    if out is None:
        Breaker.trip(f"{role}: invalid output")
        raise DependencyFailure("llm", role, "the model returned output that does not match the requested JSON schema")
    return out


def embed(texts: list[str], task: str = "RETRIEVAL_DOCUMENT", batch: int = 30) -> list[list[float]]:
    """Embed texts with Vertex text-embedding (768-d). Cached per text."""
    if fault("llm", "embed") or fault("llm_timeout", "embed"):
        raise DependencyFailure("llm", "embed", "fault drill: the embedding model is unavailable")
    out: list[list[float] | None] = [None] * len(texts)
    todo = []
    for i, t in enumerate(texts):
        p = CACHE / f"emb_{_key(EMBED, task, t)}.json"
        if p.exists():
            out[i] = json.loads(p.read_text())
        else:
            todo.append(i)
    for s in range(0, len(todo), batch):
        idx = todo[s:s + batch]
        for attempt in range(ATTEMPTS):
            try:
                resp = client().models.embed_content(
                    model=EMBED, contents=[texts[i][:2500] for i in idx],
                    config=types.EmbedContentConfig(task_type=task, output_dimensionality=768))
                break
            except Exception as e:  # noqa: BLE001
                if attempt + 1 == ATTEMPTS:
                    raise DependencyFailure("llm", "embed", f"{type(e).__name__}: {e}") from None
                time.sleep(3)
        for i, emb in zip(idx, resp.embeddings):
            out[i] = list(emb.values)
            (CACHE / f"emb_{_key(EMBED, task, texts[i])}.json").write_text(json.dumps(out[i]))
    return out  # type: ignore[return-value]


def embed_query(text: str) -> list[float]:
    return embed([text], task="RETRIEVAL_QUERY")[0]
