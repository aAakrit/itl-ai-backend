"""
Subscription service.

Follows the same module-level-function style as app/services/cms_page.py
and app/services/book_content_service.py rather than a class — matching
the existing convention rather than introducing a new one.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.subscription import Subscription
from app.models.user import User
from app.services import pricing_service
from app.services.audit_service import log_action

CYCLE_DAYS = {"monthly": 30, "yearly": 365}
TWO_PLACES = Decimal("0.01")


def get(db: Session, subscription_id: int) -> Subscription:
    sub = db.query(Subscription).filter(Subscription.id == subscription_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found.")
    return sub


def get_active_for_user(db: Session, user_id: int) -> Optional[Subscription]:
    return (
        db.query(Subscription)
        .filter(Subscription.user_id == user_id, Subscription.status == "active")
        .order_by(Subscription.expiry_date.desc())
        .first()
    )


def get_latest_for_user(db: Session, user_id: int) -> Optional[Subscription]:
    """Most recent subscription regardless of status — used for user-list summaries."""
    return (
        db.query(Subscription)
        .filter(Subscription.user_id == user_id)
        .order_by(Subscription.created_at.desc())
        .first()
    )


def create_manual(db: Session, admin_id: int, payload) -> Subscription:
    """Admin-created subscription — complimentary, offline renewal, or a manual correction."""

    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    pricing = pricing_service.resolve_plan(db, payload.plan_id, payload.billing_cycle)

    if payload.override_base_price is not None:
        base = payload.override_base_price
        gst_amount = (base * pricing["gst_rate"] / Decimal("100")).quantize(TWO_PLACES)
        pricing = {
            **pricing,
            "base_price": base,
            "gst_amount": gst_amount,
            "payable_amount": (base + gst_amount).quantize(TWO_PLACES),
        }

    start = payload.override_start_date or datetime.utcnow()
    expiry = payload.override_expiry_date or (start + timedelta(days=CYCLE_DAYS.get(payload.billing_cycle, 30)))

    sub = Subscription(
        user_id=payload.user_id,
        plan_id=pricing["plan_id"],
        plan_name=pricing["plan_name"],
        billing_cycle=payload.billing_cycle,
        base_price=pricing["base_price"],
        gst_rate=pricing["gst_rate"],
        gst_amount=pricing["gst_amount"],
        payable_amount=pricing["payable_amount"],
        status="active",
        source=payload.source,
        start_date=start,
        expiry_date=expiry,
        created_by_admin_id=admin_id,
        notes=payload.notes,
    )
    db.add(sub)
    db.flush()

    user.plan = pricing["plan_name"]

    log_action(
        db,
        actor_id=admin_id,
        action=f"subscription.created_{payload.source}",
        target_type="subscription",
        target_id=sub.id,
        new_value={"plan_id": sub.plan_id, "status": sub.status, "expiry_date": str(sub.expiry_date)},
        reason=payload.notes,
    )

    db.commit()
    db.refresh(sub)
    return sub


def update(db: Session, admin_id: int, subscription_id: int, payload) -> Subscription:
    sub = get(db, subscription_id)
    previous = {
        "status": sub.status,
        "plan_id": sub.plan_id,
        "expiry_date": str(sub.expiry_date),
        "start_date": str(sub.start_date),
    }

    data = payload.dict(exclude_unset=True, exclude={"reason"})

    if "plan_id" in data:
        cycle = data.get("billing_cycle") or sub.billing_cycle
        pricing = pricing_service.resolve_plan(db, data["plan_id"], cycle)
        sub.plan_id = pricing["plan_id"]
        sub.plan_name = pricing["plan_name"]
        sub.base_price = pricing["base_price"]
        sub.gst_amount = pricing["gst_amount"]
        sub.payable_amount = pricing["payable_amount"]
        data.pop("plan_id")

    for field, value in data.items():
        setattr(sub, field, value)

    sub.updated_at = datetime.utcnow()
    db.flush()

    log_action(
        db,
        actor_id=admin_id,
        action="subscription.updated",
        target_type="subscription",
        target_id=sub.id,
        previous_value=previous,
        new_value={"status": sub.status, "plan_id": sub.plan_id, "expiry_date": str(sub.expiry_date)},
        reason=payload.reason,
    )

    db.commit()
    db.refresh(sub)
    return sub


def extend(db: Session, admin_id: int, subscription_id: int, days: int, reason: Optional[str]) -> Subscription:
    sub = get(db, subscription_id)
    previous_expiry = sub.expiry_date

    base = sub.expiry_date if sub.expiry_date and sub.expiry_date > datetime.utcnow() else datetime.utcnow()
    sub.expiry_date = base + timedelta(days=days)
    if sub.status in ("expired", "cancelled"):
        sub.status = "active"
    sub.updated_at = datetime.utcnow()
    db.flush()

    log_action(
        db,
        actor_id=admin_id,
        action="subscription.extended",
        target_type="subscription",
        target_id=sub.id,
        previous_value={"expiry_date": str(previous_expiry)},
        new_value={"expiry_date": str(sub.expiry_date), "days": days},
        reason=reason,
    )

    db.commit()
    db.refresh(sub)
    return sub


def set_status(db: Session, admin_id: int, subscription_id: int, status: str, reason: Optional[str]) -> Subscription:
    """Shared implementation for suspend / cancel / activate."""
    sub = get(db, subscription_id)
    previous_status = sub.status
    sub.status = status
    sub.updated_at = datetime.utcnow()
    db.flush()

    log_action(
        db,
        actor_id=admin_id,
        action=f"subscription.{status}",
        target_type="subscription",
        target_id=sub.id,
        previous_value={"status": previous_status},
        new_value={"status": status},
        reason=reason,
    )

    db.commit()
    db.refresh(sub)
    return sub


def list_subscriptions(
    db: Session,
    *,
    page: int = 1,
    limit: int = 20,
    status: Optional[str] = None,
    plan_id: Optional[str] = None,
    source: Optional[str] = None,
    search: Optional[str] = None,
    expiry_window: Optional[str] = None,  # expired | today | 7d | 30d | 60d | 90d
    expiry_from: Optional[datetime] = None,
    expiry_to: Optional[datetime] = None,
) -> dict:
    query = db.query(Subscription).join(User, Subscription.user_id == User.id)

    if status:
        query = query.filter(Subscription.status == status)
    if plan_id:
        query = query.filter(Subscription.plan_id == plan_id)
    if source:
        query = query.filter(Subscription.source == source)
    if search:
        query = query.filter(or_(User.name.ilike(f"%{search}%"), User.email.ilike(f"%{search}%")))

    now = datetime.utcnow()
    if expiry_window == "expired":
        query = query.filter(Subscription.expiry_date < now)
    elif expiry_window == "today":
        query = query.filter(Subscription.expiry_date >= now, Subscription.expiry_date < now + timedelta(days=1))
    elif expiry_window in ("7d", "30d", "60d", "90d"):
        days = int(expiry_window.rstrip("d"))
        query = query.filter(Subscription.expiry_date >= now, Subscription.expiry_date <= now + timedelta(days=days))
    elif expiry_from or expiry_to:
        if expiry_from:
            query = query.filter(Subscription.expiry_date >= expiry_from)
        if expiry_to:
            query = query.filter(Subscription.expiry_date <= expiry_to)

    total = query.count()
    items = (
        query.order_by(Subscription.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return {"items": items, "total": total, "page": page, "limit": limit}