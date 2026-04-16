"""Map SanMar SOAP responses to normalized Pydantic models."""

import logging
from typing import Any

from src.models import (
    Product,
    InventoryLevel,
    SanMarProductBasicInfo,
    SanMarProductPriceInfo,
    SanMarProductImageInfo,
    SanMarProductResponse,
)

logger = logging.getLogger(__name__)

# SanMar warehouse code → name mapping
SANMAR_WAREHOUSES = {
    "1": ("PRE", "Seattle, WA"),
    "2": ("CIN", "Cincinnati, OH"),
    "3": ("COP", "Dallas, TX"),
    "4": ("REN", "Reno, NV"),
    "5": ("NJE", "Robbinsville, NJ"),
    "6": ("JAC", "Jacksonville, FL"),
    "7": ("MSP", "Minneapolis, MN"),
    "12": ("PHX", "Phoenix, AZ"),
    "31": ("RVA", "Richmond, VA"),
    # Also support code-based lookups
    "PRE": ("PRE", "Seattle, WA"),
    "CIN": ("CIN", "Cincinnati, OH"),
    "COP": ("COP", "Dallas, TX"),
    "REN": ("REN", "Reno, NV"),
    "NJE": ("NJE", "Robbinsville, NJ"),
    "JAC": ("JAC", "Jacksonville, FL"),
    "MSP": ("MSP", "Minneapolis, MN"),
    "PHX": ("PHX", "Phoenix, AZ"),
    "RVA": ("RVA", "Richmond, VA"),
}


def _safe_float(val: Any) -> float | None:
    """Safely convert a value to float, returning None for invalid/empty values."""
    if val is None:
        return None
    try:
        f = float(val)
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _safe_str(val: Any) -> str:
    """Safely convert to string, returning empty string for None."""
    if val is None:
        return ""
    return str(val).strip()


def _safe_int(val: Any) -> int | None:
    """Safely convert to int, returning None for invalid values."""
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def map_product_info_response(response: Any) -> list[Product]:
    """
    Map the response from getProductInfoByStyleColorSize to Product models.
    
    The response has a .listResponse containing items, each with:
    - .productBasicInfo
    - .productPriceInfo  
    - .productImageInfo
    """
    products = []

    if not hasattr(response, "listResponse") or response.listResponse is None:
        logger.warning("SanMar response has no listResponse")
        return products

    for item in response.listResponse:
        try:
            basic = item.productBasicInfo
            price = item.productPriceInfo
            image = item.productImageInfo

            sanmar_resp = SanMarProductResponse(
                basic=SanMarProductBasicInfo(
                    style=_safe_str(basic.style),
                    brand_name=_safe_str(basic.brandName),
                    color=_safe_str(basic.color),
                    catalog_color=_safe_str(basic.catalogColor),
                    size=_safe_str(basic.size),
                    size_index=_safe_int(basic.sizeIndex),
                    inventory_key=_safe_int(basic.inventoryKey),
                    unique_key=_safe_str(basic.uniqueKey),
                    product_title=_safe_str(basic.productTitle),
                    product_description=_safe_str(basic.productDescription),
                    product_status=_safe_str(basic.productStatus),
                    category=_safe_str(getattr(basic, "category", "")),
                    available_sizes=_safe_str(basic.availableSizes),
                    case_size=_safe_int(basic.caseSize),
                    piece_weight=_safe_float(basic.pieceWeight),
                    keywords=_safe_str(basic.keywords),
                ),
                price=SanMarProductPriceInfo(
                    piece_price=_safe_float(price.piecePrice),
                    case_price=_safe_float(price.casePrice),
                    piece_sale_price=_safe_float(price.pieceSalePrice),
                    case_sale_price=_safe_float(price.caseSalePrice),
                    price_code=_safe_str(price.priceCode),
                    price_text=_safe_str(price.priceText),
                    sale_start_date=_safe_str(getattr(price, "saleStartDate", "")),
                    sale_end_date=_safe_str(getattr(price, "saleEndDate", "")),
                ),
                image=SanMarProductImageInfo(
                    front_model=_safe_str(getattr(image, "frontModel", "")),
                    back_model=_safe_str(getattr(image, "backModel", "")),
                    front_flat=_safe_str(getattr(image, "frontFlat", "")),
                    back_flat=_safe_str(getattr(image, "backFlat", "")),
                    color_swatch_image=_safe_str(image.colorSwatchImage),
                    spec_sheet=_safe_str(image.specSheet),
                    product_image=_safe_str(image.productImage),
                    thumbnail_image=_safe_str(image.thumbnailImage),
                ),
            )

            product = sanmar_resp.to_product()
            products.append(product)

        except Exception as e:
            logger.error(f"Error mapping SanMar product variant: {e}")
            continue

    logger.info(f"Mapped {len(products)} product variants from SanMar response")
    return products


def map_inventory_response(
    response: Any,
    style: str,
    color: str = "",
    size: str = "",
) -> list[InventoryLevel]:
    """
    Map SanMar inventory response to InventoryLevel models.
    
    The inventory response structure varies by endpoint — this handles
    the getInventoryQtyForStyleColorSize response which returns
    per-warehouse quantities.
    """
    levels = []

    if response is None:
        return levels

    # The response may be a dict-like object with warehouse keys or
    # have an inventoryInfo attribute with warehouse data
    try:
        # Handle list-style response (each element is a warehouse entry)
        if hasattr(response, "listResponse") and response.listResponse:
            for item in response.listResponse:
                wh_code = _safe_str(getattr(item, "whseNo", getattr(item, "warehouseCode", "")))
                qty = _safe_int(getattr(item, "qty", getattr(item, "quantity", 0)))
                
                wh_info = SANMAR_WAREHOUSES.get(wh_code, (wh_code, wh_code))
                
                levels.append(InventoryLevel(
                    supplier="sanmar",
                    style=style,
                    color=color,
                    size=size,
                    warehouse=wh_info[0],
                    warehouse_name=wh_info[1],
                    quantity=qty or 0,
                ))
        # Handle dict-like response where keys are warehouse numbers
        elif hasattr(response, "__iter__"):
            for key in response:
                wh_code = str(key)
                qty = _safe_int(response[key]) or 0
                wh_info = SANMAR_WAREHOUSES.get(wh_code, (wh_code, wh_code))
                
                levels.append(InventoryLevel(
                    supplier="sanmar",
                    style=style,
                    color=color,
                    size=size,
                    warehouse=wh_info[0],
                    warehouse_name=wh_info[1],
                    quantity=qty,
                ))
    except Exception as e:
        logger.error(f"Error mapping SanMar inventory: {e}")

    logger.info(f"Mapped {len(levels)} inventory levels for {style}")
    return levels
