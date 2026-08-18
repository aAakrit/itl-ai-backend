import logging
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Optional

from sqlalchemy.orm import Session

from app.models.ai import AIConversation, AIMessage
from app.models.ai import AIProviderSession

from app.services.ai_service import ai_service
from app.services.ai_gateway.exceptions import AIResponseException
from app.utils import storage

logger = logging.getLogger(__name__)


class NoticeStageError(Exception):
    """
    Raised when a staged Notice Agent call is attempted out of order
    (e.g. /draft before a successful /analyze in the same conversation).
    Mirrors the vendor's own 409 analysis_required shape (spec §B3) so the
    frontend gets one consistent body whether the guard fires locally
    (before any vendor call, for a fast failure) or the vendor itself
    enforces it.
    """

    def __init__(self, detail: dict):
        self.detail = detail
        super().__init__(detail.get("detail", "Notice workflow stage error"))


class NoticeUnavailableError(Exception):
    """
    Raised when the Notice AI vendor could not be reached through EITHER
    the staged endpoints or the legacy one-shot fallback — i.e. the whole
    Notice service (at whatever URL AI_NOTICE_URL currently points to)
    looks unreachable/undeployed, not just the newer staged routes.
    Caught in routes/ai.py and turned into a clean 503 instead of letting
    the raw vendor 404 body ("AI Service Error" / "Not Found") reach the
    person, which reads like our own bug rather than a vendor outage.
    """

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


