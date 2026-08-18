from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session, aliased

from app.models.ai_usage import AIUsageLimit
from app.models.audit_log import AuditLog
from app.models.payment import Payment
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas.admin_user import UserUpdate
from app.services.audit_service import log_action


SUBSCRIPTION_STATUSES = {"pending", "active", "suspended", "cancelled", "expired"}
PAYMENT_STATUSES = {"pending", "success", "failed", "refunded"}
PAYMENT_TYPES = {"paytm", "cash", "complimentary"}
EXPIRY_WINDOWS = {"expired", "today", "7d", "30d", "60d", "90d"}


def _current_subscription_subquery(db: Session):
    """Return one best/current subscription row per user.

    Active, non-expired subscriptions are preferred. If none exists, the
    most recently-created subscription is returned. This makes the admin
    user list resilient to old data while the one-active-subscription rule
    is enforced by the subscription service.
    """
    now = datetime.utcnow()
    rank = func.row_number().over(
        partition_by=Subscription.user_id,
        order_by=(
            case(
                (and_(Subscription.status == "active", Subscription.expiry_date > now), 0),
                else_=1,
            ),
            Subscription.created_at.desc(),
            Subscription.id.desc(),
        ),
    ).label("subscription_rank")

    return (
        db.query(
            Subscription.id.label("subscription_id"),
            Subscription.user_id.label("subscription_user_id"),
            rank,
        )
        .subquery()
    )


def _latest_payment_subquery(db: Session):
    rank = func.row_number().over(
        partition_by=Payment.user_id,
        order_by=(Payment.created_at.desc(), Payment.id.desc()),
    ).label("payment_rank")

    return (
        db.query(
            Payment.id.label("payment_id"),
            Payment.user_id.label("payment_user_id"),
            rank,
        )
        .subquery()
    )


def _role_name(user: User) -> str:
    if user.is_admin:
        return "Admin"
    if user.is_staff:
        return "Staff"
    return "User"


def _subscription_summary(sub: Optional[Subscription]) -> dict:
    if not sub:
        return {
            "id": None,
            "plan_id": None,
            "plan_name": None,
            "billing_cycle": None,
            "status": None,
            "source": None,
            "base_price": None,
            "gst_rate": None,
            "gst_amount": None,
            "payable_amount": None,
            "start_date": None,
            "expiry_date": None,
            "renewal_date": None,
            "auto_renew": False,
            "remaining_days": None,
            "notes": None,
        }

    now = datetime.utcnow()
    remaining_days = None
    if sub.expiry_date:
        remaining_days = max((sub.expiry_date - now).days, 0)

    effective_status = sub.status
    if sub.expiry_date and sub.expiry_date <= now and sub.status == "active":
        effective_status = "expired"

    return {
        "id": sub.id,
        "plan_id": sub.plan_id,
        "plan_name": sub.plan_name,
        "billing_cycle": sub.billing_cycle,
        "status": effective_status,
        "source": sub.source,
        "base_price": sub.base_price,
        "gst_rate": sub.gst_rate,
        "gst_amount": sub.gst_amount,
        "payable_amount": sub.payable_amount,
        "start_date": sub.start_date,
        "expiry_date": sub.expiry_date,
        "renewal_date": sub.renewal_date,
        "auto_renew": bool(sub.auto_renew),
        "remaining_days": remaining_days,
        "notes": sub.notes,
    }


def _payment_summary(payment: Optional[Payment]) -> dict:
    if not payment:
        return {
            "id": None,
            "status": None,
            "type": None,
            "gateway": None,
            "amount": None,
            "currency": None,
            "invoice_number": None,
            "receipt_number": None,
            "paid_at": None,
            "order_id": None,
        }

    return {
        "id": payment.id,
        "status": payment.status,
        "type": payment.gateway,
        "gateway": payment.gateway,
        "amount": payment.payable_amount,
        "currency": payment.currency,
        "invoice_number": payment.invoice_number,
        "receipt_number": payment.receipt_number,
        "paid_at": payment.paid_at,
        "order_id": payment.order_id,
    }


