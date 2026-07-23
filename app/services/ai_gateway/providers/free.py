"""
Free Judgment AI Provider
"""

from __future__ import annotations

from typing import Any

from app.config import AI_FREE_URL

from app.services.ai_gateway.endpoints import FreeEndpoints
from app.schemas.ai import AIQueryRequest
from .base import BaseProvider


class FreeProvider(BaseProvider):
    """
    Provider for the Free Judgment AI service.
    """

    def __init__(self):
        super().__init__(AI_FREE_URL)

    async def search(self, payload: AIQueryRequest) -> dict:
        return await self.post(
            endpoint=FreeEndpoints.SEARCH,
            payload=payload.dict(),
        )

    async def more(self, payload: AIQueryRequest) -> dict:
        return await self.post(
            endpoint=FreeEndpoints.MORE,
            payload=payload.dict(),
        )

    async def clarify(self, payload: AIQueryRequest) -> dict:
        return await self.post(
            endpoint=FreeEndpoints.CLARIFY,
            payload=payload.dict(),
        )

    async def refine(self, payload: AIQueryRequest) -> dict:
        return await self.post(
            endpoint=FreeEndpoints.REFINE,
            payload=payload.dict(),
        )

    async def similar(self, payload: AIQueryRequest) -> dict:
        return await self.post(
            endpoint=FreeEndpoints.SIMILAR,
            payload=payload.dict(),
        )