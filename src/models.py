"""Pydantic models for normalized apparel data across suppliers."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional
from pydantic import BaseModel, Field


class TrackedStyle(BaseModel):
    """A style being tracked from a supplier."""
    id: Optional[int] = None
    supplier: Literal["sanmar", "ssactivewear"]
    style: str
    brand: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    is_active: bool = True
    added_at: Optional[datetime] = None
    last_synced: Optional[datetime] = None


class Product(BaseModel):
    """Normalized product record (one per supplier+style+color+size)."""
    tracked_style_id: Optional[int] = None
    supplier: Literal["sanmar", "ssactivewear"]
    style: str
    brand: Optional[str] = None
    color: str
    catalog_color: Optional[str] = None  # SanMar mainframe color
    size: str
    sku: Optional[str] = None
    gtin: Optional[str] = None
    piece_price: Optional[float] = None
    case_price: Optional[float] = None
    sale_price: Optional[float] = None
    sale_end_date: Optional[str] = None
    customer_price: Optional[float] = None
    map_price: Optional[float] = None
    case_qty: Optional[int] = None
    price_code: Optional[str] = None       # SanMar discount tier
    price_text: Optional[str] = None       # SanMar size range note
    size_price_code: Optional[str] = None  # S&S sizePriceCodeName
    weight: Optional[float] = None
    product_status: Optional[str] = None
    country_of_origin: Optional[str] = None
    front_image_url: Optional[str] = None
    back_image_url: Optional[str] = None
    swatch_image_url: Optional[str] = None
    spec_sheet_url: Optional[str] = None
    noe_retailing: bool = False
    last_synced: Optional[datetime] = None


class InventoryLevel(BaseModel):
    """Warehouse-level inventory for a product."""
    supplier: Literal["sanmar", "ssactivewear"]
    style: str
    color: str
    size: str
    warehouse: str
    warehouse_name: Optional[str] = None
    quantity: int = 0
    is_closeout: bool = False
    is_dropship: bool = False
    last_synced: Optional[datetime] = None


class PriceChange(BaseModel):
    """A detected price change during sync."""
    supplier: str
    style: str
    color: str
    size: str
    price_type: Literal["piece", "case", "sale", "customer", "map"]
    old_price: Optional[float] = None
    new_price: Optional[float] = None
    changed_at: Optional[datetime] = None


class SyncResult(BaseModel):
    """Result summary from a sync job run."""
    supplier: str
    sync_type: str
    styles_synced: int = 0
    skus_updated: int = 0
    price_changes: int = 0
    errors: int = 0
    error_details: list[str] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: str = "running"


# ─── SanMar-specific models (mapped from SOAP responses) ───

class SanMarProductBasicInfo(BaseModel):
    """Mapped from SanMar SOAP productBasicInfo."""
    style: str
    brand_name: str = ""
    color: str = ""            # display color
    catalog_color: str = ""    # mainframe ordering color
    size: str = ""
    size_index: Optional[int] = None
    inventory_key: Optional[int] = None
    unique_key: Optional[str] = None
    product_title: str = ""
    product_description: str = ""
    product_status: str = ""
    category: str = ""
    available_sizes: str = ""
    case_size: Optional[int] = None
    piece_weight: Optional[float] = None
    keywords: str = ""


class SanMarProductPriceInfo(BaseModel):
    """Mapped from SanMar SOAP productPriceInfo."""
    piece_price: Optional[float] = None
    case_price: Optional[float] = None
    piece_sale_price: Optional[float] = None
    case_sale_price: Optional[float] = None
    price_code: str = ""
    price_text: str = ""
    sale_start_date: Optional[str] = None
    sale_end_date: Optional[str] = None


class SanMarProductImageInfo(BaseModel):
    """Mapped from SanMar SOAP productImageInfo."""
    front_model: str = ""
    back_model: str = ""
    front_flat: str = ""
    back_flat: str = ""
    color_swatch_image: str = ""
    spec_sheet: str = ""
    product_image: str = ""
    thumbnail_image: str = ""


class SanMarProductResponse(BaseModel):
    """A single product variant from SanMar SOAP response."""
    basic: SanMarProductBasicInfo
    price: SanMarProductPriceInfo
    image: SanMarProductImageInfo

    def to_product(self) -> Product:
        """Convert to normalized Product model."""
        return Product(
            supplier="sanmar",
            style=self.basic.style,
            brand=self.basic.brand_name,
            color=self.basic.color,
            catalog_color=self.basic.catalog_color,
            size=self.basic.size,
            sku=self.basic.unique_key,
            piece_price=self.price.piece_price,
            case_price=self.price.case_price,
            sale_price=self.price.piece_sale_price,
            sale_end_date=self.price.sale_end_date,
            case_qty=self.basic.case_size,
            price_code=self.price.price_code,
            price_text=self.price.price_text,
            weight=self.basic.piece_weight,
            product_status=self.basic.product_status,
            front_image_url=self.image.front_model or self.image.front_flat,
            back_image_url=self.image.back_model or self.image.back_flat,
            swatch_image_url=self.image.color_swatch_image,
            spec_sheet_url=self.image.spec_sheet,
        )


# ─── S&S Activewear-specific models (mapped from REST JSON) ───

SS_CDN_BASE = "https://cdn.ssactivewear.com/"


class SSProductResponse(BaseModel):
    """A single SKU from S&S REST /v2/products/ response."""
    sku: str = ""
    gtin: str = ""
    style_id: Optional[int] = None
    brand_name: str = ""
    style_name: str = ""
    color_name: str = ""
    color_code: str = ""
    size_name: str = ""
    size_price_code_name: str = ""
    case_qty: Optional[int] = None
    unit_weight: Optional[float] = None
    map_price: Optional[float] = None
    piece_price: Optional[float] = None
    dozen_price: Optional[float] = None  # deprecated but still returned
    case_price: Optional[float] = None
    sale_price: Optional[float] = None
    customer_price: Optional[float] = None
    sale_expiration: Optional[str] = None
    noe_retailing: bool = False
    country_of_origin: str = ""
    color_front_image: str = ""
    color_back_image: str = ""
    color_swatch_image: str = ""
    qty: int = 0
    warehouses: list[dict] = Field(default_factory=list)

    def _prepend_cdn(self, path: str) -> str:
        """Prepend S&S CDN base URL to relative image paths."""
        if not path:
            return ""
        if path.startswith("http"):
            return path
        return f"{SS_CDN_BASE}{path}"

    def to_product(self) -> Product:
        """Convert to normalized Product model."""
        return Product(
            supplier="ssactivewear",
            style=self.style_name,
            brand=self.brand_name,
            color=self.color_name,
            size=self.size_name,
            sku=self.sku,
            gtin=self.gtin,
            piece_price=self.piece_price,
            case_price=self.case_price,
            sale_price=self.sale_price,
            sale_end_date=self.sale_expiration,
            customer_price=self.customer_price,
            map_price=self.map_price,
            case_qty=self.case_qty,
            size_price_code=self.size_price_code_name,
            weight=self.unit_weight,
            country_of_origin=self.country_of_origin,
            front_image_url=self._prepend_cdn(self.color_front_image),
            back_image_url=self._prepend_cdn(self.color_back_image),
            swatch_image_url=self._prepend_cdn(self.color_swatch_image),
            noe_retailing=self.noe_retailing,
        )

    def to_inventory_levels(self) -> list[InventoryLevel]:
        """Extract warehouse inventory from the embedded warehouses array."""
        SS_WAREHOUSE_NAMES = {
            "IL": "Bolingbrook, IL",
            "NV": "Nevada",
            "KS": "Kansas",
            "PA": "Pennsylvania",
            "NJ": "New Jersey",
        }
        levels = []
        for wh in self.warehouses:
            abbr = wh.get("warehouseAbbr", "")
            levels.append(InventoryLevel(
                supplier="ssactivewear",
                style=self.style_name,
                color=self.color_name,
                size=self.size_name,
                warehouse=abbr,
                warehouse_name=SS_WAREHOUSE_NAMES.get(abbr, abbr),
                quantity=wh.get("qty", 0),
                is_closeout=wh.get("closeout", False),
                is_dropship=wh.get("dropship", False),
            ))
        return levels
