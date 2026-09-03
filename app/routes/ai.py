"""
AI Routes

Exposes endpoints for interacting with external AI services.
"""

import os
import time
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.user import User
from app.routes.auth import get_current_user, require_admin
from app.services.chat import ChatService, NoticeStageError, NoticeUnavailableError
from app.utils.chat import get_chat_service
from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from fastapi import Depends
from fastapi.responses import JSONResponse
from app.utils import storage
from app.schemas.ai import (
    AIQueryRequest,
    AIResponse,
    AnalyticsRequest,
    ClarifyRequest,
    FeedbackRequest,
    JudgmentMoreRequest,
    JudgmentSearchRequest,
    MessageFeedbackRequest,
    MessageRefineRequest,
    NoticeAskRequest,
    NoticeDraftRequest,
    NoticeRefineRequest,
    NoticeSubmissionsRequest,
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
        provider=request.provider,
        tool=request.tool,
        module=request.module_id,
        query=request.query,
        conversation_id=request.conversation_id,
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
    # NOT redundant — this is what the frontend's "Clarify Prompt" composer
    # button actually calls (POST /ai/clarify with just {query}, before the
    # message has been sent / has a conversation to belong to). Kept as a
    # standalone, unauthenticated-payload-shape route for that reason; there
    # is no message-scoped equivalent because there's no message yet.
    #
    # Provider-routed: was previously always calling main's /api/v1/clarify
    # even when the active tool was Case Law Research, which needs
    # /api/judgements/premium/clarify/ instead.
    if request.provider == "premium":
        result = await ai_service.premium_clarify(request.dict(exclude={"provider"}))
    else:
        result = await ai_service.clarify(request.dict(exclude={"provider"}))

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
    # REDUNDANT: the frontend always calls POST /ai/messages/{message_id}/refine
    # instead (see message_refine below), which looks up the original
    # query/answer server-side from the stored message and persists the
    # refined result as a new conversation message. This standalone route
    # requires the caller to supply original_query/original_answer directly
    # and never saves anything — nothing in the app calls it. Kept only for
    # API completeness / potential external callers; safe to remove if none exist.
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
    # REDUNDANT for the same reason as standalone /refine above: the frontend
    # always calls POST /ai/messages/{message_id}/feedback (see
    # message_feedback below), which enforces one-submission-per-message and
    # persists the result. Nothing in the app calls this route.
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


@router.get(
    "/analytics",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="AI Analytics",
    description="Retrieve analytics for AI interactions. Admin only.",
)
async def analytics(
    start_date: str | None = None,
    end_date: str | None = None,
    current_user: User = Depends(require_admin),
):
    result = await ai_service.analytics(
        {k: v for k, v in {"start_date": start_date, "end_date": end_date}.items() if v is not None}
    )

    return success_response(
        data=result,
        message="Analytics retrieved successfully.",
    )

# =============================================================================
# Conversation History
# =============================================================================


@router.get(
    "/conversations",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="List Conversations",
    description="List the current user's saved AI conversations for a given Module + Tool workspace, most recent first.",
)
async def list_conversations(
    module: str | None = None,
    tool: str | None = None,
    provider: str | None = None,
    chat: ChatService = Depends(get_chat_service),
    current_user: User = Depends(get_current_user),
):
    conversations = chat.list_conversations(current_user.id, module=module, tool=tool, provider=provider)

    return success_response(
        data=[chat.serialize_conversation(c) for c in conversations],
        message="Conversations retrieved successfully.",
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Conversation",
    description="Retrieve a single conversation together with its full message history.",
)
async def get_conversation(
    conversation_id: int,
    chat: ChatService = Depends(get_chat_service),
    current_user: User = Depends(get_current_user),
):
    conversation = chat.get_conversation(current_user.id, conversation_id)

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    return success_response(
        data=chat.serialize_conversation(conversation, include_messages=True),
        message="Conversation retrieved successfully.",
    )


@router.delete(
    "/conversations/{conversation_id}",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete Conversation",
    description="Soft-delete a conversation belonging to the current user.",
)
async def delete_conversation(
    conversation_id: int,
    chat: ChatService = Depends(get_chat_service),
    current_user: User = Depends(get_current_user),
):
    deleted = chat.delete_conversation(current_user.id, conversation_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    return success_response(
        data={"id": conversation_id},
        message="Conversation deleted successfully.",
    )


class ConversationRenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)


@router.patch(
    "/conversations/{conversation_id}/rename",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Rename Conversation",
)
async def rename_conversation(
    conversation_id: int,
    payload: ConversationRenameRequest,
    chat: ChatService = Depends(get_chat_service),
    current_user: User = Depends(get_current_user),
):
    conversation = chat.rename_conversation(current_user.id, conversation_id, payload.title)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    return success_response(
        data=chat.serialize_conversation(conversation),
        message="Conversation renamed successfully.",
    )


class ConversationArchiveRequest(BaseModel):
    archived: bool = True


@router.patch(
    "/conversations/{conversation_id}/archive",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Archive/Unarchive Conversation",
)
async def archive_conversation(
    conversation_id: int,
    payload: ConversationArchiveRequest,
    chat: ChatService = Depends(get_chat_service),
    current_user: User = Depends(get_current_user),
):
    conversation = chat.set_archived(current_user.id, conversation_id, payload.archived)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    return success_response(
        data=chat.serialize_conversation(conversation),
        message="Conversation updated successfully.",
    )


@router.post(
    "/messages/{message_id}/feedback",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Message Feedback",
    description="Submit thumbs up/down on a specific assistant message. One submission per message.",
)
async def message_feedback(
    message_id: int,
    request: MessageFeedbackRequest,
    chat: ChatService = Depends(get_chat_service),
    current_user: User = Depends(get_current_user),
):
    try:
        message = await chat.submit_feedback(
            user_id=current_user.id,
            message_id=message_id,
            rating=request.rating,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Message not found.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return success_response(
        data={"id": message.id, "feedback": message.feedback},
        message="Feedback submitted successfully.",
    )


@router.post(
    "/messages/{message_id}/refine",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Refine Message",
    description="Refine an assistant answer per free-text instruction, appended as a new message in the same conversation.",
)
async def message_refine(
    message_id: int,
    request: MessageRefineRequest,
    chat: ChatService = Depends(get_chat_service),
    current_user: User = Depends(get_current_user),
):
    try:
        refined = await chat.refine(
            user_id=current_user.id,
            message_id=message_id,
            instruction=request.instruction,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Message not found.")

    return success_response(
        data=chat.serialize_message(refined),
        message="Message refined successfully.",
    )


@router.get(
    "/messages/{message_id}/attachment",
    summary="Download Message Attachment",
    description="Download the original file uploaded with a Notice Reply / Summarizer message.",
)
async def download_message_attachment(
    message_id: int,
    chat: ChatService = Depends(get_chat_service),
    current_user: User = Depends(get_current_user),
):
    message = chat.get_owned_message(current_user.id, message_id)

    if not message or not message.attachment_path:
        raise HTTPException(status_code=404, detail="Attachment not found.")

    try:
        content = storage.read_file(message.attachment_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Attachment file is missing from storage.")

    return Response(
        content=content,
        media_type=message.attachment_content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{message.attachment_filename or "download"}"',
        },
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

ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".txt"}


@router.post(
    "/notice/generate",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate Notice Reply",
    description="Generate a legal notice reply, optionally from an uploaded document.",
)
async def generate_notice_reply(
    query: str = Form(""),
    conversation_id: int | None = Form(None),
    module_id: str = Form("gst"),
    gstin: str | None = Form(None),
    file: UploadFile | None = File(None),
    chat: ChatService = Depends(get_chat_service),
    current_user: User = Depends(get_current_user),
):
    # Vendor's two real endpoints (confirmed against actual FastAPI source):
    # POST /api/notice/process (JSON, text-only, notice_text required) and
    # POST /api/notice/process-file (multipart, file-only, no notice_text
    # field at all — text is extracted from the file server-side). So
    # unlike the file endpoint's own "any of .pdf/.docx/.txt", here at
    # least one of file/text is still required from OUR side.
    if not query.strip() and not file:
        raise HTTPException(
            status_code=422,
            detail="Provide either notice text or an attached file.",
        )

    if file and file.filename:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_DOCUMENT_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}. Use PDF, DOCX, or TXT.")

    display_query = query.strip() or f"[Notice file: {file.filename}]"

    # user_name/business_name/gstin/address are accepted by BOTH vendor
    # endpoints — notice_text is NOT (it only exists on the text endpoint;
    # process_document/call_upload_provider pick the right vendor endpoint
    # based on whether a file is present, so only include notice_text when
    # there isn't one).
    extra_fields = {
        "user_name": current_user.name or "",
        "business_name": current_user.firm or "",
        "gstin": gstin or "",
        "address": current_user.address or "",
    }
    if not file:
        extra_fields["notice_text"] = query

    result = await chat.process_document(
        user_id=current_user.id,
        query=display_query,
        provider="notice",
        tool="process",
        module=module_id,
        conversation_id=conversation_id,
        file=file,
        extra_fields=extra_fields,
    )

    return success_response(
        data=result,
        message="Notice reply generated successfully.",
    )


@router.get(
    "/notice/types",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="List Notice Types",
    description="List the notice types the Notice Reply agent recognizes.",
)
async def list_notice_types(current_user: User = Depends(get_current_user)):
    result = await ai_service.get_notice_types()

    return success_response(
        data=result,
        message="Notice types retrieved successfully.",
    )


# -----------------------------------------------------------------------
# Notice Reply AI — v3 workflow (Aug 2026 vendor contract, base URL
# host:5002 — a different port from the earlier v2 contract this
# replaces).
#
# uploaded -> ANALYSED_AWAITING_FACTS -> COLLECTING_FACTS -> DRAFTED
#
# analyze() never returns a draft. submissions() runs the facts/evidence
# loop and auto-drafts once every allegation is answered (or on a "reply
# as it is" trigger the vendor detects itself). draft() forces a draft
# explicitly. refine() edits the current draft — v3 has no draft_id
# concept, it acts on the session implicitly. There is no v3 /ask
# endpoint; /notice/ask below is a compatibility shim for callers not yet
# updated to call submissions/refine directly.
# /notice/generate above is the legacy one-shot path — v3 repurposes it as
# an explicit "reply as it is" shortcut, still analysing AND drafting in
# one call — and is untouched by any of this.
# -----------------------------------------------------------------------


@router.post(
    "/notice/analyze",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze Notice (Text)",
    description="Analyse pasted/typed notice text into allegations + notice profile. Never returns a draft.",
)
async def analyze_notice(
    notice_text: str = Form(..., min_length=1, max_length=50000),
    conversation_id: int | None = Form(None),
    module_id: str = Form("gst"),
    user_name: str | None = Form(None),
    business_name: str | None = Form(None),
    gstin: str | None = Form(None),
    address: str | None = Form(None),
    chat: ChatService = Depends(get_chat_service),
    current_user: User = Depends(get_current_user),
):
    try:
        result = await chat.analyze_notice(
            user_id=current_user.id,
            conversation_id=conversation_id,
            module=module_id,
            notice_text=notice_text,
            user_name=user_name or current_user.name or "",
            business_name=business_name or current_user.firm or "",
            gstin=gstin or "",
            address=address or current_user.address or "",
        )
    except NoticeUnavailableError as exc:
        return JSONResponse(
            status_code=503,
            content={"success": False, "error": "notice_unavailable", "detail": exc.detail},
        )

    return success_response(
        data=result,
        message="Notice analysed successfully.",
    )


@router.post(
    "/notice/analyze-file",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze Notice (File)",
    description="Analyse an uploaded notice document into allegations + notice profile. Never returns a draft.",
)
async def analyze_notice_file(
    file: UploadFile = File(...),
    conversation_id: int | None = Form(None),
    module_id: str = Form("gst"),
    user_name: str | None = Form(None),
    business_name: str | None = Form(None),
    gstin: str | None = Form(None),
    address: str | None = Form(None),
    chat: ChatService = Depends(get_chat_service),
    current_user: User = Depends(get_current_user),
):
    if file.filename:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_DOCUMENT_EXTENSIONS and ext != ".pdf":
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}. Use PDF, DOCX, or TXT.")

    try:
        result = await chat.analyze_notice(
            user_id=current_user.id,
            conversation_id=conversation_id,
            module=module_id,
            file=file,
            user_name=user_name or current_user.name or "",
            business_name=business_name or current_user.firm or "",
            gstin=gstin or "",
            address=address or current_user.address or "",
        )
    except NoticeUnavailableError as exc:
        return JSONResponse(
            status_code=503,
            content={"success": False, "error": "notice_unavailable", "detail": exc.detail},
        )

    return success_response(
        data=result,
        message="Notice analysed successfully.",
    )


@router.post(
    "/notice/submissions",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit Facts/Evidence For A Notice",
    description=(
        "Facts/evidence loop. Auto-drafts once every allegation is answered, or immediately "
        'on a "reply as it is" style message.'
    ),
)
async def submit_notice_facts(
    request: NoticeSubmissionsRequest,
    chat: ChatService = Depends(get_chat_service),
    current_user: User = Depends(get_current_user),
):
    try:
        result = await chat.submit_notice_facts(
            user_id=current_user.id,
            conversation_id=request.conversation_id,
            message=request.message,
            ready_to_draft=request.ready_to_draft,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    except NoticeStageError as exc:
        return JSONResponse(status_code=409, content=exc.detail)

    return success_response(
        data=result,
        message="Submission recorded.",
    )


@router.post(
    "/notice/submissions-file",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit Evidence Files For A Notice",
    description="Multipart evidence upload — multiple files in one call.",
)
async def submit_notice_evidence_file(
    files: list[UploadFile] = File(...),
    conversation_id: int = Form(...),
    note: str | None = Form(None),
    force_draft: bool = Form(False),
    chat: ChatService = Depends(get_chat_service),
    current_user: User = Depends(get_current_user),
):
    try:
        result = await chat.submit_notice_evidence_file(
            user_id=current_user.id,
            conversation_id=conversation_id,
            files=files,
            note=note or "",
            force_draft=force_draft,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    except NoticeStageError as exc:
        return JSONResponse(status_code=409, content=exc.detail)

    return success_response(
        data=result,
        message="Evidence submitted.",
    )


@router.post(
    "/notice/draft",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Draft Notice Reply",
    description="Force a draft explicitly, optionally with extra instructions or the DIN ground included.",
)
async def draft_notice(
    request: NoticeDraftRequest,
    chat: ChatService = Depends(get_chat_service),
    current_user: User = Depends(get_current_user),
):
    try:
        result = await chat.draft_notice(
            user_id=current_user.id,
            conversation_id=request.conversation_id,
            include_din_ground=request.include_din_ground,
            extra_instruction=request.extra_instruction,
            force=request.force,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    except NoticeStageError as exc:
        return JSONResponse(status_code=409, content=exc.detail)

    return success_response(
        data=result,
        message="Notice reply drafted successfully.",
    )


@router.post(
    "/notice/refine",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Refine Notice Reply",
    description="Refine the current draft by free-text instruction. Repeatable.",
)
async def refine_notice(
    request: NoticeRefineRequest,
    chat: ChatService = Depends(get_chat_service),
    current_user: User = Depends(get_current_user),
):
    try:
        result = await chat.refine_notice(
            user_id=current_user.id,
            conversation_id=request.conversation_id,
            instruction=request.instruction,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    except NoticeStageError as exc:
        return JSONResponse(status_code=409, content=exc.detail)

    return success_response(
        data=result,
        message="Notice reply refined successfully.",
    )


@router.post(
    "/notice/ask",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Ask About Notice (compatibility shim)",
    description=(
        "COMPATIBILITY ONLY — v3 has no standalone ask endpoint. Dispatches to submissions "
        "or refine depending on phase."
    ),
)
async def ask_notice(
    request: NoticeAskRequest,
    chat: ChatService = Depends(get_chat_service),
    current_user: User = Depends(get_current_user),
):
    try:
        result = await chat.ask_notice(
            user_id=current_user.id,
            conversation_id=request.conversation_id,
            question=request.question,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    except NoticeStageError as exc:
        return JSONResponse(status_code=409, content=exc.detail)

    return success_response(
        data=result,
        message="Question answered successfully.",
    )


# =============================================================================
# Document Summarizer
# =============================================================================


@router.post(
    "/summarize",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Summarize Document",
    description="Generate an AI summary, optionally from an uploaded document.",
)
async def summarize_document(
    query: str = Form(""),
    conversation_id: int | None = Form(None),
    module_id: str = Form("gst"),
    user_instructions: str = Form(""),
    output_format: str | None = Form(None),
    force_async: bool = Form(False),
    force_sync: bool = Form(False),
    file: UploadFile | None = File(None),
    chat: ChatService = Depends(get_chat_service),
    current_user: User = Depends(get_current_user),
):
    # Vendor's two real endpoints (confirmed against actual FastAPI source):
    # POST /api/summarize/text (JSON — SummarizeTextRequest: document_text
    # required, min 50 / max 2,000,000 chars — raised from 200K) and
    # POST /api/summarize/file (multipart — no document_text field at all,
    # text is extracted from the file). Neither streams SSE — a prior doc
    # claimed otherwise; the actual source code overrides that.
    #
    # /file now branches on size: small docs return the full result inline
    # (mode: "sync"); large docs return a background job (mode: "async") —
    # force_async/force_sync map directly to the vendor's own query params
    # on that endpoint and are ignored for /text (always synchronous).
    if not query.strip() and not file:
        raise HTTPException(
            status_code=422,
            detail="Provide either text to summarize or an attached file.",
        )

    if file and file.filename:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_DOCUMENT_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}. Use PDF, DOCX, or TXT.")

    if not file and len(query.strip()) < 50:
        # Vendor's own Pydantic min_length=50 on document_text — checked
        # here too so the person gets a clear, immediate message instead of
        # a raw vendor 422.
        raise HTTPException(
            status_code=422,
            detail="Text to summarize must be at least 50 characters (or attach a file instead).",
        )

    display_query = query.strip() or f"[Summarize file: {file.filename}]"

    # document_text only exists on the text endpoint — omitted when a file
    # is present, same reasoning as notice_text above.
    extra_fields = {"user_instructions": user_instructions}
    if output_format:
        extra_fields["output_format"] = output_format
    if not file:
        extra_fields["document_text"] = query

    result = await chat.process_document(
        user_id=current_user.id,
        query=display_query,
        provider="summarizer",
        tool="summarize",
        module=module_id,
        conversation_id=conversation_id,
        file=file,
        extra_fields=extra_fields,
        force_async=force_async,
        force_sync=force_sync,
    )

    return success_response(
        data=result,
        message="Document summarized successfully.",
    )


@router.get(
    "/summarize/status/{job_id}",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Summarize Job Status",
    description="Poll the status of a background Summarizer job (large documents).",
)
async def get_summarize_job_status(
    job_id: str,
    chat: ChatService = Depends(get_chat_service),
    current_user: User = Depends(get_current_user),
):
    try:
        result = await chat.get_job_status(current_user.id, job_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Job not found.")

    return success_response(data=result, message="Job status retrieved.")


@router.get(
    "/summarize/result/{job_id}",
    response_model=AIResponse,
    status_code=status.HTTP_200_OK,
    summary="Summarize Job Result",
    description="Fetch a background Summarizer job's result once done — saves it to the conversation the first time it's called.",
)
async def get_summarize_job_result(
    job_id: str,
    chat: ChatService = Depends(get_chat_service),
    current_user: User = Depends(get_current_user),
):
    try:
        result = await chat.finalize_job(current_user.id, job_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Job not found.")

    return success_response(
        data=result,
        message="Job result retrieved." if result.get("ready") else "Job still processing.",
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
        started = time.monotonic()
        checked_at = datetime.utcnow().isoformat()
        try:
            raw = await ai_service.health(provider)
            result[provider] = {
                "status": "healthy",
                "response_time_ms": round((time.monotonic() - started) * 1000),
                "last_checked": checked_at,
                "error": None,
                "details": raw,
            }
        except Exception as exc:
            # A single down provider must not take out the health check for
            # every other provider — this previously let one provider's
            # exception propagate and fail the entire /ai/health call.
            result[provider] = {
                "status": "unhealthy",
                "response_time_ms": round((time.monotonic() - started) * 1000),
                "last_checked": checked_at,
                "error": str(exc),
                "details": None,
            }

    return success_response(
        data=result,
        message="Health check completed successfully.",
    )