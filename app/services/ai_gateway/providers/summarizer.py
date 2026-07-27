"""
Document Summarizer Provider
"""

from app.config import AI_SUMMARIZER_URL

from app.services.ai_gateway.endpoints import SummarizerEndpoints

from .base import BaseProvider


class SummarizerProvider(BaseProvider):
    """
    Provider for the Document Summarizer service.
    """

    def __init__(self):
        super().__init__(AI_SUMMARIZER_URL)

    async def summarize(
        self,
        data: dict,
        files: dict,
    ) -> dict:

        return await self.upload_sse(
            endpoint=SummarizerEndpoints.SUMMARIZE,
            data=data,
            files=files,
        )