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
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.subscription import Subscription
from app.models.user import User
from app.services import bridge_service, pricing_service
from app.services import products as product_service
from app.services.audit_service import log_action

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


def has_bridge_access(db: Session, user_id: int) -> bool:
    """True while the customer has an active, unexpired subscription that includes ITL Bridge AI."""
    now = datetime.utcnow()
    subs = (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user_id,
            Subscription.status == "active",
            or_(Subscription.expiry_date.is_(None), Subscription.expiry_date > now),
        )
        .all()
    )
    return any(product_service.BRIDGE in product_service.products_of(s) for s in subs)


def check_purchase_allowed(db: Session, user_id: int, new_products: list[str]) -> None:
    """
    Blocks buying something the customer already has more of: e.g. an ITL AI-only
    plan while an ITL AI + ITL Bridge AI subscription is active. Renewing the same
    products, or upgrading ITL AI -> bundle, is fine.
    """
    now = datetime.utcnow()
    actives = (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user_id,
            Subscription.status == "active",
            or_(Subscription.expiry_date.is_(None), Subscription.expiry_date > now),
        )
        .all()
    )
    wanted = set(new_products)
    for sub in actives:
        have = set(product_service.products_of(sub))
        if wanted < have:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"You already have an active {product_service.label(have)} subscription, "
                    f"which includes {product_service.label(wanted)}."
                ),
            )


def activate_purchase(
    db: Session,
    *,
    user_id: int,
    plan: dict,
    amounts: dict,
    source: str,
    admin_id: Optional[int] = None,
    notes: Optional[str] = None,
    start: Optional[datetime] = None,
) -> Subscription:
    """
    Grants what a paid purchase bought. Does NOT commit (the caller's transaction does).

    * Same products already active  -> renewal: that subscription's expiry moves
      forward by the purchased term (counting from its current expiry).
    * Active subscription with fewer products (ITL AI -> ITL AI + Bridge) -> upgrade:
      the new subscription replaces it (no proration).
    * Otherwise -> a new subscription starting now.

    `plan`: plan_id, plan_name, products, term_years, billing_cycle.
    `amounts`: base_price, gst_rate, gst_amount, payable_amount (what was paid).
    """
    now = start or datetime.utcnow()
    products = product_service.validate_sellable(plan["products"])
    term = int(plan["term_years"])
    wanted = set(products)

    actives = (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user_id,
            Subscription.status == "active",
            or_(Subscription.expiry_date.is_(None), Subscription.expiry_date > now),
        )
        .order_by(Subscription.expiry_date.desc())
        .all()
    )

    same = next((s for s in actives if set(product_service.products_of(s)) == wanted), None)
    snapshot = {
        "plan_id": plan["plan_id"],
        "plan_name": plan["plan_name"],
        "billing_cycle": plan.get("billing_cycle") or product_service.cycle_label(term),
        "products": products,
        "term_years": term,
        "base_price": amounts["base_price"],
        "gst_rate": amounts["gst_rate"],
        "gst_amount": amounts["gst_amount"],
        "payable_amount": amounts["payable_amount"],
    }

    if same:
        base = same.expiry_date if same.expiry_date and same.expiry_date > now else now
        same.expiry_date = product_service.add_years(base, term)
        for key, value in snapshot.items():
            setattr(same, key, value)
        same.updated_at = datetime.utcnow()
        if notes:
            same.notes = f"{same.notes}\n{notes}" if same.notes else notes
        db.flush()
        sub = same
    else:
        for old in actives:
            if set(product_service.products_of(old)) < wanted:
                old.status = "cancelled"
                old.notes = (f"{old.notes}\n" if old.notes else "") + f"Superseded by upgrade to {plan['plan_name']}."
                old.updated_at = datetime.utcnow()
        sub = Subscription(
            user_id=user_id,
            status="active",
            source=source,
            start_date=now,
            expiry_date=product_service.add_years(now, term),
            created_by_admin_id=admin_id,
            notes=notes,
            **snapshot,
        )
        db.add(sub)
        db.flush()

    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.plan = plan["plan_name"]
    return sub


