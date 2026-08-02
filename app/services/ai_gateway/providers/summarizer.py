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

    async def summarize_file(self, data: dict, files: dict, force_async: bool = False, force_sync: bool = False) -> dict:
        """
        POST /api/summarize/file — multipart, file-only. No document_text
        field; text is extracted from the uploaded file server-side
        (max 20MB, .pdf/.docx/.txt only).

        Vendor now branches on document size: small docs return the full
        result inline (mode: "sync"); large docs return HTTP 202 with a
        job_id instead (mode: "async") — see get_job_status/get_job_result.
        `force_async`/`force_sync` map to the vendor's own query params.
        """
        endpoint = SummarizerEndpoints.SUMMARIZE_FILE
        if force_async:
            endpoint += "?force_async=true"
        elif force_sync:
            endpoint += "?force_sync=true"

        return await self.upload(
            endpoint=endpoint,
            data=data,
            files=files,
        )

    async def get_job_status(self, job_id: str) -> dict:
        """GET /api/summarize/status/{job_id}"""
        return await self.get(endpoint=f"{SummarizerEndpoints.STATUS}/{job_id}")

    async def get_job_result(self, job_id: str) -> dict:
        """GET /api/summarize/result/{job_id}"""
        return await self.get(endpoint=f"{SummarizerEndpoints.RESULT}/{job_id}")
