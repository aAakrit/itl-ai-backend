from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import io

from app.db import SessionLocal
from app.models.user import User
from app.routes.auth import require_admin
from app.schemas.admin_user import UserUpdate
from app.services import admin_user as service
from app.services import admin_conversation_service
from app.services import user_export_service

router = APIRouter(
    prefix="/admin/users",
    tags=["Admin Users"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class UserExportRequest(BaseModel):
    user_ids: list[int] = Field(..., min_items=1, max_items=2000)
    format: str = Field(..., description="xlsx | docx | pdf")
    detail: str = Field("short", description="short | full")


@router.post("/export")
def export_users(
    payload: UserExportRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if payload.format not in ("xlsx", "docx", "pdf"):
        raise HTTPException(status_code=400, detail="format must be one of: xlsx, docx, pdf")
    if payload.detail not in ("short", "full"):
        raise HTTPException(status_code=400, detail="detail must be one of: short, full")

    rows = (
        service.get_users_full_by_ids(db, payload.user_ids)
        if payload.detail == "full"
        else service.get_users_by_ids(db, payload.user_ids)
    )

    if not rows:
        raise HTTPException(status_code=404, detail="None of the selected users could be found.")

    file_bytes, content_type, filename = user_export_service.build_export(rows, payload.format, payload.detail)

    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("")
def get_users(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    role: Optional[str] = None,
    status: Optional[str] = None,
    plan: Optional[str] = None,
    subscription_status: Optional[str] = Query(None, description="active | pending | suspended | cancelled | expired"),
    payment_type: Optional[str] = Query(None, description="paytm | cash | complimentary"),
    payment_status: Optional[str] = Query(None, description="pending | success | failed | refunded"),
    expiry_window: Optional[str] = Query(None, description="expired | today | 7d | 30d | 60d | 90d"),
    expiry_from: Optional[datetime] = None,
    expiry_to: Optional[datetime] = None,
    registration_from: Optional[datetime] = None,
    registration_to: Optional[datetime] = None,
    approval_status: Optional[str] = None,
    state: Optional[str] = None,
    city: Optional[str] = None,
    sort: str = Query("created_at"),
    order: str = Query("desc"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return service.get_users(
        db=db,
        page=page,
        limit=limit,
        search=search,
        role=role,
        status=status,
        plan=plan,
        subscription_status=subscription_status,
        payment_type=payment_type,
        payment_status=payment_status,
        expiry_window=expiry_window,
        expiry_from=expiry_from,
        expiry_to=expiry_to,
        registration_from=registration_from,
        registration_to=registration_to,
        approval_status=approval_status,
        state=state,
        city=city,
        sort=sort,
        order=order,
    )


@router.get("/{user_id}")
def get_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return service.get_user_detail(db, user_id)


@router.put("/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return service.update_user(db, user_id, payload, admin.id)


@router.patch("/{user_id}/approve")
def approve_user(
    user_id: int,
    reason: Optional[str] = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return service.approve_user(db, user_id, admin.id, reason)


@router.patch("/{user_id}/suspend")
def suspend_user(
    user_id: int,
    reason: Optional[str] = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return service.suspend_user(db, user_id, admin.id, reason)


@router.patch("/{user_id}/delete")
def delete_user(
    user_id: int,
    reason: Optional[str] = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return service.delete_user(db, user_id, admin.id, reason)


@router.get("/{user_id}/history")
def get_user_history(
    user_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return service.get_user_history(db, user_id, page, limit)


@router.get("/{user_id}/conversations")
def get_user_conversations(
    user_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return admin_conversation_service.list_user_conversations_for_admin(db, user_id, page=page, limit=limit)


@router.get("/{user_id}/conversations/{conversation_id}")
def get_user_conversation_detail(
    user_id: int,
    conversation_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return admin_conversation_service.get_conversation_for_admin(db, conversation_id, user_id=user_id)
