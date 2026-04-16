"""Format database rows into readable text for MCP tool responses."""

from typing import Any


def format_currency(val: Any) -> str:
    """Format a value as USD currency, or '-' if None."""
    if val is None:
        return "-"
    try:
        return f"${float(val):.2f}"
    except (ValueError, TypeError):
        return "-"


def format_number(val: Any) -> str:
    """Format a number with commas, or '-' if None."""
    if val is None:
        return "-"
    try:
        return f"{int(val):,}"
    except (ValueError, TypeError):
        return "-"


def format_product_table(rows: list[dict], include_inventory: bool = False) -> str:
    """Format product rows into a readable text table."""
    if not rows:
        return "No products found."

    lines = []
    current_style = None

    for row in rows:
        style_key = f"{row.get('supplier', '')}/{row.get('style', '')}"
        if style_key != current_style:
            current_style = style_key
            supplier = row.get("supplier", "").upper()
            brand = row.get("brand", "")
            style = row.get("style", "")
            title = row.get("title", "") or f"{brand} {style}"
            lines.append(f"\n## {title} [{supplier}]")
            lines.append(f"Style: {style} | Brand: {brand}")

        color = row.get("color", "")
        size = row.get("size", "")
        piece = format_currency(row.get("piece_price"))
        case = format_currency(row.get("case_price"))
        sale = format_currency(row.get("sale_price"))

        line = f"  {color:<20} {size:<6} Piece: {piece:<8} Case: {case:<8}"
        if row.get("sale_price"):
            line += f" SALE: {sale}"
        lines.append(line)

    return "\n".join(lines)


def format_pricing_table(rows: list[dict]) -> str:
    """Format pricing data into a comparison-friendly table."""
    if not rows:
        return "No pricing data found."

    lines = ["| Supplier | Style | Color | Size | Piece | Case | Sale | Customer | MAP |",
             "|----------|-------|-------|------|-------|------|------|----------|-----|"]

    for row in rows:
        lines.append(
            f"| {row.get('supplier', ''):<8} "
            f"| {row.get('style', ''):<5} "
            f"| {row.get('color', ''):<5} "
            f"| {row.get('size', ''):<4} "
            f"| {format_currency(row.get('piece_price')):<5} "
            f"| {format_currency(row.get('case_price')):<4} "
            f"| {format_currency(row.get('sale_price')):<4} "
            f"| {format_currency(row.get('customer_price')):<8} "
            f"| {format_currency(row.get('map_price')):<3} |"
        )

    return "\n".join(lines)


def format_inventory_table(rows: list[dict]) -> str:
    """Format inventory data grouped by color/size."""
    if not rows:
        return "No inventory data found."

    lines = ["| Warehouse | Location | Color | Size | Qty | Closeout | Dropship |",
             "|-----------|----------|-------|------|-----|----------|----------|"]

    for row in rows:
        lines.append(
            f"| {row.get('warehouse', ''):<9} "
            f"| {row.get('warehouse_name', ''):<8} "
            f"| {row.get('color', ''):<5} "
            f"| {row.get('size', ''):<4} "
            f"| {format_number(row.get('quantity')):<3} "
            f"| {'Yes' if row.get('is_closeout') else 'No':<8} "
            f"| {'Yes' if row.get('is_dropship') else 'No':<8} |"
        )

    return "\n".join(lines)


def format_price_changes(rows: list[dict]) -> str:
    """Format price change history."""
    if not rows:
        return "No price changes found in the specified period."

    lines = ["| Date | Supplier | Style | Color | Size | Type | Old | New | Change |",
             "|------|----------|-------|-------|------|------|-----|-----|--------|"]

    for row in rows:
        old_p = row.get("old_price")
        new_p = row.get("new_price")
        if old_p and new_p:
            change = new_p - old_p
            change_str = f"+{format_currency(change)}" if change > 0 else format_currency(change)
        else:
            change_str = "-"

        lines.append(
            f"| {str(row.get('changed_at', ''))[:10]} "
            f"| {row.get('supplier', '')} "
            f"| {row.get('style', '')} "
            f"| {row.get('color', '')} "
            f"| {row.get('size', '')} "
            f"| {row.get('price_type', '')} "
            f"| {format_currency(old_p)} "
            f"| {format_currency(new_p)} "
            f"| {change_str} |"
        )

    return "\n".join(lines)