def create_manual(db: Session, admin_id: int, payload) -> Subscription:
    """Admin-created subscription — complimentary, offline renewal, or a manual correction."""

    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    pricing = pricing_service.resolve_plan(db, payload.plan_id)
    products = product_service.validate_sellable(payload.products) if getattr(payload, "products", None) else pricing["products"]

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
    expiry = payload.override_expiry_date or product_service.add_years(start, pricing["term_years"])

    sub = Subscription(
        user_id=payload.user_id,
        plan_id=pricing["plan_id"],
        plan_name=pricing["plan_name"],
        billing_cycle=pricing["billing_cycle"],
        products=products,
        term_years=pricing["term_years"],
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
        new_value={"plan_id": sub.plan_id, "products": products, "status": sub.status, "expiry_date": str(sub.expiry_date)},
        reason=payload.notes,
    )

    db.commit()
    db.refresh(sub)
    bridge_service.sync_subscription(db, sub)
    return sub


def update(db: Session, admin_id: int, subscription_id: int, payload) -> Subscription:
    sub = get(db, subscription_id)
    had_bridge = product_service.BRIDGE in product_service.products_of(sub)
    previous = {
        "status": sub.status,
        "plan_id": sub.plan_id,
        "products": product_service.products_of(sub),
        "expiry_date": str(sub.expiry_date),
        "start_date": str(sub.start_date),
    }

    data = payload.dict(exclude_unset=True, exclude={"reason"})

    if "plan_id" in data:
        pricing = pricing_service.resolve_plan(db, data["plan_id"])
        sub.plan_id = pricing["plan_id"]
        sub.plan_name = pricing["plan_name"]
        sub.billing_cycle = pricing["billing_cycle"]
        sub.term_years = pricing["term_years"]
        sub.products = pricing["products"]
        sub.base_price = pricing["base_price"]
        sub.gst_amount = pricing["gst_amount"]
        sub.payable_amount = pricing["payable_amount"]
        data.pop("plan_id")
        data.pop("billing_cycle", None)

    # Explicit product access wins over what the plan implies (Admin > Users > Subscription).
    if data.get("products") is not None:
        data["products"] = product_service.validate_sellable(data["products"])
    else:
        data.pop("products", None)

    for field, value in data.items():
        setattr(sub, field, value)

    sub.updated_at = datetime.utcnow()
    db.flush()

    now_products = product_service.products_of(sub)
    log_action(
        db,
        actor_id=admin_id,
        action="subscription.updated",
        target_type="subscription",
        target_id=sub.id,
        previous_value=previous,
        new_value={"status": sub.status, "plan_id": sub.plan_id, "products": now_products, "expiry_date": str(sub.expiry_date)},
        reason=payload.reason,
    )

    db.commit()
    db.refresh(sub)
    if had_bridge and product_service.BRIDGE not in now_products:
        bridge_service.safe_revoke(sub.user_id, db)  # Bridge access was taken away
    bridge_service.sync_subscription(db, sub)
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
    bridge_service.sync_subscription(db, sub)
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
    bridge_service.sync_subscription(db, sub)
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
    product: Optional[str] = None,  # itl_ai | itl_bridge_ai
) -> dict:
    query = db.query(Subscription).join(User, Subscription.user_id == User.id)

    if status:
        query = query.filter(Subscription.status == status)
    if plan_id:
        query = query.filter(Subscription.plan_id == plan_id)
    if source:
        query = query.filter(Subscription.source == source)
    if product:
        # `products` is back-filled for old rows at startup, so it is always populated.
        if product == product_service.BRIDGE:
            query = query.filter(Subscription.products.contains([product_service.BRIDGE]))
        elif product == product_service.ITL_AI:
            query = query.filter(Subscription.products.contains([product_service.ITL_AI]))
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