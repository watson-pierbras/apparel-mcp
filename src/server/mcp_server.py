"""FastMCP server for querying apparel pricing and inventory from SQLite."""

import os
import sys
import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# Ensure all logging goes to stderr (stdout is reserved for MCP JSON-RPC)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

load_dotenv()

# Add project root to path so imports work when run as module
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.db import get_db, get_db_path
from src.shared.formatters import (
    format_currency,
    format_pricing_table,
    format_inventory_table,
    format_price_changes,
)

DB_PATH = get_db_path()

mcp = FastMCP(
    "apparel-mcp",
    instructions=(
        "Tools for querying Compound Sportswear's wholesale apparel data. "
        "Data covers SanMar and S&S Activewear catalogs — pricing, inventory, "
        "and product details. Data is cached locally and refreshed by a "
        "scheduled sync job. Use check_live_inventory only when confirming "
        "inventory before placing an actual order."
    ),
)


# ─────────────────────────────────────────────────────────────
# Tool 1: search_products
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def search_products(
    query: str = "",
    brand: str = "",
    category: str = "",
    supplier: str = "",
) -> str:
    """Search for products across both suppliers by keyword, brand, or category.

    Returns matching styles with pricing summaries. Use when someone asks
    'what Gildan tees do we carry?' or 'find me a performance polo'.

    Args:
        query: Keyword to search across style, title, brand, description
        brand: Filter by brand name (e.g. 'Gildan', 'Port & Co', 'Next Level')
        category: Filter by category (e.g. 'T-Shirts', 'Activewear', 'Fleece')
        supplier: Limit to 'sanmar' or 'ssactivewear' (omit for both)
    """
    conditions = []
    params = []

    if query:
        conditions.append(
            "(p.style LIKE ? OR p.brand LIKE ? OR ts.title LIKE ? OR ts.description LIKE ?)"
        )
        q = f"%{query}%"
        params.extend([q, q, q, q])
    if brand:
        conditions.append("p.brand LIKE ?")
        params.append(f"%{brand}%")
    if category:
        conditions.append("ts.category LIKE ?")
        params.append(f"%{category}%")
    if supplier:
        conditions.append("p.supplier = ?")
        params.append(supplier)

    where = " AND ".join(conditions) if conditions else "1=1"

    sql = f"""
        SELECT
            p.supplier, p.style, p.brand,
            ts.title, ts.category,
            MIN(p.piece_price) AS min_piece,
            MAX(p.piece_price) AS max_piece,
            MIN(p.case_price) AS min_case,
            MAX(p.case_price) AS max_case,
            MIN(p.sale_price) AS min_sale,
            COUNT(DISTINCT p.color) AS color_count,
            COUNT(DISTINCT p.size) AS size_count,
            MAX(p.last_synced) AS last_synced
        FROM products p
        LEFT JOIN tracked_styles ts ON ts.supplier = p.supplier AND ts.style = p.style
        WHERE {where}
        GROUP BY p.supplier, p.style
        ORDER BY p.brand, p.style
        LIMIT 50
    """

    async with get_db(DB_PATH) as db:
        cursor = await db.execute(sql, params)
        rows = [dict(row) for row in await cursor.fetchall()]

    if not rows:
        return "No products found matching your search."

    lines = []
    for row in rows:
        title = row["title"] or f"{row['brand']} {row['style']}"
        supplier_label = row["supplier"].upper()
        price_range = f"{format_currency(row['min_piece'])}"
        if row["min_piece"] != row["max_piece"]:
            price_range += f" - {format_currency(row['max_piece'])}"
        case_range = f"{format_currency(row['min_case'])}"
        if row["min_case"] != row["max_case"]:
            case_range += f" - {format_currency(row['max_case'])}"

        lines.append(f"**{title}** [{supplier_label}]")
        lines.append(f"  Style: {row['style']} | {row['color_count']} colors, {row['size_count']} sizes")
        lines.append(f"  Piece: {price_range} | Case: {case_range}")
        if row["min_sale"]:
            lines.append(f"  ON SALE from {format_currency(row['min_sale'])}")
        lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Tool 2: get_pricing
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_pricing(
    style: str,
    supplier: str = "",
    color: str = "",
    size: str = "",
) -> str:
    """Get all pricing tiers for a specific style.

    Returns piece, case, sale, customer, and MAP prices. Use when someone
    asks 'what's the price on PC61?' or 'how much is the Gildan 5000?'

    Args:
        style: Style number (e.g. 'PC61', '5000', 'Gildan 5000')
        supplier: Limit to 'sanmar' or 'ssactivewear' (omit for both)
        color: Filter by color name
        size: Filter by size (e.g. 'M', 'XL', '2XL')
    """
    conditions = ["p.style LIKE ?"]
    params = [f"%{style}%"]

    if supplier:
        conditions.append("p.supplier = ?")
        params.append(supplier)
    if color:
        conditions.append("p.color LIKE ?")
        params.append(f"%{color}%")
    if size:
        conditions.append("p.size = ?")
        params.append(size)

    where = " AND ".join(conditions)

    sql = f"""
        SELECT supplier, style, brand, color, size,
               piece_price, case_price, sale_price, sale_end_date,
               customer_price, map_price, case_qty, price_code,
               price_text, size_price_code, last_synced
        FROM products p
        WHERE {where}
        ORDER BY supplier, color, size
    """

    async with get_db(DB_PATH) as db:
        cursor = await db.execute(sql, params)
        rows = [dict(row) for row in await cursor.fetchall()]

    if not rows:
        return f"No pricing data found for style '{style}'. Make sure it's in your tracked styles."

    return format_pricing_table(rows)


