"""Evidence gathering: the fixed investigation toolkit every case runs through (the specialists add more on top).

Each step is one installed GSQL query on TigerGraph (via MCP) - or the offline mirror in backtests - and nothing
after the case's `opened_at` is ever read (no look-ahead).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from agent.llm import embed_query


def P(ts: str) -> datetime:
    return datetime.fromisoformat(str(ts)[:19])


@dataclass
class EvidencePack:
    case: dict
    opened_at: datetime
    txn: dict = field(default_factory=dict)
    card: dict = field(default_factory=dict)
    window: list = field(default_factory=list)        # card txns [ts-14d, opened_at]
    profile: dict = field(default_factory=dict)        # card baseline strictly before the flagged txn
    account: dict = field(default_factory=dict)        # resolved account + its history
    recurring: list = field(default_factory=list)
    device: dict = field(default_factory=dict)         # device neighbours in [ts-30d, opened_at]
    region: dict = field(default_factory=dict)
    prior: dict = field(default_factory=dict)
    memory: dict = field(default_factory=dict)
    knowledge: dict = field(default_factory=dict)
    refs: dict = field(default_factory=dict)           # step -> replayable query ref
    extra: dict = field(default_factory=dict)

    @property
    def ts(self) -> datetime:
        return P(self.txn["ts"])


def _ref(g, before: int) -> str:
    calls = g.trace.calls[before:]
    return calls[-1].ref() if calls else ""


def gather(case: dict, g: Any, agent_names: dict | None = None) -> EvidencePack:
    """Run the core toolkit. `agent_names` maps step -> specialist name for the trace."""
    an = agent_names or {}
    opened = P(case["opened_at"])
    ep = EvidencePack(case=case, opened_at=opened)

    n = len(g.trace.calls)
    ctx = g.txn_context(case["flagged_txn_id"], agent=an.get("context", "lead"))
    ep.txn, ep.card = ctx["txn"], ctx["card"]
    ep.refs["context"] = _ref(g, n)
    ts = ep.ts
    card_id = case["card_id"]

    n = len(g.trace.calls)
    ep.window = g.card_window(card_id, ts - timedelta(days=14), opened, agent=an.get("window", "transaction"))
    ep.refs["window"] = _ref(g, n)

    n = len(g.trace.calls)
    ep.profile = g.card_profile(card_id, ts, 30, agent=an.get("profile", "transaction"))
    ep.refs["profile"] = _ref(g, n)

    n = len(g.trace.calls)
    amt = float(ep.txn["amt"])
    ep.recurring = g.recurring_match(card_id, amt, max(0.30, round(0.01 * amt, 2)), ts, agent=an.get("recurring", "transaction"))
    ep.refs["recurring"] = _ref(g, n)

    n = len(g.trace.calls)
    ep.account = g.account_history(case["flagged_txn_id"], 200, agent=an.get("account", "identity"))
    ep.refs["account"] = _ref(g, n)

    if ep.txn.get("device"):
        n = len(g.trace.calls)
        ep.device = g.device_neighbors(ep.txn["device"], ts - timedelta(days=30), opened, agent=an.get("device", "network"))
        ep.refs["device"] = _ref(g, n)

    if ep.txn.get("addr1") and ep.txn.get("channel") == "in_person":
        n = len(g.trace.calls)
        ep.region = g.region_activity(ep.txn["addr1"], ts - timedelta(days=3), opened, 50, agent=an.get("region", "network"))
        ep.refs["region"] = _ref(g, n)

    n = len(g.trace.calls)
    ep.prior = g.prior_cases(card_id, agent=an.get("prior", "precedent"))
    ep.refs["prior"] = _ref(g, n)
    return ep


def memory_query_text(ep: EvidencePack, hypothesis: str = "") -> str:
    t = ep.txn
    return (f"{ep.case['trigger_type']} alert. {t.get('channel')} transaction ${t.get('amt')} product {t.get('product')} "
            f"region {t.get('addr1') or 'n/a'} device {t.get('device') or 'none'} (flag {t.get('is_new') or 'n/a'}, "
            f"proxy {t.get('proxy') or 'none'}). {hypothesis}")


def recall(ep: EvidencePack, g: Any, hypothesis: str, devices: list[str], cards: list[str], pattern: str = "",
           agent: str = "precedent") -> None:
    """Hybrid GraphRAG: case memory (vector + graph-filtered) and policy/typology knowledge."""
    qv = embed_query(memory_query_text(ep, hypothesis))
    n = len(g.trace.calls)
    ep.memory = g.similar_cases(qv, devices, cards, 8, pattern, agent=agent)
    ep.refs["memory"] = _ref(g, n)
    n = len(g.trace.calls)
    ep.knowledge = g.search_knowledge(embed_query(hypothesis or memory_query_text(ep)), 6, agent=agent)
    ep.refs["knowledge"] = _ref(g, n)
