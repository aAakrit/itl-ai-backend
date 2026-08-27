"""
Payment service — admin listing, manual/cash payment recording, and the
Paytm online checkout flow (initiate -> gateway -> callback -> finalize).

Cash payments reuse subscription_service.create_manual so both flows
produce identical, consistent subscription records. Paytm payments use
their own activation path (_activate_subscription_for_payment) since they
go through finalize_paytm_payment rather than the admin-only
SubscriptionCreateManual schema — see that function's docstring.
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.payment import Payment
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas.subscription import CashPaymentCreate, SubscriptionCreateManual
from app.services import pricing_service, subscription_service
from app.services import email_service
from app.services.audit_service import log_action

PAYMENT_STATUSES = {"pending", "success", "failed", "gateway_error", "refunded"}
PAYMENT_GATEWAYS = {"paytm", "cash", "complimentary"}


def get(db: Session, payment_id: int) -> Payment:
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found.")
    return payment


def list_payments(
    db: Session,
    *,
    page: int = 1,
    limit: int = 20,
    status: Optional[str] = None,
    gateway: Optional[str] = None,
    search: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> dict:
    query = db.query(Payment)

    if status:
        status = status.lower()
        if status not in PAYMENT_STATUSES:
            raise HTTPException(400, f"Invalid status. Expected one of: {', '.join(sorted(PAYMENT_STATUSES))}")
        query = query.filter(Payment.status == status)

    if gateway:
        gateway = gateway.lower()
        if gateway not in PAYMENT_GATEWAYS:
            raise HTTPException(400, f"Invalid gateway. Expected one of: {', '.join(sorted(PAYMENT_GATEWAYS))}")
        query = query.filter(Payment.gateway == gateway)

    if search:
        term = f"%{search}%"
        query = query.filter(
            or_(
                Payment.customer_name.ilike(term),
                Payment.customer_email.ilike(term),
                Payment.order_id.ilike(term),
                Payment.invoice_number.ilike(term),
                Payment.receipt_number.ilike(term),
            )
        )

    if date_from:
        query = query.filter(Payment.created_at >= date_from)
    if date_to:
        query = query.filter(Payment.created_at <= date_to)

    total = query.count()
    items = (
        query.order_by(Payment.created_at.desc(), Payment.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    return {"items": items, "total": total, "page": page, "limit": limit}


def record_cash_payment(db: Session, admin_id: int, payload: CashPaymentCreate) -> Payment:
    """Records an offline/cash payment and activates the subscription it pays for."""

    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    sub_payload = SubscriptionCreateManual(
        user_id=payload.user_id,
        plan_id=payload.plan_id,
        billing_cycle=payload.billing_cycle,
        source="manual",
        override_base_price=payload.override_base_price,
        notes=payload.payment_notes,
    )
    subscription = subscription_service.create_manual(db, admin_id, sub_payload)

    payment = Payment(
        user_id=payload.user_id,
        subscription_id=subscription.id,
        gateway="cash",
        status="success",
        order_id=f"CASH-{uuid.uuid4().hex[:16].upper()}",
        plan_id=subscription.plan_id,
        plan_name=subscription.plan_name,
        base_price=subscription.base_price,
        gst_rate=subscription.gst_rate,
        gst_amount=subscription.gst_amount,
        payable_amount=subscription.payable_amount,
        currency="INR",
        customer_name=user.name,
        customer_email=user.email,
        customer_mobile=user.mobile,
        recorded_by_admin_id=admin_id,
        payment_notes=payload.payment_notes,
        paid_at=datetime.utcnow(),
    )
    db.add(payment)
    db.flush()

    # Allocated after flush so the payment's own id can be embedded.
    payment.invoice_number = f"INV-CASH-{payment.id:06d}"
    payment.receipt_number = f"RCPT-CASH-{payment.id:06d}"

    log_action(
        db,
        actor_id=admin_id,
        action="payment.recorded_cash",
        target_type="payment",
        target_id=payment.id,
        new_value={
            "subscription_id": subscription.id,
            "amount": str(payment.payable_amount),
            "plan_id": payment.plan_id,
        },
        reason=payload.payment_notes,
    )

    db.commit()
    db.refresh(payment)

    email_service.send_payment_receipt_email(
        to=user.email,
        name=user.name,
        plan_name=payment.plan_name,
        amount=str(payment.payable_amount),
        order_id=payment.order_id,
    )

    return payment


# =============================================================================
# Paytm checkout flow
#
# Payment.gateway_response is used to stash a small amount of internal
# bookkeeping (billing_cycle, the txnToken, raw gateway payloads) between
# initiate and finalize — merged (never overwritten wholesale) on every
# update so nothing added earlier is lost. This avoids a schema migration
# for a single extra field, at the cost of that data living in a JSON blob
# instead of a column; fine for what it's used for (debugging + one lookup
# at finalize time), not something queried on.
# =============================================================================

def _new_order_id() -> str:
    return f"ITL-{uuid.uuid4().hex[:20].upper()}"


def create_paytm_payment(db: Session, user: User, plan_id: str, billing_cycle: str) -> Payment:
    """Creates a pending Payment row for a checkout attempt. The route then
    calls paytm_service.initiate_transaction and records the result via
    record_gateway_init."""

    pricing = pricing_service.resolve_plan(db, plan_id, billing_cycle)

    payment = Payment(
        user_id=user.id,
        gateway="paytm",
        status="pending",
        order_id=_new_order_id(),
        plan_id=pricing["plan_id"],
        plan_name=pricing["plan_name"],
        base_price=pricing["base_price"],
        gst_rate=pricing["gst_rate"],
        gst_amount=pricing["gst_amount"],
        payable_amount=pricing["payable_amount"],
        currency="INR",
        customer_name=user.name,
        customer_email=user.email,
        customer_mobile=user.mobile,
        gateway_response={"billing_cycle": billing_cycle},
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


def record_gateway_init(db: Session, payment: Payment, txn_token: str, raw_response: dict) -> Payment:
    payment.gateway_response = {
        **(payment.gateway_response or {}),
        "txn_token": txn_token,
        "init_response": raw_response,
    }
    db.commit()
    db.refresh(payment)
    return payment


def mark_init_failed(db: Session, payment: Payment, reason: str) -> Payment:
    """Paytm's application layer explicitly rejected the request (bad
    payload, invalid signature, business-rule rejection, etc). This is a
    terminal state for the attempt — retrying the identical request is
    expected to fail again the same way."""
    payment.status = "failed"
    payment.gateway_response = {**(payment.gateway_response or {}), "init_error": reason}
    db.commit()
    db.refresh(payment)
    return payment


def mark_init_gateway_error(
    db: Session,
    payment: Payment,
    reason: str,
    *,
    status_code: Optional[int] = None,
    body: Optional[str] = None,
) -> Payment:
    """Paytm's gateway was transiently unavailable (5xx/timeout/network
    error) — the request was never confirmed accepted OR rejected. This is
    deliberately NOT "failed": nothing about the payment itself is known
    to be wrong, and a retry with the same order_id is safe (see
    paytm_service._post_with_retry's docstring). Kept distinct from
    "pending" too, so it's visible in the admin payments list which
    attempts stalled on Paytm's side rather than a user simply not having
    completed checkout yet."""
    payment.status = "gateway_error"
    payment.gateway_response = {
        **(payment.gateway_response or {}),
        "init_error": reason,
        "init_error_status_code": status_code,
        "init_error_body": (body or "")[:2000] or None,
    }
    db.commit()
    db.refresh(payment)
    return payment


def get_by_order_id(db: Session, order_id: str) -> Payment:
    payment = db.query(Payment).filter(Payment.order_id == order_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found.")
    return payment


def _activate_subscription_for_payment(db: Session, payment: Payment, billing_cycle: str) -> Subscription:
    """Activates a subscription from a successful Paytm payment, using the
    pricing snapshot already on the Payment row (what the user actually
    paid) rather than a fresh CMS lookup."""

    start = datetime.utcnow()
    expiry = start + timedelta(days=subscription_service.CYCLE_DAYS.get(billing_cycle, 30))

    sub = Subscription(
        user_id=payment.user_id,
        plan_id=payment.plan_id,
        plan_name=payment.plan_name,
        billing_cycle=billing_cycle,
        base_price=payment.base_price,
        gst_rate=payment.gst_rate,
        gst_amount=payment.gst_amount,
        payable_amount=payment.payable_amount,
        status="active",
        source="online",
        start_date=start,
        expiry_date=expiry,
        notes=f"Activated by Paytm payment {payment.order_id}",
    )
    db.add(sub)
    db.flush()

    user = db.query(User).filter(User.id == payment.user_id).first()
    if user:
        user.plan = sub.plan_name

    return sub


def finalize_paytm_payment(db: Session, order_id: str, status_response: dict) -> Payment:
    """
    Called only after a server-to-server call to Paytm's Transaction Status
    API (the sole trustworthy source — see paytm_service module docstring).
    Marks the Payment success/failed and, on success, activates a
    Subscription. Idempotent — a payment already marked "success" is
    returned as-is rather than double-activating a second subscription
    (Paytm may deliver the callback more than once).
    """

    payment = get_by_order_id(db, order_id)

    if payment.status == "success":
        return payment

    body = status_response.get("body", {}) if isinstance(status_response, dict) else {}
    result_info = body.get("resultInfo", {}) if isinstance(body, dict) else {}
    txn_status = result_info.get("resultStatus")  # TXN_SUCCESS | TXN_FAILURE | PENDING

    payment.gateway_txn_id = body.get("txnId") or payment.gateway_txn_id
    payment.gateway_response = {**(payment.gateway_response or {}), "status_response": status_response}

    if txn_status == "TXN_SUCCESS":
        payment.status = "success"
        payment.paid_at = datetime.utcnow()
        db.flush()  # allocate payment.id if this is somehow still transient
        payment.invoice_number = payment.invoice_number or f"INV-{payment.id:06d}"
        payment.receipt_number = payment.receipt_number or f"RCPT-{payment.id:06d}"

        billing_cycle = (payment.gateway_response or {}).get("billing_cycle", "monthly")
        subscription = _activate_subscription_for_payment(db, payment, billing_cycle)
        payment.subscription_id = subscription.id

        log_action(
            db,
            actor_id=payment.user_id,
            action="payment.paytm_success",
            target_type="payment",
            target_id=payment.id,
            new_value={"order_id": order_id, "subscription_id": subscription.id},
        )
    elif txn_status == "TXN_FAILURE":
        payment.status = "failed"
        log_action(
            db,
            actor_id=payment.user_id,
            action="payment.paytm_failed",
            target_type="payment",
            target_id=payment.id,
            new_value={"order_id": order_id, "reason": result_info.get("resultMsg")},
        )
    # else: still PENDING on Paytm's side — leave status as "pending" so a
    # later recheck can pick it up; don't guess at an outcome Paytm hasn't
    # confirmed yet.

    db.commit()
    db.refresh(payment)

    if payment.status == "success":
        email_service.send_payment_receipt_email(
            to=payment.customer_email,
            name=payment.customer_name or "there",
            plan_name=payment.plan_name,
            amount=str(payment.payable_amount),
            order_id=payment.order_id,
        )

    return payment
