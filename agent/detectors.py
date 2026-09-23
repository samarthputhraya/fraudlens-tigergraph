"""Deterministic fraud detectors: typed findings with likelihood ratios, entity IDs and replayable query refs.

Every finding says what it rests on. Thresholds were fitted on the closed cases (eval/backtest.py), e.g.
- fraud episodes: consecutive same-account transactions are <= 48 h apart in 99% of confirmed cases;
- prior confirmed fraud on the same resolved account: 42% fraud rate vs 2.7% base in October, 0/144 cleared alerts;
- single-transaction LRs come from 14,055 confirmed-fraud vs 402,449 background transactions (Jul-Oct), see
  eval/likelihoods.md: online 2.1, proxy 3.0, online-on-in-person-card 2.7, new product 1.8, new device 1.4,
  amount above card max 1.3, new card-present region 0.46 (travel), known region 0.62.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta

from agent.evidence import EvidencePack, P

EPISODE_GAP_H = 48
RARE_DEVICE_CARDS = 25          # a device profile seen on <= this many cards all-time is "rare"
SMALL_AUTH = 5.0                # card testing: tiny authorisations
STRUCT_LO, STRUCT_HI = 400.0, 500.0


@dataclass
class Finding:
    key: str                     # detector id
    claim: str                   # human-readable, evidence-grade statement
    lr: float                    # likelihood ratio P(e|fraud)/P(e|legit)
    family: str                  # independence family (account, device, network, amount, region, behaviour, memory, customer)
    source: str = "graph"        # graph | document | customer | external
    ref: str = ""
    entity_ids: list = field(default_factory=list)
    pattern_hint: str = ""
    data: dict = field(default_factory=dict)

    @property
    def weight(self) -> float:
        return math.log(self.lr)


def _pct(values: list[float], x: float) -> float:
    if not values:
        return 0.5
    return sum(1 for v in values if v < x) / len(values)


def _suspicious_proxy(p: str) -> bool:
    return p in ("IP_PROXY:ANONYMOUS", "IP_PROXY:HIDDEN")


def run_detectors(ep: EvidencePack) -> tuple[list[Finding], dict]:
    """Returns findings and a facts dict (episode, pattern signals, links) used by assessment and policy."""
    f: list[Finding] = []
    t = ep.txn
    ts = ep.ts
    amt = float(t["amt"])
    card = ep.case["card_id"]
    online = t.get("channel") == "online"
    prof = ep.profile
    facts: dict = {"card_id": card, "customer_id": ep.case["customer_id"], "online": online, "amt": amt,
                   "shared_links": [], "connected_cards": set(), "connected_devices": set(), "episode": [t["id"]],
                   "pattern_signals": Counter()}

    # ---------------------------------------------------------------- account lineage (entity resolution)
    hist = ep.account.get("history", [])
    acct_id = ep.account.get("account", {}).get("id", "")
    fraud_prior = [h for h in hist if "confirmed_fraud" in (h.get("outcomes") or [])]
    cleared_prior = [h for h in hist if "cleared" in (h.get("outcomes") or [])]
    if fraud_prior:
        cases = sorted({c for h in fraud_prior for c in h.get("closed_cases", [])})
        pats = Counter(p for h in fraud_prior for p in (h.get("patterns") or []) if p != "none")
        f.append(Finding("account_prior_fraud",
                         f"The resolved cardholder account behind this card ({acct_id}) already had {len(fraud_prior)} "
                         f"transaction(s) confirmed as fraud in closed case(s) {', '.join(cases[:5])}, most recently "
                         f"{fraud_prior[-1]['ts'][:10]}; accounts with prior confirmed fraud were fraud 42% of the time in "
                         f"October vs a 2.7% base rate",
                         12.0, "account", ref=ep.refs.get("account", ""), entity_ids=cases[:6] + [fraud_prior[-1]["id"]],
                         data={"cases": cases, "patterns": dict(pats), "last_fraud": fraud_prior[-1]["ts"]}))
        facts["account_prior_fraud"] = cases
        facts["account_prior_patterns"] = pats
    elif len(hist) >= 5 and not cleared_prior:
        f.append(Finding("account_clean_history",
                         f"The resolved account ({acct_id}) has {len(hist)} earlier transactions and none were ever part of a "
                         f"fraud case", 0.7, "account", ref=ep.refs.get("account", ""), entity_ids=[h["id"] for h in hist[-3:]]))
    companions = [h for h in hist if (ts - P(h["ts"])).total_seconds() <= EPISODE_GAP_H * 3600
                  and float(h.get("risk_score") or 0) >= 0.7]
    if companions:
        c0 = companions[-1]
        f.append(Finding("account_companion_alert",
                         f"Another transaction on the same resolved account {((ts - P(c0['ts'])).total_seconds() / 3600):.1f} hours "
                         f"earlier ({c0['id']}, ${float(c0['amt']):,.2f}) was also scored {float(c0['risk_score']):.2f} by the model",
                         2.5, "account", ref=ep.refs.get("account", ""), entity_ids=[c0["id"]]))
        facts["companion_alert"] = c0["id"]
    if cleared_prior:
        cases = sorted({c for h in cleared_prior for c in h.get("closed_cases", [])})
        f.append(Finding("account_prior_cleared",
                         f"An earlier alert on this same account was investigated and cleared ({', '.join(cases[:3])})",
                         0.6, "memory", ref=ep.refs.get("account", ""), entity_ids=cases[:3]))

    # ---------------------------------------------------------------- windowed behaviour on the card
    win = [w for w in ep.window if P(w["ts"]) <= ep.opened_at]
    by_id = {w["id"]: w for w in win}
    near = [w for w in win if abs((P(w["ts"]) - ts).total_seconds()) <= 3 * 3600]

    # sub-threshold structuring: >=3 online purchases in [$400,$500) within 60 minutes
    band = [w for w in near if w["channel"] == "online" and STRUCT_LO <= float(w["amt"]) < STRUCT_HI]
    struct = []
    for i, w in enumerate(band):
        grp = [x for x in band if 0 <= (P(x["ts"]) - P(w["ts"])).total_seconds() <= 3600]
        if len(grp) > len(struct):
            struct = grp
    if len(struct) >= 3 and any(x["id"] == t["id"] for x in struct):
        tot = sum(float(x["amt"]) for x in struct)
        mins = (P(struct[-1]["ts"]) - P(struct[0]["ts"])).total_seconds() / 60
        f.append(Finding("structuring",
                         f"{len(struct)} online purchases within {mins:.0f} minutes, each just under $500 "
                         f"({', '.join('$%.2f' % float(x['amt']) for x in struct)}; total ${tot:,.2f}): amounts appear chosen "
                         f"to stay under a $500 authorisation threshold", 40.0, "behaviour", ref=ep.refs.get("window", ""),
                         entity_ids=[x["id"] for x in struct], pattern_hint="undocumented",
                         data={"txns": [x["id"] for x in struct], "total": tot, "minutes": mins}))
        facts["structuring"] = [x["id"] for x in struct]
        facts["pattern_signals"]["undocumented:structuring"] += 3
        devs = {x.get("device") for x in struct if x.get("device")}
        if len(devs) > 1:
            facts["connected_devices"] |= devs

    # card testing: >=3 tiny online auths within 1h, then a larger purchase
    before = [w for w in win if P(w["ts"]) <= ts + timedelta(hours=3) and P(w["ts"]) >= ts - timedelta(hours=6)]
    tiny = [w for w in before if w["channel"] == "online" and float(w["amt"]) < SMALL_AUTH]
    ct = []
    for w in tiny:
        grp = [x for x in tiny if 0 <= (P(x["ts"]) - P(w["ts"])).total_seconds() <= 3600]
        if len(grp) > len(ct):
            ct = grp
    if len(ct) >= 3:
        after = [w for w in before if P(w["ts"]) >= P(ct[-1]["ts"]) and float(w["amt"]) >= 20 and w["id"] not in {x["id"] for x in ct}]
        if after or float(t["amt"]) >= 20:
            big = after[0] if after else t
            cleared_100 = any(float(w["amt"]) > 100 for w in after)
            f.append(Finding("card_testing",
                             f"{len(ct)} online authorisations under ${SMALL_AUTH:.0f} within an hour "
                             f"({', '.join('$%.2f' % float(x['amt']) for x in ct)}), followed by a ${float(big['amt']):.2f} purchase",
                             30.0, "behaviour", ref=ep.refs.get("window", ""), entity_ids=[x["id"] for x in ct] + [big["id"]],
                             pattern_hint="card_testing", data={"cleared_over_100": cleared_100}))
            facts["card_testing"] = [x["id"] for x in ct] + [big["id"]]
            facts["card_testing_cleared_over_100"] = cleared_100
            facts["pattern_signals"]["card_testing"] += 3

    # ---------------------------------------------------------------- device & identity
    dev = t.get("device", "")
    dn = ep.device or {}
    n_cards_all = dn.get("n_cards_all_time", 0) or 0
    rare = bool(dev) and 0 < n_cards_all <= RARE_DEVICE_CARDS and dev.split(" | ")[0] != ""
    if online:
        seen_before = prof.get("device_n", {}).get(dev, 0) if dev else 0
        if dev and t.get("is_new") == "New" and seen_before == 0:
            f.append(Finding("new_device",
                             f"The purchase came from a device profile marked New for this account and never seen on this card "
                             f"before ({dev})", 1.4, "device", ref=ep.refs.get("context", ""), entity_ids=[t["id"]],
                             pattern_hint="card_not_present_new_device"))
            facts["pattern_signals"]["card_not_present_new_device"] += 1
            facts["new_device"] = True
        elif dev and seen_before >= 2:
            f.append(Finding("known_device",
                             f"The device profile ({dev}) was already used {seen_before} times on this card before the alert",
                             1.0, "device", ref=ep.refs.get("profile", ""), entity_ids=[t["id"]]))
        if _suspicious_proxy(t.get("proxy", "")):
            f.append(Finding("proxy", f"The session was routed through an {t['proxy'].split(':')[1].lower()} proxy",
                             3.0, "device", ref=ep.refs.get("context", ""), entity_ids=[t["id"]]))
            facts["proxy"] = t["proxy"]
        if not dev:
            facts["no_identity_record"] = True

    # shared-device ring: the same profile used as a NEW device by other customers inside the window, with most of the
    # profile's all-time footprint concentrated in that window (a generic browser/OS profile is never a ring signal)
    if dev and dn.get("txns"):
        others = [x for x in dn["txns"] if x["card_id"] != card and P(x["ts"]) <= ep.opened_at]
        other_cards = {x["card_id"] for x in others}
        other_custs = {x["customer_id"] for x in others}
        other_new = [x for x in others if x.get("is_new") == "New"]
        fraud_links = sorted({c for x in others for c in (x.get("closed_cases") or [])})
        inv_links = sorted({c for x in others for c in (x.get("inv_cases") or [])})
        anon = sum(1 for x in others if _suspicious_proxy(x.get("proxy", "")))
        concentration = (len(other_cards) + 1) / max(n_cards_all, 1)
        new_share = len(other_new) / max(len(others), 1)
        parts = dev.split(" | ")
        named_device = parts[0] not in ("", "Windows", "iOS Device", "MacOS") or (
            n_cards_all <= 10 and len(parts) == 4 and all(parts))
        ring = len(other_custs) >= 3 and new_share >= 0.6 and (concentration >= 0.4 or anon >= 0.5 * len(others))
        shared = (not ring) and len(other_custs) >= 2 and concentration >= 0.4 and named_device
        if ring or shared or ((fraud_links or inv_links) and named_device and concentration >= 0.2):
            members = sorted(other_cards)
            strength = (8.0 + 2.0 * min(len(other_custs), 10)) if ring else 4.0 + 1.5 * len(other_custs)
            if fraud_links or inv_links:
                strength *= 2
            f.append(Finding("shared_device",
                             f"The same device profile ({dev}) was used on {len(members)} other card(s) of {len(other_custs)} other "
                             f"customer(s) between {others[0]['ts'][:10]} and {others[-1]['ts'][:10]}"
                             f"{f', {len(other_new)} of those uses as a New device' if other_new else ''}"
                             f"{f', {anon} behind an anonymising proxy' if anon else ''}"
                             f"{'; linked closed cases ' + ', '.join(fraud_links[:4]) if fraud_links else ''}"
                             f"{'; linked investigations ' + ', '.join(inv_links[:4]) if inv_links else ''}. "
                             f"The profile appears on only {n_cards_all} card(s) in the whole dataset",
                             strength, "network", ref=ep.refs.get("device", ""), entity_ids=members[:15] + fraud_links[:4],
                             pattern_hint="undocumented" if ring else "card_not_present_new_device",
                             data={"members": members, "customers": sorted(other_custs), "fraud_cases": fraud_links,
                                   "inv_cases": inv_links, "ring": ring, "concentration": round(concentration, 2)}))
            facts["shared_links"].append(("device", dev))
            facts["connected_cards"] |= set(members)
            facts["connected_devices"].add(dev)
            facts["ring_size"] = len(other_custs) if ring else 0
            facts["shared_device_customers"] = len(other_custs)
            facts["ring_fraud_cases"] = fraud_links + inv_links
            facts["pattern_signals"]["undocumented:device_ring" if ring else "card_not_present_new_device"] += 3 if ring else 1

    # ---------------------------------------------------------------- amount, product, recurrence
    amts = prof.get("amts", [])
    if len(amts) >= 10:
        pct = _pct(amts, amt)
        mx = prof.get("amt_max", 0)
        if amt > mx:
            f.append(Finding("amount_above_max",
                             f"${amt:,.2f} is above every earlier purchase on this card (previous maximum ${mx:,.2f})",
                             1.3, "amount", ref=ep.refs.get("profile", ""), entity_ids=[t["id"]]))
            facts["amount_anomaly"] = True
        elif pct >= 0.97:
            f.append(Finding("amount_high", f"${amt:,.2f} is in the top 3% of this card's purchase amounts",
                             1.2, "amount", ref=ep.refs.get("profile", ""), entity_ids=[t["id"]]))
        elif 0.2 <= pct <= 0.8:
            f.append(Finding("amount_typical", f"${amt:,.2f} is a typical amount for this card (percentile {pct:.0%})",
                             1.0, "amount", ref=ep.refs.get("profile", ""), entity_ids=[t["id"]]))
    prods = prof.get("product_n", {})
    if prof.get("n_txn", 0) >= 10 and prods.get(t.get("product"), 0) == 0:
        f.append(Finding("new_product", f"This card has never used product code {t.get('product')} before",
                         1.8, "behaviour", ref=ep.refs.get("profile", ""), entity_ids=[t["id"]]))
        facts["new_product"] = True
    if online and prof.get("n_txn", 0) >= 20 and prof.get("n_online", 0) <= 0.05 * prof["n_txn"]:
        f.append(Finding("channel_shift",
                         f"This card is used almost only in person ({prof['n_online']} of {prof['n_txn']} earlier transactions "
                         f"online); this purchase is online", 2.7, "behaviour", ref=ep.refs.get("profile", ""), entity_ids=[t["id"]]))
        facts["channel_shift"] = True

    rec = [r for r in ep.recurring if r["id"] != t["id"]]
    six_m = [r for r in rec if (ts - P(r["ts"])).days <= 185]
    monthly_hits = [r for r in six_m if r["ts"][:7] != t["ts"][:7] and abs(P(r["ts"]).day - ts.day) <= 2]
    if monthly_hits and len(six_m) <= 12:
        months = sorted({r["ts"][:7] for r in six_m})
        f.append(Finding("recurring_amount",
                         f"The same amount (+/-1%) recurs on this card on the same day of the month: "
                         f"{', '.join(r['ts'][:10] + ' $' + format(float(r['amt']), '.2f') for r in monthly_hits[-3:])} "
                         f"({len(six_m)} matching charge(s) in the last six months), consistent with a recurring charge",
                         0.3 if ep.case["trigger_type"] == "customer_report" else 0.7, "amount",
                         ref=ep.refs.get("recurring", ""), entity_ids=[r["id"] for r in monthly_hits[-3:]],
                         data={"months": months, "same_dom": [r["id"] for r in monthly_hits]}))
        facts["recurring"] = True
        facts["recurring_txns"] = [r["id"] for r in monthly_hits[-3:]]

    # duplicate-looking repeats of the same amount within minutes (billing repeat vs testing)
    dups = [w for w in near if w["id"] != t["id"] and abs(float(w["amt"]) - amt) <= max(0.3, 0.01 * amt)
            and abs((P(w["ts"]) - ts).total_seconds()) <= 3600]
    if dups:
        facts["same_amount_repeats"] = [w["id"] for w in dups]

    # ---------------------------------------------------------------- region (card-present)
    if not online and t.get("addr1"):
        reg = t["addr1"]
        n_here = prof.get("region_n", {}).get(reg, 0)
        first = prof.get("region_first", {}).get(reg)
        if n_here == 0:
            recent_new = [w for w in win if w["addr1"] == reg and P(w["ts"]) <= ep.opened_at]
            days = {w["ts"][:10] for w in recent_new}
            home = Counter(prof.get("region_n", {})).most_common(1)
            home_reg = home[0][0] if home else ""
            home_active = [w for w in win if w["addr1"] == home_reg and abs((P(w["ts"]) - ts).total_seconds()) <= 24 * 3600]
            if len(days) >= 3:
                f.append(Finding("region_trip",
                                 f"Card-present purchases in billing region {reg} on {len(days)} different days: a sustained stay, "
                                 f"more consistent with a trip than a cloned card", 0.5, "region", ref=ep.refs.get("window", ""),
                                 entity_ids=[w["id"] for w in recent_new[:4]]))
                facts["trip"] = True
                facts["new_region"] = reg
            else:
                lr = 1.5 if home_active else 0.6
                f.append(Finding("region_new",
                                 f"Card-present purchase in billing region {reg}, where this card has no earlier history"
                                 f"{f', while activity continued in its home region {home_reg} within 24 hours' if home_active else ''}",
                                 lr, "region", ref=ep.refs.get("profile", ""), entity_ids=[t["id"]] + [w["id"] for w in home_active[:2]],
                                 pattern_hint="out_of_region_use"))
                facts["pattern_signals"]["out_of_region_use"] += 2
                facts["new_region"] = reg
        elif n_here >= 3:
            f.append(Finding("region_known",
                             f"This card has {n_here} earlier card-present purchases in billing region {reg} (first on {str(first)[:10]})",
                             0.65, "region", ref=ep.refs.get("profile", ""), entity_ids=[t["id"]]))

    # ---------------------------------------------------------------- mixed channel / account takeover signals
    acct_recent = [h for h in hist if (ts - P(h["ts"])).total_seconds() <= EPISODE_GAP_H * 3600]
    chans = {h["channel"] for h in acct_recent} | {t.get("channel")}
    if len(chans) >= 2 and (t.get("is_new") == "New" or t.get("m4") in ("M2",) or facts.get("proxy")):
        f.append(Finding("mixed_channel",
                         "Both card-present and online purchases on the same account within 48 hours, with identity anomalies "
                         "(new device, proxy or name/address match flag)", 2.0, "behaviour", ref=ep.refs.get("account", ""),
                         entity_ids=[h["id"] for h in acct_recent[-3:]] + [t["id"]], pattern_hint="account_takeover"))
        facts["pattern_signals"]["account_takeover"] += 2

    # ---------------------------------------------------------------- memory (closed cases on this card/customer)
    pc = ep.prior or {}
    facts["card_prior_patterns"] = Counter(c["pattern"] for c in pc.get("closed_cases", [])
                                           if c["outcome"] == "confirmed_fraud" and c["card_id"] == card)
    cleared_card = [c for c in pc.get("closed_cases", []) if c["outcome"] == "cleared" and c["card_id"] == card]
    if cleared_card:
        notes = cleared_card[-1].get("analyst_notes", "")
        f.append(Finding("card_prior_cleared",
                         f"This card has {len(cleared_card)} earlier alert(s) that were cleared as false alarms "
                         f"({', '.join(c['id'] for c in cleared_card[-3:])}; latest note: \"{notes[:140]}\")",
                         0.8, "memory", ref=ep.refs.get("prior", ""), entity_ids=[c["id"] for c in cleared_card[-3:]]))
    for cx in pc.get("connected_cases", []):
        if cx["outcome"] == "confirmed_fraud":
            f.append(Finding("card_connected_to_fraud",
                             f"This card was listed as a connected card in confirmed fraud case {cx['id']} ({cx['pattern']})",
                             4.0, "network", ref=ep.refs.get("prior", ""), entity_ids=[cx["id"]]))
            facts["shared_links"].append(("case", cx["id"]))
            break

    # ---------------------------------------------------------------- episode (same account, 48 h chain)
    facts["episode"] = build_episode(ep, facts)
    return f, facts


def build_episode(ep: EvidencePack, facts: dict) -> list[str]:
    t = ep.txn
    if facts.get("structuring"):
        return sorted(facts["structuring"])
    if facts.get("card_testing"):
        return sorted(facts["card_testing"])
    ts = ep.ts
    acct = ep.account.get("history", [])
    chain = [t]
    # walk backwards through the same account while gaps stay <= 48 h
    prev_ts = ts
    for h in reversed(acct):
        if h.get("outcomes") and "cleared" not in h["outcomes"]:
            break  # already part of an earlier closed case
        if (prev_ts - P(h["ts"])).total_seconds() > EPISODE_GAP_H * 3600:
            break
        if facts.get("online") and h.get("channel") != "online" and not facts["pattern_signals"].get("account_takeover"):
            continue
        chain.append(h)
        prev_ts = P(h["ts"])
    # same-device online burst on the card (covers accounts split by missing D1)
    if facts.get("online") and t.get("device") and facts.get("new_device"):
        for w in ep.window:
            if w.get("device") == t["device"] and abs((P(w["ts"]) - ts).total_seconds()) <= EPISODE_GAP_H * 3600 \
                    and P(w["ts"]) <= ep.opened_at and w["id"] not in {c["id"] for c in chain}:
                chain.append(w)
    if facts.get("ring_size") and t.get("device"):
        for x in (ep.device or {}).get("txns", []):
            if x["card_id"] == facts["card_id"] and P(x["ts"]) <= ep.opened_at and x["id"] not in {c["id"] for c in chain}:
                chain.append(x)
    return sorted({c["id"] for c in chain}, key=lambda i: next((c["ts"] for c in chain if c["id"] == i), ""))
