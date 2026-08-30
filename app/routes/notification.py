from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.user import User
from app.routes.auth import require_admin
from app.schemas.notification import NotificationResponse
from app.services import notification_service as service

router = APIRouter(prefix="/admin/notifications", tags=["Admin Notifications"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("")
def list_notifications(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    unread_only: bool = False,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    result = service.list_for_admin(db, page=page, limit=limit, unread_only=unread_only)
    return {
        **result,
        "items": [NotificationResponse.from_orm(n) for n in result["items"]],
    }


@router.post("/{notification_id}/read", response_model=NotificationResponse)
def mark_read(
    notification_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from fastapi import HTTPException

    n = service.mark_read(db, notification_id)
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found.")
    return n


@router.post("/read-all")
def mark_all_read(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    updated = service.mark_all_read(db)
    return {"success": True, "updated": updated}
