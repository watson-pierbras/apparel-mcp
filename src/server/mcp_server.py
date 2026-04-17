"""FastMCP server for querying apparel pricing and inventory from SQLite."""

import os
import sys
import logging
from typing import Optional

from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.dependencies import get_http_headers
from fastmcp.exceptions import ToolError
from dotenv import load_dotenv
from starlette.requests import Request
from starlette.responses import JSONResponse

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


# ─────────────────────────────────────────────────────────────
# Live API fallback helpers (DB-first, live only if not in DB)
# ─────────────────────────────────────────────────────────────

async def _try_live_search(query: str = "", brand: str = "", supplier: str = "") -> str | None:
    """Try searching live APIs when DB returns no results."""
    results = []

    # Try S&S live
    if not supplier or supplier == "ssactivewear":
        try:
            from src.ssactivewear.client import SSClient
            client = SSClient()
            if query:
                style_results = await client.search_styles(query=query, brand=brand)
            elif brand:
                style_results = await client.search_styles(brand=brand)
            else:
                style_results = []

            for st in style_results[:10]:
                name = st.get("styleName", "")
                br = st.get("brandName", "")
                title = st.get("title", "")
                cat = st.get("baseCategory", "")
                results.append(f"**{br} {name}** [S&S] — {title} ({cat})")
        except Exception as e:
            logger.warning(f"S&S live search fallback failed: {e}")

    # Try SanMar live
    if not supplier or supplier == "sanmar":
        try:
            from src.sanmar.client import SanMarClient
            from src.sanmar.mapper import map_product_info_response
            client = SanMarClient()
            search_term = query or brand
            if search_term:
                response = client.get_product_info(search_term)
                products = map_product_info_response(response)
                seen = set()
                for p in products:
                    if p.style not in seen:
                        seen.add(p.style)
                        results.append(f"**{p.brand} {p.style}** [SanMar]")
                    if len(seen) >= 10:
                        break
        except Exception as e:
            logger.warning(f"SanMar live search fallback failed: {e}")

    if not results:
        return None

    header = "*(Results from live API — style not in local database)*\n\n"
    footer = "\n\n*Use `add_tracked_style` to start tracking any of these styles.*"
    return header + "\n".join(results) + footer


async def _try_live_pricing(style: str, supplier: str = "") -> str | None:
    """Try fetching live pricing when DB returns no results."""
    # Try S&S
    if not supplier or supplier == "ssactivewear":
        try:
            from src.ssactivewear.client import SSClient
            client = SSClient()
            products = await client.get_products(style)
            if products:
                lines = [f"*(Live pricing from S&S API — not in local database)*\n"]
                lines.append(f"**{products[0].get('brandName', '')} {products[0].get('styleName', style)}**\n")
                lines.append("| Color | Size | Piece | Case | Sale |")
                lines.append("|-------|------|-------|------|------|")
                for p in products[:50]:  # Cap at 50 rows
                    piece = f"${p.get('piecePrice', 0):.2f}" if p.get("piecePrice") else "-"
                    case = f"${p.get('casePrice', 0):.2f}" if p.get("casePrice") else "-"
                    sale = f"${p.get('salePrice', 0):.2f}" if p.get("salePrice") else "-"
                    lines.append(f"| {p.get('colorName', '')} | {p.get('sizeName', '')} | {piece} | {case} | {sale} |")
                if len(products) > 50:
                    lines.append(f"\n*Showing 50 of {len(products)} SKUs*")
                lines.append("\n*Use `add_tracked_style` to track this style locally.*")
                return "\n".join(lines)
        except Exception as e:
            logger.warning(f"S&S live pricing fallback failed: {e}")

    # Try SanMar
    if not supplier or supplier == "sanmar":
        try:
            from src.sanmar.client import SanMarClient
            from src.sanmar.mapper import map_product_info_response
            client = SanMarClient()
            response = client.get_product_info(style)
            products = map_product_info_response(response)
            if products:
                lines = [f"*(Live pricing from SanMar API — not in local database)*\n"]
                lines.append(f"**{products[0].brand} {products[0].style}**\n")
                lines.append("| Color | Size | Piece | Case | Sale |")
                lines.append("|-------|------|-------|------|------|")
                for p in products[:50]:
                    piece = f"${p.piece_price:.2f}" if p.piece_price else "-"
                    case = f"${p.case_price:.2f}" if p.case_price else "-"
                    sale = f"${p.sale_price:.2f}" if p.sale_price else "-"
                    lines.append(f"| {p.color} | {p.size} | {piece} | {case} | {sale} |")
                if len(products) > 50:
                    lines.append(f"\n*Showing 50 of {len(products)} SKUs*")
                lines.append("\n*Use `add_tracked_style` to track this style locally.*")
                return "\n".join(lines)
        except Exception as e:
            logger.warning(f"SanMar live pricing fallback failed: {e}")

    return None


