"""
Audit log.

No audit infrastructure existed anywhere in the project before this —
confirmed by search, not assumed. This single generic table covers every
"log this admin action" requirement in one place, INCLUDING approval
history: `User.approved_at`/`approved_by` (see app/models/user.py) only
ever stores the *latest* approval snapshot, not a history. Rather than
adding a second, narrower "approval_history" table, approvals are just
audit log rows with action="user.approved" — one mechanism, not two.
"""

from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.db import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)

    # Nullable for system-initiated entries (e.g. an automatic subscription
    # expiry) — most rows will have an actor.
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # e.g. "subscription.created", "subscription.extended", "user.approved",
    # "payment.recorded_cash", "ai_limit.updated", "password.reset"
    action = Column(String(100), nullable=False, index=True)

    # e.g. "user", "subscription", "payment"
    target_type = Column(String(50), nullable=False, index=True)
    target_id = Column(Integer, nullable=False, index=True)

    previous_value = Column(JSONB, nullable=True)
    new_value = Column(JSONB, nullable=True)
    reason = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    actor = relationship("User", foreign_keys=[actor_id])