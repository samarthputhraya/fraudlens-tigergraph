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
    """One evidence-grade sentence for the case file."""
    pl, al = p["plan"], p["block_everything"]
    weak = p["customers_touched_on_weak_evidence"]
    return (f"Containment plan for the {p['ring_size']}-card ring (${p['ring_exposure_usd']:,.2f} at risk): block "
            f"{pl['cards_blocked']} card(s) ({', '.join(b['card'] for b in p['block'][:8])}{', ...' if pl['cards_blocked'] > 8 else ''}) "
            f"to cut {pl['exposure_cut_pct']}% of the exposure, and monitor the other {len(p['monitor'])}; blocking every "
            f"ring card would cut {al['exposure_cut_pct']}% but act against about {al['expected_innocent_blocked']:.1f} "
            f"customer(s) on weak evidence, against {pl['expected_innocent_blocked']:.1f} for this plan"
            + (f". Blocked on weaker evidence, named for review: {', '.join(w['card'] for w in weak)}" if weak else ""))
