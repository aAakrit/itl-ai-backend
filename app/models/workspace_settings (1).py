from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.user import User
from app.routes.auth import get_current_user, require_admin
from app.services import workspace_settings_service as service

router = APIRouter(tags=["Workspace Settings"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class WorkspaceSettingsUpdate(BaseModel):
    allow_conversation_export: Optional[bool] = None
    show_citations_by_default: Optional[bool] = None
    default_module: Optional[str] = None
    announcement_banner: Optional[str] = None
    support_email: Optional[str] = None


class UserPreferencesUpdate(BaseModel):
    theme: Optional[str] = None  # light | dark | system
    compact_mode: Optional[bool] = None
    show_citations: Optional[bool] = None


def _settings_dict(settings) -> dict:
    return {
        "allow_conversation_export": settings.allow_conversation_export,
        "show_citations_by_default": settings.show_citations_by_default,
        "default_module": settings.default_module,
        "announcement_banner": settings.announcement_banner,
        "support_email": settings.support_email,
        "updated_at": settings.updated_at,
    }


# =============================================================================
# Admin — configure the settings every user's workspace inherits
# =============================================================================

@router.get("/admin/workspace-settings")
def get_workspace_settings(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return _settings_dict(service.get_settings(db))


@router.put("/admin/workspace-settings")
def update_workspace_settings(
    payload: WorkspaceSettingsUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return _settings_dict(service.update_settings(db, admin.id, payload.dict(exclude_unset=True)))


# =============================================================================
# User-facing — effective settings for their own workspace
# =============================================================================

@router.get("/workspace/settings")
def get_my_workspace_settings(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return service.get_effective_settings(db, user.id)


@router.put("/workspace/settings")
def update_my_workspace_settings(
    payload: UserPreferencesUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service.update_user_preferences(db, user.id, payload.dict(exclude_unset=True))
    return service.get_effective_settings(db, user.id)
