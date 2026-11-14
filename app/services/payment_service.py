"""
Payment service — admin listing, manual/cash payment recording, and the
Paytm online checkout flow (initiate -> gateway -> callback -> finalize).

Cash payments reuse subscription_service.create_manual so both flows
produce identical, consistent subscription records. Paytm payments use
their own activation path (_activate_subscription_for_payment) since they
go through finalize_paytm_payment rather than the admin-only
SubscriptionCreateManual schema — see that function's docstring.
"""

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.payment import Payment
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas.subscription import CashPaymentCreate
from app.config import PAYMENT_ALERT_EMAIL
from app.services import bill_pdf, bill_service, bridge_service, coupon_service, invoice_service
from app.services import pricing_service, subscription_service
from app.services import email_service
from app.services import notification_service
from app.services import products as product_service
from app.services.audit_service import log_action

logger = logging.getLogger(__name__)

PAYMENT_STATUSES = {"pending", "success", "failed", "gateway_error", "refunded"}
PAYMENT_GATEWAYS = {"paytm", "cash", "complimentary"}


def _billing_address(user: User) -> Optional[str]:
    """Snapshot the user's address as a single line at payment time — the
    invoice needs it even if the user edits their profile afterward."""
    parts = [user.address, user.city, user.state, user.pin_code]
    joined = ", ".join(str(p) for p in parts if p)
    return joined or None


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


def _customer_snapshot_from_user(user: User) -> dict:
    return dict(
        customer_name=user.name,
        customer_email=user.email,
        customer_mobile=user.mobile,
        customer_gstin=user.gstin,
        customer_firm=user.firm,
        customer_address=user.address,
        customer_city=user.city,
        customer_state=user.state,
        customer_pin=user.pin_code,
    )


def _price_fields(plan: dict, split: dict, list_price: Decimal, discount_source: Optional[str]) -> dict:
    discount = (list_price - split["base_price"]).quantize(Decimal("0.01"))
    return dict(
        plan_id=plan["plan_id"],
        plan_name=plan["plan_name"],
        products=plan["products"],
        term_years=plan["term_years"],
        list_price=list_price,
        discount_amount=discount if discount > 0 else Decimal("0.00"),
        discount_source=discount_source if discount > 0 else None,
        base_price=split["base_price"],
        gst_rate=split["gst_rate"],
        gst_amount=split["gst_amount"],
        payable_amount=split["payable_amount"],
        cgst_amount=split["cgst_amount"],
        sgst_amount=split["sgst_amount"],
        igst_amount=split["igst_amount"],
        currency="INR",
    )


def record_cash_payment(db: Session, admin_id: int, payload: CashPaymentCreate) -> Payment:
    """Records an offline/cash payment, activates what it paid for, and issues the bill."""

    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    plan = pricing_service.resolve_plan(db, payload.plan_id)
    list_price = plan["base_price"]
    base = pricing_service.money(payload.override_base_price) if payload.override_base_price is not None else list_price
    if base <= 0:
        raise HTTPException(status_code=400, detail="The price must be greater than zero.")
    split = pricing_service.tax_split(base, user.state)

    subscription = subscription_service.activate_purchase(
        db,
        user_id=user.id,
        plan=plan,
        amounts=split,
        source="manual",
        admin_id=admin_id,
        notes=payload.payment_notes,
    )

    payment = Payment(
        user_id=user.id,
        subscription_id=subscription.id,
        gateway="cash",
        status="success",
        order_id=f"CASH-{uuid.uuid4().hex[:16].upper()}",
        salesman_id=payload.salesman_id,
        price_override_reason=payload.payment_notes if base != list_price else None,
        recorded_by_admin_id=admin_id,
        payment_notes=payload.payment_notes,
        paid_at=datetime.utcnow(),
        gateway_response={"billing_cycle": plan["billing_cycle"]},
        **_price_fields(plan, split, list_price, "salesman" if payload.salesman_id else "admin"),
        **_customer_snapshot_from_user(user),
    )
    db.add(payment)
    db.flush()

    # Allocated after flush so the payment's own id can be embedded.
    payment.receipt_number = f"RCPT-CASH-{payment.id:06d}"
    bill_service.create_for_payment(db, payment)  # sets payment.invoice_number

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
            "invoice_number": payment.invoice_number,
        },
        reason=payload.payment_notes,
    )

    db.commit()
    db.refresh(payment)

    _after_success(db, payment)
    return payment


def _build_attachments(db: Session, payment: Payment) -> list[tuple[str, bytes, str]]:
    """Bill + receipt PDFs for e-mails. Best effort — a PDF problem must never undo a payment."""
    out: list[tuple[str, bytes, str]] = []
    try:
        bill = bill_service.get_for_payment(db, payment.id)
        if bill:
            out.append((f"Bill-{bill.bill_number.replace('/', '-')}.pdf", bill_pdf.build_bill_pdf(bill), "application/pdf"))
        data, content_type, filename = invoice_service.build_receipt(payment, "pdf")
        out.append((filename, data, content_type))
    except Exception:
        logger.exception("Couldn't build bill/receipt attachments for payment %s", payment.id)
    return out


