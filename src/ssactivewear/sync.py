"""S&S Activewear sync job: pulls data from REST API and writes to SQLite."""

import json
import logging
from datetime import datetime, timezone

import aiosqlite

from src.db import get_db
from src.models import Product, InventoryLevel, SyncResult
from src.ssactivewear.client import SSClient, SSActivewearAPIError
from src.ssactivewear.mapper import map_products_response, map_inventory_from_products

logger = logging.getLogger(__name__)


class SSSync:
    """Orchestrates syncing S&S Activewear data to the local SQLite database."""

    def __init__(self, client: SSClient | None = None, db_path: str | None = None):
        self.client = client or SSClient()
        self.db_path = db_path

    async def sync_all_active(self, sync_type: str = "full") -> SyncResult:
        """Sync all active tracked S&S Activewear styles."""
        result = SyncResult(
            supplier="ssactivewear",
            sync_type=sync_type,
            started_at=datetime.now(timezone.utc),
        )

        async with get_db(self.db_path) as db:
            # Start sync log
            log_id = await self._start_sync_log(db, sync_type)

            # Get active tracked styles (include style_id for optimized fetches)
            cursor = await db.execute(
                "SELECT id, style, brand, style_id FROM tracked_styles "
                "WHERE supplier = 'ssactivewear' AND is_active = 1"
            )
            styles = await cursor.fetchall()

            if not styles:
                logger.warning("No active S&S Activewear styles to sync")
                await self._complete_sync_log(db, log_id, result, "completed")
                return result

            logger.info(f"Syncing {len(styles)} active S&S Activewear styles...")

            for row in styles:
                tracked_id, style, brand = row["id"], row["style"], row["brand"]
                ss_style_id = row["style_id"]  # numeric S&S styleID (may be None)
                try:
                    await self._sync_single_style(db, tracked_id, style, sync_type, ss_style_id)
                    result.styles_synced += 1
                except SSActivewearAPIError as e:
                    result.errors += 1
                    result.error_details.append(f"{style}: {str(e)}")
                    logger.error(f"S&S API error syncing {style}: {e}")
                except Exception as e:
                    result.errors += 1
                    result.error_details.append(f"{style}: {str(e)}")
                    logger.error(f"Unexpected error syncing {style}: {e}", exc_info=True)

            # Finalize
            result.completed_at = datetime.now(timezone.utc)
            status = "failed" if result.errors == len(styles) else "completed"
            result.status = status
            await self._complete_sync_log(db, log_id, result, status)

        logger.info(
            f"S&S sync complete: {result.styles_synced} styles, "
            f"{result.skus_updated} SKUs, {result.price_changes} price changes, "
            f"{result.errors} errors"
        )
        return result

    async def sync_single_style(self, style: str) -> SyncResult:
        """Sync a single style (used when adding a new tracked style)."""
        result = SyncResult(
            supplier="ssactivewear",
            sync_type="full",
            started_at=datetime.now(timezone.utc),
        )

        async with get_db(self.db_path) as db:
            cursor = await db.execute(
                "SELECT id FROM tracked_styles WHERE supplier = 'ssactivewear' AND style = ?",
                (style,),
            )
            row = await cursor.fetchone()
            if not row:
                result.errors = 1
                result.error_details.append(f"Style {style} not found in tracked_styles")
                result.status = "failed"
                return result

            try:
                await self._sync_single_style(db, row["id"], style, "full")
                result.styles_synced = 1
                result.status = "completed"
            except Exception as e:
                result.errors = 1
                result.error_details.append(str(e))
                result.status = "failed"
                logger.error(f"Error syncing {style}: {e}", exc_info=True)

        result.completed_at = datetime.now(timezone.utc)
        return result

    async def _sync_single_style(
        self, db: aiosqlite.Connection, tracked_style_id: int, style: str,
        sync_type: str, ss_style_id: int | None = None,
    ) -> None:
        """Sync a single style: fetch from API, detect price changes, upsert."""
        now = datetime.now(timezone.utc).isoformat()

        # Prefer styleID-based fetch (most reliable) — fall back to style name
        raw_products = None
        if ss_style_id:
            logger.info(f"Fetching S&S products via styleID={ss_style_id} for {style}")
            raw_products = await self.client.get_products_by_style_id(ss_style_id)

        if not raw_products:
            logger.info(f"Falling back to name-based fetch for S&S style {style}")
            raw_products = await self.client.get_products(style)

        if not raw_products:
            logger.warning(f"No product variants returned for S&S style {style}")
            return

        # Map to normalized Product models
        products = map_products_response(raw_products)

        if not products:
            logger.warning(f"All products failed mapping for S&S style {style}")
            return

        # Fetch style-level info for title/description/category
        style_info = await self.client.get_style(style)
        title = None
        description = None
        category = None
        if style_info:
            title = style_info.get("title") or style_info.get("styleName", "")
            description = style_info.get("description", "")
            category = style_info.get("baseCategory", "")

        # Auto-discover styleID from API response if we don't have it
        discovered_style_id = None
        if not ss_style_id and raw_products:
            first_raw = raw_products[0]
            discovered_style_id = first_raw.get("styleID")

        # Update tracked_styles with brand/title/category from API
        first = products[0]
        if discovered_style_id:
            await db.execute(
                "UPDATE tracked_styles SET brand = ?, title = ?, description = ?, "
                "category = ?, style_id = ?, last_synced = ? WHERE id = ?",
                (
                    first.brand,
                    title or f"{first.brand} {first.style}",
                    description,
                    category,
                    discovered_style_id,
                    now,
                    tracked_style_id,
                ),
            )
            logger.info(f"Discovered and stored styleID={discovered_style_id} for {style}")
        else:
            await db.execute(
                "UPDATE tracked_styles SET brand = ?, title = ?, description = ?, "
                "category = ?, last_synced = ? WHERE id = ?",
                (
                    first.brand,
                    title or f"{first.brand} {first.style}",
                    description,
                    category,
                    now,
                    tracked_style_id,
                ),
            )

        for product in products:
            product.tracked_style_id = tracked_style_id
            product.last_synced = datetime.now(timezone.utc)

            # Check for price changes before upserting
            if sync_type in ("full", "incremental"):
                await self._detect_price_changes(db, product)

            # Upsert product
            await db.execute(
                """INSERT INTO products (
                    tracked_style_id, supplier, style, brand, color, catalog_color,
                    size, sku, gtin, piece_price, case_price, sale_price, sale_end_date,
                    customer_price, map_price, case_qty, price_code, price_text,
                    size_price_code, weight, product_status, country_of_origin,
                    front_image_url, back_image_url, swatch_image_url, spec_sheet_url,
                    noe_retailing, last_synced
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(supplier, style, color, size) DO UPDATE SET
                    tracked_style_id = excluded.tracked_style_id,
                    brand = excluded.brand,
                    catalog_color = excluded.catalog_color,
                    sku = excluded.sku,
                    gtin = excluded.gtin,
                    piece_price = excluded.piece_price,
                    case_price = excluded.case_price,
                    sale_price = excluded.sale_price,
                    sale_end_date = excluded.sale_end_date,
                    customer_price = excluded.customer_price,
                    map_price = excluded.map_price,
                    case_qty = excluded.case_qty,
                    price_code = excluded.price_code,
                    price_text = excluded.price_text,
                    size_price_code = excluded.size_price_code,
                    weight = excluded.weight,
                    product_status = excluded.product_status,
                    country_of_origin = excluded.country_of_origin,
                    front_image_url = excluded.front_image_url,
                    back_image_url = excluded.back_image_url,
                    swatch_image_url = excluded.swatch_image_url,
                    spec_sheet_url = excluded.spec_sheet_url,
                    noe_retailing = excluded.noe_retailing,
                    last_synced = excluded.last_synced
                """,
                (
                    product.tracked_style_id, product.supplier, product.style,
                    product.brand, product.color, product.catalog_color,
                    product.size, product.sku, product.gtin,
                    product.piece_price, product.case_price, product.sale_price,
                    product.sale_end_date, product.customer_price, product.map_price,
                    product.case_qty, product.price_code, product.price_text,
                    product.size_price_code, product.weight, product.product_status,
                    product.country_of_origin, product.front_image_url,
                    product.back_image_url, product.swatch_image_url,
                    product.spec_sheet_url, product.noe_retailing, now,
                ),
            )

        # Upsert inventory levels
        inventory_levels = map_inventory_from_products(raw_products)
        for inv in inventory_levels:
            await db.execute(
                """INSERT INTO inventory (
                    supplier, style, color, size, warehouse, warehouse_name,
                    quantity, is_closeout, is_dropship, last_synced
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(supplier, style, color, size, warehouse) DO UPDATE SET
                    warehouse_name = excluded.warehouse_name,
                    quantity = excluded.quantity,
                    is_closeout = excluded.is_closeout,
                    is_dropship = excluded.is_dropship,
                    last_synced = excluded.last_synced
                """,
                (
                    inv.supplier, inv.style, inv.color, inv.size,
                    inv.warehouse, inv.warehouse_name, inv.quantity,
                    inv.is_closeout, inv.is_dropship, now,
                ),
            )

        await db.commit()
        logger.info(
            f"Synced {len(products)} variants and {len(inventory_levels)} "
            f"inventory levels for S&S style {style}"
        )

    async def _detect_price_changes(self, db: aiosqlite.Connection, product: Product) -> None:
        """Compare new prices against existing DB values and log changes."""
        cursor = await db.execute(
            "SELECT piece_price, case_price, sale_price, customer_price, map_price "
            "FROM products WHERE supplier = ? AND style = ? AND color = ? AND size = ?",
            (product.supplier, product.style, product.color, product.size),
        )
        existing = await cursor.fetchone()

        if not existing:
            return  # New product, no price history to compare

        price_fields = [
            ("piece", existing["piece_price"], product.piece_price),
            ("case", existing["case_price"], product.case_price),
            ("sale", existing["sale_price"], product.sale_price),
            ("customer", existing["customer_price"], product.customer_price),
            ("map", existing["map_price"], product.map_price),
        ]

        for price_type, old_val, new_val in price_fields:
            if new_val is not None and old_val != new_val:
                await db.execute(
                    "INSERT INTO price_history (supplier, style, color, size, price_type, old_price, new_price) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (product.supplier, product.style, product.color, product.size,
                     price_type, old_val, new_val),
                )
                logger.info(
                    f"Price change: {product.supplier}/{product.style}/{product.color}/{product.size} "
                    f"{price_type}: {old_val} → {new_val}"
                )

    async def _start_sync_log(self, db: aiosqlite.Connection, sync_type: str) -> int:
        """Create a sync log entry and return its ID."""
        cursor = await db.execute(
            "INSERT INTO sync_log (supplier, sync_type, started_at) VALUES (?, ?, ?)",
            ("ssactivewear", sync_type, datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()
        return cursor.lastrowid

    async def _complete_sync_log(
        self, db: aiosqlite.Connection, log_id: int, result: SyncResult, status: str
    ) -> None:
        """Update the sync log with final results."""
        await db.execute(
            "UPDATE sync_log SET styles_synced = ?, skus_updated = ?, price_changes = ?, "
            "errors = ?, error_details = ?, completed_at = ?, status = ? WHERE id = ?",
            (
                result.styles_synced, result.skus_updated, result.price_changes,
                result.errors, json.dumps(result.error_details) if result.error_details else None,
                datetime.now(timezone.utc).isoformat(), status, log_id,
            ),
        )
        await db.commit()
