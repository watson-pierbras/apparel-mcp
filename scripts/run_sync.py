#!/usr/bin/env python3
"""Run sync job for one or both suppliers.

Usage:
    python scripts/run_sync.py                          # Sync all suppliers (full)
    python scripts/run_sync.py --supplier sanmar        # SanMar only
    python scripts/run_sync.py --supplier ssactivewear  # S&S only
    python scripts/run_sync.py --type inventory_only    # Inventory refresh only
"""

import argparse
import asyncio
import logging
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv()

from src.db import init_db_sync, get_db_path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run_sanmar_sync(sync_type: str):
    """Run SanMar sync."""
    from src.sanmar.sync import SanMarSync
    syncer = SanMarSync()
    result = await syncer.sync_all_active(sync_type)
    print(f"\nSanMar sync {result.status}:")
    print(f"  Styles synced: {result.styles_synced}")
    print(f"  SKUs updated:  {result.skus_updated}")
    print(f"  Price changes: {result.price_changes}")
    print(f"  Errors:        {result.errors}")
    if result.error_details:
        for err in result.error_details:
            print(f"    - {err}")


async def run_ss_sync(sync_type: str):
    """Run S&S Activewear sync."""
    from src.ssactivewear.sync import SSSync
    syncer = SSSync()
    result = await syncer.sync_all_active(sync_type)
    print(f"\nS&S sync {result.status}:")
    print(f"  Styles synced: {result.styles_synced}")
    print(f"  SKUs updated:  {result.skus_updated}")
    print(f"  Price changes: {result.price_changes}")
    print(f"  Errors:        {result.errors}")
    if result.error_details:
        for err in result.error_details:
            print(f"    - {err}")


async def main_async(supplier: str, sync_type: str):
    """Run sync for specified supplier(s)."""
    init_db_sync()  # Ensure DB exists

    if supplier in ("sanmar", "all"):
        await run_sanmar_sync(sync_type)
    if supplier in ("ssactivewear", "all"):
        await run_ss_sync(sync_type)


def main():
    parser = argparse.ArgumentParser(description="Run supplier data sync")
    parser.add_argument("--supplier", choices=["sanmar", "ssactivewear", "all"],
                        default="all", help="Which supplier to sync")
    parser.add_argument("--type", choices=["full", "incremental", "inventory_only"],
                        default="full", help="Sync type")
    args = parser.parse_args()

    asyncio.run(main_async(args.supplier, args.type))


if __name__ == "__main__":
    main()
