"""
Public checkout API — used by the pricing-page dialog. No login needed: the
visitor proves their e-mail with a one-time code and gets a checkout token
(Authorization: Bearer <token>) that only works on these routes.
See app/services/checkout_service.py for the rules.
"""

import io
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.routes.payment import start_paytm_transaction
from app.schemas.checkout import (
    InitiateRequest,
    OtpRequest,
    OtpVerify,
    ProformaRequest,
    QuoteRequest,
    RegisterRequest,
)
from app.schemas.subscription import PaymentInitiateResponse, PaymentResponse
from app.services import bill_pdf, bill_service, checkout_service, email_service, invoice_service, paytm_service
from app.services import payment_service, pricing_service
from app.config import CHECKOUT_OTP_TTL_MINUTES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/checkout", tags=["Checkout"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> checkout_service.CheckoutSession:
    token = authorization.split(" ", 1)[1].strip() if authorization and authorization.lower().startswith("bearer ") else None
    return checkout_service.session_from_token(db, token)


# --------------------------------------------------------------------------
# Public
# --------------------------------------------------------------------------

@router.get("/salesmen")
def salesmen(db: Session = Depends(get_db)):
    return {"items": checkout_service.list_salesmen(db)}


@router.post("/otp/request")
def request_otp(payload: OtpRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Always answers the same, whether or not the address is registered."""
    code = checkout_service.create_otp(db, payload.email)
    background_tasks.add_task(
        email_service.send_checkout_otp_email,
        to=checkout_service.normalize_email(payload.email),
        otp=code,
        ttl_minutes=CHECKOUT_OTP_TTL_MINUTES,
    )
    return {"success": True, "message": "If the address is valid, a code has been sent."}


@router.post("/otp/verify")
def verify_otp(payload: OtpVerify, db: Session = Depends(get_db)):
    token = checkout_service.verify_otp(db, payload.email, payload.otp)
    return {"token": token}


# --------------------------------------------------------------------------
# Needs the checkout token
# --------------------------------------------------------------------------

@router.get("/profile")
def my_profile(session: checkout_service.CheckoutSession = Depends(get_session), db: Session = Depends(get_db)):
    return checkout_service.profile(db, session)


@router.post("/register")
def register(
    payload: RegisterRequest,
    background_tasks: BackgroundTasks,
    session: checkout_service.CheckoutSession = Depends(get_session),
    db: Session = Depends(get_db),
):
    user = checkout_service.register_account(db, session, payload)
    background_tasks.add_task(email_service.send_registration_email, to=user.email, name=user.name)
    return checkout_service.profile(db, checkout_service.CheckoutSession(session.email, user))


@router.post("/quote")
def quote(
    payload: QuoteRequest,
    session: checkout_service.CheckoutSession = Depends(get_session),
    db: Session = Depends(get_db),
):
    q = checkout_service.build_quote(
        db,
        plan_id=payload.plan_id,
        state=payload.state,
        user_id=session.user.id if session.user else None,
        coupon_code=payload.coupon_code,
        salesman_id=payload.salesman_id,
        override_base_price=payload.override_base_price,
        reason=payload.reason,
    )
    return checkout_service.quote_public(q)


@router.post("/proforma")
def proforma(
    payload: ProformaRequest,
    session: checkout_service.CheckoutSession = Depends(get_session),
    db: Session = Depends(get_db),
):
    """Unnumbered pro-forma bill (PDF) from the current dialog values. Nothing is saved."""
    q = checkout_service.build_quote(
        db,
        plan_id=payload.plan_id,
        state=payload.details.state,
        user_id=session.user.id if session.user else None,
        coupon_code=payload.coupon_code,
        salesman_id=payload.salesman_id,
        override_base_price=payload.override_base_price,
        reason=payload.reason,
    )
    details = {**payload.details.dict(), "email": session.email}
    draft = bill_service.draft_from_quote(details, q["plan"], q)
    return StreamingResponse(
        io.BytesIO(bill_pdf.build_bill_pdf(draft, proforma=True)),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="Proforma-Invoice.pdf"'},
    )


@router.post("/initiate", response_model=PaymentInitiateResponse)
async def initiate(
    payload: InitiateRequest,
    session: checkout_service.CheckoutSession = Depends(get_session),
    db: Session = Depends(get_db),
):
    """Re-computes the price on the server, records the order and opens Paytm."""
    user = session.user
    if not user:
        raise HTTPException(400, "Please create your account first.")

    q = checkout_service.build_quote(
        db,
        plan_id=payload.plan_id,
        state=payload.details.state,
        user_id=user.id,
        coupon_code=payload.coupon_code,
        salesman_id=payload.salesman_id,
        override_base_price=payload.override_base_price,
        reason=payload.reason,
    )
    details = payload.details.dict()
    if payload.update_profile:
        checkout_service.apply_profile_update(db, user, details)

    payment = payment_service.create_checkout_payment(db, user, quote=q, details=details)
    return await start_paytm_transaction(db, payment)


@router.get("/orders/{order_id}/status", response_model=PaymentResponse)
def order_status(
    order_id: str,
    session: checkout_service.CheckoutSession = Depends(get_session),
    db: Session = Depends(get_db),
):
    return checkout_service.get_own_payment(db, session, order_id)


@router.post("/orders/{order_id}/recheck", response_model=PaymentResponse)
async def order_recheck(
    order_id: str,
    session: checkout_service.CheckoutSession = Depends(get_session),
    db: Session = Depends(get_db),
):
    payment = checkout_service.get_own_payment(db, session, order_id)
    if payment.status == "success":
        return payment
    try:
        status_response = await paytm_service.verify_transaction_status(order_id)
    except paytm_service.PaytmError as e:
        logger.warning("Paytm status recheck failed for order %s (status=%s): %s", order_id, e.status_code, e)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "PAYMENT_STATUS_CHECK_UNAVAILABLE",
                "message": "Couldn't confirm this payment's status right now — please try again shortly.",
                "retryable": True,
            },
        )
    return payment_service.finalize_paytm_payment(db, order_id, status_response)


@router.get("/orders/{order_id}/bill")
def order_bill(
    order_id: str,
    session: checkout_service.CheckoutSession = Depends(get_session),
    db: Session = Depends(get_db),
):
    payment = checkout_service.get_own_payment(db, session, order_id)
    if payment.status != "success":
        raise HTTPException(400, "A bill is issued once the payment succeeds.")
    bill = bill_service.get_for_payment(db, payment.id)
    if not bill:
        raise HTTPException(404, "Your bill is being prepared — please try again in a moment or contact us.")
    filename = f"Bill-{bill.bill_number.replace('/', '-')}.pdf"
    return StreamingResponse(
        io.BytesIO(bill_pdf.build_bill_pdf(bill)),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/orders/{order_id}/receipt")
def order_receipt(
    order_id: str,
    session: checkout_service.CheckoutSession = Depends(get_session),
    db: Session = Depends(get_db),
):
    payment = checkout_service.get_own_payment(db, session, order_id)
    if payment.status != "success":
        raise HTTPException(400, "A receipt is issued once the payment succeeds.")
    data, content_type, filename = invoice_service.build_receipt(payment, "pdf")
    return StreamingResponse(
        io.BytesIO(data),
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