async def _try_live_inventory(style: str, supplier: str = "") -> str | None:
    """Try fetching live inventory when DB returns no results."""
    # Try S&S
    if not supplier or supplier == "ssactivewear":
        try:
            from src.ssactivewear.client import SSClient
            client = SSClient()
            products = await client.get_products(style)
            if products:
                wh_totals: dict[str, int] = {}
                for prod in products:
                    for wh in prod.get("warehouses", []):
                        abbr = wh.get("warehouseAbbr", "")
                        wh_totals[abbr] = wh_totals.get(abbr, 0) + wh.get("qty", 0)
                if wh_totals:
                    lines = [f"*(Live inventory from S&S API — not in local database)*\n"]
                    lines.append(f"**S&S {style}**\n")
                    total = 0
                    for wh, qty in sorted(wh_totals.items()):
                        lines.append(f"  {wh}: {qty:,} units")
                        total += qty
                    lines.append(f"\n  **Total: {total:,} units**")
                    lines.append("\n*Use `add_tracked_style` to track this style locally.*")
                    return "\n".join(lines)
        except Exception as e:
            logger.warning(f"S&S live inventory fallback failed: {e}")

    # Try SanMar
    if not supplier or supplier == "sanmar":
        try:
            from src.sanmar.client import SanMarClient
            from src.sanmar.mapper import map_inventory_response
            client = SanMarClient()
            response = client.get_inventory(style)
            levels = map_inventory_response(response, style)
            if levels:
                lines = [f"*(Live inventory from SanMar API — not in local database)*\n"]
                lines.append(f"**SanMar {style}**\n")
                total = 0
                for lv in levels:
                    lines.append(f"  {lv.warehouse} ({lv.warehouse_name}): {lv.quantity:,} units")
                    total += lv.quantity
                lines.append(f"\n  **Total: {total:,} units**")
                lines.append("\n*Use `add_tracked_style` to track this style locally.*")
                return "\n".join(lines)
        except Exception as e:
            logger.warning(f"SanMar live inventory fallback failed: {e}")

    return None


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
# Bearer-token authentication middleware
# Protects every tool call when MCP_API_KEY is set in the env.
# When unset (local dev / Claude Desktop stdio), auth is skipped.
# ─────────────────────────────────────────────────────────────

class BearerAuthMiddleware(Middleware):
    """Validate `Authorization: Bearer <MCP_API_KEY>` on every tool call."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        headers = get_http_headers() or {}
        # Accept either Authorization: Bearer <key> or x-api-key: <key>
        auth_header = headers.get("authorization", "")
        x_api_key = headers.get("x-api-key", "")

        token = None
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
        elif x_api_key:
            token = x_api_key.strip()
        elif auth_header:
            token = auth_header.strip()

        if token != self.api_key:
            raise ToolError("Unauthorized: invalid or missing API key.")

        return await call_next(context)


_MCP_API_KEY = os.getenv("MCP_API_KEY", "").strip()
if _MCP_API_KEY:
    mcp.add_middleware(BearerAuthMiddleware(_MCP_API_KEY))
    logger.info("Bearer auth enabled for tool calls.")
else:
    logger.warning(
        "MCP_API_KEY not set — server is running WITHOUT authentication. "
        "Do not expose this server publicly in this state."
    )


# ─────────────────────────────────────────────────────────────
# Well-known endpoints so MCP clients skip OAuth discovery
# ─────────────────────────────────────────────────────────────

@mcp.custom_route("/", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Root health check — used by Railway and uptime monitors."""
    return JSONResponse({
        "name": "apparel-mcp",
        "status": "ok",
        "transport": "streamable-http",
        "endpoint": "/mcp",
        "auth": "bearer" if os.getenv("MCP_API_KEY") else "none",
    })


@mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
async def oauth_protected_resource(request: Request) -> JSONResponse:
    """Tell MCP clients this server requires no OAuth (we use a simple bearer)."""
    return JSONResponse({"resource": request.url.scheme + "://" + request.url.netloc + "/mcp"})


@mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])
async def oauth_authorization_server(request: Request) -> JSONResponse:
    return JSONResponse({}, status_code=404)


@mcp.custom_route("/.well-known/openid-configuration", methods=["GET"])
async def openid_configuration(request: Request) -> JSONResponse:
    return JSONResponse({}, status_code=404)


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
        # Live API fallback
        try:
            live = await _try_live_search(query=query, brand=brand, supplier=supplier)
            if live:
                return live
        except Exception as e:
            logger.warning(f"Live search fallback failed: {e}")
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
        # Live API fallback
        try:
            live = await _try_live_pricing(style, supplier)
            if live:
                return live
        except Exception as e:
            logger.warning(f"Live pricing fallback failed: {e}")
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
        # Live API fallback
        try:
            live = await _try_live_inventory(style, supplier)
            if live:
                return live
        except Exception as e:
            logger.warning(f"Live inventory fallback failed: {e}")
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
        # Live API fallback — try both suppliers
        try:
            live = await _try_live_pricing(style)
            if live:
                return live
        except Exception as e:
            logger.warning(f"Live compare fallback failed: {e}")
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


# ─────────────────────────────────────────────────────────────
# Tool 11: search_sanmar_live
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def search_sanmar_live(
    style: str = "",
    brand: str = "",
    category: str = "",
) -> str:
    """Search SanMar's catalog in REAL-TIME via their API.

    Use this to browse SanMar products live — find new styles, explore
    brands, or look up a specific style number before adding it to tracking.

    You must provide at least one of: style, brand, or category.

    Args:
        style: Style number to look up (e.g. 'PC61', 'K540', 'G500')
        brand: Brand name — must match SanMar exactly. Options include:
               Port & Co, Sport-Tek, District, Gildan, Bella+Canvas,
               Nike, The North Face, Carhartt, Next Level, Comfort Colors,
               Champion, Hanes, New Era, OGIO, Eddie Bauer, etc.
        category: Category name. Options: T-Shirts, Activewear, Fleece,
                  Caps, Outerwear, Polos/Knits, Woven Shirts, Bags, Accessories
    """
    if not any([style, brand, category]):
        return "Please provide at least one of: style, brand, or category."

    try:
        from src.sanmar.client import SanMarClient
        from src.sanmar.mapper import map_product_info_response

        client = SanMarClient()

        if style:
            # Direct style lookup — fastest, most specific
            response = client.get_product_info(style)
        elif brand:
            response = client.get_product_info_by_brand(brand)
        elif category:
            response = client.get_product_info_by_category(category)
        else:
            return "Please provide style, brand, or category."

        products = map_product_info_response(response)

        if not products:
            return f"No products found for {'style ' + style if style else 'brand ' + brand if brand else 'category ' + category}."

        # Deduplicate to style level — group variants by style number
        styles_seen: dict[str, dict] = {}
        for p in products:
            key = p.style
            if key not in styles_seen:
                styles_seen[key] = {
                    "style": p.style,
                    "brand": p.brand or "",
                    "colors": set(),
                    "sizes": set(),
                    "min_price": p.piece_price,
                    "max_price": p.piece_price,
                    "case_price": p.case_price,
                    "image": p.front_image_url or "",
                    "status": p.product_status or "",
                }
            s = styles_seen[key]
            if p.color:
                s["colors"].add(p.color)
            if p.size:
                s["sizes"].add(p.size)
            if p.piece_price:
                if s["min_price"] is None or p.piece_price < s["min_price"]:
                    s["min_price"] = p.piece_price
                if s["max_price"] is None or p.piece_price > s["max_price"]:
                    s["max_price"] = p.piece_price

        # Format output — limit to 25 styles to keep response manageable
        style_list = list(styles_seen.values())[:25]
        total = len(styles_seen)

        lines = [f"**SanMar Live Search** — {total} styles found"]
        if total > 25:
            lines[0] += f" (showing first 25)"
        lines.append("")

        for s in style_list:
            price_str = ""
            if s["min_price"]:
                if s["min_price"] == s["max_price"]:
                    price_str = f"${s['min_price']:.2f}/pc"
                else:
                    price_str = f"${s['min_price']:.2f}–${s['max_price']:.2f}/pc"
            if s["case_price"]:
                price_str += f" (case: ${s['case_price']:.2f})"

            lines.append(f"### {s['style']} — {s['brand']}")
            if s["status"]:
                lines.append(f"Status: {s['status']}")
            lines.append(f"Colors: {len(s['colors'])} | Sizes: {', '.join(sorted(s['sizes']))}")
            if price_str:
                lines.append(f"Price: {price_str}")
            if s["image"]:
                lines.append(f"Image: {s['image']}")
            lines.append("")

        if total > 25:
            lines.append(f"*{total - 25} more styles not shown. Narrow your search with a style number or more specific brand/category.*")

        return "\n".join(lines)

    except Exception as e:
        return f"Error searching SanMar live: {str(e)}"


