"""
Premium Judgment AI Provider
"""

from __future__ import annotations

from typing import Any

from app.config import AI_PREMIUM_URL

from app.services.ai_gateway.endpoints import PremiumEndpoints
from app.schemas.ai import AIQueryRequest
from .base import BaseProvider


class PremiumProvider(BaseProvider):
    """
    Provider for the Premium Judgment AI service.
    """

    def __init__(self):
        super().__init__(AI_PREMIUM_URL)

    async def search(self, payload: AIQueryRequest) -> dict:
        return await self.post(
            endpoint=PremiumEndpoints.SEARCH,
            payload=payload.dict(),
        )

    async def more(self, payload: AIQueryRequest) -> dict:
        return await self.post(
            endpoint=PremiumEndpoints.MORE,
            payload=payload.dict(),
        )

    async def clarify(self, payload: AIQueryRequest) -> dict:
        return await self.post(
            endpoint=PremiumEndpoints.CLARIFY,
            payload=payload.dict(),
        )

    async def refine(self, payload: AIQueryRequest) -> dict:
        return await self.post(
            endpoint=PremiumEndpoints.REFINE,
            payload=payload.dict(),
        )

    async def similar(self, payload: AIQueryRequest) -> dict:
        return await self.post(
            endpoint=PremiumEndpoints.SIMILAR,
            payload=payload.dict(),
        )

    async def submit_feedback(self, payload: AIQueryRequest) -> dict:
        return await self.post(
            endpoint=PremiumEndpoints.FEEDBACK,
            payload=payload.dict(),
        )