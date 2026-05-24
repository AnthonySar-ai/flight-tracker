"""
store_data.py — saves to CSV + SQLite, computes price_change_pct
"""

import csv
import sqlite3
from pathlib import Path

DATA_DIR        = Path("data")
CSV_PATH        = DATA_DIR / "flights.csv"
DB_PATH         = DATA_DIR / "flights.db"
NO_RESULTS_PATH = DATA_DIR / "no_results.csv"

COLUMNS = [
    "checked_at", "season", "depart_date", "return_date",
    "price_eur", "airlines",
    "out_flight_nums", "out_stops", "out_dep_time", "out_arr_time",
    "out_duration", "out_duration_fmt", "out_layover_min", "out_layover_fmt",
    "ret_airlines", "ret_flight_nums", "ret_stops", "ret_dep_time", "ret_arr_time",
    "ret_duration", "ret_duration_fmt", "ret_layover_min", "ret_layover_fmt",
    "airline_count", "price_change_pct",
]


def _db_connect():
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cols_sql = "\n".join([
        "id INTEGER PRIMARY KEY AUTOINCREMENT,",
        *[f"{c} TEXT," for c in COLUMNS[:-1]],
        f"{COLUMNS[-1]} TEXT,",
        f"UNIQUE(checked_at, depart_date, out_flight_nums, price_eur)"
    ])
    conn.execute(f"CREATE TABLE IF NOT EXISTS flights ({cols_sql})")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS no_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            checked_at TEXT, depart_date TEXT, return_date TEXT,
            UNIQUE(checked_at, depart_date)
        )
    """)
    conn.commit()
    return conn


def _get_prev_cheapest(conn, depart_date, checked_at):
    row = conn.execute(
        "SELECT MIN(CAST(price_eur AS REAL)) FROM flights WHERE depart_date=? AND checked_at<?",
        (depart_date, checked_at)
    ).fetchone()
    return row[0] if row and row[0] else None


def _compute_price_change(records, conn):
    cache = {}
    for r in records:
        key = r["depart_date"]
        if key not in cache:
            cache[key] = _get_prev_cheapest(conn, key, r["checked_at"])
        prev = cache[key]
        if prev and prev > 0:
            r["price_change_pct"] = round((r["price_eur"] - prev) / prev * 100, 1)
        else:
            r["price_change_pct"] = ""
    return records


def _save_sqlite(records):
    conn = _db_connect()
    records = _compute_price_change(records, conn)
    inserted = 0
    for r in records:
        try:
            conn.execute(
                f"INSERT OR IGNORE INTO flights ({', '.join(COLUMNS)}) "
                f"VALUES ({', '.join(['?']*len(COLUMNS))})",
                [r.get(c, "") for c in COLUMNS]
            )
            inserted += conn.execute("SELECT changes()").fetchone()[0]
        except sqlite3.Error as e:
            print(f"  SQLite error: {e}")
    conn.commit()
    conn.close()
    print(f"  SQLite: {inserted} new rows → {DB_PATH}")
    return records


def _save_csv(records):
    DATA_DIR.mkdir(exist_ok=True)
    write_header = not CSV_PATH.exists()
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(records)
    print(f"  CSV: {len(records)} rows appended → {CSV_PATH}")


def log_no_results(checked_at, depart_date, return_date):
    DATA_DIR.mkdir(exist_ok=True)
    write_header = not NO_RESULTS_PATH.exists()
    with open(NO_RESULTS_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["checked_at", "depart_date", "return_date"])
        if write_header:
            writer.writeheader()
        writer.writerow({"checked_at": checked_at, "depart_date": depart_date, "return_date": return_date})
    conn = _db_connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO no_results (checked_at,depart_date,return_date) VALUES (?,?,?)",
            (checked_at, depart_date, return_date)
        )
        conn.commit()
    except:
        pass
    conn.close()


def save_flights(records):
    if not records:
        print("  No records to save.")
        return
    records = _save_sqlite(records)
    _save_csv(records)