def _after_success(db: Session, payment: Payment) -> None:
    """Everything that happens after a payment is committed as successful. Never raises."""
    try:
        sub = db.get(Subscription, payment.subscription_id) if payment.subscription_id else None
        if sub:
            bridge_service.sync_subscription(db, sub)

        user = db.query(User).filter(User.id == payment.user_id).first()
        attachments = _build_attachments(db, payment)
        amount = f"{Decimal(payment.payable_amount):.2f}"

        email_service.send_payment_receipt_email(
            to=payment.customer_email,
            name=payment.customer_name or "there",
            plan_name=payment.plan_name,
            amount=amount,
            order_id=payment.order_id,
            attachments=attachments,
        )

        salesman = None
        if payment.salesman_id:
            sm = db.query(User).filter(User.id == payment.salesman_id).first()
            salesman = sm.name if sm else None
        email_service.send_payment_alert_email(
            to=PAYMENT_ALERT_EMAIL,
            customer_name=payment.customer_name or "—",
            customer_email=payment.customer_email or "—",
            customer_mobile=payment.customer_mobile,
            plan_name=payment.plan_name,
            amount=amount,
            order_id=payment.order_id,
            gateway=payment.gateway,
            account_status=(user.status if user else "—"),
            salesman=salesman,
            bill_number=payment.invoice_number,
            attachments=attachments,
        )

        notification_service.notify_payment_completed(
            db,
            user_name=payment.customer_name or "A user",
            plan_name=payment.plan_name,
            amount=amount,
            payment_id=payment.id,
        )
    except Exception:
        logger.exception("Post-payment follow-ups failed for payment %s", payment.id)


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


