from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.user import User
from app.routes.auth import require_admin
from app.schemas.subscription import CashPaymentCreate, PaymentResponse
from app.services import payment_service as service

router = APIRouter(
    prefix="/admin/payments",
    tags=["Admin Payments"],
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
        "items": [PaymentResponse.model_validate(p) for p in result["items"]],
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
