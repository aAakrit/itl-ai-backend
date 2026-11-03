"""
ITL Bridge AI routes.

User-facing (/bridge):
  GET  /bridge/status  — plan status, today's usage, connect-button links
  POST /bridge/allow   — the Allow page's Allow / Cancel decision

Admin (/admin/bridge): plan limits, per-customer limits, customer list,
suspend / activate / revoke, dashboard stats, manual re-sync.

All calls to the MCP server happen here, server-side — the Bridge keys never
reach the browser. See app/services/bridge_service.py.
"""

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.user import User
from app.routes.auth import get_current_user, get_db, require_admin
from app.services import bridge_service as bridge
from app.services.audit_service import log_action

router = APIRouter(prefix="/bridge", tags=["ITL Bridge AI"])
admin_router = APIRouter(prefix="/admin/bridge", tags=["Admin ITL Bridge AI"])

PLAN_CODE_RE = re.compile(r"^[a-z0-9_]{1,50}$")


def _call(fn, *args, **kwargs):
    """Runs a bridge_service call and turns its errors into HTTP errors."""
    try:
        return fn(*args, **kwargs)
    except bridge.BridgeError as e:
        raise HTTPException(status_code=e.status if 400 <= e.status < 600 else 502, detail=e.message)


# =============================================================================
# User-facing
# =============================================================================

@router.get("/status")
def my_status(user: User = Depends(get_current_user)):
    if not bridge.is_configured():
        return {"enabled": False, "status": None, "links": None}

    uid = bridge.user_key(user.id)
    try:
        status = bridge.get_status(uid)
    except bridge.BridgeError as e:
        if e.status != 404:
            raise HTTPException(status_code=e.status if 400 <= e.status < 600 else 502, detail=e.message)
        # Bridge has no record of this customer yet — same as "no plan".
        status = {"user_id": uid, "exists": False, "active": False}

    # The Connect buttons are a convenience; a failure here must not hide the plan status.
    try:
        links = bridge.get_connect_links()
    except bridge.BridgeError:
        links = None

    return {"enabled": True, "status": status, "links": links}


class AllowDecision(BaseModel):
    txn: str = Field(..., min_length=1, max_length=500)
    return_url: Optional[str] = Field(None, max_length=2000)
    decision: str  # "allow" | "cancel"


@router.post("/allow")
def allow(payload: AllowDecision, user: User = Depends(get_current_user)):
    if payload.decision == "allow":
        redirect = _call(
            bridge.allow_redirect_url,
            payload.txn,
            payload.return_url,
            user.id,
            user.email,
            user.name,
        )
    else:
        redirect = bridge.deny_redirect_url(payload.txn, payload.return_url)
    return {"redirect": redirect}


# =============================================================================
# Admin
# =============================================================================

class PlanLimits(BaseModel):
    daily_limit: Optional[int] = Field(..., ge=0)
    daily_doc_limit: Optional[int] = Field(..., ge=0)


class UserLimits(BaseModel):
    daily_limit: Optional[int] = Field(..., ge=0)
    daily_doc_limit: Optional[int] = Field(..., ge=0)


class StatusChange(BaseModel):
    status: str  # "active" | "suspended"


def _audit(db: Session, admin: User, action: str, bridge_user_id: Optional[str], previous=None, new=None):
    target = bridge.website_user_id(bridge_user_id) if bridge_user_id else None
    log_action(
        db,
        actor_id=admin.id,
        action=action,
        target_type="user" if target else "bridge_plan",
        target_id=target or 0,
        previous_value=previous,
        new_value=new,
    )
    db.commit()


@admin_router.get("/stats")
def stats(admin: User = Depends(require_admin)):
    return _call(bridge.get_stats)


@admin_router.get("/plans")
def plans(admin: User = Depends(require_admin)):
    return {"plans": _call(bridge.get_plans)}


@admin_router.put("/plans/{plan}")
def update_plan(
    plan: str,
    payload: PlanLimits,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not PLAN_CODE_RE.match(plan):
        raise HTTPException(400, "Invalid plan code.")
    result = _call(bridge.set_plan_limits, plan, payload.daily_limit, payload.daily_doc_limit)
    _audit(
        db, admin, "bridge.plan_limits_updated", None,
        new={"plan": plan, "daily_limit": payload.daily_limit, "daily_doc_limit": payload.daily_doc_limit},
    )
    return result


@admin_router.get("/subscriptions")
def customers(
    q: str = "",
    status: str = "",
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
):
    data = _call(bridge.list_subscriptions, q=q, status=status, limit=limit, offset=(page - 1) * limit)
    return {
        "items": data.get("subscriptions", []),
        "total": data.get("total", 0),
        "page": page,
        "limit": limit,
    }


@admin_router.put("/subscriptions/{user_id}/limits")
def update_customer_limits(
    user_id: str,
    payload: UserLimits,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    result = _call(bridge.set_user_limits, user_id, payload.daily_limit, payload.daily_doc_limit)
    _audit(
        db, admin, "bridge.user_limits_updated", user_id,
        new={"daily_limit": payload.daily_limit, "daily_doc_limit": payload.daily_doc_limit},
    )
    return result


@admin_router.post("/subscriptions/{user_id}/status")
def change_customer_status(
    user_id: str,
    payload: StatusChange,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if payload.status not in ("active", "suspended"):
        raise HTTPException(400, "Status must be 'active' or 'suspended'.")
    result = _call(bridge.upsert_subscription, user_id, {"status": payload.status})
    _audit(db, admin, f"bridge.{'suspended' if payload.status == 'suspended' else 'activated'}", user_id,
           new={"status": payload.status})
    return result


@admin_router.post("/subscriptions/{user_id}/revoke")
def revoke_customer(
    user_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    result = _call(bridge.revoke, user_id)
    _audit(db, admin, "bridge.revoked", user_id, new={"status": "revoked"})
    return result


@admin_router.post("/resync")
def resync(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Re-sends every active website subscription to the MCP server."""
    if not bridge.is_configured():
        raise HTTPException(503, "ITL Bridge AI is not configured.")
    return bridge.resync_all(db)
