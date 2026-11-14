"""
Coupons: validation, reservation and redemption.

Discounts apply to the plan's list price BEFORE GST. A coupon can't be combined
with a salesman price edit (enforced in checkout_service).

Usage counting — a coupon use is counted when it is
  * "redeemed" (the payment succeeded), or
  * "reserved" by a checkout whose payment is still pending (and < 24 h old).
Failed / abandoned checkouts therefore free the use again automatically.
"""

import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.models.coupon import Coupon, CouponRedemption
from app.models.payment import Payment

TWO_PLACES = Decimal("0.01")
RESERVE_HOURS = 24
CODE_RE = re.compile(r"^[A-Z0-9_-]{3,40}$")


def normalize_code(code: Optional[str]) -> str:
    return (code or "").strip().upper()


def get_by_code(db: Session, code: str) -> Optional[Coupon]:
    return db.query(Coupon).filter(Coupon.code == normalize_code(code)).first()


def _counts_as_used():
    cutoff = datetime.utcnow() - timedelta(hours=RESERVE_HOURS)
    return or_(
        CouponRedemption.status == "redeemed",
        and_(
            CouponRedemption.status == "reserved",
            Payment.status == "pending",
            Payment.created_at >= cutoff,
        ),
    )


def used_count(db: Session, coupon_id: int, user_id: Optional[int] = None, exclude_payment_id: Optional[int] = None) -> int:
    q = (
        db.query(func.count(CouponRedemption.id))
        .join(Payment, Payment.id == CouponRedemption.payment_id)
        .filter(CouponRedemption.coupon_id == coupon_id, _counts_as_used())
    )
    if user_id is not None:
        q = q.filter(CouponRedemption.user_id == user_id)
    if exclude_payment_id is not None:
        q = q.filter(CouponRedemption.payment_id != exclude_payment_id)
    return q.scalar() or 0


def compute_discount(coupon: Coupon, list_price: Decimal) -> Decimal:
    if coupon.discount_type == "percent":
        discount = (list_price * Decimal(coupon.value) / Decimal("100")).quantize(TWO_PLACES)
        if coupon.max_discount is not None:
            discount = min(discount, Decimal(coupon.max_discount))
    else:
        discount = Decimal(coupon.value)
    return min(discount, list_price).quantize(TWO_PLACES)


def evaluate(
    db: Session,
    code: str,
    *,
    plan_id: str,
    list_price: Decimal,
    user_id: Optional[int],
) -> tuple[Coupon, Decimal]:
    """Returns (coupon, discount) or raises a 400 with a customer-readable reason."""
    coupon = get_by_code(db, code)
    if not coupon or not coupon.is_active:
        raise HTTPException(400, "This coupon code is not valid.")

    now = datetime.utcnow()
    if coupon.valid_from and now < coupon.valid_from:
        raise HTTPException(400, "This coupon is not active yet.")
    if coupon.valid_to and now > coupon.valid_to:
        raise HTTPException(400, "This coupon has expired.")
    if coupon.plan_ids and plan_id not in coupon.plan_ids:
        raise HTTPException(400, "This coupon doesn't apply to the selected plan.")

    if coupon.total_limit is not None and used_count(db, coupon.id) >= coupon.total_limit:
        raise HTTPException(400, "This coupon has reached its usage limit.")
    if coupon.per_user_limit is not None and user_id is not None:
        if used_count(db, coupon.id, user_id) >= coupon.per_user_limit:
            raise HTTPException(400, "You have already used this coupon the maximum number of times.")

    discount = compute_discount(coupon, list_price)
    if discount <= 0:
        raise HTTPException(400, "This coupon gives no discount on the selected plan.")
    if list_price - discount < Decimal("1.00"):
        raise HTTPException(400, "This coupon would make the plan free — please contact us instead.")
    return coupon, discount


def reserve(db: Session, coupon_id: int, user_id: int, payment: Payment, discount: Decimal) -> CouponRedemption:
    """
    Call inside the transaction that creates `payment` (already flushed so it has an id).
    Locks the coupon row so two simultaneous checkouts can't both take the last use.
    """
    coupon = db.query(Coupon).filter(Coupon.id == coupon_id).with_for_update().first()
    if not coupon or not coupon.is_active:
        raise HTTPException(400, "This coupon code is not valid.")

    # This user's own earlier pending attempts with this coupon are superseded by the new one.
    older = (
        db.query(CouponRedemption)
        .filter(
            CouponRedemption.coupon_id == coupon_id,
            CouponRedemption.user_id == user_id,
            CouponRedemption.status == "reserved",
            CouponRedemption.payment_id != payment.id,
        )
        .all()
    )
    for row in older:
        row.status = "released"
    db.flush()

    if coupon.total_limit is not None and used_count(db, coupon_id, exclude_payment_id=payment.id) >= coupon.total_limit:
        raise HTTPException(400, "This coupon has reached its usage limit.")
    if coupon.per_user_limit is not None and used_count(db, coupon_id, user_id, exclude_payment_id=payment.id) >= coupon.per_user_limit:
        raise HTTPException(400, "You have already used this coupon the maximum number of times.")

    row = CouponRedemption(
        coupon_id=coupon_id,
        user_id=user_id,
        payment_id=payment.id,
        discount_amount=discount,
        status="reserved",
    )
    db.add(row)
    db.flush()
    return row


