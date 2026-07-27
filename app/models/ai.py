from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    BigInteger,
    Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.db import Base


class AIConversation(Base):
    """
    Stores a user's AI conversation.

    A conversation may interact with multiple AI tools/providers
    (Chat, Case Law, Notice Reply, Summarizer, etc.).
    """

    __tablename__ = "ai_conversations"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Conversation Details
    title = Column(String(255), nullable=False, default="New Chat")

    # Current active provider/tool
    provider = Column(String(50), nullable=True)
    tool = Column(String(50), nullable=True)
    current_provider = Column(String(50), nullable=True)

    # Which Tax Module (e.g. "income-tax", "gst") this conversation belongs to.
    # Previously absent entirely — the frontend had no way to know which module
    # a saved conversation was created under, so it silently defaulted every
    # single one to "income-tax" regardless of what it actually was.
    module = Column(String(50), nullable=True, index=True)

    # Status
    status = Column(String(20), default="ACTIVE", nullable=False)

    is_archived = Column(Boolean, default=False)

    last_message_at = Column(DateTime, nullable=True)

    # Audit
    created_at = Column(DateTime, default=datetime.utcnow)

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    deleted_at = Column(DateTime, nullable=True)

    # Relationships
    provider_sessions = relationship(
        "AIProviderSession",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )

    messages = relationship(
        "AIMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AIMessage.created_at",
    )

    attachments = relationship(
        "AIAttachment",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            "idx_ai_conversation_user_updated",
            "user_id",
            "updated_at",
        ),
        Index(
            "idx_ai_conversation_user_deleted",
            "user_id",
            "deleted_at",
        ),
    )

