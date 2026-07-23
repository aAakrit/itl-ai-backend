"""
Notice Reply AI Provider
"""

from app.config import AI_NOTICE_URL

from app.services.ai_gateway.endpoints import NoticeEndpoints

from .base import BaseProvider


class NoticeProvider(BaseProvider):
    """
    Provider for the Notice Reply service.
    """

    def __init__(self):
        super().__init__(AI_NOTICE_URL)

    async def generate(
        self,
        data: dict,
        files: dict,
    ) -> dict:
        return await self.upload(
            endpoint=NoticeEndpoints.GENERATE,
            data=data,
            files=files,
        )