"""Prepare slim, graph-ready tables from the raw HHGoa IEEE-CIS files.

Derives `card_id` (customer_id + "-K" + rank of the sorted distinct
(card4, card6) pair within the customer, i.e. network + credit/debit) and the device
profile id (DeviceInfo | id_30 | id_31 | id_33), then validates the card_id
rule against every transaction referenced by the closed cases.
"""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PREP = ROOT / "data" / "prep"
PREP.mkdir(parents=True, exist_ok=True)

# Unnamed Vesta features kept as weak signals (documented as unnamed in evidence).
KEEP_C = [f"C{i}" for i in (1, 2, 5, 6, 9, 11, 13, 14)]
KEEP_D = [f"D{i}" for i in (1, 2, 3, 4, 10, 15)]
KEEP_M = [f"M{i}" for i in range(1, 10)]
KEEP_V = ["V258", "V257", "V294", "V283", "V317", "V307", "V127", "V133", "V70", "V91"]


def main() -> None:
    con = duckdb.connect(str(PREP / "hhgoa.duckdb"))
    con.execute("PRAGMA threads=16")

    cols = ", ".join(KEEP_C + KEEP_D + KEEP_M + KEEP_V)
    con.execute(f"""
        CREATE OR REPLACE TABLE txn_raw AS
        SELECT TransactionID, TransactionDT, TransactionAmt, ProductCD,
               card1, card2, card3, card4, card5, card6, addr1, addr2, dist1, dist2,
               P_emaildomain, R_emaildomain, {cols},
               customer_id, ts, channel, risk_score
        FROM read_csv('{(RAW / "transactions.csv").as_posix()}', all_varchar=true, header=true)
    """)

    # card_id: rank of the distinct (card4, card6) pair within the customer, '' sorts first.
    # Matches 100% of closed-case transactions and all 20 case-pack cards.
    con.execute("""
        CREATE OR REPLACE TABLE card_combo AS
        WITH combos AS (
            SELECT DISTINCT customer_id, coalesce(card4,'') AS c4, coalesce(card6,'') AS c6
            FROM txn_raw
        )
        SELECT *, customer_id || '-K' ||
               CAST(row_number() OVER (PARTITION BY customer_id ORDER BY c4 || chr(31) || c6) AS VARCHAR) AS card_id
        FROM combos
    """)

    con.execute("""
        CREATE OR REPLACE TABLE txn AS
        SELECT t.*, c.card_id,
               CAST(t.TransactionAmt AS DOUBLE) AS amt,
               CAST(t.ts AS TIMESTAMP) AS ts_dt,
               CAST(t.risk_score AS DOUBLE) AS score
        FROM txn_raw t
        JOIN card_combo c
          ON t.customer_id = c.customer_id
         AND coalesce(t.card4,'') = c.c4 AND coalesce(t.card6,'') = c.c6
    """)
    con.execute("DROP TABLE txn_raw")

    con.execute(f"""
        CREATE OR REPLACE TABLE ident AS
        SELECT TransactionID, DeviceType, DeviceInfo, id_01, id_02, id_05, id_06, id_11,
               id_12, id_15, id_16, id_23, id_28, id_29, id_30, id_31, id_33, id_34, id_35, id_38,
               coalesce(DeviceInfo,'') || ' | ' || coalesce(id_30,'') || ' | ' ||
               coalesce(id_31,'') || ' | ' || coalesce(id_33,'') AS device_profile
        FROM read_csv('{(RAW / "identity.csv").as_posix()}', all_varchar=true, header=true)
    """)

    con.execute(f"""
        CREATE OR REPLACE TABLE closed AS
        SELECT * FROM read_csv('{(RAW / "closed_cases_history.csv").as_posix()}', all_varchar=true, header=true)
    """)
    con.execute(f"""
        CREATE OR REPLACE TABLE case_pack AS
        SELECT * FROM read_csv('{(RAW / "case_pack.csv").as_posix()}', all_varchar=true, header=true)
    """)

    # Validate the card_id rule against every closed-case transaction.
    res = con.execute("""
        WITH ct AS (
            SELECT case_id, card_id AS case_card, unnest(string_split(txn_ids, '|')) AS tid
            FROM closed
        )
        SELECT count(*) AS n,
               sum(CASE WHEN t.card_id = ct.case_card THEN 1 ELSE 0 END) AS ok,
               sum(CASE WHEN t.card_id IS NULL THEN 1 ELSE 0 END) AS missing
        FROM ct LEFT JOIN txn t ON t.TransactionID = ct.tid
        WHERE ct.tid <> ''
    """).fetchone()
    print(f"closed-case txns: {res[0]}  card_id match: {res[1]}  missing txn: {res[2]}")
    bad = con.execute("""
        WITH ct AS (
            SELECT case_id, card_id AS case_card, unnest(string_split(txn_ids, '|')) AS tid FROM closed
        )
        SELECT ct.case_id, ct.case_card, t.card_id, ct.tid FROM ct JOIN txn t ON t.TransactionID = ct.tid
        WHERE t.card_id <> ct.case_card LIMIT 10
    """).fetchall()
    for row in bad:
        print("  MISMATCH", row)

    pack = con.execute("""
        SELECT p.case_id, p.card_id, t.card_id FROM case_pack p JOIN txn t ON t.TransactionID = p.flagged_txn_id
    """).fetchall()
    print("case-pack card_id match:", sum(1 for r in pack if r[1] == r[2]), "/", len(pack))

    conn_cards = con.execute("""
        SELECT count(*), sum(CASE WHEN c.card_id IS NULL THEN 1 ELSE 0 END)
        FROM (SELECT unnest(string_split(connected_card_ids, '|')) AS cid FROM closed WHERE connected_card_ids <> '') x
        LEFT JOIN card_combo c ON c.card_id = x.cid
    """).fetchone()
    print(f"connected_card_ids referenced: {conn_cards[0]}  unknown: {conn_cards[1]}")

    print(con.execute("SELECT count(*), count(DISTINCT card_id), count(DISTINCT customer_id), min(ts_dt), max(ts_dt) FROM txn").fetchone())
    print(con.execute("SELECT count(*), count(DISTINCT device_profile) FROM ident").fetchone())
    con.close()


if __name__ == "__main__":
    main()
