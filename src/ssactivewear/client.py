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

    async def get_products(
        self,
        style: str,
        color: str = "",
        size: str = "",
    ) -> list[dict]:
        """Get all product SKUs for a style, with pricing and inventory.

        S&S uses two identifiers: partNumber (S&S internal, e.g. '00760')
        and styleName (manufacturer's, e.g. '2000', '8668', '3001').
        The ?style= param accepts partNumber, StyleID, or BrandName+Name.
        We try ?style= first, then fall back to finding the partNumber
        via the styles endpoint if no results are returned.

        Args:
            style: Style number or part number (e.g. '8668', '00760', 'Gildan 5000')
            color: Optional color name to filter results client-side
            size: Optional size name to filter results client-side

        Returns:
            List of product dicts (one per SKU/color/size combo), each with
            embedded warehouses[] for inventory.
        """
        # Try direct ?style= query first (works with partNumber and StyleID)
        data = await self._get("/products/", params={"style": style})

        # If no results, the input might be a manufacturer styleName (e.g. '3001', '8668').
        # Look up the partNumber via the styles endpoint, then re-query products.
        if not data:
            logger.info(f"S&S products ?style={style} returned nothing, trying styles lookup")
            style_info = await self._get(f"/styles/{style}")
            if style_info:
                # styles endpoint may return a list or single dict
                if isinstance(style_info, list):
                    # Find exact styleName match if possible
                    match = None
                    for s in style_info:
                        if s.get("styleName", "").upper() == style.upper():
                            match = s
                            break
                    if not match:
                        match = style_info[0]
                else:
                    match = style_info

                part_number = match.get("partNumber", "")
                if part_number and part_number != style:
                    logger.info(f"Found partNumber '{part_number}' for styleName '{style}', re-querying products")
                    data = await self._get("/products/", params={"style": part_number})

        if not data:
            return []

        # Response is a flat JSON array of product objects
        if not isinstance(data, list):
            data = [data]

        # Client-side filtering (S&S doesn't support color/size query params)
        if color:
            color_lower = color.lower()
            data = [p for p in data if color_lower in p.get("colorName", "").lower()]
        if size:
            size_upper = size.upper()
            data = [p for p in data if p.get("sizeName", "").upper() == size_upper]

        logger.info(f"S&S get_products({style}): {len(data)} SKUs returned")
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

    async def search_styles(self, query: str) -> list[dict]:
        """Search S&S catalog by keyword.

        Args:
            query: Search term (e.g. 'track singlet', 'Bella+Canvas', 'performance tee')

        Returns:
            List of style dicts matching the query.
        """
        data = await self._get(f"/styles/search={query}")

        if not data:
            return []

        if not isinstance(data, list):
            data = [data]

        logger.info(f"S&S search_styles({query}): {len(data)} styles found")
        return data

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
