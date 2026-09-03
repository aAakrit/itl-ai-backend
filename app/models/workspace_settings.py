from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.db import Base


class WorkspaceSettings(Base):
    """
    Singleton (always id=1) — admin-configured defaults that shape every
    user's workspace. Not per-user; see UserPreferences for the personal
    layer (theme, etc.) that sits on top of these.
    """

    __tablename__ = "workspace_settings"

    id = Column(Integer, primary_key=True, default=1)

    allow_conversation_export = Column(Boolean, default=True, nullable=False)
    show_citations_by_default = Column(Boolean, default=True, nullable=False)
    default_module = Column(String(50), default="income-tax", nullable=False)

    # Optional banner shown at the top of every user's workspace — empty/null means none.
    announcement_banner = Column(Text, nullable=True)
    support_email = Column(String(255), nullable=True)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by_admin_id = Column(Integer, nullable=True)
