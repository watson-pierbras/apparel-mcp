#!/usr/bin/env python3
"""CLI to add tracked styles to the database.

Usage:
    python scripts/add_styles.py sanmar PC61 --brand "Port & Co"
    python scripts/add_styles.py ssactivewear "Gildan 5000" --brand "Gildan" --category "T-Shirts"
    python scripts/add_styles.py sanmar PC61,K420,ST350 --brand "Port & Co"  # comma-separated batch
"""

import argparse
import os
import sys
import sqlite3

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv()

from src.db import init_db_sync, get_db_path


def main():
    parser = argparse.ArgumentParser(description="Add styles to track")
    parser.add_argument("supplier", choices=["sanmar", "ssactivewear"],
                        help="Supplier name")
    parser.add_argument("styles", help="Style number(s), comma-separated for batch")
    parser.add_argument("--brand", default="", help="Brand name")
    parser.add_argument("--category", default="", help="Category")
    args = parser.parse_args()

    db_path = get_db_path()
    init_db_sync(db_path)  # Ensure DB exists

    conn = sqlite3.connect(db_path)
    styles = [s.strip() for s in args.styles.split(",")]
    
    added = 0
    skipped = 0
    for style in styles:
        if not style:
            continue
        try:
            conn.execute(
                "INSERT INTO tracked_styles (supplier, style, brand, category) VALUES (?, ?, ?, ?)",
                (args.supplier, style, args.brand or None, args.category or None),
            )
            print(f"  Added: {args.supplier}/{style}")
            added += 1
        except sqlite3.IntegrityError:
            print(f"  Skipped (already tracked): {args.supplier}/{style}")
            skipped += 1

    conn.commit()
    conn.close()
    print(f"\nDone. Added {added}, skipped {skipped}.")
    if added > 0:
        print(f"Run sync: python scripts/run_sync.py --supplier {args.supplier}")


if __name__ == "__main__":
    main()
