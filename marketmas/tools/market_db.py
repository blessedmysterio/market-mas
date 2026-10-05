"""Инструмент: справочная БД рыночных параметров (SQLite, строится из data/market_benchmarks.csv)."""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from .base import ToolError

_FIELDS_FLOAT = ["social_weight", "price_sensitivity", "churn_rate", "cpm_kzt", "seed_cost_kzt", "segment_size", "arpu_kzt"]


def build_db(csv_path: Path, db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute("DROP TABLE IF EXISTS market")
        conn.execute(
            "CREATE TABLE market (industry TEXT PRIMARY KEY, brands TEXT, base_shares TEXT, quality TEXT, price_index TEXT,"
            " social_weight REAL, price_sensitivity REAL, churn_rate REAL, cpm_kzt REAL, seed_cost_kzt REAL,"
            " segment_size REAL, arpu_kzt REAL, note TEXT)"
        )
        with open(csv_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                conn.execute("INSERT INTO market VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", tuple(row.values()))
    conn.close()


def market_lookup(db_path: Path, csv_path: Path, industry: str) -> dict:
    if not db_path.exists() or db_path.stat().st_mtime < csv_path.stat().st_mtime:
        build_db(csv_path, db_path)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("SELECT * FROM market WHERE industry=?", (industry.lower().strip(),))
        row = cur.fetchone()
        found = row is not None
        if not found:
            row = conn.execute("SELECT * FROM market WHERE industry='default'").fetchone()
        if row is None:
            raise ToolError("Справочник рынка пуст", retryable=False)
        cols = [d[0] for d in cur.description] if found else [d[0] for d in conn.execute("SELECT * FROM market LIMIT 1").description]
    finally:
        conn.close()
    rec = dict(zip(cols, row))
    out = {
        "industry": rec["industry"],
        "found": found,
        "brands": rec["brands"].split("|"),
        "base_shares": [float(x) for x in rec["base_shares"].split("|")],
        "quality": [float(x) for x in rec["quality"].split("|")],
        "price": [float(x) for x in rec["price_index"].split("|")],
        "note": rec["note"],
    }
    for k in _FIELDS_FLOAT:
        out[k] = float(rec[k])
    return out
