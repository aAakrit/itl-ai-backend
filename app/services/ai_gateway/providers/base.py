"""
Base provider for all AI services.

Provides:
- Shared GatewayClient instance
- Base URL configuration
- Common HTTP helper methods

Concrete providers should inherit from this class and implement
their own business-specific methods.
"""

from __future__ import annotations

from typing import Any

from app.services.ai_gateway.client import gateway_client


class BaseProvider:
    """
    Base class for all AI providers.
    """

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.client = gateway_client

    async def get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> dict:
        """
        Execute a GET request.
        """
        return await self.client.get(
            base_url=self.base_url,
            endpoint=endpoint,
            params=params,
        )

    async def post(
        self,
        endpoint: str,
        payload: dict[str, Any],
    ) -> dict:
        """
        Execute a JSON POST request.
        """
        return await self.client.post_json(
            base_url=self.base_url,
            endpoint=endpoint,
            payload=payload,
        )

    async def upload(
        self,
        endpoint: str,
        data: dict[str, Any],
        files: dict[str, Any],
    ) -> dict:
        """
        Execute a multipart/form-data request.
        """
        return await self.client.post_multipart(
            base_url=self.base_url,
            endpoint=endpoint,
            data=data,
            files=files,
        )

    async def health(self) -> dict:
        """
        Check provider health.
        """
        return await self.client.health(self.base_url)