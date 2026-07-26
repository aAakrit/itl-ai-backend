import logging
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Optional

from sqlalchemy.orm import Session

from app.models.ai import AIConversation, AIMessage
from app.models.ai import AIProviderSession

from app.services.ai_service import ai_service

logger = logging.getLogger(__name__)


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

    def get_or_create_provider_session(
        self,
        conversation_id: int,
        provider: str,
    ) -> AIProviderSession:
        """
        Returns an active provider session for the conversation.
        Creates one if it doesn't exist.
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

        session = AIProviderSession(
            conversation_id=conversation_id,
            provider=provider,
            provider_session_token=None,
            provider_metadata={},
            status="active",
        )

        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)

        return session

    # ------------------------------------------------------------------
    # User Message
    # ------------------------------------------------------------------

    def save_user_message(
        self,
        conversation_id: int,
        provider: str,
        query: str,
        parent_message_id: Optional[int] = None,
    ) -> AIMessage:
        """
        Persist the user's prompt before sending it
        to the external AI provider.
        """

        message = AIMessage(
            conversation_id=conversation_id,
            parent_message_id=parent_message_id,
            provider=provider,
            message_type="user",
            status="pending",
            query=query,
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
          - case-laws bridge: {"results": [...]} — no `answer` field at all.
        `save_ai_message` (and everything downstream: serialize_message,
        the frontend) expects a single normalized {"answer", "sources"}
        shape, so tool-specific responses are mapped to it here rather than
        leaking vendor-specific shapes into message storage.
        """

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
                await self.ai_service.feedback(
                    {
                        "message_id": message.provider_message_id,
                        "rating": rating,
                    }
                )
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

        provider_session = self.get_or_create_provider_session(
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
            },
        )

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
    ) -> list[AIConversation]:
        """
        Returns non-deleted conversations for a user, most recently active
        first. When `module`/`tool` are given, only conversations belonging
        to that exact workspace are returned — each Module+Tool combination
        must never see another combination's history.
        """

        filters = [
            AIConversation.user_id == user_id,
            AIConversation.deleted_at.is_(None),
        ]

        if module:
            filters.append(AIConversation.module == module)

        if tool:
            filters.append(AIConversation.tool == tool)

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

        return {
            "id": message.id,
            "parent_message_id": message.parent_message_id,
            "role": "user" if is_user else "assistant",
            "message_type": message.message_type,
            "status": message.status,
            "content": message.query if is_user else message.answer,
            "confidence": message.confidence,
            "query_time_ms": message.query_time_ms,
            "sources": message.sources,
            "related_judgements": message.related_judgements,
            "feedback": message.feedback,
            "created_at": message.created_at,
        }

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
            provider_session = self.get_or_create_provider_session(
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
            # Built per-tool against the vendor's *documented* contract,
            # rather than blindly forwarding our own internal request dict
            # (which includes fields like conversation_id/provider/module_id
            # the vendor never asked for and doesn't document).
            #
            # IMPORTANT: v1 /query's documented input is `{query, max_results}`
            # ONLY — it has no session_id field at all. True multi-turn memory
            # on the vendor's side requires migrating to v2 (/api/v2/sessions +
            # /api/v2/query with session_token), which is a separate, larger
            # change. Until then, conversation continuity is provided entirely
            # by our own stored history (the UI shows the full thread) — each
            # individual vendor call is stateless from the vendor's point of view.
            max_results = payload.get("max_results", 5)

            if tool == "case-laws":
                # /api/v1/case-laws requires `context_answer` — a prior answer
                # to search supporting case law around. This was previously
                # missing entirely, which is why case-law calls were failing.
                # It's not a standalone conversational endpoint: use the most
                # recent assistant answer in this conversation as context, or
                # fall back to the query itself if there isn't one yet (e.g.
                # Case Law is the very first message in a new conversation).
                context_answer = self._get_last_assistant_answer(conversation.id) or query
                provider_payload = {
                    "query": query,
                    "context_answer": context_answer,
                    "max_results": min(max_results, 10),
                }
            else:
                provider_payload = {
                    "query": query,
                    "max_results": max_results,
                }

            # ---------------------------------------------------------
            # Call AI Provider
            # ---------------------------------------------------------
            response = await self.call_provider(
                provider=provider,
                tool=tool,
                payload=provider_payload,
            )

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
                    "confidence": assistant_message.confidence,
                    "query_time_ms": assistant_message.query_time_ms,
                    "sources": assistant_message.sources,
                    "related_judgements": assistant_message.related_judgements,
                    "verification": assistant_message.verification,
                    "pipeline": assistant_message.pipeline,
                    "created_at": assistant_message.created_at,
                },
            }

        except Exception:
            self.db.rollback()
            raise

    def save_provider_session_token(
        self,
        provider_session,
        response: dict,
    ):
        """
        Update provider session information from the provider response.
        """

        token = (
            response.get("session_token")
            or response.get("conversation_id")
            or response.get("chat_session")
        )

        if token:
            provider_session.provider_session_token = token

        provider_session.updated_at = datetime.utcnow()

        self.db.flush()

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
                return await self.ai_service.query(payload)

            if tool == "clarify":
                return await self.ai_service.clarify(payload)

            if tool == "refine":
                return await self.ai_service.refine(payload)

            if tool == "case-laws":
                return await self.ai_service.case_laws(payload)

        raise ValueError(f"Unsupported provider/tool: {provider}/{tool}")