from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.user import User
from app.routes.auth import require_admin
from app.schemas.subscription import (
    SubscriptionCreateManual,
    SubscriptionUpdate,
    SubscriptionExtend,
    SubscriptionResponse,
)
from app.services import subscription_service as service

router = APIRouter(
    prefix="/admin/subscriptions",
    tags=["Admin Subscriptions"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("")
def list_subscriptions(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    plan_id: Optional[str] = None,
    source: Optional[str] = None,
    search: Optional[str] = None,
    expiry_window: Optional[str] = Query(None, description="expired | today | 7d | 30d | 60d | 90d"),
    expiry_from: Optional[datetime] = None,
    expiry_to: Optional[datetime] = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    result = service.list_subscriptions(
        db,
        page=page,
        limit=limit,
        status=status,
        plan_id=plan_id,
        source=source,
        search=search,
        expiry_window=expiry_window,
        expiry_from=expiry_from,
        expiry_to=expiry_to,
    )
    return {
        **result,
        "items": [SubscriptionResponse.model_validate(s) for s in result["items"]],
    }


@router.get("/{subscription_id}", response_model=SubscriptionResponse)
def get_subscription(
    subscription_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return service.get(db, subscription_id)


@router.post("/manual", response_model=SubscriptionResponse)
def create_manual_subscription(
    payload: SubscriptionCreateManual,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return service.create_manual(db, admin.id, payload)


@router.put("/{subscription_id}", response_model=SubscriptionResponse)
def update_subscription(
    subscription_id: int,
    payload: SubscriptionUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return service.update(db, admin.id, subscription_id, payload)


@router.post("/{subscription_id}/extend", response_model=SubscriptionResponse)
def extend_subscription(
    subscription_id: int,
    payload: SubscriptionExtend,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return service.extend(db, admin.id, subscription_id, payload.days, payload.reason)


@router.post("/{subscription_id}/suspend", response_model=SubscriptionResponse)
def suspend_subscription(
    subscription_id: int,
    reason: Optional[str] = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return service.set_status(db, admin.id, subscription_id, "suspended", reason)


@router.post("/{subscription_id}/cancel", response_model=SubscriptionResponse)
def cancel_subscription(
    subscription_id: int,
    reason: Optional[str] = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return service.set_status(db, admin.id, subscription_id, "cancelled", reason)


@router.post("/{subscription_id}/activate", response_model=SubscriptionResponse)
def activate_subscription(
    subscription_id: int,
    reason: Optional[str] = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return service.set_status(db, admin.id, subscription_id, "active", reason)