class ChatService:

    def __init__(self, db):
        self.db = db
        self.ai_service = ai_service

    @staticmethod
    def _derive_title(query: str, max_length: int = 60) -> str:
        """
        Turns the first user prompt into a short conversation title,
        the same way ChatGPT/Claude-style products do. Only used when
        a brand-new conversation is being created.
        """

        cleaned = " ".join(query.split())

        if len(cleaned) <= max_length:
            return cleaned or "New Chat"

        return cleaned[: max_length - 1].rstrip() + "…"

    # ------------------------------------------------------------------
    # Conversation
    # ------------------------------------------------------------------

    def get_or_create_conversation(
        self,
        user_id: int,
        conversation_id: Optional[int] = None,
        provider: str = "main",
        tool: str = "chat",
        module: str = "gst",
        title: Optional[str] = None,
    ) -> AIConversation:
        """
        Returns an existing conversation if supplied,
        otherwise creates a new conversation.
        """

        if conversation_id:

            conversation = (
                self.db.query(AIConversation)
                .filter(
                    AIConversation.id == conversation_id,
                    AIConversation.user_id == user_id,
                    AIConversation.deleted_at.is_(None),
                )
                .first()
            )

            if conversation and conversation.module == module and conversation.tool == tool:
                return conversation
            # A conversation_id belonging to a different module/tool workspace was
            # supplied (e.g. a stale id from a previous tool selection) — conversation
            # identity is (conversation_id + module + tool), so this is treated as
            # "no conversation" rather than silently continuing the wrong thread.

        conversation = AIConversation(
            user_id=user_id,
            title=title or "New Chat",
            provider=provider,
            tool=tool,
            module=module,
            current_provider=provider,
            status="active",
            is_archived=False,
            last_message_at=datetime.utcnow(),
        )

        self.db.add(conversation)
        self.db.commit()
        self.db.refresh(conversation)

        return conversation

    # ------------------------------------------------------------------
    # Provider Session
    # ------------------------------------------------------------------

    async def get_or_create_provider_session(
        self,
        conversation_id: int,
        provider: str,
    ) -> AIProviderSession:
        """
        Returns an active provider session for the conversation.
        Creates one if it doesn't exist.

        For `provider == "main"`, creation calls the vendor's own
        POST /api/v2/sessions to mint a real session_token, which every
        subsequent Ask Bot / Clarify / Refine call for this conversation
        then reuses — this is what actually gives the vendor bot multi-turn
        memory. Previously nothing ever called this endpoint; a locally
        generated conversation id was sent as if it were a session
        identifier, which the vendor's session lifecycle doesn't recognize.

        Case Law Research (premium/judgement service) and Notice Reply /
        Summarizer are separate vendor services with no documented
        session-creation endpoint of their own (confirmed against both the
        vendor API doc and the Django reference client — neither shows a
        premium/notice/summarizer equivalent of /api/v2/sessions). For
        those, `provider_session_token` stays unset and their own
        documented `session_id` field (this conversation's id) is used
        instead, matching their actual confirmed contracts rather than
        inventing a session mechanism that isn't documented for them.
        """

        session = (
            self.db.query(AIProviderSession)
            .filter(
                AIProviderSession.conversation_id == conversation_id,
                AIProviderSession.provider == provider,
                AIProviderSession.status == "active",
            )
            .first()
        )

        if session:
            return session

        token = None
        metadata: dict = {}

        if provider == "main":
            try:
                # Vendor request contract for POST /api/v2/sessions isn't
                # fully specified in any doc shared so far (only that it
                # exists and is called "on New Chat") — sending an empty
                # body is the safest assumption for a bare "create a
                # session" action. Response shape is defensively probed
                # for common token field names.
                response = await self.ai_service.create_session({})
                token = (
                    response.get("session_token")
                    or response.get("token")
                    or response.get("session_id")
                )
                metadata = response if isinstance(response, dict) else {}
            except Exception:
                # Don't block the conversation from being created just
                # because session provisioning failed — fall back to no
                # token (the query call below still works, just without
                # vendor-side memory for this turn).
                logger.warning(
                    "Vendor session creation failed for conversation %s",
                    conversation_id,
                    exc_info=True,
                )

        session = AIProviderSession(
            conversation_id=conversation_id,
            provider=provider,
            provider_session_token=token,
            provider_metadata=metadata,
            status="active",
        )

        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)

        return session

    async def get_or_create_notice_session(
        self,
        conversation: AIConversation,
    ) -> AIProviderSession:
        """
        Notice Agent's own POST /api/v2/sessions (§0 of the Aug 2026 staged-
        workflow contract) — previously undocumented for this vendor
        service, so `get_or_create_provider_session` never called it and
        Notice Reply always ran stateless (session_id/session_token both
        omitted, "the service behaves exactly as it does today"). Kept as
        its own method rather than folded into the generic helper above,
        so the existing "main" session path is untouched.

        `provider_metadata` on the returned row doubles as the local
        record of the notice conversation's *stage* (uploaded -> analysed
        -> drafted -> refined) plus the vendor's analysis_id/draft_id/
        revision — see _notice_session_metadata / _save_notice_session_metadata.
        """

        session = (
            self.db.query(AIProviderSession)
            .filter(
                AIProviderSession.conversation_id == conversation.id,
                AIProviderSession.provider == "notice",
                AIProviderSession.status == "active",
            )
            .first()
        )

        if session:
            return session

        token = None
        metadata: dict = {"stage": "uploaded"}

        try:
            response = await self.ai_service.notice_create_session(
                {
                    "metadata": {
                        "conversation_id": conversation.id,
                        "module": conversation.module,
                        "tool": "notice",
                    }
                }
            )
            token = response.get("session_token")
        except Exception:
            # Same fallback philosophy as get_or_create_provider_session:
            # don't block the conversation just because session
            # provisioning failed — every staged call still works, just
            # without vendor-side memory/state for this conversation.
            logger.warning(
                "Vendor session creation failed for notice conversation %s",
                conversation.id,
                exc_info=True,
            )

        session = AIProviderSession(
            conversation_id=conversation.id,
            provider="notice",
            provider_session_token=token,
            provider_metadata=metadata,
            status="active",
        )

        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)

        return session

    @staticmethod
    def _notice_session_metadata(provider_session: AIProviderSession) -> dict:
        return dict(provider_session.provider_metadata or {})

    def _save_notice_session_metadata(
        self,
        provider_session: AIProviderSession,
        updates: dict,
    ) -> None:
        """
        Merges `updates` into the notice session's stored metadata rather
        than replacing it outright — e.g. saving a new `draft_id` must not
        wipe out the already-stored `analysis_id`.
        """

        meta = dict(provider_session.provider_metadata or {})
        meta.update({k: v for k, v in updates.items() if v is not None})
        provider_session.provider_metadata = meta
        provider_session.updated_at = datetime.utcnow()
        self.db.flush()

    def _get_owned_conversation(self, user_id: int, conversation_id: int) -> AIConversation:
        conversation = self.get_conversation(user_id, conversation_id)
        if not conversation:
            raise LookupError(f"Conversation {conversation_id} not found.")
        return conversation

    @staticmethod
    def _conversation_summary(conversation: AIConversation) -> dict:
        return {
            "id": conversation.id,
            "title": conversation.title,
            "provider": conversation.provider,
            "tool": conversation.tool,
            "module": conversation.module,
            "updated_at": conversation.updated_at,
            "last_message_at": conversation.last_message_at,
        }

    # ------------------------------------------------------------------
    # User Message
    # ------------------------------------------------------------------

    def save_user_message(
        self,
        conversation_id: int,
        provider: str,
        query: str,
        parent_message_id: Optional[int] = None,
        attachment: Optional[dict] = None,
    ) -> AIMessage:
        """
        Persist the user's prompt before sending it
        to the external AI provider. `attachment`, if given, is
        {filename, content_type, size, path} from app.utils.storage.
        """

        attachment = attachment or {}

        message = AIMessage(
            conversation_id=conversation_id,
            parent_message_id=parent_message_id,
            provider=provider,
            message_type="user",
            status="pending",
            query=query,
            attachment_filename=attachment.get("filename"),
            attachment_content_type=attachment.get("content_type"),
            attachment_size=attachment.get("size"),
            attachment_path=attachment.get("path"),
        )

        self.db.add(message)
        self.db.flush()

        return message

    # ------------------------------------------------------------------
    # Assistant Message
    # ------------------------------------------------------------------

    def _get_last_assistant_answer(self, conversation_id: int) -> Optional[str]:
        """
        Most recent assistant answer in a conversation, regardless of which
        tool produced it. Used as `context_answer` for the Case Law bridge
        when the conversation already has something to search case law
        around.
        """

        last = (
            self.db.query(AIMessage)
            .filter(
                AIMessage.conversation_id == conversation_id,
                AIMessage.message_type.in_(("assistant", "refinement")),
                AIMessage.answer.isnot(None),
            )
            .order_by(AIMessage.created_at.desc())
            .first()
        )

        return last.answer if last else None

    def _normalize_provider_response(self, tool: str, response: dict) -> dict:
        """
        Different vendor tools return meaningfully different shapes:
          - chat / refine-ish tools: {"answer": "...", "sources": [...]}
          - Case Law Research (premium/search): NO "sources" field at all —
            this is why sources never showed for it. Instead it returns
            FOUR separate arrays (results, enhanced_related, statute_results,
            acts_rules_results), confirmed against the vendor's full API
            contract. Mapped here: results + statute_results +
            acts_rules_results -> sources (everything the memo actually
            cites), enhanced_related -> related_judgements (the sidebar).
          - case-laws bridge: {"results": [...]} — no `answer` field at all.
          - notice / summarize: best-effort field guessing, see below.
        `save_ai_message` (and everything downstream: serialize_message,
        the frontend) expects a single normalized {"answer", "sources",
        "related_judgements"} shape, so tool-specific responses are mapped
        to it here rather than leaking vendor-specific shapes into message
        storage. Verification/citation_audit details are deliberately left
        out of this normalized shape — they're an internal accuracy signal,
        not something to surface to end users.
        """

        if tool == "search":
            def judgement_source(card: dict) -> dict:
                return {
                    "id": card.get("id"),
                    "document_type": "judgement",
                    "reference": card.get("citation"),
                    "heading": card.get("partyname"),
                    "court": card.get("court"),
                    "court_name": card.get("court_name"),
                    "citation": card.get("citation"),
                    "similarity": card.get("similarity_score"),
                    "link": card.get("link"),
                }

            def statute_source(card: dict) -> dict:
                return {
                    "id": card.get("id"),
                    "document_type": "statute",
                    "reference": card.get("reference"),
                    "heading": card.get("heading"),
                    "similarity": card.get("similarity_score"),
                    "link": card.get("link"),
                }

            def act_rule_source(card: dict) -> dict:
                return {
                    "id": card.get("id"),
                    "document_type": card.get("document_type", "act"),
                    "reference": card.get("reference"),
                    "heading": card.get("heading"),
                    "similarity": card.get("similarity_score"),
                    "link": card.get("link"),
                }

            sources = (
                [judgement_source(c) for c in response.get("results") or []]
                + [statute_source(c) for c in response.get("statute_results") or []]
                + [act_rule_source(c) for c in response.get("acts_rules_results") or []]
            )

            related_judgements = [
                {
                    "id": c.get("id"),
                    "partyname": c.get("partyname"),
                    "court": c.get("court") or c.get("court_name"),
                    "citation": c.get("citation"),
                    "facts": c.get("facts"),
                    "issue": c.get("issue"),
                    "held": c.get("held"),
                    "ratio": c.get("ratio"),
                    "link": c.get("link"),
                }
                for c in response.get("enhanced_related") or []
            ]

            answer = response.get("answer")

            if response.get("needs_clarification") and not answer:
                # Case Law Research's clarification branch has an empty
                # `answer` and puts the question in separate fields instead
                # (unlike the Ask Bot, which puts the question text directly
                # in `answer`) — synthesize a displayable answer so this
                # doesn't render as a blank bubble.
                question = response.get("clarifying_question", "")
                missing = response.get("missing_facts") or []
                answer = question + (f"\n\nMissing details: {', '.join(missing)}" if missing else "")

            return {
                **response,
                "answer": answer,
                "sources": sources,
                "related_judgements": related_judgements,
            }

        if tool in ("process", "summarize"):
            answer = (
                response.get("generated_reply")
                # Confirmed field name for Summarizer results (both sync
                # and async) — "Everything the frontend already reads
                # (formatted_output, extracted_fields, modules,
                # verification, document_integrity_note, disclaimer) is
                # unchanged" per the vendor's summarizer update notes.
                or response.get("formatted_output")
                or response.get("summary")
                or response.get("content")
                or response.get("answer")
                or response.get("text")
            )
            if not answer:
                # None of the guessed keys matched — surface the raw
                # response rather than silently saving an empty message,
                # so at minimum nothing is lost and the real shape is
                # visible for fixing this fallback chain properly.
                import json as _json

                answer = f"_(Unrecognized response shape — raw response below)_\n\n```json\n{_json.dumps(response, indent=2, default=str)}\n```"

            return {
                **response,
                "answer": answer,
                "sources": response.get("sources"),
            }

        if tool != "case-laws":
            return response

        results = response.get("results") or []

        lines = ["**Case Law Research Results**", ""]
        for r in results:
            party = r.get("partyname", "Unknown parties")
            court = r.get("court_name", "")
            citation = r.get("citation", "")
            ratio = r.get("ratio") or r.get("held") or r.get("summary") or ""
            lines.append(f"**{r.get('rank', '')}. {party}** — {court} ({citation})")
            if ratio:
                lines.append(f"> {ratio}")
            lines.append("")

        if not results:
            lines.append("No matching case law was found for this query.")

        sources = [
            {
                "document_type": "judgement",
                "id": r.get("id"),
                "reference": r.get("partyname"),
                "heading": r.get("partyname"),
                "court_name": r.get("court_name"),
                "court_area": r.get("court_area"),
                "citation": r.get("citation"),
                "similarity": r.get("similarity_score"),
                "link": r.get("link"),
            }
            for r in results
        ]

        return {
            **response,
            "answer": "\n".join(lines),
            "sources": sources,
        }

    def save_ai_message(
        self,
        conversation_id: int,
        provider: str,
        response: dict,
        parent_message_id: Optional[int] = None,
    ) -> AIMessage:
        """
        Persist the AI provider response.
        """

        message = AIMessage(
            conversation_id=conversation_id,
            parent_message_id=parent_message_id,
            provider=provider,
            message_type="assistant",
            status="completed",

            answer=response.get("answer"),

            confidence=response.get("confidence"),

            query_time_ms=response.get("query_time_ms"),

            web_search_used=response.get("web_search_used"),

            needs_clarification=response.get("needs_clarification", False),

            deep_research_used=response.get("deep_research_used", False),

            provider_message_id=response.get("message_id"),

            provider_search_id=response.get("search_id"),

            provider_request_id=response.get("request_id"),

            sources=response.get("sources"),

            related_judgements=response.get("related_judgements"),

            verification=response.get("verification"),

            pipeline=response.get("pipeline"),

            raw_response=response,
        )

        self.db.add(message)
        self.db.flush()

        return message

    # ------------------------------------------------------------------
    # Conversation Update
    # ------------------------------------------------------------------

    def update_conversation(
        self,
        conversation: AIConversation,
        provider: str,
    ):
        """
        Updates conversation metadata after a successful interaction.
        """

        conversation.current_provider = provider
        conversation.last_message_at = datetime.utcnow()
        conversation.updated_at = datetime.utcnow()

        self.db.flush()

    # ------------------------------------------------------------------
    # Message ownership lookup
    # ------------------------------------------------------------------

    def get_owned_message(self, user_id: int, message_id: int) -> Optional[AIMessage]:
        """
        Returns a message only if it belongs to a conversation owned by
        the requesting user — the single check every message-scoped
        action (feedback, refine) must pass before doing anything else.
        """

        return (
            self.db.query(AIMessage)
            .join(AIConversation, AIMessage.conversation_id == AIConversation.id)
            .filter(
                AIMessage.id == message_id,
                AIConversation.user_id == user_id,
                AIConversation.deleted_at.is_(None),
            )
            .first()
        )

    # ------------------------------------------------------------------
    # Feedback
    # ------------------------------------------------------------------

    async def submit_feedback(
        self,
        user_id: int,
        message_id: int,
        rating: str,
    ) -> AIMessage:
        """
        Records thumbs up/down on an assistant message, forwarding it to
        the vendor's feedback API. Enforced as one submission per message —
        a second attempt raises, it does not silently overwrite the first.
        """

        if rating not in ("up", "down"):
            raise ValueError('rating must be "up" or "down"')

        message = self.get_owned_message(user_id, message_id)

        if not message or message.message_type != "assistant":
            raise LookupError("Message not found.")

        if message.feedback:
            raise ValueError("Feedback has already been submitted for this message.")

        # The vendor's real feedback contract (api_io_reference.md) is
        # POST /api/v2/feedback: {message_id, rating: "up"|"down", ...} —
        # but `message_id` there means the VENDOR's own message id, which is
        # only ever returned by v2 /query (session-token based) and the
        # judgement-bot /search endpoints. We currently call v1 /query, whose
        # documented response has no message_id at all. There is no vendor id
        # to correctly send here, so rather than guessing (e.g. sending our
        # own internal id, which the vendor's DB has never heard of) the
        # vendor call is skipped and feedback is recorded locally only.
        # TODO: once conversation flow migrates to v2 (/api/v2/sessions +
        # /api/v2/query), `message.provider_message_id` will hold the real
        # vendor id and this can call POST /api/v2/feedback for real.
        if message.provider_message_id:
            try:
                feedback_payload = {
                    "message_id": message.provider_message_id,
                    "rating": rating,
                }
                # Route to the SAME provider that answered — Case Law Research
                # (premium) messages must go to /api/judgements/premium/feedback/,
                # not the main bot's /api/v2/feedback. This was previously
                # always calling ai_service.feedback() (main only) regardless
                # of message.provider.
                if message.provider == "premium":
                    await self.ai_service.premium_feedback(feedback_payload)
                else:
                    await self.ai_service.feedback(feedback_payload)
            except Exception:
                # Local feedback recording must still succeed even if the
                # vendor call fails — don't lose the user's feedback over it.
                logger.warning("Vendor feedback submission failed for message %s", message_id, exc_info=True)

        message.feedback = rating
        self.db.commit()

        return message

    # ------------------------------------------------------------------
    # Refine
    # ------------------------------------------------------------------

    async def refine(
        self,
        user_id: int,
        message_id: int,
        instruction: str,
    ) -> AIMessage:
        """
        Refines an existing assistant answer per free-text instruction
        ("make it more formal", "add more case law", ...) and appends the
        result as a NEW assistant message in the same conversation — the
        original answer is never overwritten.
        """

        message = self.get_owned_message(user_id, message_id)

        if not message or message.message_type != "assistant":
            raise LookupError("Message not found.")

        conversation = (
            self.db.query(AIConversation)
            .filter(AIConversation.id == message.conversation_id)
            .first()
        )

        provider_session = await self.get_or_create_provider_session(
            conversation_id=conversation.id,
            provider=message.provider,
        )

        # The original user query this answer was responding to — refine
        # needs it for context alongside the answer being refined.
        parent_query = (
            self.db.query(AIMessage)
            .filter(AIMessage.id == message.parent_message_id)
            .first()
        )

        response = await self.call_provider(
            provider=message.provider,
            tool="refine",
            payload={
                "original_query": parent_query.query if parent_query else "",
                "original_answer": message.answer or "",
                "refinement_instructions": instruction,
                "message_id": message.provider_message_id,
                "session_id": conversation.id,
                **({"session_token": provider_session.provider_session_token} if provider_session.provider_session_token else {}),
            },
        )

        self._raise_if_pipeline_error(response)

        self.save_provider_session_token(provider_session=provider_session, response=response)

        # Vendor's /refine response key is `refined_answer`, not `answer`.
        normalized_response = {**response, "answer": response.get("refined_answer") or response.get("answer")}

        refined_message = self.save_ai_message(
            conversation_id=conversation.id,
            provider=message.provider,
            response=normalized_response,
            # Chained off the ORIGINAL answer (not its parent question) so the
            # message tree reflects "this is a refinement of that answer".
            parent_message_id=message.id,
        )
        refined_message.message_type = "refinement"

        self.update_conversation(conversation=conversation, provider=message.provider)
        self.db.commit()

        return refined_message

    # ------------------------------------------------------------------
    # Conversation History (list / detail / delete)
    # ------------------------------------------------------------------

    def list_conversations(
        self,
        user_id: int,
        module: Optional[str] = None,
        tool: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> list[AIConversation]:
        """
        Returns non-deleted conversations for a user, most recently active
        first. When `module`/`tool`/`provider` are given, only conversations
        belonging to that exact workspace are returned — each
        Module+Provider+Tool combination must never see another
        combination's history.
        """

        filters = [
            AIConversation.user_id == user_id,
            AIConversation.deleted_at.is_(None),
        ]

        if module:
            filters.append(AIConversation.module == module)

        if tool:
            filters.append(AIConversation.tool == tool)

        if provider:
            filters.append(AIConversation.provider == provider)

        return (
            self.db.query(AIConversation)
            .filter(*filters)
            .order_by(
                AIConversation.last_message_at.desc(),
                AIConversation.updated_at.desc(),
            )
            .all()
        )

    def get_conversation(
        self,
        user_id: int,
        conversation_id: int,
    ) -> Optional[AIConversation]:
        """
        Returns a single conversation, scoped to the requesting user.
        """

        return (
            self.db.query(AIConversation)
            .filter(
                AIConversation.id == conversation_id,
                AIConversation.user_id == user_id,
                AIConversation.deleted_at.is_(None),
            )
            .first()
        )

    def get_messages(self, conversation_id: int) -> list[AIMessage]:
        """
        Returns every message in a conversation, oldest first.
        """

        return (
            self.db.query(AIMessage)
            .filter(AIMessage.conversation_id == conversation_id)
            .order_by(AIMessage.created_at.asc())
            .all()
        )

    def delete_conversation(self, user_id: int, conversation_id: int) -> bool:
        """
        Soft-deletes a conversation. Returns False if it doesn't
        exist (or doesn't belong to the requesting user).
        """

        conversation = self.get_conversation(user_id, conversation_id)

        if not conversation:
            return False

        conversation.deleted_at = datetime.utcnow()
        conversation.status = "deleted"
        self.db.commit()

        return True

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def serialize_message(self, message: AIMessage) -> dict:
        """
        Normalizes a stored AIMessage row into a single, frontend-friendly
        shape regardless of whether it's a user or assistant row.
        """

        is_user = message.message_type == "user"

        attachment = None
        if message.attachment_path:
            attachment = {
                "filename": message.attachment_filename,
                "content_type": message.attachment_content_type,
                "size": message.attachment_size,
                # Frontend downloads through this authenticated route —
                # never serves attachment_path (the on-disk storage name) directly.
                "download_url": f"/ai/messages/{message.id}/attachment",
            }

        data = {
            "id": message.id,
            "parent_message_id": message.parent_message_id,
            "role": "user" if is_user else "assistant",
            "message_type": message.message_type,
            "status": message.status,
            "content": message.query if is_user else message.answer,
            "query_time_ms": message.query_time_ms,
            "sources": message.sources,
            "related_judgements": message.related_judgements,
            "needs_clarification": message.needs_clarification,
            "deep_research_used": message.deep_research_used,
            "feedback": message.feedback,
            "attachment": attachment,
            "job_id": message.provider_job_id,
            "created_at": message.created_at,
        }

        # Notice Agent staged workflow (§C) — persisted on assistant turns
        # so "reopen conversation" can restore the correct stage and offer
        # refine on the latest revision without replaying every message.
        if message.provider == "notice" and message.provider_metadata:
            data["stage"] = message.provider_metadata.get("stage")
            data["analysis_id"] = message.provider_metadata.get("analysis_id")
            data["draft_id"] = message.provider_metadata.get("draft_id")
            data["revision"] = message.provider_metadata.get("revision")

        return data

    def serialize_conversation(
        self,
        conversation: AIConversation,
        include_messages: bool = False,
    ) -> dict:
        """
        Normalizes a stored AIConversation row. Messages are only
        attached when explicitly requested (list views stay light).
        """

        data = {
            "id": conversation.id,
            "title": conversation.title,
            "provider": conversation.provider,
            "tool": conversation.tool,
            "module": conversation.module,
            "status": conversation.status,
            "is_archived": conversation.is_archived,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
            "last_message_at": conversation.last_message_at,
        }

        if include_messages:
            data["messages"] = [
                self.serialize_message(m) for m in self.get_messages(conversation.id)
            ]

        if conversation.tool == "notice":
            # Current stage for this conversation, straight from the
            # notice provider session — lets the frontend restore the
            # right stage on reopen without scanning every message.
            notice_session = (
                self.db.query(AIProviderSession)
                .filter(
                    AIProviderSession.conversation_id == conversation.id,
                    AIProviderSession.provider == "notice",
                    AIProviderSession.status == "active",
                )
                .first()
            )
            if notice_session and notice_session.provider_metadata:
                meta = notice_session.provider_metadata
                data["notice_stage"] = meta.get("stage", "uploaded")
                data["analysis_id"] = meta.get("analysis_id")
                data["draft_id"] = meta.get("draft_id")
                data["revision"] = meta.get("revision")

        return data

    async def query(
        self,
        *,
        user_id: int,
        query: str,
        provider: str = "main",
        tool: str = "chat",
        module: str = "gst",
        conversation_id: Optional[int] = None,
        parent_message_id: Optional[int] = None,
        payload: Optional[dict] = None,
    ) -> dict:

        payload = payload or {}

        try:
            # ---------------------------------------------------------
            # Conversation
            # ---------------------------------------------------------
            conversation = self.get_or_create_conversation(
                user_id=user_id,
                conversation_id=conversation_id,
                provider=provider,
                tool=tool,
                module=module,
                title=self._derive_title(query),
            )

            # ---------------------------------------------------------
            # Provider Session
            # ---------------------------------------------------------
            provider_session = await self.get_or_create_provider_session(
                conversation_id=conversation.id,
                provider=provider,
            )

            # ---------------------------------------------------------
            # Save User Message
            # ---------------------------------------------------------
            user_message = self.save_user_message(
                conversation_id=conversation.id,
                provider=provider,
                query=query,
                parent_message_id=parent_message_id,
            )

            # ---------------------------------------------------------
            # Provider Payload
            # ---------------------------------------------------------
            # Built per-tool against the vendor's confirmed contract — see
            # core/views.py + core/case_law_research_views.py in the vendor's
            # own Django reference client, which is authoritative over the
            # markdown API doc (which turned out to omit/misdescribe several
            # fields, including session_id — the reference client sends it
            # on every single call, main and premium alike).
            max_results = payload.get("max_results", 5)

            if tool == "case-laws":
                # MainProvider's /api/v1/case-laws — the "similar case law to
                # an existing answer" flow. Requires context_answer. NOT what
                # the "Case Law Research" tool calls (that's provider=premium,
                # tool=search, below) — kept for a possible future "find
                # similar case law" action on an existing answer.
                context_answer = self._get_last_assistant_answer(conversation.id) or query
                provider_payload = {
                    "query": query,
                    "context_answer": context_answer,
                    "max_results": min(max_results, 10),
                    "session_id": conversation.id,
                    "message_id": user_message.id,
                }
            elif provider == "premium" and tool == "search":
                # Confirmed against the vendor's full API contract for
                # /api/judgements/premium/search. Deliberately NOT the same
                # shape as chat: this service is explicitly stateless
                # ("No session_id here... each research request is
                # standalone" — vendor's own words) — sending session_id/
                # session_token here would be wrong, not just unnecessary.
                # facts/court_area/max_rounds/skip_clarification are real,
                # optional fields we don't collect from the UI yet.
                provider_payload = {
                    "query": query,
                    "max_results": min(max_results, 200),
                }
            else:
                # main/chat, premium/clarify, premium/refine — all confirmed
                # to share this same base shape plus session_id.
                provider_payload = {
                    "query": query,
                    "max_results": max_results,
                    "session_id": conversation.id,
                    "message_id": user_message.id,
                }

            if provider_session.provider_session_token and not (provider == "premium" and tool == "search"):
                # Real vendor session token (see get_or_create_provider_session)
                # — this is what actually gives the vendor bot memory of prior
                # turns, as opposed to session_id (our own conversation id,
                # which the vendor doc's v2 contract wants alongside it, not
                # instead of it). Excluded for premium/search — see above.
                provider_payload["session_token"] = provider_session.provider_session_token

            # ---------------------------------------------------------
            # Call AI Provider
            # ---------------------------------------------------------
            response = await self.call_provider(
                provider=provider,
                tool=tool,
                payload=provider_payload,
            )

            self._raise_if_pipeline_error(response)

            # ---------------------------------------------------------
            # Save Session Token
            # ---------------------------------------------------------
            self.save_provider_session_token(
                provider_session=provider_session,
                response=response,
            )

            # ---------------------------------------------------------
            # Save Assistant Message
            # ---------------------------------------------------------
            assistant_message = self.save_ai_message(
                conversation_id=conversation.id,
                provider=provider,
                response=self._normalize_provider_response(tool, response),
                parent_message_id=user_message.id,
            )

            # ---------------------------------------------------------
            # Update Conversation
            # ---------------------------------------------------------
            self.update_conversation(
                conversation=conversation,
                provider=provider,
            )

            # ---------------------------------------------------------
            # Commit
            # ---------------------------------------------------------
            self.db.commit()

            self.db.refresh(conversation)
            self.db.refresh(user_message)
            self.db.refresh(assistant_message)

            # ---------------------------------------------------------
            # API Response
            # ---------------------------------------------------------
            return {
                "conversation": {
                    "id": conversation.id,
                    "title": conversation.title,
                    "provider": conversation.provider,
                    "tool": conversation.tool,
                    "updated_at": conversation.updated_at,
                    "last_message_at": conversation.last_message_at,
                },
                "user_message": {
                    "id": user_message.id,
                    "query": user_message.query,
                    "created_at": user_message.created_at,
                },
                "assistant_message": {
                    "id": assistant_message.id,
                    "answer": assistant_message.answer,
                    "query_time_ms": assistant_message.query_time_ms,
                    "sources": assistant_message.sources,
                    "related_judgements": assistant_message.related_judgements,
                    "needs_clarification": assistant_message.needs_clarification,
                    "deep_research_used": assistant_message.deep_research_used,
                    "created_at": assistant_message.created_at,
                },
            }

        except Exception:
            self.db.rollback()
            raise

    # ------------------------------------------------------------------
    # File-upload tools (Notice Reply, Summarizer)
    # ------------------------------------------------------------------

    async def process_document(
        self,
        *,
        user_id: int,
        query: str,
        provider: str,
        tool: str,
        module: str,
        conversation_id: Optional[int] = None,
        file=None,
        extra_fields: Optional[dict] = None,
        force_async: bool = False,
        force_sync: bool = False,
    ) -> dict:
        """
        The multipart-upload equivalent of query() — same conversation/
        session/message bookkeeping, reused rather than duplicated, but
        dispatches through call_upload_provider() (multipart) instead of
        call_provider() (JSON), since Notice Reply and Summarizer are both
        file-upload endpoints on the vendor side (core/draft_assistant.py,
        core/summarizer.py).
        """

        extra_fields = extra_fields or {}

        try:
            conversation = self.get_or_create_conversation(
                user_id=user_id,
                conversation_id=conversation_id,
                provider=provider,
                tool=tool,
                module=module,
                title=self._derive_title(query),
            )

            provider_session = await self.get_or_create_provider_session(
                conversation_id=conversation.id,
                provider=provider,
            )

            user_message = self.save_user_message(
                conversation_id=conversation.id,
                provider=provider,
                query=query,
            )

            file_bytes = None
            if file is not None:
                file_bytes = await file.read()
                stored_path = storage.save_file(file_bytes, file.filename or "upload")
                user_message.attachment_filename = file.filename
                user_message.attachment_content_type = file.content_type
                user_message.attachment_size = len(file_bytes)
                user_message.attachment_path = stored_path
                self.db.flush()

            # Unlike query()/refine() (main bot, premium), notice/summarizer's
            # actual vendor request models (NoticeRequest, SummarizeTextRequest)
            # don't declare session_id/message_id fields at all — sending them
            # risks a 422 if the model forbids extra fields. `data` is exactly
            # what the route built in extra_fields, nothing added here.
            data = dict(extra_fields)

            response = await self.call_upload_provider(
                provider=provider,
                tool=tool,
                data=data,
                file_bytes=file_bytes,
                filename=file.filename if file else None,
                content_type=file.content_type if file else None,
                force_async=force_async,
                force_sync=force_sync,
            )

            self._raise_if_pipeline_error(response)

            self.save_provider_session_token(provider_session=provider_session, response=response)

            if response.get("mode") == "async":
                # Summarizer's large-document job flow — no answer yet.
                # Save a placeholder the frontend can show as "processing"
                # and poll against; get_job_status/finalize_job fill it in
                # once the vendor's background job completes.
                assistant_message = self.save_ai_message(
                    conversation_id=conversation.id,
                    provider=provider,
                    response={"answer": None, "sources": None},
                    parent_message_id=user_message.id,
                )
                assistant_message.status = "processing"
                assistant_message.provider_job_id = response.get("job_id")

                self.update_conversation(conversation=conversation, provider=provider)
                self.db.commit()
                self.db.refresh(conversation)
                self.db.refresh(user_message)
                self.db.refresh(assistant_message)

                return {
                    "conversation": {
                        "id": conversation.id,
                        "title": conversation.title,
                        "provider": conversation.provider,
                        "tool": conversation.tool,
                        "module": conversation.module,
                        "updated_at": conversation.updated_at,
                        "last_message_at": conversation.last_message_at,
                    },
                    "user_message": {
                        "id": user_message.id,
                        "query": user_message.query,
                        "created_at": user_message.created_at,
                    },
                    "assistant_message": {
                        "id": assistant_message.id,
                        "answer": None,
                        "status": "processing",
                        "job_id": response.get("job_id"),
                        "filename": response.get("filename"),
                        "est_pages": response.get("est_pages"),
                        "created_at": assistant_message.created_at,
                    },
                }

            assistant_message = self.save_ai_message(
                conversation_id=conversation.id,
                provider=provider,
                response=self._normalize_provider_response(tool, response),
                parent_message_id=user_message.id,
            )

            self.update_conversation(conversation=conversation, provider=provider)

            self.db.commit()

            self.db.refresh(conversation)
            self.db.refresh(user_message)
            self.db.refresh(assistant_message)

            return {
                "conversation": {
                    "id": conversation.id,
                    "title": conversation.title,
                    "provider": conversation.provider,
                    "tool": conversation.tool,
                    "module": conversation.module,
                    "updated_at": conversation.updated_at,
                    "last_message_at": conversation.last_message_at,
                },
                "user_message": {
                    "id": user_message.id,
                    "query": user_message.query,
                    "created_at": user_message.created_at,
                },
                "assistant_message": {
                    "id": assistant_message.id,
                    "answer": assistant_message.answer,
                    "sources": assistant_message.sources,
                    "created_at": assistant_message.created_at,
                },
            }

        except Exception:
            self.db.rollback()
            raise

    # ------------------------------------------------------------------
    # Notice Reply AI — staged conversational workflow (Part B)
    # ------------------------------------------------------------------

    @staticmethod
    def _render_notice_analysis_markdown(response: dict) -> str:
        """
        The vendor deliberately returns no `generated_reply` at the
        analysis stage (§B2 — "no legal opinion"). This renders the
        structured notice_summary/allegations into a readable markdown
        answer so the conversation transcript still shows something
        meaningful for this turn; the frontend should prefer the
        structured fields (notice_summary, allegations,
        optional_inputs_prompt) returned alongside it for real rendering.
        """

        summary = response.get("notice_summary") or {}
        allegations = response.get("allegations") or []

        lines = ["**Notice Analysis**", ""]

        field_labels = [
            ("notice_type", "Notice type"),
            ("form_number", "Form"),
            ("issuing_authority", "Issuing authority"),
            ("tax_period", "Tax period"),
            ("date_of_notice", "Date of notice"),
            ("reply_due_date", "Reply due"),
            ("personal_hearing_date", "Personal hearing"),
        ]
        for key, label in field_labels:
            value = summary.get(key)
            if value:
                lines.append(f"- **{label}:** {value}")

        amount = summary.get("amount_proposed") or {}
        if amount:
            currency = amount.get("currency", "INR")
            lines.append(
                f"- **Amount proposed:** Tax {currency} {amount.get('tax', 0):,} · "
                f"Interest {currency} {amount.get('interest', 0):,} · "
                f"Penalty {currency} {amount.get('penalty', 0):,}"
            )

        lines.append("")
        lines.append("**Allegations**")
        if allegations:
            for a in allegations:
                ref = a.get("source_ref")
                suffix = f" _({ref})_" if ref else ""
                lines.append(f"{a.get('allegation_no', '?')}. {a.get('text', '')}{suffix}")
        else:
            lines.append("No specific allegations were detected in this notice.")

        lines.append("")
        lines.append(
            "_You can add optional context (facts, explanation, legal grounds, "
            'supporting documents) or say "draft now" to generate the reply '
            "straight away._"
        )

        return "\n".join(lines)

    async def analyze_notice(
        self,
        *,
        user_id: int,
        conversation_id: Optional[int],
        module: str,
        notice_text: Optional[str] = None,
        file=None,
        user_name: str = "",
        business_name: str = "",
        gstin: str = "",
        address: str = "",
    ) -> dict:
        """
        Stage 1 — POST /api/notice/analyze or /api/notice/analyze-file.
        "Analysis always precedes drafting" (§B): this is the only entry
        point that creates a notice conversation's session/stage state.

        Falls back to the legacy one-shot /api/notice/process(-file) if the
        vendor returns 404 for the staged endpoint — i.e. this vendor
        deployment doesn't have the Aug 2026 staged workflow live yet. The
        legacy path analyses AND drafts in one call, so a fallback
        conversation starts at stage "drafted" rather than "analysed"; it's
        flagged `legacy: True` in the session metadata so draft_notice/
        refine_notice/ask_notice (which all depend on vendor-side
        analysis_id/draft_id that only the staged endpoints mint) can fail
        with a clear message instead of chasing another 404.
        """

        if not (notice_text and notice_text.strip()) and file is None:
            raise ValueError("Provide either notice text or an attached file.")

        try:
            title_seed = (notice_text or "").strip() or f"Notice: {getattr(file, 'filename', 'upload')}"

            conversation = self.get_or_create_conversation(
                user_id=user_id,
                conversation_id=conversation_id,
                provider="notice",
                tool="notice",
                module=module,
                title=self._derive_title(title_seed),
            )

            provider_session = await self.get_or_create_notice_session(conversation)

            display_query = (notice_text or "").strip() or f"[Notice file: {getattr(file, 'filename', 'upload')}]"

            user_message = self.save_user_message(
                conversation_id=conversation.id,
                provider="notice",
                query=display_query,
            )

            session_fields: dict = {"session_id": conversation.id}
            if provider_session.provider_session_token:
                session_fields["session_token"] = provider_session.provider_session_token

            file_bytes: Optional[bytes] = None
            if file is not None:
                file_bytes = await file.read()
                stored_path = storage.save_file(file_bytes, file.filename or "notice-upload")
                user_message.attachment_filename = file.filename
                user_message.attachment_content_type = file.content_type
                user_message.attachment_size = len(file_bytes)
                user_message.attachment_path = stored_path
                self.db.flush()

            legacy_fallback = False
            try:
                if file is not None:
                    data = {
                        **session_fields,
                        "user_name": user_name or "",
                        "business_name": business_name or "",
                        "gstin": gstin or "",
                        "address": address or "",
                    }
                    response = await self.ai_service.notice_analyze_file(
                        data=data,
                        files={"file": (file.filename, file_bytes, file.content_type)},
                    )
                else:
                    payload = {
                        **session_fields,
                        "notice_text": notice_text,
                        "user_name": user_name or "",
                        "business_name": business_name or "",
                        "gstin": gstin or "",
                        "address": address or "",
                    }
                    response = await self.ai_service.notice_analyze(payload)
            except AIResponseException as exc:
                if exc.status_code != 404:
                    raise
                # This vendor deployment doesn't have /api/notice/analyze(-file)
                # yet — degrade to the legacy one-shot endpoint rather than
                # surfacing a raw 404 to the user.
                logger.warning(
                    "Staged notice analyze 404'd for conversation %s — falling back to legacy /notice/process%s",
                    conversation.id,
                    "-file" if file is not None else "",
                )
                legacy_fallback = True
                legacy_data = {
                    "user_name": user_name or "",
                    "business_name": business_name or "",
                    "gstin": gstin or "",
                    "address": address or "",
                }
                try:
                    if file is not None:
                        response = await self.ai_service.generate_notice_reply(
                            data=legacy_data,
                            files={"file": (file.filename, file_bytes, file.content_type)},
                        )
                    else:
                        response = await self.ai_service.generate_notice_reply(
                            data={**legacy_data, "notice_text": notice_text},
                        )
                except Exception as legacy_exc:
                    # Both the staged AND the legacy endpoint failed — this
                    # isn't "the staged workflow isn't deployed yet" anymore,
                    # it's "the Notice AI service isn't reachable at all" at
                    # whatever URL AI_NOTICE_URL currently points to. Fail
                    # with one clear, diagnosable message instead of letting
                    # the raw vendor error (which looks identical to a bug on
                    # our end) reach the person.
                    logger.error(
                        "Legacy notice fallback ALSO failed for conversation %s "
                        "(staged endpoint 404'd, then legacy endpoint raised %r) — "
                        "the Notice AI service looks unreachable at its configured URL.",
                        conversation.id,
                        legacy_exc,
                        exc_info=True,
                    )
                    raise NoticeUnavailableError(
                        "The Notice AI service is temporarily unavailable — neither the "
                        "new nor the legacy endpoint could be reached. Please try again "
                        "shortly, or contact support if this persists."
                    ) from legacy_exc

            self._raise_if_pipeline_error(response)
            self.save_provider_session_token(provider_session=provider_session, response=response)

            if legacy_fallback:
                normalized = self._normalize_provider_response("process", response)

                self._save_notice_session_metadata(
                    provider_session,
                    {"stage": "drafted", "legacy": True},
                )

                assistant_message = self.save_ai_message(
                    conversation_id=conversation.id,
                    provider="notice",
                    response={
                        "answer": normalized.get("answer"),
                        "sources": normalized.get("sources"),
                        "message_id": response.get("message_id"),
                    },
                    parent_message_id=user_message.id,
                )
                assistant_message.message_type = "notice_draft"
                assistant_message.provider_metadata = {"stage": "drafted", "legacy": True}

                self.update_conversation(conversation=conversation, provider="notice")
                self.db.commit()

                self.db.refresh(conversation)
                self.db.refresh(user_message)
                self.db.refresh(assistant_message)

                return {
                    "conversation": self._conversation_summary(conversation),
                    "user_message": {
                        "id": user_message.id,
                        "query": user_message.query,
                        "created_at": user_message.created_at,
                    },
                    "assistant_message": {
                        "id": assistant_message.id,
                        "answer": assistant_message.answer,
                        "created_at": assistant_message.created_at,
                    },
                    # Reported as "drafted" (not "analysed") because the legacy
                    # endpoint analyses AND drafts in a single call — there is
                    # no separate analysis stage to stop at.
                    "stage": "drafted",
                    "legacy": True,
                    "sources": normalized.get("sources"),
                    "query_time_ms": response.get("query_time_ms"),
                }

            self._save_notice_session_metadata(
                provider_session,
                {
                    "stage": response.get("stage", "analysed"),
                    "analysis_id": response.get("analysis_id"),
                    "notice_summary": response.get("notice_summary"),
                    "allegations": response.get("allegations"),
                },
            )

            assistant_message = self.save_ai_message(
                conversation_id=conversation.id,
                provider="notice",
                response={
                    "answer": self._render_notice_analysis_markdown(response),
                    "sources": None,
                    "message_id": response.get("message_id"),
                },
                parent_message_id=user_message.id,
            )
            assistant_message.message_type = "notice_analysis"
            assistant_message.provider_metadata = {
                "stage": "analysed",
                "analysis_id": response.get("analysis_id"),
            }

            self.update_conversation(conversation=conversation, provider="notice")
            self.db.commit()

            self.db.refresh(conversation)
            self.db.refresh(user_message)
            self.db.refresh(assistant_message)

            return {
                "conversation": self._conversation_summary(conversation),
                "user_message": {
                    "id": user_message.id,
                    "query": user_message.query,
                    "created_at": user_message.created_at,
                },
                "assistant_message": {
                    "id": assistant_message.id,
                    "answer": assistant_message.answer,
                    "created_at": assistant_message.created_at,
                },
                "stage": response.get("stage", "analysed"),
                "analysis_id": response.get("analysis_id"),
                "notice_summary": response.get("notice_summary"),
                "allegations": response.get("allegations"),
                "optional_inputs_prompt": response.get("optional_inputs_prompt"),
                "extraction_quality": response.get("extraction_quality"),
                "query_time_ms": response.get("query_time_ms"),
            }

        except Exception:
            self.db.rollback()
            raise

    async def draft_notice(
        self,
        *,
        user_id: int,
        conversation_id: int,
        user_inputs: Optional[dict] = None,
    ) -> dict:
        """
        Stage 2 — POST /api/notice/draft. `user_inputs` may be {} or
        omitted entirely (the "draft now" path, §B3) — never required.
        """

        try:
            conversation = self._get_owned_conversation(user_id, conversation_id)
            provider_session = await self.get_or_create_notice_session(conversation)
            meta = self._notice_session_metadata(provider_session)

            analysis_id = meta.get("analysis_id")
            if not analysis_id:
                # Local fast-fail mirroring the vendor's own 409 shape
                # (§B3) — no need for a round trip to learn what our own
                # stored stage already tells us. A conversation started via
                # the legacy fallback (see analyze_notice) never has an
                # analysis_id — it went straight to a drafted reply — so
                # give that its own explanation rather than "must be
                # analysed", which would be misleading here.
                if meta.get("legacy"):
                    raise NoticeStageError(
                        {
                            "success": False,
                            "error": "legacy_mode",
                            "detail": (
                                "This conversation's reply was generated by the legacy "
                                "Notice AI (the staged analyse/draft endpoints aren't "
                                "available on this deployment yet), so there's no "
                                "separate analysis step to draft from."
                            ),
                            "stage": "drafted",
                        }
                    )
                raise NoticeStageError(
                    {
                        "success": False,
                        "error": "analysis_required",
                        "detail": "The notice must be analysed before a reply can be drafted.",
                        "next_endpoint": "/api/notice/analyze",
                        "stage": meta.get("stage", "uploaded"),
                    }
                )

            has_inputs = bool(user_inputs)
            display_query = (
                "Draft the reply (with additional context provided)"
                if has_inputs
                else "Draft the reply based only on the uploaded notice"
            )

            user_message = self.save_user_message(
                conversation_id=conversation.id,
                provider="notice",
                query=display_query,
            )

            payload: dict = {
                "session_id": conversation.id,
                "analysis_id": analysis_id,
                "user_inputs": user_inputs or {},
            }
            if provider_session.provider_session_token:
                payload["session_token"] = provider_session.provider_session_token

            response = await self.ai_service.notice_draft(payload)
            self._raise_if_pipeline_error(response)
            self.save_provider_session_token(provider_session=provider_session, response=response)

            draft_id = response.get("draft_id")
            self._save_notice_session_metadata(
                provider_session,
                {
                    "stage": response.get("stage", "drafted"),
                    "draft_id": draft_id,
                    "revision": 1,
                },
            )

            assistant_message = self.save_ai_message(
                conversation_id=conversation.id,
                provider="notice",
                response={
                    "answer": response.get("generated_reply"),
                    "sources": response.get("sources"),
                    "verification": response.get("verification"),
                    "message_id": response.get("message_id"),
                },
                parent_message_id=user_message.id,
            )
            assistant_message.message_type = "notice_draft"
            assistant_message.provider_metadata = {
                "stage": "drafted",
                "analysis_id": analysis_id,
                "draft_id": draft_id,
                "revision": 1,
            }

            self.update_conversation(conversation=conversation, provider="notice")
            self.db.commit()

            self.db.refresh(conversation)
            self.db.refresh(user_message)
            self.db.refresh(assistant_message)

            return {
                "conversation": self._conversation_summary(conversation),
                "user_message": {
                    "id": user_message.id,
                    "query": user_message.query,
                    "created_at": user_message.created_at,
                },
                "assistant_message": {
                    "id": assistant_message.id,
                    "answer": assistant_message.answer,
                    "created_at": assistant_message.created_at,
                },
                "stage": response.get("stage", "drafted"),
                "draft_id": draft_id,
                "reply_form": response.get("reply_form"),
                "deadline": response.get("deadline"),
                "fraud_track": response.get("fraud_track"),
                "allegation_coverage": response.get("allegation_coverage"),
                "sources": response.get("sources"),
                "verification": response.get("verification"),
                "citation_audit": response.get("citation_audit"),
                "advisory_notes": response.get("advisory_notes"),
                "escalation_warning": response.get("escalation_warning"),
                "disclaimer": response.get("disclaimer"),
                "query_time_ms": response.get("query_time_ms"),
            }

        except Exception:
            self.db.rollback()
            raise

    async def refine_notice(
        self,
        *,
        user_id: int,
        conversation_id: int,
        instruction: str,
    ) -> dict:
        """
        Stage 3 — POST /api/notice/refine. Repeatable: each call
        increments `revision` and returns a new draft_id (§B4), so the
        transcript can offer "undo to an earlier revision".
        """

        try:
            conversation = self._get_owned_conversation(user_id, conversation_id)
            provider_session = await self.get_or_create_notice_session(conversation)
            meta = self._notice_session_metadata(provider_session)

            draft_id = meta.get("draft_id")
            if not draft_id:
                if meta.get("legacy"):
                    raise NoticeStageError(
                        {
                            "success": False,
                            "error": "legacy_mode",
                            "detail": (
                                "This reply was generated by the legacy Notice AI, which "
                                "has no staged draft to refine. Ask a follow-up question "
                                "instead, or start a new notice once the staged endpoints "
                                "are available on this deployment."
                            ),
                            "stage": "drafted",
                        }
                    )
                raise NoticeStageError(
                    {
                        "success": False,
                        "error": "draft_required",
                        "detail": "A reply must be drafted before it can be refined.",
                        "next_endpoint": "/api/notice/draft",
                        "stage": meta.get("stage", "uploaded"),
                    }
                )

            user_message = self.save_user_message(
                conversation_id=conversation.id,
                provider="notice",
                query=instruction,
            )

            payload: dict = {
                "session_id": conversation.id,
                "draft_id": draft_id,
                "instruction": instruction,
            }
            if provider_session.provider_session_token:
                payload["session_token"] = provider_session.provider_session_token

            response = await self.ai_service.notice_refine(payload)
            self._raise_if_pipeline_error(response)
            self.save_provider_session_token(provider_session=provider_session, response=response)

            new_draft_id = response.get("draft_id", draft_id)
            new_revision = response.get("revision") or (int(meta.get("revision") or 1) + 1)

            self._save_notice_session_metadata(
                provider_session,
                {
                    "stage": response.get("stage", "refined"),
                    "draft_id": new_draft_id,
                    "revision": new_revision,
                },
            )

            assistant_message = self.save_ai_message(
                conversation_id=conversation.id,
                provider="notice",
                response={
                    "answer": response.get("generated_reply"),
                    "sources": response.get("sources"),
                    "verification": response.get("verification"),
                    "message_id": response.get("message_id"),
                },
                parent_message_id=user_message.id,
            )
            assistant_message.message_type = "notice_refine"
            assistant_message.provider_metadata = {
                "stage": "refined",
                "draft_id": new_draft_id,
                "previous_draft_id": response.get("previous_draft_id", draft_id),
                "revision": new_revision,
            }

            self.update_conversation(conversation=conversation, provider="notice")
            self.db.commit()

            self.db.refresh(conversation)
            self.db.refresh(user_message)
            self.db.refresh(assistant_message)

            return {
                "conversation": self._conversation_summary(conversation),
                "user_message": {
                    "id": user_message.id,
                    "query": user_message.query,
                    "created_at": user_message.created_at,
                },
                "assistant_message": {
                    "id": assistant_message.id,
                    "answer": assistant_message.answer,
                    "created_at": assistant_message.created_at,
                },
                "stage": response.get("stage", "refined"),
                "draft_id": new_draft_id,
                "previous_draft_id": response.get("previous_draft_id", draft_id),
                "revision": new_revision,
                "changes_summary": response.get("changes_summary"),
                "allegation_coverage": response.get("allegation_coverage"),
                "verification": response.get("verification"),
                "citation_audit": response.get("citation_audit"),
                "disclaimer": response.get("disclaimer"),
                "query_time_ms": response.get("query_time_ms"),
            }

        except Exception:
            self.db.rollback()
            raise

    async def ask_notice(
        self,
        *,
        user_id: int,
        conversation_id: int,
        question: str,
    ) -> dict:
        """
        §B5 — POST /api/notice/ask. Grounded in the analysed notice; does
        NOT change stage and does NOT touch the current draft, so this
        never advances/overwrites analysis_id, draft_id, or revision.
        """

        try:
            conversation = self._get_owned_conversation(user_id, conversation_id)
            provider_session = await self.get_or_create_notice_session(conversation)
            meta = self._notice_session_metadata(provider_session)

            if meta.get("stage", "uploaded") == "uploaded":
                raise NoticeStageError(
                    {
                        "success": False,
                        "error": "analysis_required",
                        "detail": "The notice must be analysed before it can be asked about.",
                        "next_endpoint": "/api/notice/analyze",
                        "stage": "uploaded",
                    }
                )

            if meta.get("legacy"):
                # /notice/ask is part of the same staged release as
                # /notice/analyze — if that 404'd for this conversation,
                # /notice/ask will too. Fail fast with a clear explanation
                # rather than a second confusing 404 round trip.
                raise NoticeStageError(
                    {
                        "success": False,
                        "error": "legacy_mode",
                        "detail": (
                            "This conversation is running on the legacy Notice AI, which "
                            "doesn't support grounded follow-up questions. Start a new "
                            "notice once the staged endpoints are available on this "
                            "deployment, or ask this in a fresh Ask Bot conversation."
                        ),
                        "stage": meta.get("stage"),
                    }
                )

            user_message = self.save_user_message(
                conversation_id=conversation.id,
                provider="notice",
                query=question,
            )

            payload: dict = {"session_id": conversation.id, "question": question}
            if provider_session.provider_session_token:
                payload["session_token"] = provider_session.provider_session_token

            response = await self.ai_service.notice_ask(payload)
            self._raise_if_pipeline_error(response)
            self.save_provider_session_token(provider_session=provider_session, response=response)

            assistant_message = self.save_ai_message(
                conversation_id=conversation.id,
                provider="notice",
                response={
                    "answer": response.get("answer"),
                    "sources": response.get("sources"),
                    "message_id": response.get("message_id"),
                },
                parent_message_id=user_message.id,
            )
            assistant_message.message_type = "notice_ask"
            assistant_message.provider_metadata = {"stage": meta.get("stage")}

            self.update_conversation(conversation=conversation, provider="notice")
            self.db.commit()

            self.db.refresh(conversation)
            self.db.refresh(user_message)
            self.db.refresh(assistant_message)

            return {
                "conversation": self._conversation_summary(conversation),
                "user_message": {
                    "id": user_message.id,
                    "query": user_message.query,
                    "created_at": user_message.created_at,
                },
                "assistant_message": {
                    "id": assistant_message.id,
                    "answer": assistant_message.answer,
                    "created_at": assistant_message.created_at,
                },
                "stage": meta.get("stage"),
                "citation_audit": response.get("citation_audit"),
                "query_time_ms": response.get("query_time_ms"),
            }

        except Exception:
            self.db.rollback()
            raise

    # ------------------------------------------------------------------
    # Async job polling (Summarizer large-document flow)
    # ------------------------------------------------------------------

    def _get_message_by_job_id(self, user_id: int, job_id: str) -> AIMessage:
        message = (
            self.db.query(AIMessage)
            .join(AIConversation, AIMessage.conversation_id == AIConversation.id)
            .filter(
                AIMessage.provider_job_id == job_id,
                AIConversation.user_id == user_id,
                AIConversation.deleted_at.is_(None),
            )
            .first()
        )

        if not message:
            raise LookupError("Job not found.")

        return message

    async def get_job_status(self, user_id: int, job_id: str) -> dict:
        """
        GET /api/summarize/status/{job_id}, ownership-checked via the
        message that was created when the job was submitted.
        """

        self._get_message_by_job_id(user_id, job_id)  # ownership check only

        return await self.ai_service.summarizer_job_status(job_id)

    async def finalize_job(self, user_id: int, job_id: str) -> dict:
        """
        Checks a job's result and, if done, saves the real answer onto the
        placeholder message created when the job was submitted — turning
        it from "processing" into a normal completed assistant message.
        Idempotent: if already finalized, just returns the saved message
        without re-hitting the vendor.
        """

        message = self._get_message_by_job_id(user_id, job_id)

        if message.status != "processing":
            conversation = (
                self.db.query(AIConversation)
                .filter(AIConversation.id == message.conversation_id)
                .first()
            )
            return {"ready": True, "conversation_id": conversation.id, "message": self.serialize_message(message)}

        result = await self.ai_service.summarizer_job_result(job_id)

        status = result.get("status")

        if status == "error" or result.get("detail"):
            message.status = "error"
            self.db.commit()
            raise AIResponseException(
                status_code=502,
                detail=result.get("error") or result.get("detail") or "Summarization job failed.",
            )

        if status and status != "done":
            # Polled before it was ready — 202-equivalent, pass the
            # progress info straight through.
            return {
                "ready": False,
                "status": status,
                "stage": result.get("stage"),
                "progress": result.get("progress"),
            }

        self._raise_if_pipeline_error(result)

        normalized = self._normalize_provider_response("summarize", result)
        message.answer = normalized.get("answer")
        message.sources = normalized.get("sources")
        message.status = "completed"
        message.provider_message_id = result.get("message_id") or message.provider_message_id

        self.db.commit()
        self.db.refresh(message)

        conversation = (
            self.db.query(AIConversation)
            .filter(AIConversation.id == message.conversation_id)
            .first()
        )
        self.update_conversation(conversation=conversation, provider=message.provider)
        self.db.commit()

        return {"ready": True, "conversation_id": conversation.id, "message": self.serialize_message(message)}

    def save_provider_session_token(
        self,
        provider_session,
        response: dict,
    ):
        """
        Refreshes the stored session token if the provider response
        includes an updated one. Now that sessions are minted upfront via
        get_or_create_provider_session (POST /api/v2/sessions), this is
        just keeping the stored token in sync if the vendor ever rotates
        it mid-conversation — it's not the primary way we obtain a token
        anymore. Only the explicit `session_token` key is trusted; the
        previous fallback to `response.get("conversation_id")` risked
        clobbering a real token with an unrelated echoed id.
        """

        token = response.get("session_token")

        if token:
            provider_session.provider_session_token = token
            provider_session.updated_at = datetime.utcnow()
            self.db.flush()

    def _raise_if_pipeline_error(self, response: dict) -> None:
        """
        The vendor's own pipeline can fail internally while still returning
        HTTP 200 — e.g. `{"answer": "Error: 'unverified_labels'", "confidence":
        0.0, "verification": null, "sources": []}`. Nothing about that is an
        HTTP-level failure (raise_for_status never fires), so without this
        check it gets saved and displayed as if it were a real answer.
        Detection keys on the answer text literally starting with "Error:" —
        a real answer never legitimately starts with that, so this is a
        precise, low-false-positive signal rather than a guess based on
        confidence/verification being empty (which can also happen for a
        genuine, if weak, answer).
        """

        answer = (
            response.get("answer")
            or response.get("generated_reply")
            or response.get("content")
            or response.get("refined_answer")
        )

        if isinstance(answer, str) and answer.strip().startswith("Error:"):
            raise AIResponseException(
                status_code=502,
                detail=f"The AI service reported an internal error: {answer.strip()}",
            )

    async def call_provider(
        self,
        provider: str,
        tool: str,
        payload: dict,
    ):
        """
        Dispatch the request to the existing AIService.
        """

        if provider == "main":

            if tool == "chat":
                # v2 requires session_token per the vendor doc; use it
                # whenever we have one (the normal case — see
                # get_or_create_provider_session). Falls back to v1 only if
                # vendor session creation itself failed for this conversation.
                if payload.get("session_token"):
                    return await self.ai_service.query_v2(payload)
                return await self.ai_service.query(payload)

            if tool == "clarify":
                return await self.ai_service.clarify(payload)

            if tool == "refine":
                return await self.ai_service.refine(payload)

            if tool == "case-laws":
                # Only used for the "similar case law to this existing answer"
                # style flow (requires context_answer). NOT what "Case Law
                # Research" as a primary chat tool should call — see "premium"/
                # "search" below, confirmed against the vendor's own reference
                # client (core/case_law_research_views.py CaseLawSummarizeView).
                return await self.ai_service.case_laws(payload)

        if provider == "premium":

            if tool == "search":
                # This IS "Case Law Research" as a primary ask-style tool —
                # confirmed against core/case_law_research_views.py
                # CaseLawSummarizeView, which posts to
                # /api/judgements/premium/search/ and gets back a normal
                # {answer, sources, ...} shape, same as main chat. No
                # context_answer needed for this flow.
                return await self.ai_service.premium_search(payload)

            if tool == "clarify":
                return await self.ai_service.premium_clarify(payload)

            if tool == "refine":
                return await self.ai_service.premium_refine(payload)

        raise ValueError(f"Unsupported provider/tool: {provider}/{tool}")

    async def call_upload_provider(
        self,
        provider: str,
        tool: str,
        data: dict,
        file_bytes: bytes | None = None,
        filename: str | None = None,
        content_type: str | None = None,
        force_async: bool = False,
        force_sync: bool = False,
    ):
        """
        Dispatch a multipart request to the existing AIService — the
        file-upload counterpart to call_provider(). `file_bytes` may be
        None: the vendor's own reference client sends zero-or-more files
        (request.FILES.getlist('files')), it's never required.

        Takes already-read bytes (not a FastAPI UploadFile) — the caller
        (process_document) reads the upload once, both to persist it to
        disk and to forward it here; passing the UploadFile itself into
        httpx doesn't work (see historical note below).

        Multipart field name "file" is now confirmed against the vendor's
        actual FastAPI source: both /api/notice/process-file and
        /api/summarize/file declare `file: UploadFile = File(...)` — in
        FastAPI, that parameter name IS the expected multipart field name.

        HISTORICAL BUG (fixed): this used to build `files={"file": file}`
        with the raw FastAPI/Starlette UploadFile object. httpx's `files=`
        needs actual bytes (or a sync file-like object); UploadFile.read()
        is an async coroutine, and httpx's multipart encoder calls .read()
        synchronously — so it was sending an un-awaited coroutine object as
        the file content instead of real bytes. Every notice/summarizer
        call with a file attached failed because of this.
        """

        files = {}
        if file_bytes is not None:
            files["file"] = (filename, file_bytes, content_type)

        if provider == "notice" and tool == "process":
            return await self.ai_service.generate_notice_reply(data=data, files=files)

        if provider == "summarizer" and tool == "summarize":
            return await self.ai_service.summarize_document(
                data=data, files=files, force_async=force_async, force_sync=force_sync
            )

        raise ValueError(f"Unsupported upload provider/tool: {provider}/{tool}")