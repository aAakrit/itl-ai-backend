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
# Notice Reply AI — staged conversational workflow
# =============================================================================

class NoticeAnalyzeRequest(BaseModel):
    """
    Stage 1 (pasted/typed) — POST /api/notice/analyze. Vendor's
    notice_text is required, ≤50000 chars; user_name/business_name/gstin/
    address are optional context the vendor uses for tailoring the reply,
    never guessed if absent.
    """

    conversation_id: int | None = None

    module_id: str = "gst"

    notice_text: str = Field(..., min_length=1, max_length=50000)

    user_name: str | None = None
    business_name: str | None = None
    gstin: str | None = None
    address: str | None = None


class NoticePerAllegationInput(BaseModel):
    allegation_no: int
    response: str | None = None


class NoticeUserInputs(BaseModel):
    """
    All fields optional — an empty/omitted body is the "draft now, based
    only on the uploaded notice" path (§B3). Never required to unblock
    drafting.
    """

    brief_facts: str | None = None
    explanation: str | None = None
    legal_grounds: str | None = None
    supporting_documents: list[str] | None = None
    additional_info: str | None = None
    per_allegation: list[NoticePerAllegationInput] | None = None


class NoticeDraftRequest(BaseModel):
    """
    Stage 2 — POST /api/notice/draft. `analysis_id` is intentionally NOT
    accepted here: it's looked up server-side from the notice's stored
    session state, matching the vendor's "you do not re-send them" note
    in §B3 and preventing a client from drafting against a stale/foreign
    analysis_id.
    """

    conversation_id: int

    user_inputs: NoticeUserInputs | None = None


class NoticeRefineRequest(BaseModel):
    """
    Stage 3 — POST /api/notice/refine. Repeatable; `draft_id` is likewise
    looked up server-side (always refines the latest revision).
    """

    conversation_id: int

    instruction: str = Field(..., min_length=1, max_length=2000)


class NoticeAskRequest(BaseModel):
    """
    §B5 — POST /api/notice/ask. Mid-conversation question that doesn't
    change stage or touch the current draft.
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