# ─────────────────────────────────────────────────────────────
# Tool 12: get_live_pricing
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_live_pricing(
    style: str,
    color: str = "",
    size: str = "",
) -> str:
    """Get REAL-TIME pricing for a style directly from SanMar's API.

    Bypasses the cached database and queries SanMar live. Use when you
    need guaranteed-current pricing, such as before quoting a customer
    or placing an order.

    Args:
        style: Style number (e.g. 'PC61', 'K420', 'G500')
        color: Optional color filter (e.g. 'Black', 'White')
        size: Optional size filter (e.g. 'M', 'XL', '2XL')
    """
    try:
        from src.sanmar.client import SanMarClient
        from src.sanmar.mapper import map_product_info_response

        client = SanMarClient()
        response = client.get_product_info(style, color, size)
        products = map_product_info_response(response)

        if not products:
            return f"No pricing data returned from SanMar for style {style}."

        # Group by color for a clean pricing table
        color_groups: dict[str, list] = {}
        for p in products:
            key = p.color or "Unknown"
            if key not in color_groups:
                color_groups[key] = []
            color_groups[key].append(p)

        lines = [f"**LIVE Pricing for SanMar {style}** (real-time from API)\n"]

        # If a specific color was requested or only one color exists
        if len(color_groups) == 1 or color:
            lines.append("| Color | Size | Piece | Case | Sale |")
            lines.append("|-------|------|-------|------|------|")
            for c_name, variants in sorted(color_groups.items()):
                for v in sorted(variants, key=lambda x: x.size or "ZZZ"):
                    piece = f"${v.piece_price:.2f}" if v.piece_price else "-"
                    case = f"${v.case_price:.2f}" if v.case_price else "-"
                    sale = f"${v.sale_price:.2f}" if v.sale_price else "-"
                    lines.append(f"| {c_name} | {v.size} | {piece} | {case} | {sale} |")
        else:
            # Multiple colors — show summary per color with size range pricing
            lines.append("| Color | Sizes | Piece Range | Case Price |")
            lines.append("|-------|-------|-------------|------------|")
            for c_name, variants in sorted(color_groups.items()):
                sizes = sorted(set(v.size for v in variants))
                prices = [v.piece_price for v in variants if v.piece_price]
                case_prices = [v.case_price for v in variants if v.case_price]

                if prices:
                    min_p, max_p = min(prices), max(prices)
                    if min_p == max_p:
                        price_str = f"${min_p:.2f}"
                    else:
                        price_str = f"${min_p:.2f}–${max_p:.2f}"
                else:
                    price_str = "-"

                case_str = f"${case_prices[0]:.2f}" if case_prices else "-"
                size_str = ", ".join(sizes[:6])
                if len(sizes) > 6:
                    size_str += f" +{len(sizes)-6} more"

                lines.append(f"| {c_name} | {size_str} | {price_str} | {case_str} |")

        lines.append(f"\n*{len(products)} total SKUs across {len(color_groups)} colors*")

        # Add brand and image if available
        first = products[0]
        if first.brand:
            lines.insert(1, f"*{first.brand} {first.style}*\n")
        if first.front_image_url:
            lines.append(f"\nProduct image: {first.front_image_url}")

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching live pricing: {str(e)}"


