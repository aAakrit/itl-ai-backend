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
    # Notice Agent v3 (Aug 2026 contract) — analyse -> submissions
    # (facts/evidence loop, auto-drafts when ready) -> draft (explicit/
    # forced) -> refine. Replaces the earlier v2 staged contract wholesale;
    # there is no v3 /ask endpoint.
    # ------------------------------------------------------------------

    async def create_session(self, payload: dict) -> dict:
        """
        POST /api/v2/sessions — OPTIONAL best-effort registration only in
        v3 ("analyze adopts an unseen id" on its own). Never treated as a
        precondition for anything else in this provider.
        """
        return await self.post(
            endpoint=NoticeEndpoints.SESSIONS,
            payload=payload,
        )

    async def analyze(self, payload: dict) -> dict:
        """
        POST /api/notice/analyze — allegations ONLY, per the vendor's own
        rule: "analyze never returns a draft". payload carries session_id
        (client-generated), notice_text, user_name, business_name, gstin,
        address.
        """
        return await self.post(
            endpoint=NoticeEndpoints.ANALYZE_TEXT,
            payload=payload,
        )

    async def analyze_file(self, data: dict, files: dict) -> dict:
        """POST /api/notice/analyze-file — same rule, uploaded document instead of pasted text."""
        return await self.upload(
            endpoint=NoticeEndpoints.ANALYZE_FILE,
            data=data,
            files=files,
        )

    async def submissions(self, payload: dict) -> dict:
        """
        POST /api/notice/submissions — the facts/evidence loop. Body:
        session_id, message, ready_to_draft, (notice_text for restart
        recovery only). Returns EITHER a "still collecting" response
        (phase COLLECTING_FACTS, evidence_matrix, follow_up_questions) OR,
        once every allegation is answered (or the user says "reply as it
        is" / equivalent), auto-drafts and returns the full draft response
        (phase DRAFTED, generated_reply present) directly from this call.
        """
        return await self.post(
            endpoint=NoticeEndpoints.SUBMISSIONS,
            payload=payload,
        )

    async def submissions_file(self, data: dict, files: list) -> dict:
        """
        POST /api/notice/submissions-file — multipart evidence upload.
        `files` is a list of (fieldname, (filename, bytes, content_type))
        tuples since the field is repeatable (multiple evidence files in
        one call); httpx accepts a list of tuples for repeated multipart
        fields where a plain dict cannot represent duplicate keys.
        """
        return await self.client.post_multipart(
            base_url=self.base_url,
            endpoint=NoticeEndpoints.SUBMISSIONS_FILE,
            data=data,
            files=files,
        )

    async def draft(self, payload: dict) -> dict:
        """
        POST /api/notice/draft — explicit draft trigger. Body: session_id,
        include_din_ground, extra_instruction, force (true = draft despite
        open follow-up questions), notice_text (restart recovery only).
        Normally the draft is produced automatically by submissions() once
        every allegation is answered; this is for "force it now" or a
        direct re-draft with new instructions.
        """
        return await self.post(
            endpoint=NoticeEndpoints.DRAFT,
            payload=payload,
        )

    async def refine(self, payload: dict) -> dict:
        """
        POST /api/notice/refine — body: session_id, instruction,
        current_draft (optional — only needed if session_id isn't live),
        notice_type (optional). No draft_id concept in v3; refine acts on
        the session's current draft implicitly.
        """
        return await self.post(
            endpoint=NoticeEndpoints.REFINE,
            payload=payload,
        )

    async def session_status(self, session_id: str) -> dict:
        """GET /api/notice/session/{session_id} — phase, notice_type, allegations, evidence_matrix, etc."""
        return await self.get(endpoint=NoticeEndpoints.SESSION_STATUS.format(session_id=session_id))

    async def supported_formats(self) -> dict:
        """GET /api/notice/supported-formats — drives the file picker's accept list so it never drifts from the vendor."""
        return await self.get(endpoint=NoticeEndpoints.SUPPORTED_FORMATS)