"""
Payment service — admin listing and manual/cash payment recording.

Online (Paytm) payments belong to the not-yet-built user-facing checkout
flow (app/services/paytm_service.py has the gateway plumbing only; there is
no route wired up to actually create a Payment row from it yet). This
module covers the admin side that IS wired up end-to-end:

  * browsing payment history (list/get)
  * recording an offline/cash payment, which activates a subscription
    exactly the way a successful online payment would

Cash payments reuse subscription_service.create_manual so both flows
produce identical, consistent subscription records — pricing snapshot,
audit log entry, and `user.plan` update all happen in one place.
"""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.payment import Payment
from app.models.user import User
from app.schemas.subscription import CashPaymentCreate, SubscriptionCreateManual
from app.services import subscription_service
from app.services.audit_service import log_action

PAYMENT_STATUSES = {"pending", "success", "failed", "refunded"}
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
    return payment
