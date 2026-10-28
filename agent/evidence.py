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


def known_device(profile: str | None) -> str:
    """A device profile with every field blank (" |  |  | ", about 4,000 identity rows) says nothing about the device:
    it is treated as no profile, never as one device shared by everyone who has it."""
    return profile if profile and profile.replace("|", "").strip() else ""


def gather(case: dict, g: Any, agent_names: dict | None = None) -> EvidencePack:
    """Run the core toolkit. `agent_names` maps step -> specialist name for the trace."""
    an = agent_names or {}
    opened = P(case["opened_at"])
    ep = EvidencePack(case=case, opened_at=opened)

    n = len(g.trace.calls)
    ctx = g.txn_context(case["flagged_txn_id"], agent=an.get("context", "lead"))
    ep.txn, ep.card = ctx["txn"], ctx["card"]
    ep.refs["context"] = _ref(g, n)
    if ep.txn and "device" in ep.txn:
        ep.txn["device"] = known_device(ep.txn["device"])
    if not ep.txn or not ep.txn.get("ts"):
        from agent.safety import InvalidInput
        raise InvalidInput("txn_context", f"flagged transaction {case['flagged_txn_id']} does not exist in the graph; "
                                          f"nothing was investigated or invented")
    ts = ep.ts
    if opened < ts:
        from agent.safety import InvalidInput
        raise InvalidInput("case_row", f"the case is opened at {case['opened_at']}, before its flagged transaction "
                                       f"({ep.txn['ts']}); the case record is inconsistent")
    # Data integrity: investigate the card that actually made the transaction. If the case record names another card,
    # say so (an analyst must reconcile it) instead of silently reading the wrong card's history.
    record_card = ep.txn.get("card_id") or case["card_id"]
    record_customer = ep.txn.get("customer_id") or case["customer_id"]
    if record_card != case["card_id"] or record_customer != case["customer_id"]:
        ep.extra["card_mismatch"] = {"case_card": case["card_id"], "record_card": record_card,
                                     "case_customer": case["customer_id"], "record_customer": record_customer}
        ep.case = {**case, "card_id": record_card, "customer_id": record_customer,
                   "case_pack_card_id": case["card_id"], "case_pack_customer_id": case["customer_id"]}
    card_id = ep.case["card_id"]

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
    ep.prior = g.prior_cases(card_id, opened, agent=an.get("prior", "precedent"))
    ep.refs["prior"] = _ref(g, n)

    typology_evidence(ep, g, an)
    return ep


def typology_evidence(ep: EvidencePack, g: Any, an: dict | None = None) -> None:
    """Evidence for the new-typology detectors (agent/typologies.py): the card's last 30 days, its own 90-day baseline
    when a micro-charge run is possible, the reach of each recipient domain it paid, and a window scan for other cards
    with the same signature. Everything is read up to the case's open time only."""
    from agent import typologies as ty
    an = an or {}
    card = ep.case["card_id"]
    lo, hi = ty.window(ep.opened_at)
    n = len(g.trace.calls)
    rows = g.card_window(card, lo, hi, agent=an.get("window", "transaction"))
    ep.extra["window_30d"] = rows
    ep.refs["window_30d"] = _ref(g, n)
    if ty.micro_run(rows, hi, 0) is not None:
        n = len(g.trace.calls)
        base_lo = lo - timedelta(days=ty.BASELINE_D)
        base = g.card_window(card, base_lo, lo, agent=an.get("window", "transaction"))
        ep.extra["micro_prior_n"] = sum(1 for r in base if r.get("channel") == "online" and float(r["amt"]) < ty.MICRO_MAX
                                        and base_lo < P(r["ts"]) <= lo)
        ep.refs["micro_baseline"] = _ref(g, n)
    domains: list[str] = []
    for r in sorted(rows, key=lambda r: r["ts"], reverse=True):
        d = r.get("r_email") or ""
        if r.get("channel") == "online" and d and d not in domains:
            domains.append(d)
    flagged = ep.txn.get("r_email") or ""
    if flagged in domains:
        domains.remove(flagged)
        domains.insert(0, flagged)
    ep.extra["recipient"] = {}
    for d in domains[:4]:
        n = len(g.trace.calls)
        st = g.recipient_activity(d, lo, hi, hi - timedelta(days=210), agent=an.get("network", "network"))
        ep.extra["recipient"][d] = {"domain": d, "cards_window": st["cards_window"],
                                    "monthly_cards": list(st["monthly_cards"].values()),
                                    "window_txns": st.get("window_txns") or []}
        ep.refs[f"recipient:{d}"] = _ref(g, n)
    candidates = [ep.extra.get("micro_prior_n") is not None, ty.spoofed_device(rows, hi), ty.escalating_ramp(rows, hi)]
    if any(candidates):
        n = len(g.trace.calls)
        ep.extra["typology_scan"] = g.typology_scan(lo, hi, lo - timedelta(days=ty.BASELINE_D),
                                                    agent=an.get("network", "network"))
        ep.refs["typology_scan"] = _ref(g, n)


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
    ep.memory = g.similar_cases(qv, devices, cards, 8, pattern, before=ep.opened_at, agent=agent)
    ep.refs["memory"] = _ref(g, n)
    n = len(g.trace.calls)
    ep.knowledge = g.search_knowledge(embed_query(hypothesis or memory_query_text(ep)), 6, agent=agent)
    ep.refs["knowledge"] = _ref(g, n)
