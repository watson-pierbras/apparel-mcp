"""S&S Activewear REST API client.

Read-only client for S&S Activewear's V2 REST API.
All endpoints are HTTP GET — zero ordering or purchasing capability.

API docs: https://api.ssactivewear.com/v2/
Rate limit: 60 requests per minute
Auth: HTTP Basic (account number + API key)
"""

import asyncio
import logging
import os
import time
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://api.ssactivewear.com/v2"
CDN_BASE = "https://cdn.ssactivewear.com/"

# Stay under 60/min with a safety buffer
MAX_REQUESTS_PER_MINUTE = 55
MIN_REQUEST_INTERVAL = 60.0 / MAX_REQUESTS_PER_MINUTE  # ~1.09s

# In-memory catalog cache — S&S /styles/ returns the full catalog (~5700 rows,
# ~6MB) in about 1s. We cache it so repeat lookups by styleName are instant.
# Refreshed every 15 minutes to pick up new styles.
_CATALOG_TTL_SEC = 900
_catalog_cache: dict[str, Any] = {"fetched_at": 0.0, "data": []}
_catalog_lock = asyncio.Lock()


class SSActivewearAPIError(Exception):
    """Raised when S&S Activewear API returns an error."""
    pass


class SSClient:
    """Async client for S&S Activewear REST API (read-only)."""

    def __init__(
        self,
        account_number: str | None = None,
        api_key: str | None = None,
    ):
        self.account_number = account_number or os.getenv("SS_ACCOUNT_NUMBER", "")
        self.api_key = api_key or os.getenv("SS_API_KEY", "")

        if not self.account_number or not self.api_key:
            raise ValueError(
                "S&S Activewear credentials required. Set SS_ACCOUNT_NUMBER "
                "and SS_API_KEY environment variables."
            )

        self._auth = httpx.BasicAuth(self.account_number, self.api_key)
        self._last_request_time: float = 0.0
        self._request_lock = asyncio.Lock()

    def _get_client(self) -> httpx.AsyncClient:
        """Create a new httpx client for each request context."""
        return httpx.AsyncClient(
            base_url=BASE_URL,
            auth=self._auth,
            timeout=httpx.Timeout(60.0, connect=15.0),
            headers={"Accept": "application/json"},
        )

    async def _throttle(self) -> None:
        """Simple rate limiter — enforces minimum interval between requests."""
        async with self._request_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < MIN_REQUEST_INTERVAL:
                wait = MIN_REQUEST_INTERVAL - elapsed
                logger.debug(f"Rate limiting: waiting {wait:.2f}s")
                await asyncio.sleep(wait)
            self._last_request_time = time.monotonic()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
        reraise=True,
    )
    async def _get(self, path: str, params: dict | None = None) -> Any:
        """Execute a GET request with rate limiting and retry."""
        await self._throttle()

        async with self._get_client() as client:
            logger.info(f"S&S API GET: {path} params={params}")
            response = await client.get(path, params=params)

            # Log remaining rate limit if header present
            remaining = response.headers.get("X-Rate-Limit-Remaining")
            if remaining:
                logger.debug(f"S&S rate limit remaining: {remaining}")

            if response.status_code == 404:
                # S&S returns 404 for not-found items with an error envelope
                return None

            response.raise_for_status()

            data = response.json()

            # Check for error envelope: {"errors": [{"field": ..., "message": ...}]}
            if isinstance(data, dict) and "errors" in data:
                errors = data["errors"]
                msgs = [e.get("message", str(e)) for e in errors]
                raise SSActivewearAPIError(f"S&S API error: {'; '.join(msgs)}")

            return data

    # ─── Product Methods ───────────────────────────────────────

    async def _get_catalog(self) -> list[dict]:
        """Fetch the full S&S style catalog, cached in-memory for 15 min.

        S&S's /styles/ endpoint (no path arg) returns the full style catalog
        in one call — ~5,700 rows, ~6MB JSON, ~1s latency. It's the only
        reliable way to resolve a manufacturer styleName (e.g. '8667', '3001',
        '567P') to its internal styleID when the caller can't provide a brand.

        Strategy: fetch once per 15-minute window, hold in memory, serve all
        styleName lookups from the cached list. Cache is shared across all
        SSClient instances via a module-level dict.

        Returns:
            List of style dicts (may be empty on API failure).
        """
        async with _catalog_lock:
            now = time.monotonic()
            age = now - _catalog_cache["fetched_at"]
            if _catalog_cache["data"] and age < _CATALOG_TTL_SEC:
                logger.debug(f"S&S catalog cache hit (age={age:.0f}s, {len(_catalog_cache['data'])} styles)")
                return _catalog_cache["data"]

            logger.info("S&S catalog cache miss — fetching full /styles/ list")
            try:
                data = await self._get("/styles/")
            except Exception as e:
                logger.warning(f"Failed to refresh S&S catalog: {e}")
                # On failure, return whatever we have (even if stale/empty)
                return _catalog_cache["data"]

            if not isinstance(data, list):
                data = [data] if data else []

            _catalog_cache["data"] = data
            _catalog_cache["fetched_at"] = now
            logger.info(f"S&S catalog cached: {len(data)} styles")
            return data

    async def resolve_style_id(
        self,
        style: str,
        brand: str = "",
    ) -> dict | None:
        """Resolve a user-supplied style identifier to a specific S&S style record.

        Handles the core S&S lookup trap: the /products/ endpoint's ?style=
        parameter matches against styleID (numeric internal ID) and partNumber,
        NOT styleName. So raw manufacturer style numbers like '8667' either
        404 (no such styleID) or return the WRONG product (e.g. '8967' →
        DRI DUCK 7355 because styleID=8967 belongs to that unrelated product).

        Resolution order (fastest → slowest):
        1. If `brand` is given → hit /styles/{Brand} {styleName} (single API call,
           returns exact match).
        2. Otherwise → scan the cached /styles/ catalog for an exact styleName
           match. If 1 hit → return it. If multiple hits across brands →
           return the list as a dict with ambiguity marker.

        Args:
            style: Manufacturer style number (e.g. '8667', '3001', '567P') OR
                   S&S partNumber (e.g. '17585', '00606').
            brand: Optional brand name to disambiguate (e.g. 'Alleson Athletic',
                   'Bella+Canvas'). Strongly recommended when the style number
                   could collide across brands.

        Returns:
            - Single matching style dict (has styleID, styleName, partNumber,
              brandName, title) on unique match.
            - Dict with key 'ambiguous' and 'matches' list if multiple brands
              use the same styleName.
            - None if no match found.
        """
        if not style:
            return None

        style_norm = style.strip().upper()

        # Strategy 1: brand + style path lookup — most precise, single API call
        if brand:
            brand_clean = brand.strip()
            # Try exact 'Brand StyleName' first — S&S accepts spaces in path
            path = f"/styles/{brand_clean} {style.strip()}"
            try:
                data = await self._get(path)
            except Exception as e:
                logger.warning(f"Brand+style path lookup failed: {e}")
                data = None

            if data:
                matches = data if isinstance(data, list) else [data]
                # Filter to exact styleName match (defensive)
                exact = [
                    m for m in matches
                    if str(m.get("styleName", "")).upper() == style_norm
                ]
                if exact:
                    logger.info(
                        f"Resolved '{brand} {style}' via brand+style path → "
                        f"styleID={exact[0].get('styleID')}, "
                        f"partNumber={exact[0].get('partNumber')}"
                    )
                    return exact[0]

        # Strategy 2: catalog scan by styleName (works without brand hint)
        catalog = await self._get_catalog()
        if catalog:
            name_hits = [
                s for s in catalog
                if str(s.get("styleName", "")).upper() == style_norm
            ]

            # Narrow by brand if supplied and we found multiple hits
            if name_hits and brand:
                brand_lower = brand.strip().lower()
                brand_filtered = [
                    s for s in name_hits
                    if brand_lower in str(s.get("brandName", "")).lower()
                    or str(s.get("brandName", "")).lower() in brand_lower
                ]
                if brand_filtered:
                    name_hits = brand_filtered

            if len(name_hits) == 1:
                hit = name_hits[0]
                logger.info(
                    f"Resolved styleName '{style}' via catalog → "
                    f"styleID={hit.get('styleID')}, "
                    f"partNumber={hit.get('partNumber')}, "
                    f"brand={hit.get('brandName')}"
                )
                return hit

            if len(name_hits) > 1:
                logger.info(
                    f"Ambiguous styleName '{style}' — {len(name_hits)} brands match"
                )
                return {"ambiguous": True, "matches": name_hits}

            # Strategy 2b: maybe it's a partNumber not a styleName
            part_hits = [
                s for s in catalog
                if str(s.get("partNumber", "")).upper() == style_norm
            ]
            if len(part_hits) == 1:
                hit = part_hits[0]
                logger.info(
                    f"Resolved partNumber '{style}' via catalog → "
                    f"styleID={hit.get('styleID')}, brand={hit.get('brandName')}"
                )
                return hit

        # Strategy 3: last-resort direct /styles/{X} lookup (only matches
        # numeric styleID — kept for partNumber-like inputs as a fallback)
        try:
            data = await self._get(f"/styles/{style}")
        except Exception:
            data = None
        if data:
            match = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else None)
            if match:
                logger.info(
                    f"Resolved '{style}' via direct /styles/ path → "
                    f"styleID={match.get('styleID')}, brand={match.get('brandName')}"
                )
                return match

        return None

    async def get_products(
        self,
        style: str,
        color: str = "",
        size: str = "",
        brand: str = "",
    ) -> list[dict]:
        """Get all product SKUs for a style, with pricing and inventory.

        S&S uses three identifiers, and ONLY styleID is reliable for /products/:
          • styleID    — numeric internal (e.g. 4560 = Alleson 8667)
          • partNumber — S&S SKU prefix (e.g. '17585', '00606')
          • styleName  — manufacturer's number (e.g. '8667', '3001', '567P')

        The ?style= query param matches against styleID and partNumber but
        NOT styleName. So a raw '8667' either 404s (no such styleID) or
        returns a completely different product (e.g. '8967' collides with
        DRI DUCK's styleID=8967).

        Correct approach: resolve styleName → styleID first via
        `resolve_style_id`, then call ?styleId={N}.

        Args:
            style: Style number, part number, or styleID. Accepts anything the
                   user might paste — we'll figure it out.
            color: Optional color name filter (client-side substring).
            size: Optional size name filter (client-side exact).
            brand: Optional brand hint — strongly recommended when the style
                   number could collide across brands (e.g. any 4-digit number).

        Returns:
            List of product dicts (one per SKU/color/size combo), each with
            embedded warehouses[] for inventory. Returns empty list if the
            style can't be resolved or returns no SKUs.

        Raises:
            SSActivewearAPIError: if the styleName is ambiguous across brands
                and no brand hint was supplied. The error message lists the
                matching brands so the caller can disambiguate.
        """
        # Step 1 — resolve to a canonical style record
        resolved = await self.resolve_style_id(style, brand=brand)

        if not resolved:
            # Last-ditch: maybe the raw ?style= still works (e.g. a true
            # partNumber that isn't in the catalog yet)
            logger.info(f"No catalog match for '{style}', trying direct ?style=")
            raw = await self._get("/products/", params={"style": style})
            if raw:
                data = raw if isinstance(raw, list) else [raw]
                return self._apply_sku_filters(data, color, size)
            return []

        # Handle ambiguity — bubble up a useful error
        if resolved.get("ambiguous"):
            matches = resolved["matches"]
            brand_list = ", ".join(
                f"{m.get('brandName', '?')} ({m.get('title', '?')})"
                for m in matches[:5]
            )
            raise SSActivewearAPIError(
                f"Style '{style}' exists in {len(matches)} brands: {brand_list}. "
                f"Pass brand='<BrandName>' to disambiguate."
            )

        # Step 2 — fetch all SKUs via styleID (the only 100%-reliable method)
        style_id = resolved.get("styleID")
        if not style_id:
            return []

        data = await self._get("/products/", params={"styleId": style_id})

        if not data:
            # Odd case: catalog has the style but /products/ returned nothing.
            # Try partNumber as a secondary path.
            part_number = resolved.get("partNumber", "")
            if part_number:
                logger.info(f"styleId={style_id} returned 0 products, trying partNumber={part_number}")
                data = await self._get("/products/", params={"style": part_number})

        if not data:
            return []

        if not isinstance(data, list):
            data = [data]

        return self._apply_sku_filters(data, color, size)

    @staticmethod
    def _apply_sku_filters(data: list[dict], color: str, size: str) -> list[dict]:
        """Apply client-side color/size filters to a product list.

        S&S's /products/ endpoint does not support color or size filters,
        so we filter locally. Color match is substring (case-insensitive),
        size match is exact (case-insensitive).
        """
        if color:
            color_lower = color.lower()
            data = [p for p in data if color_lower in (p.get("colorName", "") or "").lower()]
        if size:
            size_upper = size.upper()
            data = [p for p in data if (p.get("sizeName", "") or "").upper() == size_upper]
        logger.info(f"S&S get_products: {len(data)} SKUs after filtering (color={color!r}, size={size!r})")
        return data

    async def get_products_by_style_id(self, style_id: int) -> list[dict]:
        """Fetch all product SKUs using the numeric styleID (most reliable method).

        This is the approach used by vendo-server — fetches via ?styleId={numeric}
        which is the most reliable way to get S&S product data.

        Args:
            style_id: Numeric S&S styleID (e.g. 9182)

        Returns:
            List of product dicts (one per SKU/color/size combo).
        """
        data = await self._get("/products/", params={"styleId": style_id})
        if not data:
            return []
        if not isinstance(data, list):
            data = [data]
        logger.info(f"S&S get_products_by_style_id({style_id}): {len(data)} SKUs returned")
        return data

    async def get_style(self, style: str) -> dict | None:
        """Get style-level info (brand, title, description, category).

        Args:
            style: Style identifier — styleID, partNumber, or 'BrandName StyleName'

        Returns:
            Style dict or None if not found.
        """
        data = await self._get(f"/styles/{style}")

        if not data:
            return None

        # If multiple styles returned (e.g. partial match), return first
        if isinstance(data, list):
            return data[0] if data else None

        return data

    async def search_styles(
        self,
        query: str = "",
        brand: str = "",
    ) -> list[dict]:
        """Search S&S catalog by keyword, brand, or style identifier.

        The official /styles/search= endpoint is effectively non-functional —
        it returns an empty list for nearly every query we've tested. Instead,
        we search the cached full-catalog list (/styles/) client-side, which
        is fast (instant after first warm), reliable, and supports rich
        filtering without hammering the S&S API.

        Args:
            query: Keyword / style number / part number (e.g. '3001', 'track singlet')
            brand: Brand name filter (e.g. 'Alleson Athletic', 'Bella+Canvas')

        Returns:
            List of style dicts matching the filters.
        """
        if not (query or brand):
            return []

        catalog = await self._get_catalog()
        if not catalog:
            return []

        query_lower = query.strip().lower() if query else ""
        query_upper = query.strip().upper() if query else ""
        brand_lower = brand.strip().lower() if brand else ""

        def _matches(s: dict) -> bool:
            # Brand filter is strict: must match brandName (substring,
            # case-insensitive, bidirectional to handle 'Bella' vs 'Bella+Canvas').
            if brand_lower:
                bn = str(s.get("brandName", "")).lower()
                if brand_lower not in bn and bn not in brand_lower:
                    return False

            # Query filter matches styleName/partNumber/title/description/category.
            if query_lower:
                # Exact styleName/partNumber is the strongest signal
                if str(s.get("styleName", "")).upper() == query_upper:
                    return True
                if str(s.get("partNumber", "")).upper() == query_upper:
                    return True
                # Fall back to substring match across text fields
                haystack = " ".join([
                    str(s.get("styleName", "")),
                    str(s.get("title", "")),
                    str(s.get("description") or ""),
                    str(s.get("baseCategory", "")),
                ]).lower()
                if query_lower not in haystack:
                    return False

            return True

        results = [s for s in catalog if _matches(s)]

        # Stable ordering: exact styleName matches first, then title matches,
        # then everything else — makes the first result the most relevant.
        def _score(s: dict) -> int:
            if not query_upper:
                return 2
            if str(s.get("styleName", "")).upper() == query_upper:
                return 0
            if str(s.get("partNumber", "")).upper() == query_upper:
                return 1
            return 2

        results.sort(key=_score)

        logger.info(
            f"S&S search_styles(query={query!r}, brand={brand!r}): "
            f"{len(results)} styles found in catalog of {len(catalog)}"
        )
        return results

    async def get_brands(self) -> list[dict]:
        """Get all available brands.

        Returns:
            List of brand dicts with brandID, name, image, noeRetailing.
        """
        data = await self._get("/Brands/")
        return data if isinstance(data, list) else []

    async def get_categories(self) -> list[dict]:
        """Get all available categories.

        Returns:
            List of category dicts with categoryID, name.
        """
        data = await self._get("/categories/")
        return data if isinstance(data, list) else []
