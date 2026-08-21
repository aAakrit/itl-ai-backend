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
    Main AI chat request.
    """

    conversation_id: int | None = None

    provider: str = "main"

    tool: str = "chat"

    # Namespaces the conversation by Tax Module (e.g. "income-tax", "gst").
    # The vendor AI itself doesn't distinguish modules yet — this is purely
    # so conversation history stays correctly separated per module in our DB.
    module_id: str = "gst"

    deep_research: bool = False

class ClarifyRequest(BaseModel):
    """
    Query clarification — vendor contract is `{query}` only (confirmed
    against api_io_reference.md). No `previous_answer`/session fields exist
    on this endpoint; the vendor either returns a list of clarifying
    `options` for a vague query, or `needs_clarification: false`.
    """

    query: str = Field(..., min_length=1, max_length=5000)

    # Which bot to clarify against — "main" (Ask Bot, /api/v1/clarify) or
    # "premium" (Case Law Research, /api/judgements/premium/clarify/).
    # This fires before a message/conversation exists, so the frontend
    # must tell us which tool's Clarify button was clicked.
    provider: str = "main"


class RefineRequest(BaseModel):
    """
    Refine an existing answer. Vendor contract (api_io_reference.md):
    {original_query, original_answer, refinement_instructions, message_id?}
    — response has `refined_answer`, not `answer`.
    """

    original_query: str = Field(..., min_length=1, max_length=5000)

    original_answer: str = Field(..., min_length=1, max_length=15000)

    refinement_instructions: str = Field(..., min_length=1, max_length=3000)

    message_id: int | None = None


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
    User feedback. Vendor contract (api_io_reference.md), POST /api/v2/feedback:
    {message_id, rating: "up"|"down", issue_categories?, user_comment?, expected_answer?}
    `message_id` must be the VENDOR's own message id — only returned by v2
    /query (session-based) and the judgement-bot /search endpoints, never by
    v1 /query. See ChatService.submit_feedback for how this is currently handled.
    """

    message_id: int

    rating: str = Field(..., pattern="^(up|down)$")

    issue_categories: list[str] | None = None

    user_comment: str | None = None

    expected_answer: str | None = None


class MessageFeedbackRequest(BaseModel):
    """
    Thumbs up/down on a specific assistant message.
    """

    rating: str = Field(..., pattern="^(up|down)$")


class MessageRefineRequest(BaseModel):
    """
    Free-text instruction for refining a specific assistant message.
    """

    instruction: str = Field(..., min_length=1, max_length=2000)


# =============================================================================
# Notice Reply AI — v3 workflow (analyse -> submissions -> draft -> refine)
# =============================================================================

class NoticeAnalyzeRequest(BaseModel):
    """
    POST /api/notice/analyze. Vendor's notice_text is required, ≤50000
    chars; user_name/business_name/gstin/address are optional context.
    Returns allegations + notice profile ONLY — never a draft.
    """

    conversation_id: int | None = None

    module_id: str = "gst"

    notice_text: str = Field(..., min_length=1, max_length=50000)

    user_name: str | None = None
    business_name: str | None = None
    gstin: str | None = None
    address: str | None = None


class NoticeSubmissionsRequest(BaseModel):
    """
    POST /api/notice/submissions — the facts/evidence loop. `message` is
    free text: facts, evidence description, an answer to a follow-up
    question, or a "reply as it is" trigger phrase, which the vendor
    detects itself and drafts immediately. Auto-drafts once every
    allegation is answered (or `ready_to_draft` is set).
    """

    conversation_id: int

    message: str = Field(..., min_length=1, max_length=8000)
    ready_to_draft: bool = False


class NoticeDraftRequest(BaseModel):
    """
    POST /api/notice/draft — explicit draft trigger. Normally the vendor
    auto-drafts from submissions() once every allegation is answered;
    this is for forcing a draft despite open follow-ups, or redrafting
    with extra instructions / the DIN ground included.
    """

    conversation_id: int

    include_din_ground: bool = False
    extra_instruction: str = Field("", max_length=2000)
    force: bool = False


class NoticeRefineRequest(BaseModel):
    """
    POST /api/notice/refine. Repeatable; v3 has no draft_id concept —
    refine acts on the session's current draft implicitly.
    """

    conversation_id: int

    instruction: str = Field(..., min_length=1, max_length=2000)


class NoticeAskRequest(BaseModel):
    """
    COMPATIBILITY endpoint only — v3 has no standalone /api/notice/ask.
    Dispatches server-side to submissions() or refine() depending on the
    conversation's current phase.
    """

    conversation_id: int

    question: str = Field(..., min_length=1, max_length=2000)


# =============================================================================
# Generic Response
# =============================================================================

class AIResponse(BaseModel):
    """
    Generic success envelope. `data` intentionally accepts Any because
    each AI route (chat, premium search, free search, notice, summarizer,
    health, ...) returns a different shaped payload from the external
    AI service / ChatService, not a single fixed schema.
    """

    success: bool = True

    message: str = "Success"

    data: Any = None


class ErrorResponse(BaseModel):
    """
    Generic error response.
    """

    success: bool = False

    error: str

    message: str