# ─────────────────────────────────────────────────────────────
# Tool 3: check_inventory
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def check_inventory(
    style: str,
    supplier: str = "",
    color: str = "",
    size: str = "",
    warehouse: str = "",
) -> str:
    """Check cached warehouse-level inventory for a style.

    Returns quantities by warehouse. This uses cached data — for real-time
    inventory before placing an order, use check_live_inventory instead.

    Args:
        style: Style number (e.g. 'PC61', '5000')
        supplier: Limit to 'sanmar' or 'ssactivewear' (omit for both)
        color: Filter by color name
        size: Filter by size
        warehouse: Filter by warehouse code (e.g. 'JAC', 'IL')
    """
    conditions = ["i.style LIKE ?"]
    params = [f"%{style}%"]

    if supplier:
        conditions.append("i.supplier = ?")
        params.append(supplier)
    if color:
        conditions.append("i.color LIKE ?")
        params.append(f"%{color}%")
    if size:
        conditions.append("i.size = ?")
        params.append(size)
    if warehouse:
        conditions.append("i.warehouse = ?")
        params.append(warehouse.upper())

    where = " AND ".join(conditions)

    sql = f"""
        SELECT i.supplier, i.style, i.color, i.size,
               i.warehouse, i.warehouse_name, i.quantity,
               i.is_closeout, i.is_dropship, i.last_synced
        FROM inventory i
        WHERE {where}
        ORDER BY i.supplier, i.color, i.size, i.warehouse
    """

    async with get_db(DB_PATH) as db:
        cursor = await db.execute(sql, params)
        rows = [dict(row) for row in await cursor.fetchall()]

    if not rows:
        return f"No inventory data found for style '{style}'."

    # Add total summary
    total = sum(r["quantity"] for r in rows)
    header = f"**Total inventory for {style}: {total:,} units across {len(set(r['warehouse'] for r in rows))} warehouses**\n\n"

    return header + format_inventory_table(rows)


