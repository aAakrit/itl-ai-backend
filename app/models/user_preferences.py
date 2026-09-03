from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String

from app.db import Base


class UserPreferences(Base):
    """
    Personal workspace preferences, one row per user. `show_citations`
    is nullable: null means "inherit the admin's current default" rather
    than a fixed per-user choice — see workspace_settings_service.get_effective_settings.
    """

    __tablename__ = "user_preferences"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)

    theme = Column(String(10), default="system", nullable=False)  # light | dark | system
    compact_mode = Column(Boolean, default=False, nullable=False)
    show_citations = Column(Boolean, nullable=True)  # null = inherit admin default

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
