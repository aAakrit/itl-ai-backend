"""
High-level AI Service.

Acts as the business layer between FastAPI routes and the AI Gateway.
"""

from __future__ import annotations

from typing import Any

from app.services.ai_gateway.gateway import ai_gateway


class AIService:
    """
    Business service for all AI operations.
    """

    def __init__(self):
        self.main = ai_gateway.get_provider("main")
        self.premium = ai_gateway.get_provider("premium")
        self.free = ai_gateway.get_provider("free")
        self.notice = ai_gateway.get_provider("notice")
        self.summarizer = ai_gateway.get_provider("summarizer")

    # ========================================================================
    # Main AI
    # ========================================================================

    async def query(self, payload: dict[str, Any]) -> dict:
        return await self.main.query(payload)

    async def query_v2(self, payload: dict[str, Any]) -> dict:
        return await self.main.query_v2(payload)

    async def clarify(self, payload: dict[str, Any]) -> dict:
        return await self.main.clarify(payload)

    async def refine(self, payload: dict[str, Any]) -> dict:
        return await self.main.refine(payload)

    async def case_laws(self, payload: dict[str, Any]) -> dict:
        return await self.main.case_laws(payload)

    async def create_session(self, payload: dict[str, Any]) -> dict:
        return await self.main.create_session(payload)

    async def feedback(self, payload: dict[str, Any]) -> dict:
        return await self.main.submit_feedback(payload)

    async def analytics(self, params: dict[str, Any] | None = None) -> dict:
        return await self.main.analytics(params)

    # ========================================================================
    # Premium Judgment AI
    # ========================================================================

    async def premium_search(self, payload: dict[str, Any]) -> dict:
        return await self.premium.search(payload)

    async def premium_more(self, payload: dict[str, Any]) -> dict:
        return await self.premium.more(payload)

    async def premium_clarify(self, payload: dict[str, Any]) -> dict:
        return await self.premium.clarify(payload)

    async def premium_refine(self, payload: dict[str, Any]) -> dict:
        return await self.premium.refine(payload)

    async def premium_similar(self, payload: dict[str, Any]) -> dict:
        return await self.premium.similar(payload)

    async def premium_feedback(self, payload: dict[str, Any]) -> dict:
        return await self.premium.submit_feedback(payload)

    # ========================================================================
    # Free Judgment AI
    # ========================================================================

    async def free_search(self, payload: dict[str, Any]) -> dict:
        return await self.free.search(payload)

    async def free_more(self, payload: dict[str, Any]) -> dict:
        return await self.free.more(payload)

    async def free_clarify(self, payload: dict[str, Any]) -> dict:
        return await self.free.clarify(payload)

    async def free_refine(self, payload: dict[str, Any]) -> dict:
        return await self.free.refine(payload)

    async def free_similar(self, payload: dict[str, Any]) -> dict:
        return await self.free.similar(payload)

    # ========================================================================
    # Notice Reply AI
    # ========================================================================

    async def generate_notice_reply(
        self,
        data: dict[str, Any],
        files: dict[str, Any] | None = None,
    ) -> dict:
        if files:
            return await self.notice.generate_from_file(data, files)
        return await self.notice.generate_from_text(data)

    async def get_notice_types(self) -> dict:
        return await self.notice.get_notice_types()

    # ------------------------------------------------------------------
    # Notice Reply AI — v3 staged workflow (analyse -> submissions -> draft -> refine)
    # ------------------------------------------------------------------

    async def notice_create_session(self, payload: dict[str, Any]) -> dict:
        return await self.notice.create_session(payload)

    async def notice_analyze(self, payload: dict[str, Any]) -> dict:
        return await self.notice.analyze(payload)

    async def notice_analyze_file(
        self,
        data: dict[str, Any],
        files: dict[str, Any],
    ) -> dict:
        return await self.notice.analyze_file(data, files)

    async def notice_submissions(self, payload: dict[str, Any]) -> dict:
        return await self.notice.submissions(payload)

    async def notice_submissions_file(
        self,
        data: dict[str, Any],
        files: list,
    ) -> dict:
        return await self.notice.submissions_file(data, files)

    async def notice_draft(self, payload: dict[str, Any]) -> dict:
        return await self.notice.draft(payload)

    async def notice_refine(self, payload: dict[str, Any]) -> dict:
        return await self.notice.refine(payload)

    async def notice_session_status(self, session_id: str) -> dict:
        return await self.notice.session_status(session_id)

    async def notice_supported_formats(self) -> dict:
        return await self.notice.supported_formats()

    # ========================================================================
    # Document Summarizer
    # ========================================================================

    async def summarize_document(
        self,
        data: dict[str, Any],
        files: dict[str, Any] | None = None,
        force_async: bool = False,
        force_sync: bool = False,
    ) -> dict:
        if files:
            return await self.summarizer.summarize_file(data, files, force_async=force_async, force_sync=force_sync)
        return await self.summarizer.summarize_text(data)

    async def summarizer_job_status(self, job_id: str) -> dict:
        return await self.summarizer.get_job_status(job_id)

    async def summarizer_job_result(self, job_id: str) -> dict:
        return await self.summarizer.get_job_result(job_id)

    async def health(self, provider: str):
        return await ai_gateway.get_provider(provider).health()

ai_service = AIService()