# ─────────────────────────────────────────────────────────────
# Tool 4: check_live_inventory
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def check_live_inventory(
    style: str,
    supplier: str,
    color: str = "",
    size: str = "",
) -> str:
    """Check REAL-TIME inventory directly from the supplier API.

    Use this ONLY when confirming inventory before placing an actual purchase
    order. For browsing and research, use check_inventory (cached) instead.

    Args:
        style: Style number (e.g. 'PC61', '5000')
        supplier: Required — 'sanmar' or 'ssactivewear'
        color: Color name (recommended for SanMar)
        size: Size (recommended for SanMar)
    """
    try:
        if supplier == "sanmar":
            from src.sanmar.client import SanMarClient
            from src.sanmar.mapper import map_inventory_response

            client = SanMarClient()
            response = client.get_inventory(style, color, size)
            levels = map_inventory_response(response, style, color, size)

            if not levels:
                return f"No live inventory data returned for SanMar style {style}."

            lines = [f"**LIVE inventory for SanMar {style}** (real-time from API)\n"]
            total = 0
            for lv in levels:
                lines.append(f"  {lv.warehouse} ({lv.warehouse_name}): {lv.quantity:,} units")
                total += lv.quantity
            lines.append(f"\n  **Total: {total:,} units**")
            return "\n".join(lines)

        elif supplier == "ssactivewear":
            from src.ssactivewear.client import SSClient

            client = SSClient()
            products = await client.get_products(style)

            if not products:
                return f"No live inventory data returned for S&S style {style}."

            lines = [f"**LIVE inventory for S&S {style}** (real-time from API)\n"]
            # Aggregate by warehouse across all color/size variants
            wh_totals: dict[str, int] = {}
            for prod in products:
                if color and color.lower() not in prod.get("colorName", "").lower():
                    continue
                if size and size.upper() != prod.get("sizeName", "").upper():
                    continue
                for wh in prod.get("warehouses", []):
                    abbr = wh.get("warehouseAbbr", "")
                    wh_totals[abbr] = wh_totals.get(abbr, 0) + wh.get("qty", 0)

            for wh, qty in sorted(wh_totals.items()):
                lines.append(f"  {wh}: {qty:,} units")
            lines.append(f"\n  **Total: {sum(wh_totals.values()):,} units**")
            return "\n".join(lines)

        else:
            return f"Unknown supplier '{supplier}'. Use 'sanmar' or 'ssactivewear'."

    except Exception as e:
        return f"Error fetching live inventory: {str(e)}"


# ─────────────────────────────────────────────────────────────
# Tool 5: compare_pricing
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def compare_pricing(
    style: str,
    size: str = "",
) -> str:
    """Compare pricing for a style across both suppliers (SanMar and S&S).

    Use when someone asks 'what's cheaper, SanMar or S&S for the Gildan 5000?'
    or 'compare pricing between suppliers.'

    Args:
        style: Style number or name to compare (e.g. '5000', 'PC61')
        size: Filter by size for a more focused comparison
    """
    conditions = ["style LIKE ?"]
    params = [f"%{style}%"]
    if size:
        conditions.append("size = ?")
        params.append(size)

    where = " AND ".join(conditions)

    sql = f"""
        SELECT supplier, style, brand, color, size,
               piece_price, case_price, sale_price, customer_price, map_price
        FROM products
        WHERE {where}
        ORDER BY size, color, supplier
    """

    async with get_db(DB_PATH) as db:
        cursor = await db.execute(sql, params)
        rows = [dict(row) for row in await cursor.fetchall()]

    if not rows:
        return f"No data found for style '{style}' in either supplier."

    # Group by supplier for summary
    by_supplier: dict[str, list] = {}
    for row in rows:
        by_supplier.setdefault(row["supplier"], []).append(row)

    lines = [f"**Pricing Comparison: {style}**\n"]

    for supplier, supplier_rows in by_supplier.items():
        pieces = [r["piece_price"] for r in supplier_rows if r["piece_price"]]
        cases = [r["case_price"] for r in supplier_rows if r["case_price"]]
        label = supplier.upper()

        lines.append(f"**{label}** ({len(supplier_rows)} SKUs)")
        if pieces:
            lines.append(f"  Piece: {format_currency(min(pieces))} - {format_currency(max(pieces))}")
        if cases:
            lines.append(f"  Case:  {format_currency(min(cases))} - {format_currency(max(cases))}")
        lines.append("")

    lines.append("\n**Detailed breakdown:**\n")
    lines.append(format_pricing_table(rows))

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Tool 6: get_price_changes
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_price_changes(
    days: int = 30,
    supplier: str = "",
    style: str = "",
) -> str:
    """Show recent price changes detected during sync jobs.

    Use when someone asks 'did any prices change?' or 'what changed this week?'

    Args:
        days: Look back this many days (default 30)
        supplier: Filter by supplier
        style: Filter by style number
    """
    conditions = [f"changed_at > datetime('now', '-{days} days')"]
    params = []

    if supplier:
        conditions.append("supplier = ?")
        params.append(supplier)
    if style:
        conditions.append("style LIKE ?")
        params.append(f"%{style}%")

    where = " AND ".join(conditions)

    sql = f"""
        SELECT supplier, style, color, size, price_type,
               old_price, new_price, changed_at
        FROM price_history
        WHERE {where}
        ORDER BY changed_at DESC
        LIMIT 100
    """

    async with get_db(DB_PATH) as db:
        cursor = await db.execute(sql, params)
        rows = [dict(row) for row in await cursor.fetchall()]

    return format_price_changes(rows)


