"""
AI usage limits.

One row per user. Reused rather than duplicated: actual usage HISTORY
(what was asked, when) already exists in AIConversation/AIMessage
(app/models/ai.py) — this table only stores the *limits and counters*,
never a copy of conversation data. Admin "view conversation history"
queries AIConversation/AIMessage directly (see subscription_service.py);
this table is purely for enforcing/displaying quota.
"""

from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, BigInteger
from sqlalchemy.orm import relationship

from app.db import Base


class AIUsageLimit(Base):
    __tablename__ = "ai_usage_limits"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)

    # Question-count limits. Null = unlimited for that period.
    daily_limit = Column(Integer, nullable=True)
    daily_used = Column(Integer, nullable=False, default=0)

    monthly_limit = Column(Integer, nullable=True)
    monthly_used = Column(Integer, nullable=False, default=0)

    yearly_limit = Column(Integer, nullable=True)
    yearly_used = Column(Integer, nullable=False, default=0)

    # Token-based limit, independent of question counts (a query can cost
    # a variable number of tokens — e.g. deep research costs more).
    token_balance = Column(BigInteger, nullable=True)  # null = unlimited
    tokens_used = Column(BigInteger, nullable=False, default=0)

    # daily | weekly | monthly | yearly | manual | on_renewal
    reset_frequency = Column(String(20), nullable=False, default="monthly")
    last_reset_at = Column(DateTime, default=datetime.utcnow)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])