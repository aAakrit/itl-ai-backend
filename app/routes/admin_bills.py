import io
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.user import User
from app.routes.auth import require_admin
from app.schemas.checkout import BillCancel, BillResponse, BillWrite
from app.services import bill_pdf, bill_service as service
from app.services.audit_service import log_action

router = APIRouter(prefix="/admin/bills", tags=["Admin Bills"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _data(payload: BillWrite) -> dict:
    data = payload.dict(exclude_unset=True)
    if data.get("lines") is not None:
        data["lines"] = [dict(line, amount=str(line["amount"])) for line in data["lines"]]
    return data


@router.get("")
def list_bills(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    financial_year: Optional[str] = None,
    status: Optional[str] = Query(None, description="active | cancelled"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    result = service.list_bills(db, page=page, limit=limit, search=search, financial_year=financial_year, status=status)
    return {**result, "items": [BillResponse.from_orm(b) for b in result["items"]]}


@router.get("/prefill")
def prefill(
    user_id: Optional[int] = None,
    plan_id: Optional[str] = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Starting values for a new bill — from a user's profile and/or a plan. Saves nothing."""
    return service.prefill(db, user_id=user_id, plan_id=plan_id)


@router.get("/{bill_id}", response_model=BillResponse)
def get_bill(bill_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return service.get(db, bill_id)


@router.post("", response_model=BillResponse)
def create_bill(payload: BillWrite, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    bill = service.create_bill(db, _data(payload), created_by=admin.id)
    log_action(db, actor_id=admin.id, action="bill.created", target_type="bill", target_id=bill.id,
               new_value={"bill_number": bill.bill_number, "total": str(bill.total_after_tax)})
    db.commit()
    return bill


@router.put("/{bill_id}", response_model=BillResponse)
def update_bill(bill_id: int, payload: BillWrite, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    bill = service.update_bill(db, bill_id, _data(payload))
    log_action(db, actor_id=admin.id, action="bill.updated", target_type="bill", target_id=bill.id,
               new_value={"bill_number": bill.bill_number, "total": str(bill.total_after_tax)})
    db.commit()
    return bill


@router.post("/{bill_id}/cancel", response_model=BillResponse)
def cancel_bill(bill_id: int, payload: BillCancel, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    bill = service.cancel_bill(db, bill_id, payload.reason)
    log_action(db, actor_id=admin.id, action="bill.cancelled", target_type="bill", target_id=bill.id,
               new_value={"bill_number": bill.bill_number}, reason=payload.reason)
    db.commit()
    return bill


@router.get("/{bill_id}/pdf")
def bill_pdf_file(bill_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    bill = service.get(db, bill_id)
    filename = f"Bill-{bill.bill_number.replace('/', '-')}.pdf"
    return StreamingResponse(
        io.BytesIO(bill_pdf.build_bill_pdf(bill)),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
