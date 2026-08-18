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

    # ------------------------------------------------------------------
    # Staged conversational workflow (Aug 2026 contract, Part B)
    # ------------------------------------------------------------------

    async def create_session(self, payload: dict) -> dict:
        """
        POST /api/v2/sessions — shared session envelope (§0), called once
        per conversation. Mints a session_token that every later analyze/
        draft/refine/ask call for this conversation reuses.
        """
        return await self.post(
            endpoint=NoticeEndpoints.SESSIONS,
            payload=payload,
        )

    async def analyze(self, payload: dict) -> dict:
        """
        POST /api/notice/analyze — Stage 1 (pasted/typed notice text).
        Returns summary + allegations only, per the state-machine spec —
        never a generated_reply at this stage.
        """
        return await self.post(
            endpoint=NoticeEndpoints.ANALYZE_TEXT,
            payload=payload,
        )

    async def analyze_file(self, data: dict, files: dict) -> dict:
        """
        POST /api/notice/analyze-file — Stage 1 (uploaded PDF/DOCX/TXT/
        scanned image PDF). Same response shape as analyze().
        """
        return await self.upload(
            endpoint=NoticeEndpoints.ANALYZE_FILE,
            data=data,
            files=files,
        )

    async def draft(self, payload: dict) -> dict:
        """
        POST /api/notice/draft — Stage 2. Vendor enforces analysis-first
        with a 409 analysis_required if this is called before a successful
        analyze() in the same session.
        """
        return await self.post(
            endpoint=NoticeEndpoints.DRAFT,
            payload=payload,
        )

    async def refine(self, payload: dict) -> dict:
        """
        POST /api/notice/refine — Stage 3, repeatable. Each call increments
        `revision` and returns a new draft_id.
        """
        return await self.post(
            endpoint=NoticeEndpoints.REFINE,
            payload=payload,
        )

    async def ask(self, payload: dict) -> dict:
        """
        POST /api/notice/ask — mid-conversation Q&A grounded in the
        analysed notice. Does not change stage and does not touch the
        current draft.
        """
        return await self.post(
            endpoint=NoticeEndpoints.ASK,
            payload=payload,
        )