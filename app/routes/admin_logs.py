from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.audit_log import AuditLog
from app.models.user import User
from app.routes.auth import require_admin
from app.services import admin_conversation_service

router = APIRouter(tags=["Admin Logs"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =============================================================================
# Admin > Logs — AI conversations across every user
# =============================================================================

@router.get("/admin/conversations")
def list_conversations(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user_id: Optional[int] = None,
    module: Optional[str] = Query(None, description="e.g. income-tax, gst"),
    tool: Optional[str] = Query(None, description="e.g. chat, case_law, notice, summarizer"),
    search: Optional[str] = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return admin_conversation_service.list_conversations_for_admin(
        db, page=page, limit=limit, user_id=user_id, module=module, tool=tool, search=search
    )


@router.get("/admin/conversations/{conversation_id}")
def get_conversation(
    conversation_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return admin_conversation_service.get_conversation_for_admin(db, conversation_id)


# =============================================================================
# Admin > Audit logs — every admin/staff action, full history
# =============================================================================

@router.get("/admin/audit-logs")
def list_audit_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    actor_id: Optional[int] = None,
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    search: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(AuditLog)

    if actor_id:
        query = query.filter(AuditLog.actor_id == actor_id)
    if action:
        query = query.filter(AuditLog.action == action)
    if target_type:
        query = query.filter(AuditLog.target_type == target_type)
    if date_from:
        query = query.filter(AuditLog.created_at >= date_from)
    if date_to:
        query = query.filter(AuditLog.created_at <= date_to)
    if search:
        term = f"%{search}%"
        query = query.filter(AuditLog.reason.ilike(term))

    total = query.count()
    rows = (
        query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    actor_ids = {row.actor_id for row in rows if row.actor_id is not None}
    actors = {}
    if actor_ids:
        actors = {u.id: {"name": u.name, "email": u.email} for u in db.query(User).filter(User.id.in_(actor_ids)).all()}

    items = [
        {
            "id": row.id,
            "actor_id": row.actor_id,
            "actor_name": actors.get(row.actor_id, {}).get("name") if row.actor_id else None,
            "actor_email": actors.get(row.actor_id, {}).get("email") if row.actor_id else None,
            "action": row.action,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "previous_value": row.previous_value,
            "new_value": row.new_value,
            "reason": row.reason,
            "created_at": row.created_at,
        }
        for row in rows
    ]

    return {"items": items, "total": total, "page": page, "limit": limit}


@router.get("/admin/audit-logs/actions")
def list_audit_actions(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Distinct action values seen so far — powers the filter dropdown
    without hardcoding a list that drifts from what log_action() calls
    actually use across the codebase."""
    rows = db.query(AuditLog.action).distinct().order_by(AuditLog.action.asc()).all()
    return {"actions": [r[0] for r in rows]}
