#!/usr/bin/env python3
"""Seed the SQLite database with all 136 CMP tracked styles and import
S&S Activewear pricing from the vendo Postgres export CSVs.

Usage:
    python scripts/seed_styles.py
    python scripts/seed_styles.py --csv-dir /path/to/csv/dir   # custom CSV location
"""

import argparse
import csv
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv()

from src.db import init_db_sync, get_db_path

# ── Master style list ─────────────────────────────────────────
# fmt: off
SS_STYLES = [
    # (style, brand)
    ("3001", "Bella+Canvas"), ("3001CVC", "Bella+Canvas"), ("3001Y", "Bella+Canvas"),
    ("3001YCVC", "Bella+Canvas"), ("3001B", "Bella+Canvas"), ("6400", "Bella+Canvas"),
    ("3501", "Bella+Canvas"), ("3501Y", "Bella+Canvas"), ("3501CVC", "Bella+Canvas"),
    ("3480", "Bella+Canvas"), ("3480C", "Bella+Canvas"), ("1533", "Bella+Canvas"),
    ("3413", "Bella+Canvas"), ("3413Y", "Bella+Canvas"), ("3413T", "Bella+Canvas"),
    ("1717", "Comfort Colors"), ("9018", "Comfort Colors"), ("6014", "Comfort Colors"),
    ("4800M", "M&O"), ("4850M", "M&O"),
    ("8668", "Alleson Athletic"), ("8967", "Alleson Athletic"), ("8662", "Alleson Athletic"),
    ("7272", "Alleson Athletic"), ("7274", "Alleson Athletic"),
    ("3SOC2A", "Alleson Athletic"), ("3SOC2Y", "Alleson Athletic"),
    ("3BBA", "Alleson Athletic"), ("3BBY", "Alleson Athletic"),
    ("N5387", "A4"), ("NB5244", "A4"), ("N5244", "A4"), ("NW5383", "A4"),
    ("5000", "Gildan"), ("5000B", "Gildan"), ("5000L", "Gildan"),
    ("5100", "C2 Sport"), ("5200", "C2 Sport"), ("5104", "C2 Sport"), ("5204", "C2 Sport"),
    ("SS4500", "Independent Trading Co"), ("SS4001Y", "Independent Trading Co"),
    ("SS3000", "Independent Trading Co"), ("IND20PNT", "Independent Trading Co"),
    ("EXP54LWZ", "Independent Trading Co"),
    ("996MR", "Jerzees"), ("975MPR", "Jerzees"), ("562", "Jerzees"),
    ("112", "Richardson"),
    ("SP15", None), ("1501KC", None), ("GB400", None), ("GB210", None),
    ("6577CD", None), ("GB997", None),
    ("A230", "Adidas"), ("A401", "Adidas"),
    ("CE106", None), ("SHMHSST", None), ("222830", None), ("108085", None),
]

SANMAR_STYLES = [
    ("PC90", "Port & Co"), ("PC90Y", "Port & Co"), ("PC90H", "Port & Co"),
    ("LPC78H", "Port & Co"), ("PC90YH", "Port & Co"), ("PC78J", "Port & Co"),
    ("PC78YJ", "Port & Co"), ("PC78", "Port & Co"), ("PC78H", "Port & Co"),
    ("PC78SP", "Port & Co"),
    ("ST446", "Sport-Tek"), ("LST446", "Sport-Tek"), ("YST446", "Sport-Tek"),
    ("ST447", "Sport-Tek"), ("LST447", "Sport-Tek"),
    ("ST356", "Sport-Tek"), ("LST356", "Sport-Tek"),
    ("ST551", "Sport-Tek"), ("YST551", "Sport-Tek"),
    ("ST550", "Sport-Tek"), ("LST550", "Sport-Tek"),
    ("ST650", "Sport-Tek"), ("LST650", "Sport-Tek"),
    ("ST104", "Sport-Tek"), ("LST104", "Sport-Tek"), ("ST741", "Sport-Tek"),
    ("ST350", "Sport-Tek"),
    ("ST358", "Sport-Tek"), ("LST358", "Sport-Tek"), ("YST358", "Sport-Tek"),
    ("ST359", "Sport-Tek"),
    ("ST485", "Sport-Tek"), ("PST485", "Sport-Tek"),
    ("PST871", "Sport-Tek"), ("LPST871", "Sport-Tek"),
    ("ST870", "Sport-Tek"), ("LST870", "Sport-Tek"),
    ("ST850", "Sport-Tek"), ("LST850", "Sport-Tek"),
    ("ST251", "Sport-Tek"), ("ST255", "Sport-Tek"), ("ST267", "Sport-Tek"), ("STF205", "Sport-Tek"),
    ("ST400", "Sport-Tek"), ("ST400LS", "Sport-Tek"), ("ST6040", "Sport-Tek"),
    ("LST410", "Sport-Tek"), ("ST6044", "Sport-Tek"),
    ("LST60403", "Sport-Tek"), ("LST6041", "Sport-Tek"),
    ("JST489", "Sport-Tek"), ("YST489", "Sport-Tek"), ("JST488", "Sport-Tek"),
    ("ST100", "Sport-Tek"), ("ST101", "Sport-Tek"), ("ST100LS", "Sport-Tek"), ("STA05", "Sport-Tek"),
    ("LNEA123", "New Era"), ("LNEA108", "New Era"),
    ("NEA600", "New Era"), ("YNEA600", "New Era"), ("NEA523", "New Era"),
    ("NE902", "New Era"), ("NEB600", "New Era"),
    ("DT6000", "District"), ("DT6102", "District"), ("DT6107", "District"),
    ("STC64", "Sport-Tek"), ("STC65", "Sport-Tek"),
    ("BP78", None), ("K420", "Port Authority"), ("PC54", "Port & Co"), ("PC61", "Port & Co"),
]
# fmt: on


