from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.db import Base


class Notification(Base):
    """
    Admin-facing notifications. Two creation patterns:

      * event-triggered — created once, at the moment something happens
        (a user registers, a payment completes). See notification_service.create().
      * derived-on-view — "subscription expiring soon" has no single event
        to hook; it's synced (deduplicated, see notification_service._sync_expiring_soon)
        whenever the admin notification list is queried, rather than requiring
        a cron/scheduler this project doesn't otherwise have.

    Both end up as ordinary rows here — the frontend doesn't need to know
    which path created one.
    """

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)

    # user_pending_approval | payment_completed | subscription_expiring
    type = Column(String(50), nullable=False, index=True)

    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=True)

    # What this notification is about, e.g. target_type="user", target_id=42
    # — lets the frontend deep-link straight to the relevant admin record.
    target_type = Column(String(50), nullable=True, index=True)
    target_id = Column(Integer, nullable=True, index=True)

    is_read = Column(Boolean, default=False, nullable=False, index=True)
    read_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
