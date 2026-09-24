"""Deterministic fraud detectors: typed findings with likelihood ratios, entity IDs and replayable query refs.

Every finding says what it rests on. Thresholds were fitted on the closed cases (eval/backtest.py), e.g.
- fraud episodes: consecutive same-account transactions are <= 48 h apart in 99% of confirmed cases;
- prior confirmed fraud on the same resolved account: 42% fraud rate vs 2.7% base in October, 0/144 cleared alerts;
- single-transaction LRs come from 14,055 confirmed-fraud vs 402,449 background transactions (Jul-Oct), see
  eval/likelihoods.md: online 2.1, proxy 3.0, online-on-in-person-card 2.7, new product 1.8, new device 1.4,
  amount above card max 1.3, new card-present region 0.46 (travel), known region 0.62.
"""
from __future__ import annotations

import json
import math
import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from agent.evidence import EvidencePack, P

EPISODE_GAP_H = 48
RARE_DEVICE_CARDS = 25          # a device profile seen on <= this many cards all-time is "rare"
SMALL_AUTH = 5.0                # card testing: tiny authorisations
STRUCT_LO, STRUCT_HI = 400.0, 500.0
FRAUD_SCORED = 0.5              # a transaction the model scores at or above this is treated as fraud-like evidence
EPISODE_SAMPLES = 4000          # Monte Carlo draws for the probabilistic 48 h episode chain


def _model_meta() -> tuple[float, str]:
    rep = Path(__file__).resolve().parents[1] / "eval" / "model_report.json"
    try:
        r = json.loads(rep.read_text(encoding="utf-8"))
        return float(r.get("novdec_mean_p_cal") or 0.0275), f"{r['validation']['auc_october_all']:.3f}"
    except Exception:  # noqa: BLE001
        return 0.0275, "n/a"


MODEL_BASE_RATE, MODEL_AUC = _model_meta()


