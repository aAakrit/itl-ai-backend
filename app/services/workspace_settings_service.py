"""
Workspace settings: two layers.

  WorkspaceSettings  — admin-configured, one row, shapes every user's workspace
  UserPreferences    — personal, one row per user, layered on top

`get_effective_settings(db, user_id)` merges them for the workspace UI to
consume in one call — the admin's citations default, for example, is used
unless the user has explicitly chosen their own (show_citations is not None).
"""

from sqlalchemy.orm import Session

from app.models.user_preferences import UserPreferences
from app.models.workspace_settings import WorkspaceSettings

SINGLETON_ID = 1


def get_settings(db: Session) -> WorkspaceSettings:
    settings = db.query(WorkspaceSettings).filter(WorkspaceSettings.id == SINGLETON_ID).first()
    if not settings:
        settings = WorkspaceSettings(id=SINGLETON_ID)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def update_settings(db: Session, admin_id: int, patch: dict) -> WorkspaceSettings:
    settings = get_settings(db)
    for field in ("allow_conversation_export", "show_citations_by_default", "default_module", "announcement_banner", "support_email"):
        if field in patch and patch[field] is not None:
            setattr(settings, field, patch[field])
    settings.updated_by_admin_id = admin_id
    db.commit()
    db.refresh(settings)
    return settings


def get_user_preferences(db: Session, user_id: int) -> UserPreferences:
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == user_id).first()
    if not prefs:
        prefs = UserPreferences(user_id=user_id)
        db.add(prefs)
        db.commit()
        db.refresh(prefs)
    return prefs


def update_user_preferences(db: Session, user_id: int, patch: dict) -> UserPreferences:
    prefs = get_user_preferences(db, user_id)
    for field in ("theme", "compact_mode", "show_citations"):
        if field in patch:
            setattr(prefs, field, patch[field])
    db.commit()
    db.refresh(prefs)
    return prefs


def get_effective_settings(db: Session, user_id: int) -> dict:
    settings = get_settings(db)
    prefs = get_user_preferences(db, user_id)

    return {
        "theme": prefs.theme,
        "compact_mode": prefs.compact_mode,
        "show_citations": prefs.show_citations if prefs.show_citations is not None else settings.show_citations_by_default,
        "allow_conversation_export": settings.allow_conversation_export,
        "default_module": settings.default_module,
        "announcement_banner": settings.announcement_banner,
        "support_email": settings.support_email,
    }
