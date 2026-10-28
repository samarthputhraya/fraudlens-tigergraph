"""Fraud patterns the policy's five documented patterns don't cover (Final Round challenge 1: new typologies).

The bank's model was never retrained, and January carries activity it has never seen, so a low model score is at
best weak evidence of innocence. These detectors look for the shape of the abuse instead:

- micro_run        charges too small to trip any threshold: >= 4 online charges under $10 on >= 3 different days within
                   30 days, on a card that had at most 1 such charge in the 90 days before (sudden onset)
- recipient_surge  many cards paying one recipient: the recipient e-mail domain of this card's recent online purchases
                   is suddenly paid by >= 5 cards in 30 days, >= 3x its usual monthly reach (policy R6 names "the same
                   recipient email in one window" as a shared origin)
- spoofed_device   a device fingerprint that can't be real: one specific handset model reported with operating systems
                   from different families (an Android build string with Windows, iOS or Mac OS), as a New device
- escalating_ramp  limit probing: >= 4 online purchases within 14 days whose amounts climb (at least two near-doublings,
                   last >= 3x the first, reaching >= $500), plus any repeats at the top amount

Every detector reads only transactions up to the case's open time (no look-ahead) and returns the exact transaction
IDs it rests on. Background rates on July-December are measured in eval/typology_backtest.py.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta

MICRO_MAX = 10.0
MICRO_MIN_N, MICRO_MIN_DAYS, MICRO_MAX_PRIOR = 4, 3, 1
MICRO_SAME_MAX = 2              # 3+ small charges of one amount is a subscription, not a micro-charge run
SURGE_MIN_CARDS, SURGE_RATIO = 5, 3.0
RAMP_MIN_N, RAMP_WINDOW_D, RAMP_MIN_TOP, RAMP_MIN_GROWTH = 4, 14, 500.0, 3.0
LOOKBACK_D, BASELINE_D = 30, 90

GENERIC_DEVICE_INFO = {"", "windows", "ios device", "macos", "trident/7.0", "rv:11.0", "linux"}
_ANDROID = re.compile(r"build/|^(sm-|samsung|sgh-|lg|lm-|moto|xt\d|huawei|honor|ale-|cam-|rne-|sla-|tag-|vns-|was-|"
                      r"pixel|nexus|htc|zte|z\d{3}|k\d{2}|rct|f\d{4}|g\d{4}|redmi|mi |oneplus|lenovo|alcatel|\d{4}[a-z])", re.I)


def P(ts: str) -> datetime:
    return datetime.fromisoformat(str(ts)[:19])


def os_family(os_name: str) -> str:
    s = (os_name or "").lower()
    if s.startswith("windows"):
        return "windows"
    if s.startswith("ios"):
        return "ios"
    if s.startswith("mac"):
        return "mac"
    if s.startswith("android"):
        return "android"
    return ""


def hardware_family(device_info: str) -> str:
    s = (device_info or "").strip().lower()
    if s in GENERIC_DEVICE_INFO:
        return ""
    if s.startswith("ios") or s.startswith("iphone") or s.startswith("ipad"):
        return "ios"
    if _ANDROID.search(s):
        return "android"
    return ""


@dataclass
class Typology:
    key: str
    name: str
    txns: list                      # transaction IDs this rests on, in time order
    claim: str
    description: str                # pattern_description wording (undocumented patterns)
    pattern: str = "undocumented"
    shared: tuple | None = None     # (kind, value) for R6, e.g. ("recipient email", "sc.rr.com")
    ring: list = field(default_factory=list)   # other cards showing the same signature in the window
    data: dict = field(default_factory=dict)

    @property
    def total(self) -> float:
        return round(sum(self.data.get("amounts", {}).get(i, 0.0) for i in self.txns), 2)


def _online(rows: list[dict], end: datetime) -> list[dict]:
    return sorted((r for r in rows if r.get("channel") == "online" and P(r["ts"]) <= end), key=lambda r: (r["ts"], r["id"]))


def _money(x: float) -> str:
    return f"${x:,.2f}"


# ---- single-card signatures ----------------------------------------------------------------------------------------

def subscription(amounts: list[float]) -> bool:
    """Small charges that repeat one exact amount (four $7.42 charges a week apart) are a recurring charge."""
    rounded = [round(float(a), 2) for a in amounts]
    return bool(rounded) and max(rounded.count(a) for a in set(rounded)) > MICRO_SAME_MAX


def micro_run(rows30: list[dict], end: datetime, prior_micro_n: int) -> Typology | None:
    micro = [r for r in _online(rows30, end) if float(r["amt"]) < MICRO_MAX]
    days = sorted({r["ts"][:10] for r in micro})
    if len(micro) < MICRO_MIN_N or len(days) < MICRO_MIN_DAYS or prior_micro_n > MICRO_MAX_PRIOR:
        return None
    if subscription([r["amt"] for r in micro]):
        return None
    amts = {r["id"]: float(r["amt"]) for r in micro}
    return Typology(
        "micro_run", "micro-charge run", [r["id"] for r in micro],
        f"{len(micro)} online charges under ${MICRO_MAX:.0f} on {len(days)} different days between {days[0]} and {days[-1]} "
        f"({', '.join(_money(a) for a in amts.values())}), on a card with {prior_micro_n} such charge(s) in the "
        f"{BASELINE_D} days before: charges too small to trip any amount threshold",
        "Micro-charge run: a card that never carried tiny online charges suddenly shows four or more, each under $10, "
        "spread across several days so no single one trips an amount or velocity threshold. The agent found it by "
        "comparing the card's last 30 days with its own 90-day baseline in the graph and then scanning the same window "
        "for other cards with the same signature.",
        data={"amounts": amts, "days": days, "prior_micro_n": prior_micro_n})


def spoofed_device(rows30: list[dict], end: datetime) -> Typology | None:
    groups: dict[str, list[dict]] = {}
    for r in _online(rows30, end):
        parts = (r.get("device") or "").split(" | ")
        if len(parts) < 2:
            continue
        info = parts[0].strip()
        if hardware_family(info) == "":
            continue
        groups.setdefault(info, []).append(r)
    best = None
    for info, rs in groups.items():
        hw = hardware_family(info)
        fams = {os_family(r["device"].split(" | ")[1]) for r in rs} - {""}
        contradicts = {f for f in fams if f != hw}
        if not contradicts and len(fams) < 2:
            continue
        if not any(r.get("is_new") == "New" for r in rs):
            continue
        if best is None or len(rs) > len(best[1]):
            best = (info, rs, fams)
    if not best:
        return None
    info, rs, fams = best
    amts = {r["id"]: float(r["amt"]) for r in rs}
    proxied = sum(1 for r in rs if str(r.get("proxy") or "").upper().startswith("IP_PROXY"))
    oses = sorted({r["device"].split(" | ")[1] or "(blank)" for r in rs})
    return Typology(
        "spoofed_device", "spoofed device fingerprint", [r["id"] for r in rs],
        f"{len(rs)} online purchase(s) ({', '.join(_money(a) for a in amts.values())}) from a device that reports itself as "
        f"'{info}', an {'iOS' if hardware_family(info) == 'ios' else 'Android'} handset, but with "
        f"operating system(s) {', '.join(oses)}: a fingerprint no real "
        f"device produces, marked New for this account{f', {proxied} behind an anonymising proxy' if proxied else ''}",
        "Spoofed-fingerprint purchases: high-value online purchases from a brand-new device whose fingerprint is internally "
        "impossible (one handset model reporting operating systems from different families), usually behind an anonymising "
        "proxy, so no device profile repeats across the cards it hits. The agent found it by checking each device's "
        "hardware against its reported operating system and then scanning the same window for other cards with the same "
        "signature.",
        data={"amounts": amts, "device_info": info, "os": oses, "proxied": proxied})


def escalating_ramp(rows30: list[dict], end: datetime) -> Typology | None:
    # consecutive online purchases of one product code: a ramp may not skip over a smaller purchase in between
    by_product: dict[str, list[dict]] = {}
    for r in _online(rows30, end):
        if float(r["amt"]) >= 20:
            by_product.setdefault(r.get("product") or "", []).append(r)
    best: list[dict] = []
    for rs in by_product.values():
        for i in range(len(rs)):
            run = [rs[i]]
            for r in rs[i + 1:]:
                if (P(r["ts"]) - P(run[0]["ts"])).days > RAMP_WINDOW_D or float(r["amt"]) < 0.98 * float(run[-1]["amt"]):
                    break
                run.append(r)
            amts = [float(r["amt"]) for r in run]
            doublings = sum(1 for a, b in zip(amts, amts[1:]) if b >= 1.8 * a)
            if (len(run) >= RAMP_MIN_N and doublings >= 2 and amts[-1] >= RAMP_MIN_TOP
                    and amts[-1] >= RAMP_MIN_GROWTH * amts[0] and len(run) > len(best)):
                best = run
    if not best:
        return None
    amts = {r["id"]: float(r["amt"]) for r in best}
    vals = list(amts.values())
    top = max(vals)
    repeats = sum(1 for a in vals if a >= 0.98 * top)
    return Typology(
        "escalating_ramp", "escalating-value ramp", [r["id"] for r in best],
        f"{len(best)} online purchases between {best[0]['ts'][:10]} and {best[-1]['ts'][:10]} climbing from "
        f"{_money(vals[0])} to {_money(top)} ({' -> '.join(_money(a) for a in vals)})"
        f"{f', with {repeats} charges at the top amount' if repeats > 1 else ''}: the pattern of someone probing the card's limit",
        "Escalating-value ramp: a run of online purchases on one card in which each charge roughly doubles the last until it "
        "reaches a ceiling, then repeats at that ceiling - probing how much the card will authorise. It differs from card "
        "testing, which starts with tiny authorisations. The agent found it by scanning the card's last 14-30 days for "
        "monotonically climbing amounts.",
        data={"amounts": amts, "repeats_at_top": repeats})


def recipient_surge(rows30: list[dict], end: datetime, domain_stats: dict) -> Typology | None:
    """domain_stats: {"domain", "cards_window": [card ids], "monthly_cards": [counts per prior month]}"""
    dom = domain_stats.get("domain") or ""
    mine = [r for r in _online(rows30, end) if (r.get("r_email") or "") == dom]
    n = len(set(domain_stats.get("cards_window") or []))
    base = domain_stats.get("monthly_cards") or []
    usual = statistics.median(base) if base else 0.0
    if not dom or not mine or n < SURGE_MIN_CARDS or n < SURGE_RATIO * max(usual, 1.0):
        return None
    amts = {r["id"]: float(r["amt"]) for r in mine}
    return Typology(
        "recipient_surge", "recipient surge", [r["id"] for r in mine],
        f"This card's online purchase(s) ({', '.join(_money(a) for a in amts.values())}) went to recipient e-mail domain "
        f"{dom}, which {n} different cards paid in the 30 days before this case, against a median of {usual:.0f} card(s) "
        f"a month in the earlier months it was paid at all: "
        f"many cards paying one recipient",
        f"Recipient surge: many unrelated cards suddenly paying the same recipient (e-mail domain {dom}), in modest online "
        f"amounts and without any shared device, so device- and region-based ring checks see nothing. The agent found it by "
        f"comparing how many cards paid that recipient in the case window with the recipient's own monthly history in the "
        f"graph.",
        shared=("recipient email", dom), ring=sorted(set(domain_stats.get("cards_window") or [])),
        data={"amounts": amts, "domain": dom, "cards_window": n, "usual_monthly": usual})


# ---- ring context from the window scan ------------------------------------------------------------------------------

def _micro_member(c: dict) -> bool:
    """One typology_scan micro row: the same thresholds as micro_run, and not a subscription."""
    return (c["n"] >= MICRO_MIN_N and c["days"] >= MICRO_MIN_DAYS and c["prior_n"] <= MICRO_MAX_PRIOR
            and not subscription([x.split("|")[2] for x in c.get("txns") or []]))


def ring_members(kind: str, scan: dict, card: str) -> list[str]:
    """Other cards showing the same signature in the same window (from the typology_scan graph query)."""
    out: set[str] = set()
    if kind == "micro_run":
        for c in scan.get("micro", []):
            if c["card_id"] != card and _micro_member(c):
                out.add(c["card_id"])
    elif kind == "spoofed_device":
        by_card: dict[str, list[dict]] = {}
        for r in scan.get("new_device_txns", []):
            by_card.setdefault(r["card_id"], []).append(r)
        for c, rs in by_card.items():
            if c != card and spoofed_device(rs, datetime.max) is not None:
                out.add(c)
    elif kind == "escalating_ramp":
        by_card = {}
        for r in scan.get("ramp_txns", []):
            by_card.setdefault(r["card_id"], []).append(r)
        for c, rs in by_card.items():
            if c != card and escalating_ramp(rs, datetime.max) is not None:
                out.add(c)
    return sorted(out)


def ring_exposures(kind: str, scan: dict, recipient: dict | None = None) -> dict[str, dict]:
    """Per ring card: the transactions of its own signature, their total, and how strong that evidence is.

    conf is P(this card is compromised | its own signature), set from the signature's precision on July-October, the
    months whose labels are complete (eval/typology_backtest.json): micro-charge runs and escalating ramps are only
    about 1 in 3 confirmed there, so a ring member carrying one is monitored, never blocked, on that alone. Spoofed
    fingerprints never occur in July-December background; a card paying a surging recipient twice or more matches the
    September-October surges, which were 17 of 27 confirmed."""
    out: dict[str, dict] = {}
    if kind == "micro_run":
        for c in scan.get("micro", []):
            if _micro_member(c):
                txns = [x.split("|") for x in c.get("txns") or []]
                out[c["card_id"]] = {"txns": [t[0] for t in txns], "exposure": round(sum(float(t[2]) for t in txns), 2),
                                     "conf": 0.5, "why": f"its own sudden run of {c['n']} sub-$10 online charges on {c['days']} days"}
    elif kind in ("spoofed_device", "escalating_ramp"):
        rows_key = "new_device_txns" if kind == "spoofed_device" else "ramp_txns"
        by_card: dict[str, list[dict]] = {}
        for r in scan.get(rows_key, []):
            by_card.setdefault(r["card_id"], []).append(r)
        fn = spoofed_device if kind == "spoofed_device" else escalating_ramp
        for c, rs in by_card.items():
            typ = fn(rs, datetime.max)
            if typ is not None:
                out[c] = {"txns": typ.txns, "exposure": typ.total, "conf": 0.85 if kind == "spoofed_device" else 0.5,
                          "why": f"its own {typ.name} ({len(typ.txns)} purchase(s))"}
    elif kind == "recipient_surge" and recipient:
        by_card = {}
        for r in recipient.get("window_txns") or []:
            by_card.setdefault(r["card_id"], []).append(r)
        for c, rs in by_card.items():
            out[c] = {"txns": [r["id"] for r in rs], "exposure": round(sum(float(r["amt"]) for r in rs), 2),
                      "conf": 0.8 if len(rs) >= 2 else 0.6,
                      "why": f"{len(rs)} payment(s) to {recipient.get('domain')} in the window"}
    return out


def window(end: datetime, days: int = LOOKBACK_D) -> tuple[datetime, datetime]:
    return end - timedelta(days=days), end