def _mp(x: dict) -> float:
    try:
        return float(x.get("model_p", -1))
    except (TypeError, ValueError):
        return -1.0


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
    in_model: bool = False       # the learned model already sees this signal: explained, never counted twice

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
    mp = float(t.get("model_p", -1) if t.get("model_p") is not None else -1)
    has_model = mp >= 0
    facts["model_p"] = mp if has_model else None
    if has_model:
        lr = (mp / (1 - mp)) / (MODEL_BASE_RATE / (1 - MODEL_BASE_RATE)) if 0 < mp < 1 else (0.05 if mp <= 0 else 200.0)
        f.append(Finding("model_score",
                         f"The transaction model trained on the bank's own closed cases (4,665 confirmed-fraud and 900 cleared "
                         f"investigations, July-October; October hold-out AUC {MODEL_AUC}) scores this transaction {mp:.3f}, "
                         f"against a {MODEL_BASE_RATE:.1%} base rate. It reads the unnamed Vesta C/D/M/V columns, the identity "
                         f"record, running aggregates of the resolved account and the graph's memory of earlier closed cases, all "
                         f"as known at transaction time (it never sees the case outcome)",
                         max(0.02, min(lr, 400.0)), "model", ref=ep.refs.get("context", ""), entity_ids=[t["id"]],
                         data={"model_p": mp}))

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
                         data={"cases": cases, "patterns": dict(pats), "last_fraud": fraud_prior[-1]["ts"]}, in_model=has_model))
        facts["account_prior_fraud"] = cases
        facts["account_prior_patterns"] = pats
    elif len(hist) >= 5 and not cleared_prior:
        f.append(Finding("account_clean_history",
                         f"The resolved account ({acct_id}) has {len(hist)} earlier transactions and none were ever part of a "
                         f"fraud case", 0.7, "account", ref=ep.refs.get("account", ""), entity_ids=[h["id"] for h in hist[-3:]],
                         in_model=has_model))
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
                         0.6, "memory", ref=ep.refs.get("account", ""), entity_ids=cases[:3], in_model=has_model))

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
                             pattern_hint="card_not_present_new_device", in_model=has_model))
            facts["pattern_signals"]["card_not_present_new_device"] += 1
            facts["new_device"] = True
        elif dev and seen_before >= 2:
            f.append(Finding("known_device",
                             f"The device profile ({dev}) was already used {seen_before} times on this card before the alert",
                             1.0, "device", ref=ep.refs.get("profile", ""), entity_ids=[t["id"]], in_model=has_model))
        if _suspicious_proxy(t.get("proxy", "")):
            kind = t['proxy'].split(':')[1].lower()
            f.append(Finding("proxy", f"The session was routed through {'an' if kind[:1] in 'aeiou' else 'a'} {kind} proxy",
                             3.0, "device", ref=ep.refs.get("context", ""), entity_ids=[t["id"]], in_model=has_model))
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
        # a ring = one device new to many accounts AND mostly behind an anonymising proxy (new OS/browser versions
        # also concentrate in late months, so concentration alone is not evidence)
        ring = len(other_custs) >= 3 and new_share >= 0.6 and anon >= 0.5 * len(others)
        near_in_time = [x for x in others if abs((P(x["ts"]) - ts).total_seconds()) <= 7 * 86400]
        scored = [x for x in near_in_time if _mp(x) >= FRAUD_SCORED]
        shared = (not ring) and named_device and n_cards_all <= 10 and len({x["customer_id"] for x in near_in_time}) >= 2
        if has_model and shared:
            # R6 needs fraud on the other cards, not just a shared device: the model must score their use as fraud
            shared = len({x["customer_id"] for x in scored}) >= 1
        if ring or shared or ((fraud_links or inv_links) and named_device and concentration >= 0.2):
            members = sorted(other_cards) if (ring or not has_model) else sorted({x["card_id"] for x in scored} or other_cards)
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
                             f"The profile appears on only {n_cards_all} card(s) in the whole dataset"
                             f"{'. The transaction model scores ' + str(len(scored)) + ' of those other-card uses as fraud (' + ', '.join(x['id'] + ' ' + format(_mp(x), '.2f') for x in scored[:4]) + ')' if has_model and scored else ''}",
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
                             1.3, "amount", ref=ep.refs.get("profile", ""), entity_ids=[t["id"]], in_model=has_model))
            facts["amount_anomaly"] = True
        elif pct >= 0.97:
            f.append(Finding("amount_high", f"${amt:,.2f} is in the top 3% of this card's purchase amounts",
                             1.2, "amount", ref=ep.refs.get("profile", ""), entity_ids=[t["id"]], in_model=has_model))
        elif 0.2 <= pct <= 0.8:
            f.append(Finding("amount_typical", f"${amt:,.2f} is a typical amount for this card (percentile {pct:.0%})",
                             1.0, "amount", ref=ep.refs.get("profile", ""), entity_ids=[t["id"]], in_model=has_model))
    prods = prof.get("product_n", {})
    if prof.get("n_txn", 0) >= 10 and prods.get(t.get("product"), 0) == 0:
        f.append(Finding("new_product", f"This card has never used product code {t.get('product')} before",
                         1.8, "behaviour", ref=ep.refs.get("profile", ""), entity_ids=[t["id"]], in_model=has_model))
        facts["new_product"] = True
    if online and prof.get("n_txn", 0) >= 20 and prof.get("n_online", 0) <= 0.05 * prof["n_txn"]:
        f.append(Finding("channel_shift",
                         f"This card is used almost only in person ({prof['n_online']} of {prof['n_txn']} earlier transactions "
                         f"online); this purchase is online", 2.7, "behaviour", ref=ep.refs.get("profile", ""), entity_ids=[t["id"]],
                         in_model=has_model))
        facts["channel_shift"] = True

    rec = [r for r in ep.recurring if r["id"] != t["id"]]
    six_m = [r for r in rec if (ts - P(r["ts"])).days <= 185]
    monthly_hits = [r for r in six_m if r["ts"][:7] != t["ts"][:7] and abs(P(r["ts"]).day - ts.day) <= 2]
    if has_model:
        # "their own recurring pattern": the earlier charge must look like the same cardholder (same purchaser e-mail
        # domain and the same device profile / channel), not another person sharing an anonymised card bucket
        monthly_hits = [r for r in monthly_hits if (r.get("p_email") or "") == (t.get("p_email") or "")
                        and (r.get("device") or "") == (t.get("device") or "") and r.get("product") == t.get("product")]
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
                                 f"Card-present purchases in billing region {region_label(reg)} on {len(days)} different days: a sustained stay, "
                                 f"more consistent with a trip than a cloned card", 0.5, "region", ref=ep.refs.get("window", ""),
                                 entity_ids=[w["id"] for w in recent_new[:4]]))
                facts["trip"] = True
                facts["new_region"] = reg
            else:
                lr = 1.5 if home_active else 0.6
                f.append(Finding("region_new",
                                 f"Card-present purchase in billing region {region_label(reg)}, where this card has no earlier history"
                                 f"{f', while activity continued in its home region {region_label(home_reg)} within 24 hours' if home_active else ''}",
                                 lr, "region", ref=ep.refs.get("profile", ""), entity_ids=[t["id"]] + [w["id"] for w in home_active[:2]],
                                 pattern_hint="out_of_region_use", in_model=has_model))
                facts["pattern_signals"]["out_of_region_use"] += 2
                facts["new_region"] = reg
        elif n_here >= 3:
            f.append(Finding("region_known",
                             f"This card has {n_here} earlier card-present purchases in billing region {region_label(reg)} (first on {str(first)[:10]})",
                             0.65, "region", ref=ep.refs.get("profile", ""), entity_ids=[t["id"]], in_model=has_model))

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
                         0.8, "memory", ref=ep.refs.get("prior", ""), entity_ids=[c["id"] for c in cleared_card[-3:]],
                         in_model=has_model))
    for cx in pc.get("connected_cases", []):
        if cx["outcome"] == "confirmed_fraud":
            f.append(Finding("card_connected_to_fraud",
                             f"This card was listed as a connected card in confirmed fraud case {cx['id']} ({cx['pattern']})",
                             4.0, "network", ref=ep.refs.get("prior", ""), entity_ids=[cx["id"]]))
            facts["shared_links"].append(("case", cx["id"]))
            break

    # ---------------------------------------------------------------- episode (same account, 48 h chain)
    facts["episode"] = build_episode(ep, facts)
    reg_n = Counter(prof.get("region_n", {}))
    facts["home_region"] = reg_n.most_common(1)[0][0] if reg_n else ""
    rows = {w["id"]: w for w in ep.window}
    rows[t["id"]] = t
    facts["episode_rows"] = [rows[i] for i in facts["episode"] if i in rows]
    return f, facts


