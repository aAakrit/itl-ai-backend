"""
Document Summarizer AI Provider
"""

from app.config import AI_SUMMARIZER_URL

from app.services.ai_gateway.endpoints import SummarizerEndpoints

from .base import BaseProvider


class SummarizerProvider(BaseProvider):
    """
    Provider for the Document Summarizer service. Two separate, mutually
    exclusive vendor endpoints (confirmed against the vendor's actual
    FastAPI source) — never both at once. Neither streams SSE; both are
    plain JSON responses (a prior doc claimed otherwise — the actual
    source code overrides that).
    """

    def __init__(self):
        super().__init__(AI_SUMMARIZER_URL)

    async def summarize_text(self, data: dict) -> dict:
        """
        POST /api/summarize/text — JSON body, text-only.
        Vendor's SummarizeTextRequest: document_text (required, 50-200000
        chars), user_instructions (optional, max 2000), output_format
        (optional). No file, no session/message ids.
        """
        return await self.post(
            endpoint=SummarizerEndpoints.SUMMARIZE_TEXT,
            payload=data,
        )

    async def summarize_file(self, data: dict, files: dict) -> dict:
        """
        POST /api/summarize/file — multipart, file-only. No document_text
        field; text is extracted from the uploaded file server-side
        (max 20MB, .pdf/.docx/.txt only).
        """
        return await self.upload(
            endpoint=SummarizerEndpoints.SUMMARIZE_FILE,
            data=data,
            files=files,
        )
