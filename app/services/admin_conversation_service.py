"""
Admin access to AI conversation history.

The data has existed all along in AIConversation/AIMessage (app/models/ai.py)
— ChatService already has everything needed to serialize a single user's
own conversations, but nothing let an admin browse across ALL users, which
is what both the per-user "AI Conversations" tab and the global
Admin > Logs page need. This module is that missing layer: plain read
queries plus ChatService's existing serializers, no new data model.
"""

from typing import Optional

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.ai import AIConversation
from app.models.user import User
from app.services.chat import ChatService


def list_conversations_for_admin(
    db: Session,
    *,
    page: int = 1,
    limit: int = 20,
    user_id: Optional[int] = None,
    module: Optional[str] = None,
    tool: Optional[str] = None,
    search: Optional[str] = None,
) -> dict:
    """Global conversation browser — Admin > Logs. Filterable by user,
    module (income-tax/gst/...), tool, and a title/user search."""

    query = (
        db.query(AIConversation, User)
        .join(User, User.id == AIConversation.user_id)
        .filter(AIConversation.deleted_at.is_(None))
    )

    if user_id:
        query = query.filter(AIConversation.user_id == user_id)
    if module:
        query = query.filter(AIConversation.module == module)
    if tool:
        query = query.filter(AIConversation.tool == tool)
    if search:
        term = f"%{search}%"
        query = query.filter(
            or_(
                AIConversation.title.ilike(term),
                User.name.ilike(term),
                User.email.ilike(term),
            )
        )

    total = query.count()
    rows = (
        query.order_by(AIConversation.last_message_at.desc().nullslast(), AIConversation.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    items = [
        {
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
            "user_id": user.id,
            "user_name": user.name,
            "user_email": user.email,
        }
        for conversation, user in rows
    ]

    return {"items": items, "total": total, "page": page, "limit": limit}


def get_conversation_for_admin(db: Session, conversation_id: int, *, user_id: Optional[int] = None) -> dict:
    """A single conversation with its full message history — the "view
    more" drill-down from either Admin > Logs or a user's AI Conversations
    tab. `user_id`, when given, scopes the lookup to that user (used by the
    per-user tab so one admin URL can't be used to browse another user's
    conversation by guessing an id)."""

    query = db.query(AIConversation, User).join(User, User.id == AIConversation.user_id).filter(
        AIConversation.id == conversation_id,
        AIConversation.deleted_at.is_(None),
    )
    if user_id is not None:
        query = query.filter(AIConversation.user_id == user_id)

    row = query.first()
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    conversation, user = row

    chat = ChatService(db)
    data = chat.serialize_conversation(conversation, include_messages=True)
    data["user_id"] = user.id
    data["user_name"] = user.name
    data["user_email"] = user.email
    return data


def list_user_conversations_for_admin(db: Session, user_id: int, *, page: int = 1, limit: int = 20) -> dict:
    """Per-user AI Conversations tab on the user detail page."""
    return list_conversations_for_admin(db, page=page, limit=limit, user_id=user_id)