class AIProviderSession(Base):
    """
    Maps an application conversation to a provider-specific session.

    Examples:
    - Main AI V2 -> session_token
    - Future providers may have conversation/thread IDs

    NOTE:
    Premium/Free Case Law search_ids are stored on AIMessage,
    not here, because a conversation can have multiple searches.
    """

    __tablename__ = "ai_provider_sessions"

    id = Column(Integer, primary_key=True, index=True)

    conversation_id = Column(
        Integer,
        ForeignKey("ai_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Provider Name
    # Example:
    # main_ai
    # premium_case_law
    # free_case_law
    # notice_reply
    # summarizer
    provider = Column(String(50), nullable=False)

    # Provider Session Token
    # Example:
    # session_token returned by Main AI V2
    provider_session_token = Column(
        String(255),
        nullable=True,
        index=True,
    )

    # Complete provider-specific metadata
    # Store anything else without requiring schema changes.
    provider_metadata = Column(
        JSONB,
        nullable=True,
    )

    # Status
    status = Column(
        String(20),
        default="ACTIVE",
        nullable=False,
    )

    # Audit
    created_at = Column(
        DateTime,
        default=datetime.utcnow,
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # Relationships
    conversation = relationship(
        "AIConversation",
        back_populates="provider_sessions",
    )

    __table_args__ = (
        Index(
            "idx_ai_provider_provider_token",
            "provider",
            "provider_session_token",
        ),
    )

class AIMessage(Base):
    """
    Stores every AI interaction within a conversation.

    One record contains one user query and the corresponding
    AI response.

    This table is intentionally provider-agnostic.
    """

    __tablename__ = "ai_messages"

    id = Column(Integer, primary_key=True, index=True)

    conversation_id = Column(
        Integer,
        ForeignKey("ai_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    parent_message_id = Column(
        Integer,
        ForeignKey("ai_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ------------------------------------------------------------------
    # Provider Information
    # ------------------------------------------------------------------

    provider = Column(
        String(50),
        nullable=False,
        index=True,
    )

    provider_message_id = Column(
        String(255),
        nullable=True,
        index=True,
    )

    provider_search_id = Column(
        String(255),
        nullable=True,
        index=True,
    )

    provider_request_id = Column(
        String(255),
        nullable=True,
        index=True,
    )

    # ------------------------------------------------------------------
    # Message Information
    # ------------------------------------------------------------------

    # chat
    # clarification
    # refinement
    # case_law
    # notice_reply
    # summary
    message_type = Column(
        String(50),
        nullable=False,
        default="chat",
    )

    status = Column(
        String(20),
        nullable=False,
        default="COMPLETED",
    )

    # ------------------------------------------------------------------
    # User Query
    # ------------------------------------------------------------------

    query = Column(
        Text,
        nullable=True,
    )

    # ------------------------------------------------------------------
    # AI Response
    # ------------------------------------------------------------------

    answer = Column(
        Text,
        nullable=True,
    )

    # ------------------------------------------------------------------
    # Performance
    # ------------------------------------------------------------------

    confidence = Column(
        Float,
        nullable=True,
    )

    query_time_ms = Column(
        Integer,
        nullable=True,
    )

    web_search_used = Column(
        Boolean,
        default=False,
    )

    # "up" | "down" | null. Set once, then locked — enforced in the route,
    # not just the UI, so a replayed request can't submit feedback twice.
    feedback = Column(
        String(10),
        nullable=True,
    )

    # Uploaded document metadata (Notice Reply / Summarizer). Attached to
    # the USER message row, since the upload is something the user
    # provided. `attachment_path` is a storage-relative path (see
    # app/utils/storage.py), never served directly — always through the
    # authenticated /ai/messages/{id}/attachment download route.
    attachment_filename = Column(String(255), nullable=True)
    attachment_content_type = Column(String(100), nullable=True)
    attachment_size = Column(Integer, nullable=True)
    attachment_path = Column(String(500), nullable=True)

    # ------------------------------------------------------------------
    # Structured Response
    # ------------------------------------------------------------------

    sources = Column(
        JSONB,
        nullable=True,
    )

    related_judgements = Column(
        JSONB,
        nullable=True,
    )

    verification = Column(
        JSONB,
        nullable=True,
    )

    pipeline = Column(
        JSONB,
        nullable=True,
    )

    provider_metadata = Column(
            JSONB,
            nullable=True,
        )

    # Complete vendor response
    raw_response = Column(
        JSONB,
        nullable=True,
    )

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------

    conversation = relationship(
        "AIConversation",
        back_populates="messages",
    )

    parent_message = relationship(
        "AIMessage",
        remote_side=[id],
        backref="child_messages",
    )

    attachments = relationship(
        "AIAttachment",
        back_populates="message",
        cascade="all, delete-orphan",
    )

    feedback = relationship(
        "AIFeedback",
        back_populates="message",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            "idx_ai_message_conversation_created",
            "conversation_id",
            "created_at",
        ),
        Index(
            "idx_ai_message_provider_message",
            "provider_message_id",
        ),
        Index(
            "idx_ai_message_provider_search",
            "provider_search_id",
        ),
        Index(
            "idx_ai_message_parent",
            "parent_message_id",
        ),
    )

class AIAttachment(Base):
    """
    Stores files uploaded by the user.

    Used for:
    - Notice Reply
    - Summarizer
    - Future RAG uploads
    """

    __tablename__ = "ai_attachments"

    id = Column(Integer, primary_key=True, index=True)

    conversation_id = Column(
        Integer,
        ForeignKey("ai_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    message_id = Column(
        Integer,
        ForeignKey("ai_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Original filename uploaded by user
    original_name = Column(
        String(500),
        nullable=False,
    )

    # Stored filename (UUID or generated name)
    stored_name = Column(
        String(500),
        nullable=False,
    )

    mime_type = Column(
        String(100),
        nullable=True,
    )

    file_size = Column(
        BigInteger,
        nullable=True,
    )

    storage_path = Column(
        String(1000),
        nullable=False,
    )

    checksum = Column(
        String(255),
        nullable=True,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
    )

    # Relationships

    conversation = relationship(
        "AIConversation",
        back_populates="attachments",
    )

    message = relationship(
        "AIMessage",
        back_populates="attachments",
    )

class AIFeedback(Base):
    """
    Stores user feedback for an AI response.

    This maps to the provider feedback endpoint while also
    preserving our own application feedback history.
    """

    __tablename__ = "ai_feedback"

    id = Column(Integer, primary_key=True, index=True)

    message_id = Column(
        Integer,
        ForeignKey("ai_messages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Provider feedback id returned by vendor
    provider_feedback_id = Column(
        String(255),
        nullable=True,
        index=True,
    )

    # Rating
    # positive
    # negative
    rating = Column(
        String(20),
        nullable=False,
    )

    # Example:
    # ["Incorrect Citation", "Hallucination"]
    issue_categories = Column(
        JSONB,
        nullable=True,
    )

    user_comment = Column(
        Text,
        nullable=True,
    )

    expected_answer = Column(
        Text,
        nullable=True,
    )

    provider_metadata = Column(
            JSONB,
            nullable=True,
        )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # Relationships

    message = relationship(
        "AIMessage",
        back_populates="feedback",
    )