# ─────────────────────────────────────────────────────────────
# Tool 13: search_ss_live
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def search_ss_live(
    style: str = "",
    brand: str = "",
    query: str = "",
) -> str:
    """Search S&S Activewear's catalog in REAL-TIME via their API.

    Use this to browse S&S products live — find Alleson, Bella+Canvas,
    Next Level, Gildan, and other styles before adding them to tracking.

    You must provide at least one of: style, brand, or query.

    Args:
        style: Style number or part number (e.g. '8668', '00760', '3001')
        brand: Brand name (e.g. 'Alleson Athletic', 'Bella+Canvas', 'Next Level')
        query: Keyword search (e.g. 'track singlet', 'performance tee')
    """
    if not any([style, brand, query]):
        return "Please provide at least one of: style, brand, or query."

    try:
        from src.ssactivewear.client import SSClient
        from src.ssactivewear.mapper import map_products_response

        client = SSClient()

        if style:
            # Direct product lookup by style — most specific
            raw_products = await client.get_products(style)

            if not raw_products:
                return f"No products found for S&S style '{style}'."

            # Group SKUs by style name
            styles_seen: dict[str, dict] = {}
            for p in raw_products:
                key = p.get("styleName", style)
                if key not in styles_seen:
                    styles_seen[key] = {
                        "style": key,
                        "brand": p.get("brandName", ""),
                        "colors": set(),
                        "sizes": set(),
                        "min_price": p.get("piecePrice"),
                        "max_price": p.get("piecePrice"),
                        "case_price": p.get("casePrice"),
                        "image": p.get("colorFrontImage", ""),
                    }
                s = styles_seen[key]
                if p.get("colorName"):
                    s["colors"].add(p["colorName"])
                if p.get("sizeName"):
                    s["sizes"].add(p["sizeName"])
                pp = p.get("piecePrice")
                if pp:
                    if s["min_price"] is None or pp < s["min_price"]:
                        s["min_price"] = pp
                    if s["max_price"] is None or pp > s["max_price"]:
                        s["max_price"] = pp

        else:
            # Keyword or brand search via styles endpoint
            style_results = await client.search_styles(query=query, brand=brand)

            if not style_results:
                search_desc = brand or query
                return f"No styles found for S&S search '{search_desc}'."

            styles_seen = {}
            for st in style_results:
                key = st.get("styleName") or st.get("partNumber") or str(st.get("styleID", ""))
                if key and key not in styles_seen:
                    styles_seen[key] = {
                        "style": key,
                        "brand": st.get("brandName", ""),
                        "colors": set(),
                        "sizes": set(),
                        "min_price": None,
                        "max_price": None,
                        "case_price": None,
                        "image": st.get("styleImage", ""),
                        "title": st.get("title", ""),
                        "category": st.get("baseCategory", ""),
                    }

        # Format output — limit to 25 styles
        style_list = list(styles_seen.values())[:25]
        total = len(styles_seen)

        lines = [f"**S&S Activewear Live Search** — {total} styles found"]
        if total > 25:
            lines[0] += f" (showing first 25)"
        lines.append("")

        cdn_base = "https://cdn.ssactivewear.com/"

        for s in style_list:
            price_str = ""
            if s.get("min_price"):
                if s["min_price"] == s.get("max_price"):
                    price_str = f"${s['min_price']:.2f}/pc"
                else:
                    price_str = f"${s['min_price']:.2f}–${s['max_price']:.2f}/pc"
            if s.get("case_price"):
                price_str += f" (case: ${s['case_price']:.2f})"

            lines.append(f"### {s['style']} — {s['brand']}")
            if s.get("title"):
                lines.append(f"{s['title']}")
            if s.get("category"):
                lines.append(f"Category: {s['category']}")
            if s["colors"]:
                lines.append(f"Colors: {len(s['colors'])} | Sizes: {', '.join(sorted(s['sizes']))}")
            if price_str:
                lines.append(f"Price: {price_str}")
            if s.get("image"):
                img = s["image"]
                if img and not img.startswith("http"):
                    img = cdn_base + img
                lines.append(f"Image: {img}")
            lines.append("")

        if total > 25:
            lines.append(f"*{total - 25} more styles not shown. Narrow your search with a style number or more specific brand/query.*")

        return "\n".join(lines)

    except Exception as e:
        return f"Error searching S&S Activewear live: {str(e)}"


