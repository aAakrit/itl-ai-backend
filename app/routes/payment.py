import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import FRONTEND_URL
from app.db import SessionLocal
from app.models.user import User
from app.routes.auth import get_current_user, require_admin
from app.schemas.subscription import CashPaymentCreate, PaymentInitiateRequest, PaymentInitiateResponse, PaymentResponse
from app.services import payment_service as service
from app.services import paytm_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/payments",
    tags=["Admin Payments"],
)

# User-facing checkout — separate router (different prefix/auth) but same
# module since it's all "payments".
checkout_router = APIRouter(
    prefix="/payments",
    tags=["Payments"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("")
def list_payments(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    gateway: Optional[str] = Query(None, description="paytm | cash | complimentary"),
    search: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    result = service.list_payments(
        db,
        page=page,
        limit=limit,
        status=status,
        gateway=gateway,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )
    return {
        **result,
        "items": [PaymentResponse.from_orm(p) for p in result["items"]],
    }


@router.get("/{payment_id}", response_model=PaymentResponse)
def get_payment(
    payment_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return service.get(db, payment_id)


@router.post("/cash", response_model=PaymentResponse)
def record_cash_payment(
    payload: CashPaymentCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return service.record_cash_payment(db, admin.id, payload)


# =============================================================================
# User-facing checkout
# =============================================================================

@checkout_router.post("/initiate", response_model=PaymentInitiateResponse)
async def initiate_payment(
    payload: PaymentInitiateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Creates a pending Payment, opens a Paytm transaction for it, and
    returns everything the frontend needs to redirect into Paytm's hosted
    checkout page."""

    payment = service.create_paytm_payment(db, user, payload.plan_id, payload.billing_cycle)

    try:
        result = await paytm_service.initiate_transaction(
            order_id=payment.order_id,
            amount=str(payment.payable_amount),
            customer_id=str(user.id),
            email=user.email,
            mobile=user.mobile,
        )
    except Exception as e:
        logger.exception("Paytm initiateTransaction failed for order %s", payment.order_id)
        service.mark_init_failed(db, payment, str(e))
        raise HTTPException(status_code=502, detail="Couldn't reach Paytm — please try again.")

    body = result.get("body", {}) if isinstance(result, dict) else {}
    result_info = body.get("resultInfo", {}) if isinstance(body, dict) else {}

    if result_info.get("resultStatus") != "S":
        reason = result_info.get("resultMsg", "Paytm rejected the request.")
        service.mark_init_failed(db, payment, reason)
        raise HTTPException(status_code=502, detail=reason)

    txn_token = body.get("txnToken")
    if not txn_token:
        service.mark_init_failed(db, payment, "Paytm did not return a txnToken.")
        raise HTTPException(status_code=502, detail="Paytm did not return a transaction token.")

    service.record_gateway_init(db, payment, txn_token, result)

    return PaymentInitiateResponse(
        order_id=payment.order_id,
        amount=payment.payable_amount,
        txn_token=txn_token,
        paytm_params={
            "mid": paytm_service.PAYTM_MID,
            "orderId": payment.order_id,
            "txnToken": txn_token,
            "checkoutUrl": paytm_service.checkout_url(payment.order_id),
        },
    )


@checkout_router.post("/paytm/callback")
async def paytm_callback(request: Request, db: Session = Depends(get_db)):
    """
    Paytm POSTs form-encoded fields here (the callbackUrl set at initiate
    time) after the user completes — or abandons — checkout. This is the
    only place PAYTM_CALLBACK_URL should point to.

    The callback's own checksum is checked as a first-pass sanity filter,
    but the checksum result is NOT what decides success/failure — the
    Transaction Status API call below is. A missing/invalid checksum is
    logged, not trusted, and doesn't block the authoritative status check.
    """

    form = await request.form()
    params = dict(form)
    order_id = params.get("ORDERID")

    if not order_id:
        return RedirectResponse(
            url=f"{FRONTEND_URL}/billing/return?status=error&reason=missing_order_id",
            status_code=303,
        )

    checksum_ok = paytm_service.verify_callback_checksum(params)
    if not checksum_ok:
        logger.warning("Paytm callback checksum mismatch for order %s", order_id)

    try:
        status_response = await paytm_service.verify_transaction_status(order_id)
    except Exception:
        logger.exception("Paytm status check failed for order %s", order_id)
        return RedirectResponse(
            url=f"{FRONTEND_URL}/billing/return?status=error&order_id={order_id}",
            status_code=303,
        )

    payment = service.finalize_paytm_payment(db, order_id, status_response)

    return RedirectResponse(
        url=f"{FRONTEND_URL}/billing/return?status={payment.status}&order_id={order_id}",
        status_code=303,
    )


@checkout_router.get("/{order_id}/status", response_model=PaymentResponse)
def payment_status(
    order_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payment = service.get_by_order_id(db, order_id)
    if payment.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Not your payment.")
    return payment


@checkout_router.post("/{order_id}/recheck", response_model=PaymentResponse)
async def recheck_payment(
    order_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Forces a fresh Transaction Status pull — useful when the browser
    lands back on the site before Paytm's async callback has arrived."""

    payment = service.get_by_order_id(db, order_id)
    if payment.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Not your payment.")
    if payment.status == "success":
        return payment

    status_response = await paytm_service.verify_transaction_status(order_id)
    return service.finalize_paytm_payment(db, order_id, status_response)
