#!/usr/bin/env python3
"""Initialize the SQLite database with schema, indexes, and PRAGMAs."""

import os
import sys

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv()

from src.db import init_db_sync, get_db_path


def main():
    db_path = get_db_path()
    print(f"Initializing database at: {db_path}")
    init_db_sync(db_path)
    print("Database initialized successfully.")
    print(f"  - Tables: tracked_styles, products, inventory, price_history, sync_log")
    print(f"  - WAL mode enabled")
    print(f"  - Foreign keys enabled")
    print(f"\nNext steps:")
    print(f"  1. Add styles to track: python scripts/add_styles.py sanmar PC61 --brand 'Port & Co'")
    print(f"  2. Run a sync: python scripts/run_sync.py --supplier sanmar")


if __name__ == "__main__":
    main()