# ─────────────────────────────────────────────────────────────
# Tool 7: list_tracked_styles
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def list_tracked_styles(
    supplier: str = "",
    category: str = "",
    active_only: bool = True,
) -> str:
    """List all styles currently being tracked from suppliers.

    Args:
        supplier: Filter by supplier ('sanmar' or 'ssactivewear')
        category: Filter by category
        active_only: Only show active styles (default true)
    """
    conditions = []
    params = []

    if supplier:
        conditions.append("supplier = ?")
        params.append(supplier)
    if category:
        conditions.append("category LIKE ?")
        params.append(f"%{category}%")
    if active_only:
        conditions.append("is_active = 1")

    where = " AND ".join(conditions) if conditions else "1=1"

    sql = f"""
        SELECT supplier, style, brand, title, category, is_active,
               added_at, last_synced
        FROM tracked_styles
        WHERE {where}
        ORDER BY supplier, brand, style
    """

    async with get_db(DB_PATH) as db:
        cursor = await db.execute(sql, params)
        rows = [dict(row) for row in await cursor.fetchall()]

    if not rows:
        return "No tracked styles found."

    lines = ["| Supplier | Style | Brand | Title | Category | Last Synced |",
             "|----------|-------|-------|-------|----------|-------------|"]
    for row in rows:
        synced = str(row["last_synced"] or "Never")[:16]
        lines.append(
            f"| {row['supplier']} | {row['style']} | {row.get('brand', '')} "
            f"| {row.get('title', '')[:30]} | {row.get('category', '')} | {synced} |"
        )

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Tool 8: add_tracked_style
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def add_tracked_style(
    supplier: str,
    style: str,
    brand: str = "",
) -> str:
    """Add a new style to track from a supplier.

    After adding, run a sync to pull its data. Use when someone says
    'start tracking the Gildan 5000 from SanMar' or 'add PC61'.

    Args:
        supplier: 'sanmar' or 'ssactivewear'
        style: Style number (e.g. 'PC61', '5000', 'Gildan 5000')
        brand: Brand name (optional, will be filled during sync)
    """
    if supplier not in ("sanmar", "ssactivewear"):
        return f"Invalid supplier '{supplier}'. Use 'sanmar' or 'ssactivewear'."

    async with get_db(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO tracked_styles (supplier, style, brand) VALUES (?, ?, ?)",
                (supplier, style, brand or None),
            )
            await db.commit()
            return (
                f"Added {style} from {supplier} to tracked styles. "
                f"Run a sync to pull pricing and inventory data."
            )
        except Exception as e:
            if "UNIQUE constraint" in str(e):
                return f"Style {style} from {supplier} is already being tracked."
            raise