def region_label(x) -> str:
    """Billing region codes are floats in the source data ('126.0'); people read them as codes ('126')."""
    s = str(x or "")
    return s[:-2] if s.endswith(".0") else s


def episode_chain(ep: EvidencePack, samples: int = EPISODE_SAMPLES) -> list[dict]:
    """Probabilistic fraud episode on the card: the bank's closed cases chain fraud transactions on the same card while
    consecutive gaps stay <= 48 h (between-case gaps on a card are never shorter). Each card transaction up to
    `opened_at` is fraud with the model's calibrated probability; we sample the chain that contains the flagged
    transaction and keep every transaction that belongs to it in at least half of the draws."""
    t = ep.txn
    rows = sorted([w for w in ep.window if P(w["ts"]) <= ep.opened_at] + ([] if any(w["id"] == t["id"] for w in ep.window) else [t]),
                  key=lambda w: (w["ts"], w["id"]))
    ids = [w["id"] for w in rows]
    fi = ids.index(t["id"])
    ps = [max(0.0, _mp(w)) for w in rows]
    secs = [P(w["ts"]).timestamp() for w in rows]
    rng = random.Random(int(t["id"]) if str(t["id"]).isdigit() else 7)
    hits = [0] * len(rows)
    gap = EPISODE_GAP_H * 3600
    for _ in range(samples):
        lab = [i == fi or rng.random() < ps[i] for i in range(len(rows))]
        lo = fi
        j = fi - 1
        while j >= 0:
            if lab[j]:
                if secs[lo] - secs[j] > gap:
                    break
                lo = j
            j -= 1
        hi = fi
        j = fi + 1
        while j < len(rows):
            if lab[j]:
                if secs[j] - secs[hi] > gap:
                    break
                hi = j
            j += 1
        for k in range(lo, hi + 1):
            if lab[k]:
                hits[k] += 1
    out = []
    for w, h in zip(rows, hits):
        if h / samples >= 0.5:
            out.append({**w, "chain_p": round(h / samples, 3)})
    return out


def build_episode(ep: EvidencePack, facts: dict) -> list[str]:
    t = ep.txn
    if facts.get("structuring"):
        return sorted(facts["structuring"])
    if facts.get("card_testing"):
        return sorted(facts["card_testing"])
    if facts.get("model_p") is not None and not facts.get("ring_size"):
        chain = episode_chain(ep)
        facts["episode_chain"] = [{"id": w["id"], "ts": w["ts"], "amt": w["amt"], "model_p": _mp(w), "chain_p": w["chain_p"]}
                                  for w in chain]
        return [w["id"] for w in chain]
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
            if w.get("device") == t["device"] and abs((P(w["ts"]) - ts).total_seconds()) <= EPISODE_GAP_H * 3600                     and P(w["ts"]) <= ep.opened_at and w["id"] not in {c["id"] for c in chain}:
                chain.append(w)
    if facts.get("ring_size") and t.get("device"):
        for x in (ep.device or {}).get("txns", []):
            if x["card_id"] == facts["card_id"] and P(x["ts"]) <= ep.opened_at and x["id"] not in {c["id"] for c in chain}:
                chain.append(x)
    return sorted({c["id"] for c in chain}, key=lambda i: next((c["ts"] for c in chain if c["id"] == i), ""))
