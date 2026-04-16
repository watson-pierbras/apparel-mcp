"""Shared database utilities for the dashboard."""

import os
import json
import sqlite3
from pathlib import Path

import pandas as pd

# Resolve DB path the same way the MCP server does
DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "apparel.db"))
SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "settings.json")


def get_conn() -> sqlite3.Connection:
    """Get a read-only SQLite connection for dashboard queries."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_write_conn() -> sqlite3.Connection:
    """Get a writable SQLite connection for dashboard mutations."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def query_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Execute a query and return a pandas DataFrame."""
    conn = get_conn()
    try:
        df = pd.read_sql_query(sql, conn, params=params)
        return df
    finally:
        conn.close()


def execute(sql: str, params: tuple = ()) -> None:
    """Execute a write operation."""
    conn = get_write_conn()
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def load_settings() -> dict:
    """Load dashboard settings from JSON file."""
    defaults = {
        "default_supplier": "sanmar",
        "low_stock_threshold": 50,
        "alert_check_on_sync": True,
    }
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH) as f:
                return {**defaults, **json.load(f)}
        except (json.JSONDecodeError, IOError):
            pass
    return defaults


def save_settings(settings: dict) -> None:
    """Save dashboard settings to JSON file."""
    Path(SETTINGS_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)