# ─────────────────────────────────────────────────────────────
# Tool 14: get_ss_live_pricing
# ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_ss_live_pricing(
    style: str,
    color: str = "",
    size: str = "",
) -> str:
    """Get REAL-TIME pricing for a style directly from S&S Activewear's API.

    Bypasses the cached database and queries S&S live. Use when you
    need guaranteed-current pricing, such as before quoting a customer
    or placing an order.

    Args:
        style: Style number (e.g. '8668', '3001', '00760')
        color: Optional color filter (e.g. 'Black', 'White')
        size: Optional size filter (e.g. 'M', 'XL', '2XL')
    """
    try:
        from src.ssactivewear.client import SSClient

        client = SSClient()
        products = await client.get_products(style, color, size)

        if not products:
            return f"No pricing data returned from S&S for style {style}."

        # Group by color for a clean pricing table
        color_groups: dict[str, list] = {}
        for p in products:
            key = p.get("colorName", "Unknown")
            if key not in color_groups:
                color_groups[key] = []
            color_groups[key].append(p)

        lines = [f"**LIVE Pricing for S&S {style}** (real-time from API)\n"]

        # Add brand from first product
        first = products[0]
        brand = first.get("brandName", "")
        style_name = first.get("styleName", style)
        if brand:
            lines.insert(1, f"*{brand} {style_name}*\n")

        # If a specific color was requested or only one color exists
        if len(color_groups) == 1 or color:
            lines.append("| Color | Size | Piece | Case | Sale | Dozen |")
            lines.append("|-------|------|-------|------|------|-------|")
            for c_name, variants in sorted(color_groups.items()):
                for v in sorted(variants, key=lambda x: x.get("sizeName", "ZZZ")):
                    piece = f"${v['piecePrice']:.2f}" if v.get("piecePrice") else "-"
                    case = f"${v['casePrice']:.2f}" if v.get("casePrice") else "-"
                    sale = f"${v['salePrice']:.2f}" if v.get("salePrice") else "-"
                    dozen = f"${v['dozenPrice']:.2f}" if v.get("dozenPrice") else "-"
                    lines.append(f"| {c_name} | {v.get('sizeName', '')} | {piece} | {case} | {sale} | {dozen} |")
        else:
            # Multiple colors — show summary per color with size range pricing
            lines.append("| Color | Sizes | Piece Range | Case Price | Sale |")
            lines.append("|-------|-------|-------------|------------|------|")
            for c_name, variants in sorted(color_groups.items()):
                sizes = sorted(set(v.get("sizeName", "") for v in variants))
                prices = [v["piecePrice"] for v in variants if v.get("piecePrice")]
                case_prices = [v["casePrice"] for v in variants if v.get("casePrice")]
                sale_prices = [v["salePrice"] for v in variants if v.get("salePrice")]

                if prices:
                    min_p, max_p = min(prices), max(prices)
                    if min_p == max_p:
                        price_str = f"${min_p:.2f}"
                    else:
                        price_str = f"${min_p:.2f}–${max_p:.2f}"
                else:
                    price_str = "-"

                case_str = f"${case_prices[0]:.2f}" if case_prices else "-"
                sale_str = f"${min(sale_prices):.2f}" if sale_prices else "-"
                size_str = ", ".join(sizes[:6])
                if len(sizes) > 6:
                    size_str += f" +{len(sizes)-6} more"

                lines.append(f"| {c_name} | {size_str} | {price_str} | {case_str} | {sale_str} |")

        lines.append(f"\n*{len(products)} total SKUs across {len(color_groups)} colors*")

        # Add image if available
        front_img = first.get("colorFrontImage", "")
        if front_img:
            if not front_img.startswith("http"):
                front_img = f"https://cdn.ssactivewear.com/{front_img}"
            lines.append(f"\nProduct image: {front_img}")

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching S&S live pricing: {str(e)}"


def main():
    """Entry point for the MCP server."""
    import argparse

    parser = argparse.ArgumentParser(description="Apparel MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="Transport protocol (default: stdio for Claude Desktop, streamable-http for networked/container use)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind when using streamable-http (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind when using streamable-http (default: 8000)",
    )
    args = parser.parse_args()

    if args.transport == "streamable-http":
        mcp.run(transport="http", host=args.host, port=args.port, stateless_http=True)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
