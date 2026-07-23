"""
Main AI Provider

Handles communication with the primary AI service.
"""

from __future__ import annotations
from typing import Any
from app.config import AI_MAIN_URL
from .base import BaseProvider
from app.services.ai_gateway.endpoints import MainEndpoints
from app.schemas.ai import AIQueryRequest

class MainProvider(BaseProvider):
    """
    Provider for the Main AI service.
    """

    def __init__(self):
        super().__init__(AI_MAIN_URL)

    async def query(self, payload: AIQueryRequest) -> dict:
        """
        Submit a query to the main AI.
        """
        return await self.post(
            endpoint=MainEndpoints.QUERY,
            payload=payload,
        )

    async def query_v2(self, payload: AIQueryRequest) -> dict:
        """
        Submit a query using API v2.
        """
        return await self.post(
            endpoint=MainEndpoints.QUERY_V2,
            payload=payload.dict(),
        )

    async def clarify(self, payload: AIQueryRequest) -> dict:
        """
        Generate clarification questions.
        """
        return await self.post(
            endpoint=MainEndpoints.CLARIFY,
            payload=payload.dict(),
        )

    async def refine(self, payload: AIQueryRequest) -> dict:
        """
        Refine an existing answer.
        """
        return await self.post(
            endpoint=MainEndpoints.REFINE,
            payload=payload.dict(),
        )

    async def case_laws(self, payload: AIQueryRequest) -> dict:
        """
        Retrieve related case laws.
        """
        return await self.post(
            endpoint=MainEndpoints.CASE_LAWS,
            payload=payload.dict(),
        )

    async def create_session(self, payload: AIQueryRequest) -> dict:
        """
        Create or update an AI session.
        """
        return await self.post(
            endpoint=MainEndpoints.SESSIONS,
            payload=payload.dict(),
        )

    async def submit_feedback(self, payload: AIQueryRequest) -> dict:
        """
        Submit user feedback.
        """
        return await self.post(
            endpoint=MainEndpoints.FEEDBACK,
            payload=payload.dict(),
        )

    async def analytics(self, payload: AIQueryRequest) -> dict:
        """
        Fetch analytics information.
        """
        return await self.post(
            endpoint=MainEndpoints.ANALYTICS,
            payload=payload.dict(),
        )