def create_paytm_payment(db: Session, user: User, plan_id: str, billing_cycle: Optional[str] = None) -> Payment:
    """Pending Payment for a logged-in customer paying list price (the old /payments/initiate path).
    The route then calls paytm_service.initiate_transaction and records the result via record_gateway_init."""

    plan = pricing_service.resolve_plan(db, plan_id)
    subscription_service.check_purchase_allowed(db, user.id, plan["products"])
    split = pricing_service.tax_split(plan["base_price"], user.state)

    payment = Payment(
        user_id=user.id,
        gateway="paytm",
        status="pending",
        order_id=_new_order_id(),
        gateway_response={"billing_cycle": plan["billing_cycle"]},
        **_price_fields(plan, split, plan["base_price"], None),
        **_customer_snapshot_from_user(user),
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


def create_checkout_payment(db: Session, user: User, *, quote: dict, details: dict) -> Payment:
    """
    Pending Payment for the public checkout dialog. `quote` comes from
    checkout_service.build_quote (server-computed); `details` are the customer's
    (editable) billing details, snapshotted onto the payment for the bill.
    The coupon use, if any, is reserved in the same transaction.
    """
    plan = quote["plan"]
    payment = Payment(
        user_id=user.id,
        gateway="paytm",
        status="pending",
        order_id=_new_order_id(),
        coupon_id=quote["coupon"].id if quote.get("coupon") else None,
        coupon_code=quote["coupon"].code if quote.get("coupon") else None,
        salesman_id=quote.get("salesman_id"),
        price_override_reason=quote.get("reason"),
        gateway_response={"billing_cycle": plan["billing_cycle"]},
        customer_name=details["name"],
        customer_email=user.email,
        customer_mobile=details["mobile"],
        customer_gstin=details.get("gstin"),
        customer_firm=details.get("firm"),
        customer_address=details["address"],
        customer_city=details["city"],
        customer_state=details["state"],
        customer_pin=details["pin_code"],
        **_price_fields(plan, quote, quote["list_price"], quote["discount_source"]),
    )
    db.add(payment)
    try:
        db.flush()
        if quote.get("coupon"):
            coupon_service.reserve(db, quote["coupon"].id, user.id, payment, quote["discount_amount"])
        db.commit()
    except Exception:
        db.rollback()
        raise
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


def mark_init_failed(db: Session, payment: Payment, reason: str, *, raw_response: Optional[dict] = None) -> Payment:
    """Paytm's application layer explicitly rejected the request (bad
    payload, invalid signature, business-rule rejection, etc). This is a
    terminal state for the attempt — retrying the identical request is
    expected to fail again the same way."""
    payment.status = "failed"
    payment.gateway_response = {
        **(payment.gateway_response or {}),
        "init_error": reason,
        **({"init_error_response": raw_response} if raw_response is not None else {}),
    }
    coupon_service.release(db, payment)
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
    coupon_service.release(db, payment)  # the customer's retry creates a fresh order and reserves again
    db.commit()
    db.refresh(payment)
    return payment


def get_by_order_id(db: Session, order_id: str) -> Payment:
    payment = db.query(Payment).filter(Payment.order_id == order_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found.")
    return payment


def _activate_subscription_for_payment(db: Session, payment: Payment) -> Subscription:
    """Grants what a successful Paytm payment bought, from the snapshot on the Payment
    row (what the customer actually paid for) rather than a fresh CMS lookup."""

    term = payment.term_years or 1
    plan = {
        "plan_id": payment.plan_id,
        "plan_name": payment.plan_name,
        "products": payment.products or product_service.legacy_products_for_plan(payment.plan_id),
        "term_years": term,
        "billing_cycle": product_service.cycle_label(term),
    }
    amounts = {
        "base_price": payment.base_price,
        "gst_rate": payment.gst_rate,
        "gst_amount": payment.gst_amount,
        "payable_amount": payment.payable_amount,
    }
    return subscription_service.activate_purchase(
        db,
        user_id=payment.user_id,
        plan=plan,
        amounts=amounts,
        source="online",
        notes=f"Activated by Paytm payment {payment.order_id}",
    )


def finalize_paytm_payment(db: Session, order_id: str, status_response: dict) -> Payment:
    """
    Called only after a server-to-server call to Paytm's Transaction Status
    API (the sole trustworthy source — see paytm_service module docstring).
    Marks the Payment success/failed and, on success, activates the purchase,
    issues the bill and redeems the coupon — all in ONE transaction.
    Idempotent — a payment already marked "success" is returned as-is
    (Paytm may deliver the callback more than once).

    The amount Paytm says was paid must equal the amount we asked for; otherwise
    nothing is activated and the payment is flagged for a human to look at.
    """

    # Row lock: the Paytm callback, a user recheck and the background
    # reconciler can all land here for the same order at the same moment.
    # populate_existing() re-reads the row so the "already success?" check
    # below sees what the winner of the lock committed.
    payment = (
        db.query(Payment)
        .filter(Payment.order_id == order_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found.")

    if payment.status == "success":
        db.rollback()  # release the lock; nothing to change
        return payment

    body = status_response.get("body", {}) if isinstance(status_response, dict) else {}
    result_info = body.get("resultInfo", {}) if isinstance(body, dict) else {}
    txn_status = result_info.get("resultStatus")  # TXN_SUCCESS | TXN_FAILURE | PENDING

    payment.gateway_txn_id = body.get("txnId") or payment.gateway_txn_id
    payment.gateway_response = {**(payment.gateway_response or {}), "status_response": status_response}

    mismatch_paid = None
    if txn_status == "TXN_SUCCESS":
        reported = body.get("txnAmount")
        if reported is not None:
            try:
                if abs(Decimal(str(reported)) - Decimal(payment.payable_amount)) > Decimal("0.01"):
                    mismatch_paid = str(reported)
            except Exception:
                mismatch_paid = str(reported)

    outcome = None
    if txn_status == "TXN_SUCCESS" and mismatch_paid is None:
        payment.status = "success"
        payment.paid_at = datetime.utcnow()
        db.flush()  # allocate payment.id if this is somehow still transient
        payment.receipt_number = payment.receipt_number or f"RCPT-{payment.id:06d}"

        subscription = _activate_subscription_for_payment(db, payment)
        payment.subscription_id = subscription.id
        coupon_service.mark_redeemed(db, payment)

        # The bill is created in a SAVEPOINT: if it somehow fails, the customer's payment and
        # activation still stand and an admin can create the bill by hand.
        try:
            with db.begin_nested():
                bill_service.create_for_payment(db, payment)
        except Exception:
            logger.exception("Bill creation failed for payment %s — create it manually", payment.id)

        log_action(
            db,
            actor_id=payment.user_id,
            action="payment.paytm_success",
            target_type="payment",
            target_id=payment.id,
            new_value={"order_id": order_id, "subscription_id": subscription.id, "invoice_number": payment.invoice_number},
        )
        outcome = "success"
    elif txn_status == "TXN_SUCCESS":
        payment.status = "failed"
        payment.gateway_response = {
            **(payment.gateway_response or {}),
            "amount_mismatch": {"expected": str(payment.payable_amount), "paytm_reported": mismatch_paid},
        }
        coupon_service.release(db, payment)
        logger.error(
            "Paytm amount mismatch for order %s: expected %s, Paytm reported %s — NOT activated",
            order_id, payment.payable_amount, mismatch_paid,
        )
        log_action(
            db,
            actor_id=payment.user_id,
            action="payment.amount_mismatch",
            target_type="payment",
            target_id=payment.id,
            new_value={"order_id": order_id, "expected": str(payment.payable_amount), "paytm_reported": mismatch_paid},
        )
        outcome = "mismatch"
    elif txn_status == "TXN_FAILURE":
        payment.status = "failed"
        coupon_service.release(db, payment)
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

    if outcome == "success":
        _after_success(db, payment)
    elif outcome == "mismatch":
        email_service.send_payment_mismatch_email(
            to=PAYMENT_ALERT_EMAIL,
            order_id=payment.order_id,
            expected=f"{Decimal(payment.payable_amount):.2f}",
            paid=mismatch_paid or "?",
            customer_email=payment.customer_email or "—",
        )

    return payment
