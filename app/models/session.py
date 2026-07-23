from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from datetime import datetime
from app.db import Base

class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(Integer, primary_key=True)

    user_id = Column(Integer, ForeignKey("users.id"))

    token_jti = Column(String, unique=True)
    ip_address = Column(String)
    user_agent = Column(String)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    invalidated_at = Column(DateTime, nullable=True)
    invalidation_reason = Column(String, nullable=True)