def _ai_summary(usage: Optional[AIUsageLimit]) -> dict:
    if not usage:
        return {
            "daily_limit": None,
            "daily_used": 0,
            "daily_remaining": None,
            "monthly_limit": None,
            "monthly_used": 0,
            "monthly_remaining": None,
            "yearly_limit": None,
            "yearly_used": 0,
            "yearly_remaining": None,
            "token_balance": None,
            "tokens_used": 0,
            "reset_frequency": None,
            "last_reset_at": None,
        }

    def remaining(limit, used):
        return None if limit is None else max(limit - (used or 0), 0)

    return {
        "daily_limit": usage.daily_limit,
        "daily_used": usage.daily_used or 0,
        "daily_remaining": remaining(usage.daily_limit, usage.daily_used),
        "monthly_limit": usage.monthly_limit,
        "monthly_used": usage.monthly_used or 0,
        "monthly_remaining": remaining(usage.monthly_limit, usage.monthly_used),
        "yearly_limit": usage.yearly_limit,
        "yearly_used": usage.yearly_used or 0,
        "yearly_remaining": remaining(usage.yearly_limit, usage.yearly_used),
        "token_balance": usage.token_balance,
        "tokens_used": usage.tokens_used or 0,
        "reset_frequency": usage.reset_frequency,
        "last_reset_at": usage.last_reset_at,
    }


def get_users(
    db: Session,
    page: int,
    limit: int,
    search: Optional[str] = None,
    role: Optional[str] = None,
    status: Optional[str] = None,
    plan: Optional[str] = None,
    sort: str = "created_at",
    order: str = "desc",
    subscription_status: Optional[str] = None,
    payment_type: Optional[str] = None,
    payment_status: Optional[str] = None,
    expiry_window: Optional[str] = None,
    expiry_from: Optional[datetime] = None,
    expiry_to: Optional[datetime] = None,
    registration_from: Optional[datetime] = None,
    registration_to: Optional[datetime] = None,
    approval_status: Optional[str] = None,
    state: Optional[str] = None,
    city: Optional[str] = None,
):
    """Return the existing admin user list enriched with current entitlement data.

    Subscription/payment/AI information is loaded in the same database query
    instead of issuing one API/query per user row.
    """
    current_sub_rank = _current_subscription_subquery(db)
    latest_payment_rank = _latest_payment_subquery(db)
    CurrentSubscription = aliased(Subscription)
    LatestPayment = aliased(Payment)

    query = (
        db.query(User, CurrentSubscription, LatestPayment, AIUsageLimit)
        .outerjoin(
            current_sub_rank,
            and_(
                current_sub_rank.c.subscription_user_id == User.id,
                current_sub_rank.c.subscription_rank == 1,
            ),
        )
        .outerjoin(
            CurrentSubscription,
            CurrentSubscription.id == current_sub_rank.c.subscription_id,
        )
        .outerjoin(
            latest_payment_rank,
            and_(
                latest_payment_rank.c.payment_user_id == User.id,
                latest_payment_rank.c.payment_rank == 1,
            ),
        )
        .outerjoin(
            LatestPayment,
            LatestPayment.id == latest_payment_rank.c.payment_id,
        )
        .outerjoin(AIUsageLimit, AIUsageLimit.user_id == User.id)
    )

    if search:
        term = f"%{search}%"
        query = query.filter(
            or_(
                User.name.ilike(term),
                User.email.ilike(term),
                User.mobile.ilike(term),
                User.firm.ilike(term),
            )
        )

    if status:
        query = query.filter(User.status == status.upper())

    if approval_status:
        query = query.filter(User.status == approval_status.upper())

    if role:
        role = role.lower()
        if role == "admin":
            query = query.filter(User.is_admin.is_(True))
        elif role == "staff":
            query = query.filter(User.is_staff.is_(True), User.is_admin.is_(False))
        elif role == "user":
            query = query.filter(User.is_admin.is_(False), User.is_staff.is_(False))

    if plan:
        query = query.filter(CurrentSubscription.plan_id == plan)

    if subscription_status:
        subscription_status = subscription_status.lower()
        if subscription_status not in SUBSCRIPTION_STATUSES:
            raise HTTPException(400, f"Invalid subscription_status. Expected one of: {', '.join(sorted(SUBSCRIPTION_STATUSES))}")
        now = datetime.utcnow()
        if subscription_status == "active":
            query = query.filter(
                CurrentSubscription.status == "active",
                CurrentSubscription.expiry_date > now,
            )
        elif subscription_status == "expired":
            query = query.filter(
                or_(
                    CurrentSubscription.status == "expired",
                    and_(CurrentSubscription.status == "active", CurrentSubscription.expiry_date <= now),
                )
            )
        else:
            query = query.filter(CurrentSubscription.status == subscription_status)

    if payment_type:
        payment_type = payment_type.lower()
        if payment_type not in PAYMENT_TYPES:
            raise HTTPException(400, f"Invalid payment_type. Expected one of: {', '.join(sorted(PAYMENT_TYPES))}")
        query = query.filter(LatestPayment.gateway == payment_type)

    if payment_status:
        payment_status = payment_status.lower()
        if payment_status not in PAYMENT_STATUSES:
            raise HTTPException(400, f"Invalid payment_status. Expected one of: {', '.join(sorted(PAYMENT_STATUSES))}")
        query = query.filter(LatestPayment.status == payment_status)

    now = datetime.utcnow()
    if expiry_window:
        expiry_window = expiry_window.lower()
        if expiry_window not in EXPIRY_WINDOWS:
            raise HTTPException(400, f"Invalid expiry_window. Expected one of: {', '.join(sorted(EXPIRY_WINDOWS))}")
        if expiry_window == "expired":
            query = query.filter(CurrentSubscription.expiry_date < now)
        elif expiry_window == "today":
            query = query.filter(
                CurrentSubscription.expiry_date >= now,
                CurrentSubscription.expiry_date < now + timedelta(days=1),
            )
        else:
            days = int(expiry_window.rstrip("d"))
            query = query.filter(
                CurrentSubscription.expiry_date >= now,
                CurrentSubscription.expiry_date <= now + timedelta(days=days),
            )

    if expiry_from:
        query = query.filter(CurrentSubscription.expiry_date >= expiry_from)
    if expiry_to:
        query = query.filter(CurrentSubscription.expiry_date <= expiry_to)

    if registration_from:
        query = query.filter(User.created_at >= registration_from)
    if registration_to:
        query = query.filter(User.created_at <= registration_to)

    if state:
        query = query.filter(User.state.ilike(f"%{state}%"))
    if city:
        query = query.filter(User.city.ilike(f"%{city}%"))

    sortable = {
        "name": User.name,
        "email": User.email,
        "status": User.status,
        "created_at": User.created_at,
        "last_login": getattr(User, "last_login", User.created_at),
        "plan": CurrentSubscription.plan_name,
        "subscription_status": CurrentSubscription.status,
        "expiry_date": CurrentSubscription.expiry_date,
        "payment_status": LatestPayment.status,
        "payment_type": LatestPayment.gateway,
    }

    sort_column = sortable.get(sort, User.created_at)
    query = query.order_by(sort_column.asc() if order.lower() == "asc" else sort_column.desc())

    total = query.count()
    rows = query.offset((page - 1) * limit).limit(limit).all()

    items = []
    for user, subscription, payment, ai_usage in rows:
        items.append(
            {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "mobile": user.mobile,
                "firm": user.firm,
                "plan": subscription.plan_name if subscription else getattr(user, "plan", None),
                "role": _role_name(user),
                "status": user.status,
                "last_login": getattr(user, "last_login", None),
                "created_at": user.created_at,
                "subscription": _subscription_summary(subscription),
                "payment": _payment_summary(payment),
                "ai_usage": _ai_summary(ai_usage),
            }
        )

    return {"items": items, "page": page, "limit": limit, "total": total}


