from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.user import User
from app.routes.auth import require_admin
from app.schemas.checkout import CouponCreate, CouponResponse, CouponUpdate
from app.services import coupon_service as service
from app.services.audit_service import log_action

router = APIRouter(prefix="/admin/coupons", tags=["Admin Coupons"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("")
def list_coupons(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    active: Optional[bool] = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    result = service.list_coupons(db, page=page, limit=limit, search=search, active=active)
    return {**result, "items": [CouponResponse.from_orm(c) for c in result["items"]]}


@router.get("/{coupon_id}", response_model=CouponResponse)
def get_coupon(coupon_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return service.get(db, coupon_id)


@router.post("", response_model=CouponResponse)
def create_coupon(payload: CouponCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    coupon = service.create(db, admin.id, payload.dict())
    log_action(db, actor_id=admin.id, action="coupon.created", target_type="coupon", target_id=coupon.id,
               new_value={"code": coupon.code, "type": coupon.discount_type, "value": str(coupon.value)})
    db.commit()
    return coupon


@router.put("/{coupon_id}", response_model=CouponResponse)
def update_coupon(coupon_id: int, payload: CouponUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    data = payload.dict(exclude_unset=True)
    coupon = service.update(db, coupon_id, data)
    log_action(db, actor_id=admin.id, action="coupon.updated", target_type="coupon", target_id=coupon.id,
               new_value={k: str(v) for k, v in data.items()})
    db.commit()
    return coupon
