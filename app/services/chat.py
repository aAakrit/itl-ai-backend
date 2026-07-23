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

    # ------------------------------------------------------------------
    # Conversation
    # ------------------------------------------------------------------

    def get_or_create_conversation(
        self,
        user_id: int,
        conversation_id: Optional[int] = None,
        provider: str = "main",
        tool: str = "chat",
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

            if conversation:
                return conversation

        conversation = AIConversation(
            user_id=user_id,
            title=title or "New Chat",
            provider=provider,
            tool=tool,
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

async def query(
    self,
    *,
    user_id: int,
    query: str,
    provider: str = "main",
    tool: str = "chat",
    conversation_id: Optional[int] = None,
    parent_message_id: Optional[int] = None,
    provider_callback: Callable[[], Awaitable[Dict[str, Any]]],
):
    """
    Complete chat orchestration.

    Flow:

    Conversation
        ↓
    Provider Session
        ↓
    Save User Message
        ↓
    Existing AI Provider
        ↓
    Save Assistant Message
        ↓
    Update Conversation
        ↓
    Commit
    """

    try:

        conversation = self.get_or_create_conversation(
            user_id=user_id,
            conversation_id=conversation_id,
            provider=provider,
            tool=tool,
        )

        provider_session = self.get_or_create_provider_session(
            conversation_id=conversation.id,
            provider=provider,
        )

        user_message = self.save_user_message(
            conversation_id=conversation.id,
            provider=provider,
            query=query,
            parent_message_id=parent_message_id,
        )

        response = await provider_callback()

        if response.get("session_token"):
            provider_session.provider_session_token = response["session_token"]

        self.save_ai_message(
            conversation_id=conversation.id,
            provider=provider,
            response=response,
            parent_message_id=user_message.id,
        )

        self.update_conversation(
            conversation,
            provider,
        )

        self.db.commit()

        return response

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