# ─────────────────────────────────────────────────────────────
# Tool 9: get_product_details
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_product_details(
    style: str,
    supplier: str = "",
    color: str = "",
) -> str:
    """Get full product details including images, specs, and inventory summary.

    Args:
        style: Style number
        supplier: Limit to one supplier
        color: Filter by color
    """
    conditions = ["p.style LIKE ?"]
    params = [f"%{style}%"]

    if supplier:
        conditions.append("p.supplier = ?")
        params.append(supplier)
    if color:
        conditions.append("p.color LIKE ?")
        params.append(f"%{color}%")

    where = " AND ".join(conditions)

    async with get_db(DB_PATH) as db:
        # Get product data
        cursor = await db.execute(
            f"""SELECT p.*, ts.title, ts.description, ts.category
                FROM products p
                LEFT JOIN tracked_styles ts ON ts.supplier = p.supplier AND ts.style = p.style
                WHERE {where}
                ORDER BY p.color, p.size
                LIMIT 100""",
            params,
        )
        products = [dict(row) for row in await cursor.fetchall()]

        if not products:
            return f"No product details found for style '{style}'."

        # Get inventory summary
        inv_cursor = await db.execute(
            f"""SELECT warehouse, warehouse_name, SUM(quantity) as total_qty
                FROM inventory
                WHERE style LIKE ? {'AND supplier = ?' if supplier else ''}
                GROUP BY warehouse
                ORDER BY total_qty DESC""",
            [f"%{style}%"] + ([supplier] if supplier else []),
        )
        inv_rows = [dict(row) for row in await inv_cursor.fetchall()]

    first = products[0]
    title = first.get("title") or f"{first['brand']} {first['style']}"

    lines = [
        f"# {title}",
        f"**Supplier:** {first['supplier'].upper()}",
        f"**Brand:** {first.get('brand', '')}",
        f"**Style:** {first['style']}",
        f"**Category:** {first.get('category', '')}",
        f"**Status:** {first.get('product_status', '')}",
        f"**Description:** {first.get('description', '')}",
    ]

    if first.get("front_image_url"):
        lines.append(f"**Front Image:** {first['front_image_url']}")
    if first.get("spec_sheet_url"):
        lines.append(f"**Spec Sheet:** {first['spec_sheet_url']}")

    # Colors available
    colors = sorted(set(p["color"] for p in products))
    lines.append(f"\n**Colors ({len(colors)}):** {', '.join(colors)}")

    # Sizes available
    sizes = sorted(set(p["size"] for p in products))
    lines.append(f"**Sizes ({len(sizes)}):** {', '.join(sizes)}")

    # Price range
    pieces = [p["piece_price"] for p in products if p.get("piece_price")]
    cases = [p["case_price"] for p in products if p.get("case_price")]
    if pieces:
        lines.append(f"**Piece Price:** {format_currency(min(pieces))} - {format_currency(max(pieces))}")
    if cases:
        lines.append(f"**Case Price:** {format_currency(min(cases))} - {format_currency(max(cases))}")

    # Inventory summary
    if inv_rows:
        total = sum(r["total_qty"] for r in inv_rows)
        lines.append(f"\n**Total Inventory: {total:,} units**")
        for r in inv_rows:
            lines.append(f"  {r['warehouse']} ({r['warehouse_name']}): {r['total_qty']:,}")

    lines.append(f"\n*Last synced: {first.get('last_synced', 'Never')}*")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Tool 10: sync_status
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def sync_status(supplier: str = "") -> str:
    """Check when data was last synced and see recent sync job results.

    Args:
        supplier: Filter by supplier (omit for all)
    """
    conditions = []
    params = []
    if supplier:
        conditions.append("supplier = ?")
        params.append(supplier)

    where = " AND ".join(conditions) if conditions else "1=1"

    sql = f"""
        SELECT supplier, sync_type, styles_synced, skus_updated,
               price_changes, errors, error_details, started_at,
               completed_at, status
        FROM sync_log
        WHERE {where}
        ORDER BY started_at DESC
        LIMIT 10
    """

    async with get_db(DB_PATH) as db:
        cursor = await db.execute(sql, params)
        rows = [dict(row) for row in await cursor.fetchall()]

    if not rows:
        return "No sync history found. Run a sync job first."

    lines = ["**Recent Sync Jobs:**\n",
             "| Date | Supplier | Type | Styles | SKUs | Price Changes | Errors | Status |",
             "|------|----------|------|--------|------|---------------|--------|--------|"]

    for row in rows:
        date = str(row["started_at"])[:16]
        lines.append(
            f"| {date} | {row['supplier']} | {row['sync_type']} "
            f"| {row['styles_synced']} | {row['skus_updated']} "
            f"| {row['price_changes']} | {row['errors']} | {row['status']} |"
        )

    return "\n".join(lines)


def main():
    """Entry point for the MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
