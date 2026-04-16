"""Map S&S Activewear REST JSON responses to normalized Pydantic models."""

import logging
from typing import Any

from src.models import Product, InventoryLevel, SSProductResponse

logger = logging.getLogger(__name__)


def _safe_float(val: Any) -> float | None:
    """Safely convert a value to float, returning None for invalid/empty values."""
    if val is None:
        return None
    try:
        f = float(val)
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _safe_int(val: Any) -> int | None:
    """Safely convert to int, returning None for invalid values."""
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _safe_str(val: Any) -> str:
    """Safely convert to string, returning empty string for None."""
    if val is None:
        return ""
    return str(val).strip()


def _map_single_product(raw: dict) -> SSProductResponse:
    """Map a single S&S product JSON dict to SSProductResponse model.

    S&S returns camelCase JSON; our Pydantic model uses snake_case.
    """
    return SSProductResponse(
        sku=_safe_str(raw.get("sku")),
        gtin=_safe_str(raw.get("gtin")),
        style_id=_safe_int(raw.get("styleID")),
        brand_name=_safe_str(raw.get("brandName")),
        style_name=_safe_str(raw.get("styleName")),
        color_name=_safe_str(raw.get("colorName")),
        color_code=_safe_str(raw.get("colorCode")),
        size_name=_safe_str(raw.get("sizeName")),
        size_price_code_name=_safe_str(raw.get("sizePriceCodeName")),
        case_qty=_safe_int(raw.get("caseQty")),
        unit_weight=_safe_float(raw.get("unitWeight")),
        map_price=_safe_float(raw.get("mapPrice")),
        piece_price=_safe_float(raw.get("piecePrice")),
        dozen_price=_safe_float(raw.get("dozenPrice")),
        case_price=_safe_float(raw.get("casePrice")),
        sale_price=_safe_float(raw.get("salePrice")),
        customer_price=_safe_float(raw.get("customerPrice")),
        sale_expiration=_safe_str(raw.get("saleExpiration")),
        noe_retailing=bool(raw.get("noeRetailing", False)),
        country_of_origin=_safe_str(raw.get("countryOfOrigin")),
        color_front_image=_safe_str(raw.get("colorFrontImage")),
        color_back_image=_safe_str(raw.get("colorBackImage")),
        color_swatch_image=_safe_str(raw.get("colorSwatchImage")),
        qty=_safe_int(raw.get("qty")) or 0,
        warehouses=raw.get("warehouses", []),
    )


def map_products_response(raw_products: list[dict]) -> list[Product]:
    """Map a list of S&S product JSON dicts to normalized Product models.

    Args:
        raw_products: List of raw product dicts from /v2/products/ endpoint.

    Returns:
        List of normalized Product models.
    """
    products = []
    for raw in raw_products:
        try:
            ss_resp = _map_single_product(raw)
            product = ss_resp.to_product()
            products.append(product)
        except Exception as e:
            style = raw.get("styleName", "?")
            color = raw.get("colorName", "?")
            size = raw.get("sizeName", "?")
            logger.error(f"Error mapping S&S product {style}/{color}/{size}: {e}")
            continue

    logger.info(f"Mapped {len(products)} product variants from S&S response")
    return products


def map_inventory_from_products(raw_products: list[dict]) -> list[InventoryLevel]:
    """Extract warehouse-level inventory from S&S product response.

    S&S embeds inventory in each product's warehouses[] array, so we
    extract it from the same products response — no separate API call needed.

    Args:
        raw_products: List of raw product dicts from /v2/products/ endpoint.

    Returns:
        Flat list of InventoryLevel models (one per product×warehouse combo).
    """
    levels = []
    for raw in raw_products:
        try:
            ss_resp = _map_single_product(raw)
            levels.extend(ss_resp.to_inventory_levels())
        except Exception as e:
            logger.error(f"Error mapping S&S inventory: {e}")
            continue

    logger.info(f"Mapped {len(levels)} inventory levels from S&S response")
    return levels