def _redemption(db: Session, payment_id: int) -> Optional[CouponRedemption]:
    return db.query(CouponRedemption).filter(CouponRedemption.payment_id == payment_id).first()


def mark_redeemed(db: Session, payment: Payment) -> None:
    row = _redemption(db, payment.id)
    if row:
        row.status = "redeemed"


def release(db: Session, payment: Payment) -> None:
    row = _redemption(db, payment.id)
    if row and row.status == "reserved":
        row.status = "released"


# --------------------------------------------------------------------------
# Admin CRUD
# --------------------------------------------------------------------------

def _usage_map(db: Session, coupon_ids: list[int]) -> dict[int, int]:
    if not coupon_ids:
        return {}
    rows = (
        db.query(CouponRedemption.coupon_id, func.count(CouponRedemption.id))
        .join(Payment, Payment.id == CouponRedemption.payment_id)
        .filter(CouponRedemption.coupon_id.in_(coupon_ids), _counts_as_used())
        .group_by(CouponRedemption.coupon_id)
        .all()
    )
    return {cid: n for cid, n in rows}


def list_coupons(db: Session, *, page: int, limit: int, search: Optional[str], active: Optional[bool]) -> dict:
    q = db.query(Coupon)
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(or_(Coupon.code.ilike(like), Coupon.description.ilike(like)))
    if active is not None:
        q = q.filter(Coupon.is_active.is_(active))
    total = q.count()
    items = q.order_by(Coupon.created_at.desc(), Coupon.id.desc()).offset((page - 1) * limit).limit(limit).all()
    usage = _usage_map(db, [c.id for c in items])
    for c in items:
        c.times_used = usage.get(c.id, 0)
    return {"items": items, "total": total, "page": page, "limit": limit}


def get(db: Session, coupon_id: int) -> Coupon:
    coupon = db.query(Coupon).filter(Coupon.id == coupon_id).first()
    if not coupon:
        raise HTTPException(404, "Coupon not found.")
    coupon.times_used = _usage_map(db, [coupon.id]).get(coupon.id, 0)
    return coupon


def _check_fields(data: dict) -> None:
    if "code" in data:
        data["code"] = normalize_code(data["code"])
        if not CODE_RE.match(data["code"]):
            raise HTTPException(400, "Code must be 3-40 characters: letters, digits, '-' or '_'.")
    dtype = data.get("discount_type")
    value = data.get("value")
    if dtype is not None and dtype not in ("percent", "flat"):
        raise HTTPException(400, "discount_type must be 'percent' or 'flat'.")
    if value is not None and Decimal(value) <= 0:
        raise HTTPException(400, "Discount value must be greater than zero.")
    if dtype == "percent" and value is not None and Decimal(value) > 100:
        raise HTTPException(400, "A percentage discount can't exceed 100.")
    vf, vt = data.get("valid_from"), data.get("valid_to")
    if vf and vt and vt <= vf:
        raise HTTPException(400, "'Valid to' must be after 'valid from'.")
    for key in ("total_limit", "per_user_limit"):
        if data.get(key) is not None and data[key] < 1:
            raise HTTPException(400, f"{key} must be at least 1 (leave empty for unlimited).")


def create(db: Session, admin_id: int, data: dict) -> Coupon:
    _check_fields(data)
    if get_by_code(db, data["code"]):
        raise HTTPException(400, "A coupon with this code already exists.")
    if data.get("plan_ids"):
        known = {str(p.get("id")) for p in _cms_plans(db)}
        bad = [p for p in data["plan_ids"] if p not in known]
        if bad:
            raise HTTPException(400, f"Unknown plan id(s): {', '.join(bad)}.")
    coupon = Coupon(**data, created_by_admin_id=admin_id)
    db.add(coupon)
    db.commit()
    db.refresh(coupon)
    coupon.times_used = 0
    return coupon


def update(db: Session, coupon_id: int, data: dict) -> Coupon:
    coupon = get(db, coupon_id)
    # Code and discount type are fixed once created: customers may already hold the code,
    # and past redemptions refer to the discount that applied.
    data.pop("code", None)
    data.pop("discount_type", None)
    merged_type = coupon.discount_type
    _check_fields({**data, "discount_type": merged_type, "value": data.get("value", coupon.value)})
    for key, value in data.items():
        setattr(coupon, key, value)
    db.commit()
    db.refresh(coupon)
    coupon.times_used = _usage_map(db, [coupon.id]).get(coupon.id, 0)
    return coupon


def _cms_plans(db: Session) -> list[dict]:
    from app.services import pricing_service

    return pricing_service.get_cms_plans(db)
