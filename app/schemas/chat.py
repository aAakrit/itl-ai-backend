from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


# --------------------------------------------------------------------------
# Conversation
# --------------------------------------------------------------------------

class ConversationCreate(BaseModel):
    title: Optional[str] = None
    provider: str = "main"
    tool: str = "chat"


class ConversationUpdate(BaseModel):
    title: Optional[str] = None
    is_archived: Optional[bool] = None


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: Optional[str]
    provider: str
    tool: str
    current_provider: Optional[str]
    status: str
    is_archived: bool
    last_message_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------
# Messages
# --------------------------------------------------------------------------

class MessageCreate(BaseModel):
    conversation_id: Optional[int] = None
    query: str


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int

    conversation_id: int

    parent_message_id: Optional[int]

    provider: str

    message_type: str

    status: str

    query: Optional[str]

    answer: Optional[str]

    confidence: Optional[float]

    query_time_ms: Optional[int]

    web_search_used: Optional[bool]

    sources: Optional[List[Dict[str, Any]]]

    related_judgements: Optional[List[Dict[str, Any]]]

    verification: Optional[Dict[str, Any]]

    pipeline: Optional[Dict[str, Any]]

    created_at: datetime


# --------------------------------------------------------------------------
# Chat Response
# --------------------------------------------------------------------------

class ChatResponse(BaseModel):
    conversation: ConversationResponse
    message: MessageResponse


# --------------------------------------------------------------------------
# Conversation List
# --------------------------------------------------------------------------

class ConversationListResponse(BaseModel):
    conversations: List[ConversationResponse]
    total: int