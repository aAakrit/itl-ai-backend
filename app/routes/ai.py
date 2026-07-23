"""
AI Routes

Exposes endpoints for interacting with external AI services.
"""

from app.models.user import User
from app.routes.auth import get_current_user
from app.services.chat import ChatService
from app.utils.chat import get_chat_service
from fastapi import (
    APIRouter,
    File,
    Form,
    UploadFile,
    status,
)
from fastapi import Depends
from app.schemas.ai import (
    AIQueryRequest,
    AIResponse,
    AnalyticsRequest,
    ClarifyRequest,
    FeedbackRequest,
    JudgmentMoreRequest,
    JudgmentSearchRequest,
    RefineRequest,
    SessionCreateRequest,
    SimilarRequest,
)
from app.services.ai_service import ai_service
from app.utils.response import success_response

router = APIRouter(
    prefix="/ai",
    tags=["AI"],
)

# =============================================================================
# Main AI
# =============================================================================


@router.post(
    "/query",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Query Main AI",
    description="Submit a query to the Main AI service.",
)
async def query(
    request: AIQueryRequest,
    chat: ChatService = Depends(get_chat_service),
    current_user: User = Depends(get_current_user),
):
    result = await chat.query(
        user_id=current_user.id,
        provider="main",
        tool="chat",
        query=request.query,
        conversation_id=getattr(request, "conversation_id", None),
        payload=request.dict(),
    )

    return success_response(
        data=result,
        message="Query processed successfully.",
    )


@router.post(
    "/query/v2",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Query Main AI (v2)",
    description="Submit a query using Main AI API v2.",
)
async def query_v2(request: AIQueryRequest):
    result = await ai_service.query_v2(request.dict())

    return success_response(
        data=result,
        message="Query processed successfully.",
    )


@router.post(
    "/clarify",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Clarify Query",
    description="Generate clarification questions for the submitted query.",
)
async def clarify(request: ClarifyRequest):
    result = await ai_service.clarify(request.dict())

    return success_response(
        data=result,
        message="Clarification generated successfully.",
    )


@router.post(
    "/refine",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Refine Response",
    description="Refine an existing AI response using additional instructions.",
)
async def refine(request: RefineRequest):
    result = await ai_service.refine(request.dict())

    return success_response(
        data=result,
        message="Response refined successfully.",
    )


@router.post(
    "/case-laws",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve Case Laws",
    description="Retrieve relevant case laws related to the submitted query.",
)
async def case_laws(request: AIQueryRequest):
    result = await ai_service.case_laws(request.dict())

    return success_response(
        data=result,
        message="Case laws retrieved successfully.",
    )


@router.post(
    "/feedback",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit Feedback",
    description="Submit user feedback for an AI response.",
)
async def feedback(request: FeedbackRequest):
    result = await ai_service.feedback(request.dict())

    return success_response(
        data=result,
        message="Feedback submitted successfully.",
    )


@router.post(
    "/sessions",
    response_model=AIResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create or Update Session",
    description="Create or update an AI conversation session.",
)
async def create_session(request: SessionCreateRequest):
    result = await ai_service.create_session(request.dict())

    return success_response(
        data=result,
        message="Session created successfully.",
    )


@router.post(
    "/analytics",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="AI Analytics",
    description="Retrieve analytics for AI interactions.",
)
async def analytics(request: AnalyticsRequest):
    result = await ai_service.analytics(request.dict())

    return success_response(
        data=result,
        message="Analytics retrieved successfully.",
    )

# =============================================================================
# Premium Judgment AI
# =============================================================================


@router.post(
    "/premium/search",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Premium Judgment Search",
    description="Search judgments using the Premium AI service.",
)
async def premium_search(request: JudgmentSearchRequest):
    result = await ai_service.premium_search(request.dict())

    return success_response(
        data=result,
        message="Premium judgment search completed successfully.",
    )


@router.post(
    "/premium/more",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Load More Premium Results",
    description="Retrieve additional Premium AI judgment search results.",
)
async def premium_more(request: JudgmentMoreRequest):
    result = await ai_service.premium_more(request.dict())

    return success_response(
        data=result,
        message="Additional premium results retrieved successfully.",
    )


