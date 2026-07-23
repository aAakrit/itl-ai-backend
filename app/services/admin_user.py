from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.admin_user import UserUpdate

def get_users(
    db: Session,
    page: int,
    limit: int,
    search: Optional[str] = None,
    role: Optional[str] = None,
    status: Optional[str] = None,
    plan: Optional[str] = None,
    sort: str = "created_at",
    order: str = "desc",
):

    query = db.query(User)

    if search:
        query = query.filter(
            or_(
                User.name.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
                User.mobile.ilike(f"%{search}%"),
                User.firm.ilike(f"%{search}%"),
            )
        )

    if status:
        query = query.filter(
            User.status == status.upper()
        )

    if role:

        role = role.lower()

        if role == "admin":
            query = query.filter(User.is_admin.is_(True))

        elif role == "staff":
            query = query.filter(User.is_staff.is_(True))

        elif role == "user":
            query = query.filter(
                User.is_admin.is_(False),
                User.is_staff.is_(False),
            )


    if plan and hasattr(User, "plan"):
        query = query.filter(
            User.plan == plan
        )


    sortable = {
        "name": User.name,
        "email": User.email,
        "status": User.status,
        "created_at": User.created_at,
        "last_login": getattr(User, "last_login", User.created_at),
    }

    sort_column = sortable.get(
        sort,
        User.created_at,
    )

    if order.lower() == "asc":
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    total = query.count()

    users = (
        query
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    items = []

    for user in users:

        if user.is_admin:
            role_name = "Admin"
        elif user.is_staff:
            role_name = "Staff"
        else:
            role_name = "User"

        items.append(
            {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "mobile": user.mobile,
                "firm": user.firm,
                "plan": getattr(user, "plan", None),
                "role": role_name,
                "status": user.status,
                "last_login": getattr(user, "last_login", None),
                "created_at": user.created_at,
            }
        )

    return {
        "items": items,
        "page": page,
        "limit": limit,
        "total": total,
    }

def get_user(
    db: Session,
    user_id: int,
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

    return user

def update_user(
    db: Session,
    user_id: int,
    payload: UserUpdate,
):

    user = get_user(db, user_id)

    data = payload.dict(exclude_unset=True)

    for field, value in data.items():
        setattr(user, field, value)

    if hasattr(user, "updated_at"):
        user.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(user)

    return {
        "success": True,
        "message": "User updated successfully",
    }


def approve_user(
    db: Session,
    user_id: int,
    admin_id: int,
):

    user = get_user(db, user_id)

    user.status = "APPROVED"

    if hasattr(user, "approved_at"):
        user.approved_at = datetime.utcnow()

    if hasattr(user, "approved_by"):
        user.approved_by = admin_id

    db.commit()

    return {
        "success": True,
        "message": "User approved successfully",
    }


def suspend_user(
    db: Session,
    user_id: int,
):

    user = get_user(db, user_id)

    user.status = "SUSPENDED"

    db.commit()

    return {
        "success": True,
        "message": "User suspended successfully",
    }

def delete_user(
    db: Session,
    user_id: int,
):

    user = get_user(db, user_id)

    user.status = "DELETED"

    if hasattr(user, "deleted_at"):
        user.deleted_at = datetime.utcnow()

    db.commit()

    return {
        "success": True,
        "message": "User deleted successfully",
    }


def get_user_history(
    db: Session,
    user_id: int,
):

    get_user(db, user_id)

    return {
        "items": []
    }