"""
Who may use what.

* The ITL AI workspace (everything under /ai/*): admins, staff, and customers with an active
  subscription that includes the ITL AI product. The Bridge-only plans (bundle_*) do NOT include it.
* ITL Bridge AI (the GST AI / Income Tax AI connectors): customers with an active subscription
  that includes ITL Bridge AI.

`GET /access/me` tells the frontend which of these the signed-in user has, so it can decide where
to send them after login and what to show.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.user import User
from app.routes.auth import get_current_user
from app.services import subscription_service

router = APIRouter(prefix="/access", tags=["Access"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def has_workspace_access(db: Session, user: User) -> bool:
    return bool(user.is_admin or user.is_staff or subscription_service.has_itl_ai_access(db, user.id))


def require_workspace_access(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    if not has_workspace_access(db, user):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "WORKSPACE_ACCESS_REQUIRED",
                "message": "Your plan doesn't include the ITL AI workspace. Subscribe to ITL AI to use it.",
            },
        )
    return user


@router.get("/me")
def my_access(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {
        "workspace": has_workspace_access(db, user),
        "bridge": subscription_service.has_bridge_access(db, user.id),
        "is_admin": bool(user.is_admin),
        "is_staff": bool(user.is_staff),
    }
