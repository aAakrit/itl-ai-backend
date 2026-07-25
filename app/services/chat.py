from datetime import datetime
from json import tool
from typing import Any, Awaitable, Callable, Dict, Optional

from sqlalchemy.orm import Session

from app.models.ai import AIConversation, AIMessage
from app.models.ai import AIProviderSession

from app.services.ai_service import ai_service


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
            provider_payload = {
                **payload,
                "query": query,
                "session_id": provider_session.provider_session_token,
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
                response=response,
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