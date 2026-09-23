"""TigerGraph connection helper with retries for Savanna auto-resume (first call after idle may 502)."""
from __future__ import annotations

import os
import time
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pyTigerGraph import TigerGraphConnection

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

GRAPH = os.getenv("TG_GRAPHNAME", "Fraud")


@lru_cache(maxsize=1)
def conn() -> TigerGraphConnection:
    host = os.environ["TG_HOST"].rstrip("/")
    secret = os.getenv("TG_SECRET", "")
    kwargs = dict(host=host, graphname=GRAPH)
    if secret:
        kwargs["gsqlSecret"] = secret
    else:
        kwargs["username"] = os.getenv("TG_USERNAME", "tigergraph")
        kwargs["password"] = os.getenv("TG_PASSWORD", "tigergraph")
    if "tgcloud" in host:
        kwargs["tgCloud"] = True
    else:
        kwargs["restppPort"] = os.getenv("TG_RESTPP_PORT", "14240")
        kwargs["gsPort"] = os.getenv("TG_GS_PORT", "14240")
    c = TigerGraphConnection(**kwargs)
    if secret:
        retry(lambda: c.getToken(secret))
    return c


def retry(fn, tries: int = 12, wait: float = 12.0):
    """Retry through Savanna auto-resume (502/503/connection errors) for ~150 s."""
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - network layer raises many types
            msg = str(e)
            last = e
            transient = any(k in msg for k in ("502", "503", "504", "Connection", "timed out", "Max retries", "resum"))
            if not transient or i == tries - 1:
                raise
            print(f"  [tg] transient error ({msg[:80]}), retry {i + 1}/{tries} in {wait:.0f}s")
            time.sleep(wait)
    raise last  # pragma: no cover


def gsql(text: str) -> str:
    return retry(lambda: conn().gsql(text))


def run_query(name: str, params: dict | None = None, timeout: int = 60000):
    return retry(lambda: conn().runInstalledQuery(name, params=params or {}, timeout=timeout))
