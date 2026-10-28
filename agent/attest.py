"""Attestation: every query-backed claim cites only IDs its own query returns, so a judge who re-runs the query sees
every one of them (eval/attest_check.py does exactly that)."""
from __future__ import annotations


def ids_in(obj, out: set | None = None) -> set:
    """Every string-ish value in a query result, with packed "id|ts|amt" strings split into their parts."""
    out = set() if out is None else out
    if isinstance(obj, dict):
        for v in obj.values():
            ids_in(v, out)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            ids_in(v, out)
    elif obj is not None:
        s = str(obj)
        out.add(s)
        if "|" in s:
            out.update(p.strip() for p in s.split("|"))
    return out


def ref_results(ep) -> dict:
    """The result each query reference in this investigation returned, as held in the evidence pack."""
    r, x = ep.refs, ep.extra
    pairs = [("context", {"txn": ep.txn, "card": ep.card}), ("window", ep.window), ("profile", ep.profile),
             ("recurring", ep.recurring), ("account", ep.account), ("device", ep.device), ("region", ep.region),
             ("prior", ep.prior), ("memory", ep.memory), ("window_30d", x.get("window_30d")),
             ("typology_scan", x.get("typology_scan"))]
    out = {r[k]: v for k, v in pairs if r.get(k) and v is not None}
    for dom, st in (x.get("recipient") or {}).items():
        if r.get(f"recipient:{dom}"):
            out[r[f"recipient:{dom}"]] = st
    return out
