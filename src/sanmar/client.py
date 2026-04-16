"""SanMar SOAP API client using zeep."""

import os
import logging
from typing import Any, Optional

from zeep import Client
from zeep.transports import Transport
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

# WSDL endpoints
PRODUCT_WSDL = "https://ws.sanmar.com:8080/SanMarWebService/SanMarProductInfoServicePort?wsdl"
PRICING_WSDL = "https://ws.sanmar.com:8080/SanMarWebService/SanMarPricingServicePort?wsdl"
INVENTORY_WSDL = "https://ws.sanmar.com:8080/SanMarWebService/SanMarWebServicePort?wsdl"


class SanMarClient:
    """Client for SanMar SOAP API."""

    def __init__(
        self,
        customer_number: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ):
        self.customer_number = customer_number or os.getenv("SANMAR_CUSTOMER_NUMBER", "")
        self.username = username or os.getenv("SANMAR_USERNAME", "")
        self.password = password or os.getenv("SANMAR_PASSWORD", "")

        if not all([self.customer_number, self.username, self.password]):
            raise ValueError(
                "SanMar credentials required. Set SANMAR_CUSTOMER_NUMBER, "
                "SANMAR_USERNAME, SANMAR_PASSWORD environment variables."
            )

        self._transport = Transport(timeout=60, operation_timeout=60)
        self._product_client: Client | None = None
        self._pricing_client: Client | None = None
        self._inventory_client: Client | None = None

    @property
    def _credentials(self) -> dict:
        """Standard SanMar credential block for SOAP calls."""
        return {
            "sanMarCustomerNumber": self.customer_number,
            "sanMarUserName": self.username,
            "sanMarUserPassword": self.password,
            "senderId": "",
            "senderPassword": "",
        }

    def _get_product_client(self) -> Client:
        """Lazy-init product WSDL client."""
        if self._product_client is None:
            logger.info("Initializing SanMar Product SOAP client...")
            self._product_client = Client(wsdl=PRODUCT_WSDL, transport=self._transport)
        return self._product_client

    def _get_pricing_client(self) -> Client:
        """Lazy-init pricing WSDL client."""
        if self._pricing_client is None:
            logger.info("Initializing SanMar Pricing SOAP client...")
            self._pricing_client = Client(wsdl=PRICING_WSDL, transport=self._transport)
        return self._pricing_client

    def _get_inventory_client(self) -> Client:
        """Lazy-init inventory WSDL client."""
        if self._inventory_client is None:
            logger.info("Initializing SanMar Inventory SOAP client...")
            self._inventory_client = Client(wsdl=INVENTORY_WSDL, transport=self._transport)
        return self._inventory_client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def get_product_info(
        self,
        style: str,
        color: str = "",
        size: str = "",
    ) -> Any:
        """
        Get product info, pricing, and images for a style.
        
        Pass empty strings for color/size to get ALL variants of a style.
        Returns the raw zeep response object with .listResponse containing
        items with .productBasicInfo, .productPriceInfo, .productImageInfo.
        """
        client = self._get_product_client()
        logger.info(f"Fetching product info: style={style}, color={color}, size={size}")

        response = client.service.getProductInfoByStyleColorSize(
            arg0={"style": style, "color": color, "size": size},
            arg1=self._credentials,
        )

        if hasattr(response, "errorOccurred") and response.errorOccurred:
            msg = getattr(response, "message", "Unknown SanMar API error")
            raise SanMarAPIError(f"SanMar API error for {style}: {msg}")

        return response

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def get_pricing(
        self,
        style: str,
        color: str,
        size: str,
    ) -> Any:
        """Get pricing for a specific style+color+size."""
        client = self._get_pricing_client()
        logger.info(f"Fetching pricing: style={style}, color={color}, size={size}")

        response = client.service.getPricing(
            arg0={"style": style, "color": color, "size": size},
            arg1=self._credentials,
        )

        if hasattr(response, "errorOccurred") and response.errorOccurred:
            msg = getattr(response, "message", "Unknown error")
            raise SanMarAPIError(f"SanMar pricing error for {style}/{color}/{size}: {msg}")

        return response

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def get_inventory(
        self,
        style: str,
        color: str = "",
        size: str = "",
    ) -> Any:
        """
        Get inventory quantities by warehouse.
        
        Pass empty strings for color/size to attempt style-level inventory.
        """
        client = self._get_inventory_client()
        logger.info(f"Fetching inventory: style={style}, color={color}, size={size}")

        response = client.service.getInventoryQtyForStyleColorSize(
            arg0=style,
            arg1=color,
            arg2=size,
            arg3=self._credentials,
        )

        if hasattr(response, "errorOccurred") and response.errorOccurred:
            msg = getattr(response, "message", "Unknown error")
            raise SanMarAPIError(f"SanMar inventory error for {style}: {msg}")

        return response


class SanMarAPIError(Exception):
    """Raised when SanMar API returns an error."""
    pass
