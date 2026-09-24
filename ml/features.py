"""Feature table for the transaction model, with no look-ahead.

Every feature on a transaction uses only what the bank knew when that transaction happened:
- the row itself (amount, product, card, billing region, e-mail domains, the unnamed Vesta C/D/M/V columns and the
  identity record), labelled honestly as unnamed signals;
- running aggregates over *earlier* transactions only (same resolved account, same card, same device profile, ...);
- graph memory: confirmed-fraud / cleared closed cases on the same resolved account and card that were already
  closed before this transaction (Account -> Transaction -> ClosedCase in TigerGraph).

The resolved account is the same entity the graph uses: card_id + billing region + account-open day (ts day - D1).
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PREP = ROOT / "data" / "prep"


def _cache_raw(con: duckdb.DuckDBPyConnection) -> None:
    PREP.mkdir(parents=True, exist_ok=True)
    for name, src in (("raw_txn.parquet", "transactions.csv"), ("raw_ident.parquet", "identity.csv")):
        out = PREP / name
        if not out.exists():
            con.execute(f"copy (select * from read_csv_auto('{(RAW / src).as_posix()}', sample_size=-1)) "
                        f"to '{out.as_posix()}' (format parquet)")


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false")
    _cache_raw(con)
    con.execute(f"create or replace view t as select * from read_parquet('{(PREP / 'raw_txn.parquet').as_posix()}')")
    con.execute(f"create or replace view i as select * from read_parquet('{(PREP / 'raw_ident.parquet').as_posix()}')")
    con.execute(f"attach '{(PREP / 'hhgoa.duckdb').as_posix()}' as p (read_only)")
    return con


def _closed_case_rows(con: duckdb.DuckDBPyConnection) -> None:
    closed = pd.read_csv(RAW / "closed_cases_history.csv")
    rows = []
    for _, r in closed.iterrows():
        for x in str(r.txn_ids).split("|"):
            if x and x != "nan":
                rows.append((int(x), r.outcome, r.closed_at, r.case_id))
    cx = pd.DataFrame(rows, columns=["TransactionID", "outcome", "closed_at", "case_id"])
    cx["closed_at"] = pd.to_datetime(cx.closed_at)
    con.register("cx", cx)


RUN_KEYS = ["P_emaildomain", "R_emaildomain", "dist1", "D15", "C13", "V258", "V307", "V294", "DeviceInfo", "id_31"]
FREQ_KEYS = ["card1", "addr1", "P_emaildomain", "R_emaildomain", "DeviceInfo", "id_30", "id_31", "id_33", "device_profile"]


def build(con: duckdb.DuckDBPyConnection | None = None) -> pd.DataFrame:
    """Returns one row per transaction: raw columns + causal aggregates + graph-memory features + label."""
    con = con or connect()
    _closed_case_rows(con)
    con.execute("""
        create or replace temp table base as
        select t.*, i.* exclude (TransactionID), a.card_id, a.account_id,
               cast(t.ts as timestamp) as tts,
               coalesce(i.DeviceInfo,'') || ' | ' || coalesce(i.id_30,'') || ' | ' || coalesce(i.id_31,'') || ' | ' ||
                 coalesce(i.id_33,'') as device_profile
        from t left join i using (TransactionID) join p.txn_acct a using (TransactionID)
    """)
    # running (strictly earlier) aggregates, computed on a narrow key table and joined back (wide sorts are slow)
    keys = ", ".join(sorted(set(RUN_KEYS) | set(FREQ_KEYS)))
    con.execute(f"create or replace temp table nk as select TransactionID, TransactionDT, TransactionAmt, account_id, card_id, {keys} from base")
    firsts = ", ".join(
        f"(row_number() over (partition by account_id, {k} order by TransactionDT, TransactionID) = 1)::int as f_{k}"
        for k in RUN_KEYS)
    con.execute(f"create or replace temp table nk2 as select *, {firsts} from nk")
    prev = "partition by account_id order by TransactionDT, TransactionID rows between unbounded preceding and 1 preceding"
    nus = ", ".join(f"coalesce(sum(f_{k}) over w, 0) as acct_nu_{k}" for k in RUN_KEYS)
    freqs = ", ".join(
        f"count(*) over (partition by {k} order by TransactionDT, TransactionID rows between unbounded preceding and 1 preceding) as fq_{k}"
        for k in FREQ_KEYS)
    con.execute(f"""
        create or replace temp table agg as
        select TransactionID,
          count(*) over w as acct_n_prev,
          avg(TransactionAmt) over w as acct_amt_mean_prev,
          stddev(TransactionAmt) over w as acct_amt_std_prev,
          max(TransactionAmt) over w as acct_amt_max_prev,
          TransactionDT - max(TransactionDT) over w as acct_secs_since_prev,
          {nus},
          count(*) over (partition by card_id order by TransactionDT, TransactionID rows between unbounded preceding and 1 preceding) as card_n_prev,
          TransactionDT - max(TransactionDT) over (partition by card_id order by TransactionDT, TransactionID rows between unbounded preceding and 1 preceding) as card_secs_since_prev,
          {freqs}
        from nk2
        window w as ({prev})
    """)
    con.execute("create or replace temp table feats as select b.*, a.* exclude (TransactionID) from base b join agg a using (TransactionID)")
    # graph memory: closed cases on the same account / card already closed before this transaction
    con.execute("""
        create or replace temp table ca as
        select a.account_id, a.card_id, t.ts::timestamp fts, cx.closed_at, cx.outcome
        from cx join p.txn_acct a using (TransactionID) join t using (TransactionID)
    """)
    con.execute("""
        create or replace temp table mem as
        with acc as (
          select f.TransactionID,
            count(*) filter (where ca.outcome='confirmed_fraud') acct_prior_fraud,
            count(*) filter (where ca.outcome='cleared') acct_prior_cleared,
            min(date_diff('day', ca.fts, f.tts)) filter (where ca.outcome='confirmed_fraud') acct_days_since_fraud
          from feats f join ca on ca.account_id = f.account_id and ca.closed_at < f.tts group by 1),
        crd as (
          select f.TransactionID,
            count(*) filter (where ca.outcome='confirmed_fraud') card_prior_fraud,
            count(*) filter (where ca.outcome='cleared') card_prior_cleared,
            min(date_diff('day', ca.fts, f.tts)) filter (where ca.outcome='confirmed_fraud') card_days_since_fraud
          from feats f join ca on ca.card_id = f.card_id and ca.closed_at < f.tts group by 1)
        select coalesce(acc.TransactionID, crd.TransactionID) TransactionID, acc.* exclude (TransactionID), crd.* exclude (TransactionID)
        from acc full outer join crd using (TransactionID)
    """)
    df = con.execute("""
        select f.* exclude (tts), month(f.tts) as month, hour(f.tts) as hour, dayofweek(f.tts) as dow,
               m.* exclude (TransactionID),
               (f.TransactionID in (select TransactionID from cx where outcome='confirmed_fraud'))::int as y,
               (f.TransactionID in (select TransactionID from cx where outcome='cleared'))::int as cleared
        from feats f left join mem m using (TransactionID)
    """).df()
    for c in ("acct_prior_fraud", "acct_prior_cleared", "card_prior_fraud", "card_prior_cleared"):
        df[c] = df[c].fillna(0)
    df["amt_rel_acct_mean"] = df.TransactionAmt / df.acct_amt_mean_prev
    df["amt_rel_acct_max"] = df.TransactionAmt / df.acct_amt_max_prev
    df["cents"] = (df.TransactionAmt - df.TransactionAmt.astype(int)).round(2)
    return df


# identifiers, timestamps, labels and look-up keys are never model inputs
NON_FEATURES = {"TransactionID", "TransactionDT", "ts", "y", "cleared", "month", "card_id", "account_id", "customer_id",
                "card1", "device_profile"}


def encode(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    for c in df.columns:
        if c in NON_FEATURES:
            continue
        if not pd.api.types.is_numeric_dtype(df[c]):
            df[c] = df[c].astype("category").cat.codes.astype("int32")
    feats = [c for c in df.columns if c not in NON_FEATURES]
    return df, feats
