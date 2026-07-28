"""
Notice Reply AI Provider
"""

from app.config import AI_NOTICE_URL

from app.services.ai_gateway.endpoints import NoticeEndpoints

from .base import BaseProvider


class NoticeProvider(BaseProvider):
    """
    Provider for the Notice Reply service. Two separate, mutually
    exclusive vendor endpoints (confirmed against the vendor's actual
    FastAPI source) — never both at once.
    """

    def __init__(self):
        super().__init__(AI_NOTICE_URL)

    async def generate_from_text(self, data: dict) -> dict:
        """
        POST /api/notice/process — JSON body, text-only.
        Vendor's NoticeRequest reads: notice_text, user_name,
        business_name, gstin, address. No file, no session/message ids —
        sending fields it doesn't expect risks a 422 if the model forbids
        extras, so `data` should contain exactly those fields.
        """
        return await self.post(
            endpoint=NoticeEndpoints.PROCESS_TEXT,
            payload=data,
        )

    async def generate_from_file(self, data: dict, files: dict) -> dict:
        """
        POST /api/notice/process-file — multipart, file-only. No
        notice_text field exists on this endpoint; the vendor extracts
        text from the uploaded file itself. Only .pdf/.docx/.txt accepted.
        """
        return await self.upload(
            endpoint=NoticeEndpoints.PROCESS_FILE,
            data=data,
            files=files,
        )

    async def get_notice_types(self) -> dict:
        """GET /api/notice/types"""
        return await self.get(endpoint=NoticeEndpoints.TYPES)
