"""Gemini on Vertex AI: text generation, JSON generation and embeddings, with token accounting and disk caching."""
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

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

PRO = os.getenv("LLM_MODEL_PRO", "gemini-3.1-pro-preview")
FLASH = os.getenv("LLM_MODEL_FLASH", "gemini-3.5-flash")
EMBED = os.getenv("EMBED_MODEL", "text-embedding-005")
CACHE = ROOT / "runs" / "llm_cache"
CACHE.mkdir(parents=True, exist_ok=True)

_client = None
_lock = threading.Lock()


class Usage:
    """Per-investigation token counter (thread-local so parallel specialists don't collide)."""

    _local = threading.local()

    @classmethod
    def reset(cls) -> None:
        cls._local.tokens = 0
        cls._local.calls = 0

    @classmethod
    def add(cls, n: int) -> None:
        cls._local.tokens = getattr(cls._local, "tokens", 0) + int(n or 0)
        cls._local.calls = getattr(cls._local, "calls", 0) + 1

    @classmethod
    def tokens(cls) -> int:
        return getattr(cls._local, "tokens", 0)


def client() -> genai.Client:
    global _client
    with _lock:
        if _client is None:
            _client = genai.Client(vertexai=True, project=os.environ["GOOGLE_CLOUD_PROJECT"],
                                   location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
                                   http_options=types.HttpOptions(timeout=int(os.getenv("LLM_TIMEOUT_MS", "150000"))))
    return _client


def _key(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:24]


def generate(prompt: str, system: str = "", model: str | None = None, json_schema: dict | None = None,
             temperature: float = 0.2, cache: bool = True, usage_sink: list | None = None) -> str:
    """Generate text (or JSON when json_schema is given). Cached on disk by (model, system, prompt, schema)."""
    model = model or PRO
    key = _key(model, system, prompt, json_schema, temperature)
    path = CACHE / f"{key}.json"
    if cache and path.exists():
        rec = json.loads(path.read_text(encoding="utf-8"))
        Usage.add(rec.get("tokens", 0))
        if usage_sink is not None:
            usage_sink.append(rec.get("tokens", 0))
        return rec["text"]
    last = None
    for attempt in range(3):
        if attempt == 2 and model != FLASH:
            model = FLASH  # degrade gracefully to the fast model on repeated failures
        cfg = types.GenerateContentConfig(
            temperature=temperature, system_instruction=system or None,
            thinking_config=types.ThinkingConfig(thinking_level="low" if model == FLASH else "medium"),
            http_options=types.HttpOptions(timeout=60000 if model == FLASH else 150000))
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
            path.write_text(json.dumps({"text": text, "tokens": tokens, "model": model}), encoding="utf-8")
            return text
        except Exception as e:  # noqa: BLE001 - retry transient API errors
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"LLM call failed: {last}")


def generate_json(prompt: str, schema: dict, system: str = "", model: str | None = None, **kw) -> dict:
    text = generate(prompt, system=system, model=model, json_schema=schema, **kw)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        return json.loads(text[start:end + 1])


def embed(texts: list[str], task: str = "RETRIEVAL_DOCUMENT", batch: int = 30) -> list[list[float]]:
    """Embed texts with Vertex text-embedding (768-d). Cached per text."""
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
        for attempt in range(5):
            try:
                resp = client().models.embed_content(
                    model=EMBED, contents=[texts[i][:2500] for i in idx],
                    config=types.EmbedContentConfig(task_type=task, output_dimensionality=768))
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 4:
                    raise
                time.sleep(3 * (attempt + 1))
                print("embed retry", e)
        for i, emb in zip(idx, resp.embeddings):
            out[i] = list(emb.values)
            (CACHE / f"emb_{_key(EMBED, task, texts[i])}.json").write_text(json.dumps(out[i]))
    return out  # type: ignore[return-value]


def embed_query(text: str) -> list[float]:
    return embed([text], task="RETRIEVAL_QUERY")[0]