def _safe_float(val: str) -> float | None:
    """Convert CSV price string to float, returning None for empty/invalid."""
    if not val or val.strip() == "":
        return None
    try:
        f = float(val)
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def seed_tracked_styles(conn: sqlite3.Connection) -> tuple[int, int]:
    """Insert all tracked styles. Returns (added, skipped)."""
    added = skipped = 0

    for style, brand in SS_STYLES:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO tracked_styles (supplier, style, brand) VALUES (?, ?, ?)",
                ("ssactivewear", style, brand),
            )
            if conn.total_changes > added + skipped:
                added += 1
            else:
                skipped += 1
        except sqlite3.IntegrityError:
            skipped += 1

    for style, brand in SANMAR_STYLES:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO tracked_styles (supplier, style, brand) VALUES (?, ?, ?)",
                ("sanmar", style, brand),
            )
            if conn.total_changes > added + skipped:
                added += 1
            else:
                skipped += 1
        except sqlite3.IntegrityError:
            skipped += 1

    conn.commit()
    return added, skipped


def build_style_id_map(csv_path: str) -> dict[str, int]:
    """Build styleName → styleID mapping from ss_styles_export.csv."""
    mapping = {}
    with open(csv_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            style_name = row.get("styleName", "").strip()
            style_id = row.get("styleID", "").strip()
            if style_name and style_id:
                try:
                    mapping[style_name] = int(style_id)
                except ValueError:
                    continue
    return mapping


def import_ss_products(
    conn: sqlite3.Connection,
    products_csv: str,
    style_id_map: dict[str, int],
    tracked_ss_styles: set[str],
) -> int:
    """Import S&S product SKUs from vendo export. Returns count imported."""
    now = datetime.now(timezone.utc).isoformat()
    batch = []
    imported = 0

    # Build styleID→styleName reverse map for CSV lookup
    id_to_name: dict[int, str] = {}
    for name, sid in style_id_map.items():
        if name in tracked_ss_styles:
            id_to_name[sid] = name

    # Also build set of tracked styleIDs for fast lookup
    tracked_ids = set(id_to_name.keys())

    with open(products_csv, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Check if this product belongs to a tracked style
            csv_style_id = row.get("styleID", "").strip()
            csv_style_name = row.get("styleName", "").strip()

            # Match by styleName first (more reliable), then by styleID
            if csv_style_name in tracked_ss_styles:
                style = csv_style_name
            elif csv_style_id:
                try:
                    sid = int(csv_style_id)
                    if sid in tracked_ids:
                        style = id_to_name[sid]
                    else:
                        continue
                except ValueError:
                    continue
            else:
                continue

            color = row.get("colorName", "").strip()
            size = row.get("sizeName", "").strip()
            if not color or not size:
                continue

            batch.append((
                "ssactivewear", style, row.get("brandName", "").strip(),
                color, size,
                row.get("sku", "").strip(),
                _safe_float(row.get("piecePrice", "")),
                _safe_float(row.get("casePrice", "")),
                _safe_float(row.get("salePrice", "")),
                _safe_float(row.get("customerPrice", "")),
                now,
            ))

            if len(batch) >= 1000:
                conn.executemany(
                    """INSERT OR REPLACE INTO products
                       (supplier, style, brand, color, size, sku,
                        piece_price, case_price, sale_price, customer_price,
                        last_synced)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    batch,
                )
                imported += len(batch)
                batch = []

    if batch:
        conn.executemany(
            """INSERT OR REPLACE INTO products
               (supplier, style, brand, color, size, sku,
                piece_price, case_price, sale_price, customer_price,
                last_synced)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            batch,
        )
        imported += len(batch)

    conn.commit()
    return imported


def update_style_ids(conn: sqlite3.Connection, style_id_map: dict[str, int]) -> int:
    """Update tracked_styles.style_id for S&S styles using the vendo mapping."""
    updated = 0
    for style_name, style_id in style_id_map.items():
        cursor = conn.execute(
            "UPDATE tracked_styles SET style_id = ? "
            "WHERE supplier = 'ssactivewear' AND style = ? AND style_id IS NULL",
            (style_id, style_name),
        )
        if cursor.rowcount > 0:
            updated += 1
    conn.commit()
    return updated


def main():
    parser = argparse.ArgumentParser(description="Seed styles and import S&S pricing")
    parser.add_argument(
        "--csv-dir",
        default="/home/user/workspace",
        help="Directory containing ss_styles_export.csv and ss_products_export.csv",
    )
    args = parser.parse_args()

    db_path = get_db_path()
    print(f"Database: {db_path}")

    # Migrate existing DB first — add style_id column before init_db_sync
    # (init_db_sync creates the index which requires the column to exist)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("ALTER TABLE tracked_styles ADD COLUMN style_id INTEGER")
        conn.commit()
        print("Added style_id column to tracked_styles")
    except sqlite3.OperationalError:
        pass  # Column already exists or table doesn't exist yet
    conn.close()

    # Now ensure full schema is current (creates tables + indexes)
    init_db_sync(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")

    # ── Step 1: Seed tracked styles ──────────────────────────
    print("\n── Seeding tracked styles ──")
    added, skipped = seed_tracked_styles(conn)
    total = conn.execute("SELECT COUNT(*) FROM tracked_styles").fetchone()[0]
    ss_count = conn.execute(
        "SELECT COUNT(*) FROM tracked_styles WHERE supplier='ssactivewear'"
    ).fetchone()[0]
    sm_count = conn.execute(
        "SELECT COUNT(*) FROM tracked_styles WHERE supplier='sanmar'"
    ).fetchone()[0]
    print(f"  Total tracked styles: {total} ({ss_count} S&S + {sm_count} SanMar)")

    # ── Step 2: Build styleID mapping from vendo export ──────
    styles_csv = os.path.join(args.csv_dir, "ss_styles_export.csv")
    products_csv = os.path.join(args.csv_dir, "ss_products_export.csv")

    if not os.path.exists(styles_csv):
        print(f"\nWARNING: {styles_csv} not found — skipping S&S product import")
        conn.close()
        return

    print("\n── Building styleID mapping from vendo export ──")
    style_id_map = build_style_id_map(styles_csv)
    print(f"  Loaded {len(style_id_map)} styleName→styleID mappings")

    # Get set of tracked S&S styles for filtering
    tracked_ss = set(
        row[0]
        for row in conn.execute(
            "SELECT style FROM tracked_styles WHERE supplier='ssactivewear'"
        ).fetchall()
    )
    matched = sum(1 for s in tracked_ss if s in style_id_map)
    print(f"  Matched {matched}/{len(tracked_ss)} tracked S&S styles to vendo styleIDs")

    # ── Step 3: Update style_ids in tracked_styles ───────────
    print("\n── Updating style_ids ──")
    id_count = update_style_ids(conn, style_id_map)
    print(f"  Updated {id_count} tracked styles with styleIDs")

    # ── Step 4: Import products from vendo export ────────────
    if not os.path.exists(products_csv):
        print(f"\nWARNING: {products_csv} not found — skipping product import")
        conn.close()
        return

    print("\n── Importing S&S product pricing from vendo export ──")
    imported = import_ss_products(conn, products_csv, style_id_map, tracked_ss)
    print(f"  Imported {imported:,} product SKUs")

    # ── Summary ──────────────────────────────────────────────
    print("\n══ SEED COMPLETE ══")
    total_products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    styles_with_id = conn.execute(
        "SELECT COUNT(*) FROM tracked_styles WHERE style_id IS NOT NULL"
    ).fetchone()[0]
    print(f"  Tracked styles:    {total}")
    print(f"  S&S with styleID:  {styles_with_id}")
    print(f"  Total products:    {total_products:,}")

    # Show styles that are missing from vendo (need live API to resolve)
    missing = [s for s in tracked_ss if s not in style_id_map]
    if missing:
        print(f"\n  ⚠ {len(missing)} S&S styles not in vendo (need live API sync):")
        for s in sorted(missing):
            print(f"    - {s}")

    # Show per-style product counts
    print("\n  Top styles by SKU count:")
    for row in conn.execute(
        """SELECT style, brand, COUNT(*) as cnt
           FROM products WHERE supplier='ssactivewear'
           GROUP BY style ORDER BY cnt DESC LIMIT 10"""
    ).fetchall():
        print(f"    {row[0]:12s} {row[1] or '':20s} {row[2]:5d} SKUs")

    conn.close()


if __name__ == "__main__":
    main()
