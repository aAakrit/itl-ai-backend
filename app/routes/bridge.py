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
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.bridge_connection import BridgeConnection
from app.models.user import User
from app.routes.auth import get_current_user, get_db, require_admin
from app.services import bridge_service as bridge
from app.services import subscription_service
from app.services import products as product_service
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

def _plan_summary(sub) -> Optional[dict]:
    """The customer's ITL Bridge AI plan as the website knows it (not from the MCP server)."""
    if sub is None:
        return None
    now = datetime.utcnow()
    status = sub.status
    if status == "active" and sub.expiry_date and sub.expiry_date <= now:
        status = "expired"
    days_left = max((sub.expiry_date - now).days, 0) if status == "active" and sub.expiry_date else None
    return {
        "plan_name": sub.plan_name,
        "products": product_service.products_of(sub),
        "term_years": product_service.term_years_of(sub),
        "status": status,
        "start_date": sub.start_date,
        "expiry_date": sub.expiry_date,
        "days_left": days_left,
    }


@router.get("/status")
def my_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    What the account page's "ITL Bridge AI" section shows. One entry per connector
    (GST AI, Income Tax AI) with its plan status, usage, connect links and whether the
    customer has approved it. Nothing is returned for a customer without an active
    subscription that includes ITL Bridge AI — the section is then hidden.
    """
    if not bridge.configured_connectors():
        return {"enabled": False, "has_access": False, "subscription": None, "connectors": []}

    plan = _plan_summary(subscription_service.latest_bridge_subscription(db, user.id))
    if not subscription_service.has_bridge_access(db, user.id):
        # Suspended / expired / cancelled: no connectors, but the customer still sees their plan
        # (and a Renew button). `subscription` is null only if they never had ITL Bridge AI.
        return {"enabled": True, "has_access": False, "subscription": plan, "connectors": []}

    approved = {
        c.connector: c
        for c in db.query(BridgeConnection).filter(BridgeConnection.user_id == user.id).all()
    }
    uid = bridge.user_key(user.id)
    blocked = bridge.blocked_connectors(db, user.id)
    sub = subscription_service.get_active_for_user(db, user.id)
    sync_tried = False

    def entry(key: str, **extra) -> dict:
        row = approved.get(key)
        base = {
            "key": key, "label": bridge.CONNECTORS[key]["label"], "status": None, "links": None,
            "error": None, "connected": row is not None,
            "connected_at": row.connected_at if row else None, "disabled": False,
        }
        base.update(extra)
        return base

    connectors = []
    for key in bridge.CONNECTORS:  # always both, GST first
        if key in blocked:
            # Switched off by an admin: no plan details or connect links, just the fact.
            connectors.append(entry(key, connected=False, connected_at=None, disabled=True))
            continue
        if not bridge.is_configured(key):
            connectors.append(entry(key, error="not_configured"))
            continue

        def fetch_status():
            try:
                return bridge.get_status(uid, connector=key), None
            except bridge.BridgeError as e:
                if e.status == 404:
                    # The connector has no record of this customer yet — same as "no plan".
                    return {"user_id": uid, "exists": False, "active": False}, None
                return None, e.message

        status, error = fetch_status()

        # The customer's plan should already be on this server. If it isn't (e.g. the plan was
        # created before the connector was set up), push it now — once — and look again.
        if status is not None and not status.get("active") and sub is not None and not sync_tried:
            sync_tried = True
            bridge.sync_subscription(db, sub)
            status, error = fetch_status()

        # The Connect buttons are a convenience; a failure here must not hide the plan status.
        try:
            links = bridge.get_connect_links(connector=key)
        except bridge.BridgeError:
            links = None
        connectors.append(entry(key, status=status, links=links, error=error))

    return {"enabled": True, "has_access": True, "subscription": plan, "connectors": connectors}


class AllowDecision(BaseModel):
    txn: str = Field(..., min_length=1, max_length=500)
    return_url: Optional[str] = Field(None, max_length=2000)
    decision: str  # "allow" | "cancel"


def _record_connection(db: Session, user_id: int, connector: str, txn: str) -> None:
    row = db.query(BridgeConnection).filter(
        BridgeConnection.user_id == user_id, BridgeConnection.connector == connector
    ).first()
    now = datetime.utcnow()
    if row:
        row.connected_at, row.last_txn = now, txn
    else:
        db.add(BridgeConnection(user_id=user_id, connector=connector, connected_at=now, last_txn=txn))
    try:
        db.commit()
    except IntegrityError:  # two Allow clicks at once — the other one already wrote it
        db.rollback()


@router.post("/allow")
def allow(payload: AllowDecision, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The Allow page's decision. The connector (GST / Income Tax) comes from the return_url,
    so the customer is sent back to the right MCP server with a token signed for it."""
    connector = _call(bridge.resolve_connector, payload.return_url)

    if payload.decision == "allow":
        if not subscription_service.has_bridge_access(db, user.id):
            raise HTTPException(
                status_code=403,
                detail="Your plan doesn't include ITL Bridge AI. Subscribe to ITL AI + ITL Bridge AI to connect.",
            )
        if connector in bridge.blocked_connectors(db, user.id):
            raise HTTPException(
                status_code=403,
                detail=f"{bridge.CONNECTORS[connector]['label']} has been disabled on your account. Please contact support.",
            )
        redirect = _call(
            bridge.allow_redirect_url,
            payload.txn,
            payload.return_url,
            user.id,
            user.email,
            user.name,
            connector,
        )
        _record_connection(db, user.id, connector, payload.txn)
    else:
        redirect = bridge.deny_redirect_url(payload.txn, payload.return_url, connector)
    return {"redirect": redirect, "connector": connector}


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


