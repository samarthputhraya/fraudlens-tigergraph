"""Export graph-ready CSVs from the prepared DuckDB tables (run graph/prep.py first).

One CSV per loading job file. Transactions carry their own edges (MADE, BILLED_IN,
PURCHASER_EMAIL, RECIPIENT_EMAIL) so the largest file is uploaded only once.
"""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
PREP = ROOT / "data" / "prep"
OUT = PREP / "load"
OUT.mkdir(parents=True, exist_ok=True)


def num(col: str) -> str:
    return f"coalesce(try_cast({col} AS DOUBLE), -1)"


def copy(con: duckdb.DuckDBPyConnection, name: str, sql: str) -> None:
    path = (OUT / f"{name}.csv").as_posix()
    con.execute(f"COPY ({sql}) TO '{path}' (HEADER, DELIMITER ',', QUOTE '\"')")
    n = con.execute(f"SELECT count(*) FROM ({sql})").fetchone()[0]
    size = (OUT / f"{name}.csv").stat().st_size / 1e6
    print(f"{name:16s} {n:>9,} rows  {size:8.1f} MB")


def main() -> None:
    con = duckdb.connect(str(PREP / "hhgoa.duckdb"))

    copy(con, "customers", "SELECT DISTINCT customer_id FROM txn ORDER BY 1")

    copy(con, "cards", """
        SELECT card_id, any_value(customer_id) AS customer_id,
               coalesce(any_value(card4),'') AS network, coalesce(any_value(card6),'') AS card_type,
               any_value(card1) AS issuer, count(*) AS n_txn,
               strftime(min(ts_dt), '%Y-%m-%d %H:%M:%S') AS first_ts,
               strftime(max(ts_dt), '%Y-%m-%d %H:%M:%S') AS last_ts
        FROM txn GROUP BY card_id ORDER BY card_id
    """)

    # Resolved account (IEEE-CIS "uid"): card + billing region + account-open day = floor(dt/86400) - D1.
    con.execute("""
        CREATE OR REPLACE TABLE txn_acct AS
        SELECT TransactionID, card_id, addr1, ts_dt,
               CASE WHEN try_cast(D1 AS DOUBLE) IS NULL THEN NULL
                    ELSE CAST(floor(CAST(TransactionDT AS DOUBLE) / 86400) - CAST(D1 AS DOUBLE) AS BIGINT) END AS open_day
        FROM txn
    """)
    con.execute("""
        CREATE OR REPLACE TABLE txn_acct AS
        SELECT *, CASE WHEN open_day IS NULL THEN NULL
                       ELSE card_id || '|' || coalesce(addr1, '') || '|' || CAST(open_day AS VARCHAR) END AS account_id
        FROM txn_acct
    """)
    copy(con, "accounts", """
        SELECT account_id AS id, any_value(card_id) AS card_id, coalesce(any_value(addr1),'') AS addr1,
               any_value(open_day) AS open_day, count(*) AS n_txn,
               strftime(min(ts_dt), '%Y-%m-%d %H:%M:%S') AS first_ts, strftime(max(ts_dt), '%Y-%m-%d %H:%M:%S') AS last_ts
        FROM txn_acct WHERE account_id IS NOT NULL GROUP BY account_id
    """)
    copy(con, "account_edges", """
        SELECT TransactionID AS txn_id, account_id FROM txn_acct WHERE account_id IS NOT NULL
    """)

    copy(con, "transactions", f"""
        SELECT TransactionID AS id, card_id, customer_id,
               strftime(ts_dt, '%Y-%m-%d %H:%M:%S') AS ts, TransactionDT AS dt, amt,
               ProductCD AS product, channel, score AS risk_score,
               coalesce(addr1,'') AS addr1, coalesce(addr2,'') AS addr2,
               {num('dist1')} AS dist1, {num('dist2')} AS dist2,
               coalesce(P_emaildomain,'') AS p_email, coalesce(R_emaildomain,'') AS r_email,
               coalesce(M1,'')||coalesce(M2,'')||coalesce(M3,'') AS m123,
               coalesce(M4,'') AS m4, coalesce(M5,'') AS m5, coalesce(M6,'') AS m6,
               coalesce(M7,'')||coalesce(M8,'')||coalesce(M9,'') AS m789,
               {num('C1')} AS c1, {num('C2')} AS c2, {num('C5')} AS c5, {num('C6')} AS c6,
               {num('C9')} AS c9, {num('C11')} AS c11, {num('C13')} AS c13, {num('C14')} AS c14,
               {num('D1')} AS d1, {num('D2')} AS d2, {num('D3')} AS d3, {num('D4')} AS d4,
               {num('D10')} AS d10, {num('D15')} AS d15,
               {num('V258')} AS v258, {num('V257')} AS v257, {num('V294')} AS v294,
               {num('V283')} AS v283, {num('V317')} AS v317, {num('V307')} AS v307,
               {num('V127')} AS v127, {num('V133')} AS v133, {num('V70')} AS v70, {num('V91')} AS v91
        FROM txn ORDER BY ts_dt
    """)

    # Chronological NEXT chain within each card.
    copy(con, "next_edges", """
        SELECT TransactionID AS src, nxt AS dst, gap_s FROM (
            SELECT TransactionID,
                   lead(TransactionID) OVER w AS nxt,
                   CAST(date_diff('second', ts_dt, lead(ts_dt) OVER w) AS BIGINT) AS gap_s
            FROM txn WINDOW w AS (PARTITION BY card_id ORDER BY ts_dt, TransactionID)
        ) WHERE nxt IS NOT NULL
    """)

    copy(con, "devices", """
        SELECT device_profile AS id,
               coalesce(any_value(DeviceInfo),'') AS device_info, coalesce(any_value(id_30),'') AS os,
               coalesce(any_value(id_31),'') AS browser, coalesce(any_value(id_33),'') AS screen,
               coalesce(any_value(DeviceType),'') AS device_type,
               count(*) AS n_txn,
               ((CASE WHEN any_value(DeviceInfo) IS NULL THEN 1 ELSE 0 END) +
                (CASE WHEN any_value(id_30) IS NULL THEN 1 ELSE 0 END) +
                (CASE WHEN any_value(id_33) IS NULL THEN 1 ELSE 0 END)) >= 2 AS generic
        FROM ident GROUP BY device_profile
    """)

    copy(con, "device_edges", f"""
        SELECT i.TransactionID AS txn_id, i.device_profile AS device_id,
               coalesce(i.id_15,'') AS is_new, coalesce(i.id_23,'') AS proxy,
               coalesce(i.id_34,'') AS id_34, coalesce(i.DeviceType,'') AS device_type,
               {num('i.id_01')} AS id_01, {num('i.id_02')} AS id_02, {num('i.id_05')} AS id_05,
               {num('i.id_06')} AS id_06, {num('i.id_11')} AS id_11
        FROM ident i JOIN txn t ON t.TransactionID = i.TransactionID
    """)

    # Card-level projections for graph algorithms (WCC / Louvain) and fast neighbourhood lookups.
    copy(con, "card_device", """
        SELECT t.card_id, i.device_profile AS device_id, count(*) AS n,
               sum(CASE WHEN i.id_15 = 'New' THEN 1 ELSE 0 END) AS n_new,
               strftime(min(t.ts_dt), '%Y-%m-%d %H:%M:%S') AS first_ts,
               strftime(max(t.ts_dt), '%Y-%m-%d %H:%M:%S') AS last_ts
        FROM ident i JOIN txn t ON t.TransactionID = i.TransactionID
        GROUP BY t.card_id, i.device_profile
    """)
    copy(con, "card_region", """
        SELECT card_id, addr1 AS region_id, count(*) AS n,
               strftime(min(ts_dt), '%Y-%m-%d %H:%M:%S') AS first_ts,
               strftime(max(ts_dt), '%Y-%m-%d %H:%M:%S') AS last_ts
        FROM txn WHERE addr1 IS NOT NULL GROUP BY card_id, addr1
    """)

    copy(con, "closed_cases", """
        SELECT case_id, customer_id, card_id, opened_at, closed_at, outcome, pattern,
               coalesce(first_fraud_txn_id,'') AS first_fraud_txn_id, n_txns, exposure_usd,
               coalesce(actions_taken,'') AS actions_taken, report_filed = 'Yes' AS report_filed,
               replace(replace(analyst_notes, chr(10), ' '), '"', '''') AS analyst_notes,
               coalesce(txn_ids,'') AS txn_ids, coalesce(connected_card_ids,'') AS connected_card_ids
        FROM closed
    """)
    copy(con, "closed_involves", """
        SELECT case_id, tid AS txn_id FROM (
            SELECT case_id, unnest(string_split(txn_ids, '|')) AS tid FROM closed) WHERE tid <> ''
    """)
    copy(con, "closed_connected", """
        SELECT case_id, cid AS card_id FROM (
            SELECT case_id, unnest(string_split(connected_card_ids, '|')) AS cid FROM closed
            WHERE connected_card_ids IS NOT NULL) WHERE cid <> ''
    """)
    con.close()


if __name__ == "__main__":
    main()