def get_user(db: Session, user_id: int):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def get_user_detail(db: Session, user_id: int) -> dict:
    user = get_user(db, user_id)
    subscription = (
        db.query(Subscription)
        .filter(Subscription.user_id == user_id)
        .order_by(Subscription.created_at.desc(), Subscription.id.desc())
        .first()
    )
    payment = (
        db.query(Payment)
        .filter(Payment.user_id == user_id)
        .order_by(Payment.created_at.desc(), Payment.id.desc())
        .first()
    )
    ai_usage = db.query(AIUsageLimit).filter(AIUsageLimit.user_id == user_id).first()

    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "mobile": user.mobile,
        "telephone": user.telephone,
        "fax": user.fax,
        "firm": user.firm,
        "address": user.address,
        "city": user.city,
        "state": user.state,
        "pin_code": user.pin_code,
        "plan": subscription.plan_name if subscription else getattr(user, "plan", None),
        "status": user.status,
        "is_admin": user.is_admin,
        "is_staff": user.is_staff,
        "approved_at": getattr(user, "approved_at", None),
        "approved_by": getattr(user, "approved_by", None),
        "last_login": getattr(user, "last_login", None),
        "created_at": user.created_at,
        "updated_at": getattr(user, "updated_at", None),
        "subscription": _subscription_summary(subscription),
        "subscription_history": [
            _subscription_summary(item)
            for item in db.query(Subscription)
            .filter(Subscription.user_id == user_id)
            .order_by(Subscription.created_at.desc(), Subscription.id.desc())
            .limit(50)
            .all()
        ],
        "payment": _payment_summary(payment),
        "ai_usage": _ai_summary(ai_usage),
    }


