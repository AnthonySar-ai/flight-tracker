"""
store_data.py
Saves to data/flights.csv and data/flights.db
Duplicate rows (same checked_at + depart_date + airlines + price) are ignored.
"""

import csv
import sqlite3
from pathlib import Path

DATA_DIR = Path("data")
CSV_PATH = DATA_DIR / "flights.csv"
DB_PATH  = DATA_DIR / "flights.db"

COLUMNS = [
    "checked_at",
    "season",
    "depart_date",
    "return_date",
    "price_eur",
    "airlines",
    "out_stops",
    "out_dep_time",
    "out_arr_time",
    "out_duration",
    "ret_stops",
    "ret_dep_time",
    "ret_arr_time",
    "ret_duration",
]


def _db_connect():
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS flights (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            checked_at   TEXT,
            season       TEXT,
            depart_date  TEXT,
            return_date  TEXT,
            price_eur    REAL,
            airlines     TEXT,
            out_stops    TEXT,
            out_dep_time TEXT,
            out_arr_time TEXT,
            out_duration TEXT,
            ret_stops    TEXT,
            ret_dep_time TEXT,
            ret_arr_time TEXT,
            ret_duration TEXT,
            UNIQUE(checked_at, depart_date, airlines, price_eur)
        )
    """)
    conn.commit()
    return conn


def _save_sqlite(records):
    conn = _db_connect()
    inserted = 0
    for r in records:
        try:
            conn.execute(
                f"INSERT OR IGNORE INTO flights ({', '.join(COLUMNS)}) "
                f"VALUES ({', '.join(['?'] * len(COLUMNS))})",
                [r.get(c, "") for c in COLUMNS]
            )
            inserted += conn.execute("SELECT changes()").fetchone()[0]
        except sqlite3.Error as e:
            print(f"  SQLite error: {e}")
    conn.commit()
    conn.close()
    print(f"  SQLite: {inserted} new rows → {DB_PATH}")


def _save_csv(records):
    DATA_DIR.mkdir(exist_ok=True)
    write_header = not CSV_PATH.exists()
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(records)
    print(f"  CSV: {len(records)} rows appended → {CSV_PATH}")


def save_flights(records):
    if not records:
        print("  No records to save.")
        return
    _save_csv(records)
    _save_sqlite(records)