@router.post(
    "/premium/clarify",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Clarify Premium Judgment Query",
    description="Generate clarification questions for a Premium AI judgment query.",
)
async def premium_clarify(request: ClarifyRequest):
    result = await ai_service.premium_clarify(request.dict())

    return success_response(
        data=result,
        message="Premium clarification generated successfully.",
    )


@router.post(
    "/premium/refine",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Refine Premium Judgment Response",
    description="Refine an existing Premium AI judgment response.",
)
async def premium_refine(request: RefineRequest):
    result = await ai_service.premium_refine(request.dict())

    return success_response(
        data=result,
        message="Premium response refined successfully.",
    )


@router.post(
    "/premium/similar",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Find Similar Judgments",
    description="Retrieve judgments similar to the selected Premium judgment.",
)
async def premium_similar(request: SimilarRequest):
    result = await ai_service.premium_similar(request.dict())

    return success_response(
        data=result,
        message="Similar premium judgments retrieved successfully.",
    )


@router.post(
    "/premium/feedback",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit Premium Feedback",
    description="Submit user feedback for Premium AI responses.",
)
async def premium_feedback(request: FeedbackRequest):
    result = await ai_service.premium_feedback(request.dict())

    return success_response(
        data=result,
        message="Premium feedback submitted successfully.",
    )

# =============================================================================
# Free Judgment AI
# =============================================================================


@router.post(
    "/free/search",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Free Judgment Search",
    description="Search judgments using the Free AI service.",
)
async def free_search(request: JudgmentSearchRequest):
    result = await ai_service.free_search(request.dict())

    return success_response(
        data=result,
        message="Free judgment search completed successfully.",
    )


@router.post(
    "/free/more",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Load More Free Results",
    description="Retrieve additional Free AI judgment search results.",
)
async def free_more(request: JudgmentMoreRequest):
    result = await ai_service.free_more(request.dict())

    return success_response(
        data=result,
        message="Additional free results retrieved successfully.",
    )


@router.post(
    "/free/clarify",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Clarify Free Judgment Query",
    description="Generate clarification questions for a Free AI judgment query.",
)
async def free_clarify(request: ClarifyRequest):
    result = await ai_service.free_clarify(request.dict())

    return success_response(
        data=result,
        message="Free clarification generated successfully.",
    )


@router.post(
    "/free/refine",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Refine Free Judgment Response",
    description="Refine an existing Free AI judgment response.",
)
async def free_refine(request: RefineRequest):
    result = await ai_service.free_refine(request.dict())

    return success_response(
        data=result,
        message="Free response refined successfully.",
    )


@router.post(
    "/free/similar",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Find Similar Free Judgments",
    description="Retrieve judgments similar to the selected Free judgment.",
)
async def free_similar(request: SimilarRequest):
    result = await ai_service.free_similar(request.dict())

    return success_response(
        data=result,
        message="Similar free judgments retrieved successfully.",
    )


# =============================================================================
# Notice Reply AI
# =============================================================================


@router.post(
    "/notice/generate",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate Notice Reply",
    description="Generate a legal notice reply from uploaded documents.",
)
async def generate_notice_reply(
    prompt: str = Form(...),
    session_id: str | None = Form(None),
    file: UploadFile = File(...),
):
    payload = {
        "prompt": prompt,
        "session_id": session_id,
    }

    result = await ai_service.generate_notice_reply(
        data=payload,
        files={"file": file},
    )

    return success_response(
        data=result,
        message="Notice reply generated successfully.",
    )


# =============================================================================
# Document Summarizer
# =============================================================================


@router.post(
    "/summarize",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Summarize Document",
    description="Generate an AI summary for the uploaded document.",
)
async def summarize_document(
    prompt: str = Form(...),
    session_id: str | None = Form(None),
    file: UploadFile = File(...),
):
    payload = {
        "prompt": prompt,
        "session_id": session_id,
    }

    result = await ai_service.summarize_document(
        data=payload,
        files={"file": file},
    )

    return success_response(
        data=result,
        message="Document summarized successfully.",
    )


# =============================================================================
# Health Check
# =============================================================================


@router.get(
    "/health",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="AI Gateway Health",
    description="Check the health status of all configured AI providers.",
)
async def health():
    providers = [
        "main",
        "premium",
        "free",
        "notice",
        "summarizer",
    ]

    result = {}

    for provider in providers:
        result[provider] = await ai_service.health(provider)

    return success_response(
        data=result,
        message="Health check completed successfully.",
    )