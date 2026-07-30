from datetime import datetime
from typing import Optional

from app.schemas.admin_user import UserUpdate
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.services import admin_user as service
from app.db import SessionLocal
from app.models.user import User
from app.routes.auth import get_current_user, require_admin

router = APIRouter(
    prefix="/admin/users",
    tags=["Admin Users"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("")
def get_users(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    role: Optional[str] = None,
    status: Optional[str] = None,
    plan: Optional[str] = None,
    sort: str = Query("created_at"),
    order: str = Query("desc"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    # Was previously building an identical `items` list here and then
    # discarding it in favor of calling service.get_users() anyway — the
    # exact same query ran twice per request for no reason. Delegates
    # cleanly now.
    return service.get_users(
        db=db,
        page=page,
        limit=limit,
        search=search,
        role=role,
        status=status,
        plan=plan,
        sort=sort,
        order=order,
    )


# ------------------------------------------------------------------
# User Detail
# ------------------------------------------------------------------

@router.get("/{user_id}")
def get_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = (
        db.query(User)
        .filter(User.id == user_id)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

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
        "plan": getattr(user, "plan", None),
        "status": user.status,
        "is_admin": user.is_admin,
        "is_staff": user.is_staff,
        "last_login": getattr(user, "last_login", None),
        "created_at": user.created_at,
        "updated_at": getattr(user, "updated_at", None),
    }


# ------------------------------------------------------------------
# Update User
# ------------------------------------------------------------------

@router.put("/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = (
        db.query(User)
        .filter(User.id == user_id)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    editable_fields = [
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
    ]

    for field, value in payload.dict(exclude_unset=True).items():
        setattr(user, field, value)

    if hasattr(user, "updated_at"):
        user.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(user)

    return {
        "success": True,
        "message": "User updated successfully",
    }


# ------------------------------------------------------------------
# Approve User
# ------------------------------------------------------------------

@router.patch("/{user_id}/approve")
def approve_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(404, "User not found")

    user.status = "APPROVED"

    if hasattr(user, "approved_at"):
        user.approved_at = datetime.utcnow()

    if hasattr(user, "approved_by"):
        user.approved_by = admin.id

    db.commit()

    return {"success": True}


# ------------------------------------------------------------------
# Suspend User
# ------------------------------------------------------------------

@router.patch("/{user_id}/suspend")
def suspend_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(404, "User not found")

    user.status = "SUSPENDED"

    db.commit()

    return {"success": True}


# ------------------------------------------------------------------
# Soft Delete User
# ------------------------------------------------------------------

@router.patch("/{user_id}/delete")
def delete_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(404, "User not found")

    user.status = "DELETED"

    if hasattr(user, "deleted_at"):
        user.deleted_at = datetime.utcnow()

    db.commit()

    return {"success": True}


# ------------------------------------------------------------------
# User History (Placeholder)
# ------------------------------------------------------------------

@router.get("/{user_id}/history")
def get_user_history(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(404, "User not found")

    return {
        "items": []
    }