"""
Admin notifications.

Three triggers, per product requirements:
  1. user_pending_approval  — a new user registered and needs approve/reject
  2. subscription_expiring  — an active subscription expires within 7 days
  3. payment_completed      — a payment (cash or Paytm) succeeded

(1) and (3) are created inline at the exact moment the event happens —
see calls in app/routes/auth.py and app/services/payment_service.py.

(2) has no single triggering event; "expires in 7 days" is only true
relative to the current moment. Rather than adding a scheduler/cron this
project doesn't otherwise have, `list_for_admin` runs `_sync_expiring_soon`
first on every call — cheap (one indexed query), idempotent (skips
subscriptions that already have a live, undismissed notification), and
means the admin notification list is always accurate whenever it's
actually viewed, without needing a background job to keep it that way.
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.models.subscription import Subscription
from app.models.user import User

EXPIRY_WINDOW_DAYS = 7


def create(
    db: Session,
    *,
    type: str,
    title: str,
    body: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
) -> Notification:
    notification = Notification(
        type=type,
        title=title,
        body=body,
        target_type=target_type,
        target_id=target_id,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification


def notify_user_pending_approval(db: Session, user: User) -> Notification:
    return create(
        db,
        type="user_pending_approval",
        title=f"{user.name} needs approval",
        body=f"{user.email} just registered and is awaiting approval or rejection.",
        target_type="user",
        target_id=user.id,
    )


def notify_payment_completed(db: Session, *, user_name: str, plan_name: str, amount: str, payment_id: int) -> Notification:
    return create(
        db,
        type="payment_completed",
        title=f"Payment received from {user_name}",
        body=f"₹{amount} for {plan_name}.",
        target_type="payment",
        target_id=payment_id,
    )


def _sync_expiring_soon(db: Session) -> None:
    now = datetime.utcnow()
    window_end = now + timedelta(days=EXPIRY_WINDOW_DAYS)

    expiring = (
        db.query(Subscription, User)
        .join(User, User.id == Subscription.user_id)
        .filter(
            Subscription.status == "active",
            Subscription.expiry_date.isnot(None),
            Subscription.expiry_date >= now,
            Subscription.expiry_date <= window_end,
        )
        .all()
    )

    if not expiring:
        return

    sub_ids = [sub.id for sub, _ in expiring]
    already_notified = {
        n.target_id
        for n in db.query(Notification.target_id)
        .filter(
            Notification.type == "subscription_expiring",
            Notification.target_type == "subscription",
            Notification.target_id.in_(sub_ids),
            # Re-notify if it was dismissed a while ago and is now closer
            # to expiry again isn't needed — a subscription only crosses
            # into the 7-day window once — but this guards against
            # creating a duplicate on every single page view either way.
        )
        .all()
    }

    for sub, user in expiring:
        if sub.id in already_notified:
            continue
        days_left = max(0, (sub.expiry_date - now).days)
        create(
            db,
            type="subscription_expiring",
            title=f"{user.name}'s subscription expires soon",
            body=f"{sub.plan_name} expires in {days_left} day{'s' if days_left != 1 else ''} ({sub.expiry_date:%d %b %Y}).",
            target_type="subscription",
            target_id=sub.id,
        )


def list_for_admin(db: Session, *, page: int = 1, limit: int = 20, unread_only: bool = False) -> dict:
    _sync_expiring_soon(db)

    query = db.query(Notification)
    if unread_only:
        query = query.filter(Notification.is_read.is_(False))

    total = query.count()
    unread_count = db.query(Notification).filter(Notification.is_read.is_(False)).count()

    items = (
        query.order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return {"items": items, "total": total, "page": page, "limit": limit, "unread_count": unread_count}


def mark_read(db: Session, notification_id: int) -> Optional[Notification]:
    n = db.query(Notification).filter(Notification.id == notification_id).first()
    if not n:
        return None
    n.is_read = True
    n.read_at = datetime.utcnow()
    db.commit()
    db.refresh(n)
    return n


def mark_all_read(db: Session) -> int:
    updated = (
        db.query(Notification)
        .filter(Notification.is_read.is_(False))
        .update({"is_read": True, "read_at": datetime.utcnow()})
    )
    db.commit()
    return updated