def update_user(db: Session, user_id: int, payload: UserUpdate, admin_id: int):
    user = get_user(db, user_id)
    data = payload.dict(exclude_unset=True)

    # `plan` is intentionally not accepted as a subscription-management
    # operation. Subscription changes must go through subscription_service
    # so pricing snapshots, dates and audit records remain consistent.
    data.pop("plan", None)

    editable_fields = {
        "name",
        "firm",
        "mobile",
        "telephone",
        "fax",
        "address",
        "city",
        "state",
        "pin_code",
        "status",
        "is_admin",
        "is_staff",
    }

    invalid_fields = set(data) - editable_fields
    if invalid_fields:
        raise HTTPException(400, f"Fields cannot be updated here: {', '.join(sorted(invalid_fields))}")

    previous = {field: getattr(user, field) for field in data}

    for field, value in data.items():
        setattr(user, field, value)

    user.updated_at = datetime.utcnow()
    db.flush()

    new_values = {field: getattr(user, field) for field in data}
    log_action(
        db,
        actor_id=admin_id,
        action="user.updated",
        target_type="user",
        target_id=user.id,
        previous_value=previous,
        new_value=new_values,
    )

    db.commit()
    db.refresh(user)

    return {"success": True, "message": "User updated successfully"}


def approve_user(db: Session, user_id: int, admin_id: int, reason: Optional[str] = None):
    user = get_user(db, user_id)
    previous = {"status": user.status, "approved_at": str(user.approved_at) if user.approved_at else None, "approved_by": user.approved_by}

    user.status = "APPROVED"
    user.approved_at = datetime.utcnow()
    user.approved_by = admin_id
    user.updated_at = datetime.utcnow()

    log_action(
        db,
        actor_id=admin_id,
        action="user.approved",
        target_type="user",
        target_id=user.id,
        previous_value=previous,
        new_value={"status": user.status, "approved_at": str(user.approved_at), "approved_by": admin_id},
        reason=reason,
    )
    db.commit()

    return {"success": True, "message": "User approved successfully"}


def suspend_user(db: Session, user_id: int, admin_id: int, reason: Optional[str] = None):
    user = get_user(db, user_id)
    previous = {"status": user.status}
    user.status = "SUSPENDED"
    user.updated_at = datetime.utcnow()

    log_action(
        db,
        actor_id=admin_id,
        action="user.suspended",
        target_type="user",
        target_id=user.id,
        previous_value=previous,
        new_value={"status": user.status},
        reason=reason,
    )
    db.commit()

    return {"success": True, "message": "User suspended successfully"}


def delete_user(db: Session, user_id: int, admin_id: int, reason: Optional[str] = None):
    user = get_user(db, user_id)
    previous = {"status": user.status, "deleted_at": str(user.deleted_at) if user.deleted_at else None}
    user.status = "DELETED"
    user.deleted_at = datetime.utcnow()
    user.updated_at = datetime.utcnow()

    log_action(
        db,
        actor_id=admin_id,
        action="user.deleted",
        target_type="user",
        target_id=user.id,
        previous_value=previous,
        new_value={"status": user.status, "deleted_at": str(user.deleted_at)},
        reason=reason,
    )
    db.commit()

    return {"success": True, "message": "User deleted successfully"}


def get_user_history(db: Session, user_id: int, page: int = 1, limit: int = 50):
    get_user(db, user_id)

    query = (
        db.query(AuditLog)
        .filter(AuditLog.target_type == "user", AuditLog.target_id == user_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    )

    total = query.count()
    rows = query.offset((page - 1) * limit).limit(limit).all()

    actor_ids = {row.actor_id for row in rows if row.actor_id is not None}
    actors = {}
    if actor_ids:
        actors = {
            user.id: user.name
            for user in db.query(User).filter(User.id.in_(actor_ids)).all()
        }

    return {
        "items": [
            {
                "id": row.id,
                "timestamp": row.created_at,
                "action": row.action,
                "performed_by": actors.get(row.actor_id),
                "description": row.reason,
                "previous_value": row.previous_value,
                "new_value": row.new_value,
                "target_type": row.target_type,
                "target_id": row.target_id,
            }
            for row in rows
        ],
        "page": page,
        "limit": limit,
        "total": total,
    }