def _conn(connector: str) -> str:
    if connector not in bridge.CONNECTORS:
        raise HTTPException(400, "Unknown connector. Use 'gst' or 'it'.")
    return connector


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
def stats(connector: str = Query("gst"), admin: User = Depends(require_admin)):
    return _call(bridge.get_stats, connector=_conn(connector))


@admin_router.get("/plans")
def plans(connector: str = Query("gst"), admin: User = Depends(require_admin)):
    return {"plans": _call(bridge.get_plans, connector=_conn(connector))}


@admin_router.put("/plans/{plan}")
def update_plan(
    plan: str,
    payload: PlanLimits,
    connector: str = Query("gst"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not PLAN_CODE_RE.match(plan):
        raise HTTPException(400, "Invalid plan code.")
    result = _call(bridge.set_plan_limits, plan, payload.daily_limit, payload.daily_doc_limit, connector=_conn(connector))
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
    connector: str = Query("gst"),
    admin: User = Depends(require_admin),
):
    data = _call(bridge.list_subscriptions, q=q, status=status, limit=limit, offset=(page - 1) * limit, connector=_conn(connector))
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
    connector: str = Query("gst"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    result = _call(bridge.set_user_limits, user_id, payload.daily_limit, payload.daily_doc_limit, connector=_conn(connector))
    _audit(
        db, admin, "bridge.user_limits_updated", user_id,
        new={"daily_limit": payload.daily_limit, "daily_doc_limit": payload.daily_doc_limit},
    )
    return result


@admin_router.post("/subscriptions/{user_id}/status")
def change_customer_status(
    user_id: str,
    payload: StatusChange,
    connector: str = Query("gst"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if payload.status not in ("active", "suspended"):
        raise HTTPException(400, "Status must be 'active' or 'suspended'.")
    result = _call(bridge.upsert_subscription, user_id, {"status": payload.status}, connector=_conn(connector))
    _audit(db, admin, f"bridge.{'suspended' if payload.status == 'suspended' else 'activated'}", user_id,
           new={"status": payload.status})
    return result


@admin_router.post("/subscriptions/{user_id}/revoke")
def revoke_customer(
    user_id: str,
    connector: str = Query("gst"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    result = _call(bridge.revoke, user_id, connector=_conn(connector))
    _audit(db, admin, "bridge.revoked", user_id, new={"status": "revoked"})
    return result


@admin_router.post("/resync")
def resync(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Re-sends every active website subscription to the MCP server."""
    if not bridge.configured_connectors():
        raise HTTPException(503, "ITL Bridge AI is not configured.")
    return bridge.resync_all(db)


class ConnectorToggle(BaseModel):
    connector: str
    enabled: bool


@admin_router.get("/access/{user_id}")
def admin_connector_access(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Which connectors (GST AI / Income Tax AI) are switched on for this customer."""
    return {"connectors": bridge.connector_access(db, user_id)}


@admin_router.put("/access/{user_id}")
def admin_set_connector_access(
    user_id: int,
    payload: ConnectorToggle,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Switch one connector on/off for one customer. Takes effect immediately on that MCP server."""
    _conn(payload.connector)
    synced = _call(bridge.set_connector_enabled, db, user_id, payload.connector, payload.enabled, admin.id)
    log_action(
        db,
        actor_id=admin.id,
        action="bridge.connector_enabled" if payload.enabled else "bridge.connector_disabled",
        target_type="user",
        target_id=user_id,
        new_value={"connector": payload.connector, "enabled": payload.enabled},
    )
    db.commit()
    return {"connectors": bridge.connector_access(db, user_id), "synced": bool(synced)}
