from typing import Any

from pydantic import BaseModel, Field


# =============================================================================
# Base Models
# =============================================================================

class SessionRequest(BaseModel):
    """
    Base request containing an optional session identifier.
    """

    session_id: str | None = None


class QueryRequest(SessionRequest):
    """
    Base query request shared across AI services.
    """

    query: str = Field(..., min_length=1)

    metadata: dict[str, Any] | None = None


# =============================================================================
# Main AI
# =============================================================================

class AIQueryRequest(QueryRequest):
    """
    Main AI query request.
    """

    deep_research: bool = False


class ClarifyRequest(SessionRequest):
    """
    Clarification request.
    """

    query: str = Field(..., min_length=1)

    previous_answer: str = Field(..., min_length=1)


class RefineRequest(SessionRequest):
    """
    Refine an existing answer.
    """

    query: str = Field(..., min_length=1)

    previous_answer: str = Field(..., min_length=1)

    instruction: str = Field(..., min_length=1)


class SessionCreateRequest(BaseModel):
    """
    Create or update an AI session.
    """

    session_id: str | None = None

    title: str | None = None

    metadata: dict[str, Any] | None = None


class AnalyticsRequest(BaseModel):
    """
    Analytics request.
    """

    session_id: str | None = None

    start_date: str | None = None

    end_date: str | None = None


# =============================================================================
# Judgment AI (Premium / Free)
# =============================================================================

class JudgmentSearchRequest(QueryRequest):
    """
    Search request for Premium and Free Judgment AI.
    """

    filters: dict[str, Any] | None = None


class JudgmentMoreRequest(SessionRequest):
    """
    Request for 'More' results.
    """

    result_id: str = Field(..., min_length=1)


class SimilarRequest(SessionRequest):
    """
    Request for similar judgments.
    """

    judgment_id: str = Field(..., min_length=1)


# =============================================================================
# Feedback
# =============================================================================

class FeedbackRequest(BaseModel):
    """
    User feedback.
    """

    session_id: str

    rating: int = Field(..., ge=1, le=5)

    comment: str | None = None


# =============================================================================
# Generic Response
# =============================================================================

class AIResponse(BaseModel):
    """
    Generic AI response wrapper.
    """

    success: bool = True

    data: dict[str, Any]


class ErrorResponse(BaseModel):
    """
    Generic error response.
    """

    success: bool = False

    error: str

    message: str