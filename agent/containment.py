"""Containment planner (Final Round challenge 7): given a ring, the smallest set of cards to block that cuts the most
exposure, with every customer the action would touch on weak evidence named explicitly.

Blocking is the costliest action for an innocent customer (it scores zero on a legitimate case, and a real customer
loses their card), so each card is blocked only when the exposure it stops outweighs the expected harm:

    block card c  if  conf(c) * exposure(c) - (1 - conf(c)) * INNOCENT_COST > 0      (and conf(c) >= MIN_BLOCK_CONF)

conf(c) is how sure the evidence makes us that card c itself is compromised (its own signature, not just its link to
the ring). INNOCENT_COST is the dollar-equivalent harm of blocking an innocent customer; it is a stated assumption, set
to $250 by default and swept in eval/containment_backtest.py. Every other ring card is monitored (MONITOR_CONNECTED_CARDS
or STEP_UP_AUTH), which costs a legitimate customer nothing.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

INNOCENT_COST = 250.0
MIN_BLOCK_CONF = 0.7


@dataclass
class Member:
    card: str
    exposure: float          # suspicious spend on this card inside the ring window
    conf: float              # P(this card is compromised | its own evidence)
    why: str                 # the evidence behind conf, in one line
    txns: list               # the transactions the exposure is made of


def plan(members: list[Member], innocent_cost: float = INNOCENT_COST) -> dict:
    total = round(sum(m.exposure for m in members), 2)
    scored = sorted(members, key=lambda m: m.conf * m.exposure - (1 - m.conf) * innocent_cost, reverse=True)
    block = [m for m in scored if m.conf >= MIN_BLOCK_CONF and m.conf * m.exposure - (1 - m.conf) * innocent_cost > 0]
    monitor = [m for m in scored if m not in block]
    cut = round(sum(m.exposure for m in block), 2)
    weak = [m for m in block if m.conf < 0.9]

    def summary(ms: list[Member]) -> dict:
        c = round(sum(m.exposure for m in ms), 2)
        return {"cards_blocked": len(ms), "exposure_cut_usd": c, "exposure_cut_pct": round(100 * c / total, 1) if total else 0.0,
                "expected_innocent_blocked": round(sum(1 - m.conf for m in ms), 2)}

    return {
        "ring_size": len(members), "ring_exposure_usd": total, "innocent_cost_usd": innocent_cost,
        "block": [asdict(m) for m in block], "monitor": [asdict(m) for m in monitor],
        "plan": summary(block), "block_everything": summary(members),
        "customers_touched_on_weak_evidence": [{"card": m.card, "conf": m.conf, "why": m.why} for m in weak],
    }


def describe(p: dict) -> str:
    """One evidence-grade sentence for the case file. The plan is a recommendation for the analyst: this case's own
    actions block at most this case's card."""
    pl, al = p["plan"], p["block_everything"]
    weak = p["customers_touched_on_weak_evidence"]
    blocked = ", ".join(b["card"] for b in p["block"][:8]) + (", ..." if pl["cards_blocked"] > 8 else "")
    if pl["cards_blocked"] == p["ring_size"]:
        tail = (f"Every ring card has strong evidence of its own, so the plan blocks all {p['ring_size']} "
                f"({blocked}), cutting 100% of it; an expected {pl['expected_innocent_blocked']:.1f} of them could still "
                f"belong to customers who are not compromised")
    else:
        tail = ((f"Blocking {pl['cards_blocked']} card(s) ({blocked}) would cut {pl['exposure_cut_pct']}% of it"
                 if pl["cards_blocked"] else "No ring card has strong enough evidence of its own to block")
                + f", and the other {len(p['monitor'])} would be monitored. Blocking every ring card would cut "
                f"{al['exposure_cut_pct']}% but is expected to block {al['expected_innocent_blocked']:.1f} customer(s) "
                f"who are not compromised, against {pl['expected_innocent_blocked']:.1f} for this plan")
    return (f"Containment plan for the analyst (this case's own actions cover only its card): the {p['ring_size']}-card "
            f"ring has ${p['ring_exposure_usd']:,.2f} at risk. " + tail
            + (f". Blocked on weaker evidence, named for review: {', '.join(w['card'] for w in weak)}" if weak else "") + ".")
