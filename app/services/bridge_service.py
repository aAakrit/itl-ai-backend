"""
ITL Bridge AI — website <-> MCP server integration.

Python port of the vendor's `itl-bridge.js` helper (the handover document
assumes a Node backend; this project is FastAPI, so the same calls live
here). Keys come from the environment and are only ever used server-side.

Two responsibilities:

1. Thin client for the MCP server's Bridge API (status, limits, plans,
   customers, stats) and the signed Allow-page handoff.
2. `sync_subscription` — called after any subscription change (online
   payment, cash payment, renewal, plan change, suspend, cancel) to tell the
   MCP server who has which plan. It NEVER raises: a Bridge outage must not
   break a payment or an admin action. Anything missed is repaired by the
   nightly `resync_all` (the Bridge call is idempotent).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote

import httpx
from jose import jwt

from app.services import products as product_service
from app.config import (
    BRIDGE_ADMIN_KEY,
    BRIDGE_API_URL,
    BRIDGE_HANDOFF_SECRET,
    BRIDGE_IT_ADMIN_KEY,
    BRIDGE_IT_API_URL,
    BRIDGE_IT_HANDOFF_SECRET,
    BRIDGE_IT_PLAN_MAP,
    BRIDGE_IT_RETURN_URL,
    BRIDGE_PLAN_MAP,
    BRIDGE_USER_PREFIX,
)

logger = logging.getLogger(__name__)

RETURN_PREFIX = "https://mcp.incometaxlibrary.com/bridge/return"  # GST connector (the default)

# Two separate MCP servers, each with its own host, admin key and subscriptions. They share one
# hand-off secret. A customer who buys ITL Bridge AI gets a subscription on BOTH.
CONNECTORS: dict[str, dict] = {
    "gst": {
        "label": "GST AI",
        "api_url": BRIDGE_API_URL,
        "admin_key": BRIDGE_ADMIN_KEY,
        "secret": BRIDGE_HANDOFF_SECRET,
        "return_prefix": RETURN_PREFIX,
        "plan_map": {},
    },
    "it": {
        "label": "Income Tax AI",
        "api_url": BRIDGE_IT_API_URL,
        "admin_key": BRIDGE_IT_ADMIN_KEY,
        "secret": BRIDGE_IT_HANDOFF_SECRET,
        "return_prefix": BRIDGE_IT_RETURN_URL,
        "plan_map": {},
    },
}
BRIDGE_PLAN_CODES = {"bridge_yearly", "bridge_3year", "bundle_yearly", "bundle_3year", "bundle_5year"}
REQUEST_TIMEOUT = 10.0


class BridgeError(Exception):
    def __init__(self, message: str, status: int = 502, data: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.data = data or {}


def _connector(key: str) -> dict:
    try:
        return CONNECTORS[key]
    except KeyError:
        raise BridgeError(f"Unknown connector '{key}'.", 400)


def is_configured(connector: str = "gst") -> bool:
    c = CONNECTORS.get(connector)
    return bool(c and c["admin_key"] and c["secret"])


def configured_connectors() -> list[str]:
    """Connectors that have their key + secret set on this deployment (GST first)."""
    return [k for k in CONNECTORS if is_configured(k)]


def resolve_connector(return_url: Optional[str]) -> str:
    """Which connector an Allow-page request belongs to, from its return_url.
    No return_url -> the GST connector (the original default). A return_url that is not one of
    OUR connectors' return addresses is rejected rather than silently sent somewhere else."""
    if not return_url:
        return "gst"
    for key, c in CONNECTORS.items():
        if return_url.startswith(c["return_prefix"]):
            return key
    raise BridgeError("This connection link is not valid. Please connect again from your AI application.", 400)


def user_key(user_id: int) -> str:
    """Site-prefixed id, e.g. "in:12". Use this format in every Bridge call."""
    return f"{BRIDGE_USER_PREFIX}:{user_id}"


def website_user_id(bridge_user_id: str) -> Optional[int]:
    """Inverse of user_key — used to attach audit entries to a website user."""
    try:
        return int(str(bridge_user_id).split(":", 1)[1])
    except (IndexError, ValueError):
        return None


# ── Allow page handoff ───────────────────────────────────────────────────

def safe_return_url(return_url: Optional[str], connector: Optional[str] = None) -> str:
    """Only ever redirect back to one of our own MCP servers — the right one for the connector."""
    key = connector or resolve_connector(return_url)
    prefix = _connector(key)["return_prefix"]
    return return_url if return_url and return_url.startswith(prefix) else prefix


def _with_params(url: str, **params: str) -> str:
    return str(httpx.URL(url).copy_merge_params(params))


def allow_redirect_url(
    txn: str,
    return_url: Optional[str],
    user_id: int,
    email: str = "",
    name: str = "",
    connector: Optional[str] = None,
) -> str:
    key = connector or resolve_connector(return_url)
    c = _connector(key)
    if not c["secret"]:
        raise BridgeError("ITL Bridge AI is not configured.", 503)
    now = datetime.utcnow()
    # `sub` must be exactly the user id used in the PUT /subscriptions/{id} calls (see user_key).
    token = jwt.encode(
        {
            "sub": user_key(user_id),
            "email": email or "",
            "name": name or "",
            "txn": txn,
            "aud": "itl-bridge",
            "iat": now,
            "exp": now + timedelta(minutes=2),
        },
        c["secret"],
        algorithm="HS256",
    )
    return _with_params(safe_return_url(return_url, key), txn=txn, token=token)


def deny_redirect_url(txn: str, return_url: Optional[str], connector: Optional[str] = None) -> str:
    return _with_params(safe_return_url(return_url, connector), txn=txn, error="access_denied")


# ── Website -> MCP server API ───────────────────────────────────────────

def _api(method: str, path: str, body: Optional[dict] = None, params: Optional[dict] = None, connector: str = "gst") -> dict:
    c = _connector(connector)
    if not is_configured(connector):
        raise BridgeError("ITL Bridge AI is not configured.", 503)
    try:
        res = httpx.request(
            method,
            c["api_url"] + path,
            json=body,
            params=params,
            headers={"X-Bridge-Key": c["admin_key"]},
            timeout=REQUEST_TIMEOUT,
        )
    except httpx.HTTPError as e:
        raise BridgeError(f"Couldn't reach the ITL Bridge AI service: {e}", 502)

    try:
        data = res.json()
    except ValueError:
        data = {}

    if res.status_code >= 400:
        message = data.get("error_description") or data.get("error") or f"Bridge API {res.status_code}"
        raise BridgeError(message, res.status_code, data)
    return data


def _q(value: str) -> str:
    return quote(value, safe="")  # same as JS encodeURIComponent


def upsert_subscription(user_id: str, sub: dict, connector: str = "gst") -> dict:
    return _api("PUT", f"/subscriptions/{_q(user_id)}", sub, connector=connector)


def get_status(user_id: str, connector: str = "gst") -> dict:
    return _api("GET", f"/subscriptions/{_q(user_id)}", connector=connector)


def revoke(user_id: str, connector: str = "gst") -> dict:
    return _api("POST", f"/subscriptions/{_q(user_id)}/revoke", connector=connector)


def get_connect_links(connector: str = "gst") -> dict:
    return _api("GET", "/connect-links", connector=connector)


def get_plans(connector: str = "gst") -> list:
    return _api("GET", "/plans", connector=connector).get("plans", [])


def set_plan_limits(plan: str, daily_searches: Optional[int], daily_documents: Optional[int], connector: str = "gst") -> dict:
    return _api("PUT", f"/plans/{_q(plan)}", {"daily_limit": daily_searches, "daily_doc_limit": daily_documents}, connector=connector)


def set_user_limits(user_id: str, daily_searches: Optional[int], daily_documents: Optional[int], connector: str = "gst") -> dict:
    return _api(
        "PUT",
        f"/subscriptions/{_q(user_id)}/limits",
        {"daily_limit": daily_searches, "daily_doc_limit": daily_documents},
        connector=connector,
    )


def list_subscriptions(q: str = "", status: str = "", limit: int = 50, offset: int = 0, connector: str = "gst") -> dict:
    return _api("GET", "/subscriptions", params={"q": q, "status": status, "limit": limit, "offset": offset}, connector=connector)


def get_stats(connector: str = "gst") -> dict:
    return _api("GET", "/stats", connector=connector)


# ── Subscription sync (payment hooks) ───────────────────────────────────

def resolve_plan_code(
    plan_id: Optional[str],
    billing_cycle: Optional[str] = None,
    products: Optional[list] = None,
    term_years: Optional[int] = None,
) -> Optional[str]:
    """Maps a subscription to a Bridge plan code, or None when it doesn't include ITL Bridge AI.

    With `products` (the normal case): the ITL AI + ITL Bridge AI bundle maps to
    bundle_yearly / bundle_3year / bundle_5year by term. Without them, falls back
    to the old plan-id / BRIDGE_PLAN_MAP lookup."""
    if products is not None:
        if product_service.BRIDGE not in products:
            return None
        # Older standalone Bridge plans keep their own codes.
        if plan_id in product_service.LEGACY_STANDALONE_BRIDGE_IDS:
            return plan_id
        # Everything else (Bridge-only plans, and the older ITL AI + Bridge bundle) maps by term.
        code = product_service.BRIDGE_BUNDLE_CODE_BY_TERM.get(int(term_years or 1))
        if not code:
            logger.error("No Bridge plan code for a %s-year term.", term_years)
        return code

    if not plan_id:
        return None
    if plan_id in BRIDGE_PLAN_CODES:
        return plan_id
    try:
        mapping = json.loads(BRIDGE_PLAN_MAP or "{}")
    except ValueError:
        logger.error("BRIDGE_PLAN_MAP is not valid JSON — no plans will sync to ITL Bridge AI.")
        return None
    code = mapping.get(f"{plan_id}:{billing_cycle}") or mapping.get(str(plan_id))
    return code if code in BRIDGE_PLAN_CODES else None


def _plan_code_for(connector: str, code: str) -> str:
    """The plan code to send to a connector (the IT server may name its plans differently)."""
    if connector != "it":
        return code
    try:
        return json.loads(BRIDGE_IT_PLAN_MAP or "{}").get(code, code)
    except ValueError:
        logger.error("BRIDGE_IT_PLAN_MAP is not valid JSON — using the GST plan codes for Income Tax.")
        return code


def clear_connections(db, user_id: int) -> None:
    """Forget the 'connected' marks for a customer whose Bridge access was removed."""
    try:
        from app.models.bridge_connection import BridgeConnection

        db.query(BridgeConnection).filter(BridgeConnection.user_id == user_id).delete()
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.error("Couldn't clear Bridge connections for user %s: %s", user_id, e)


def safe_revoke(user_id: int, db=None) -> bool:
    """Removes a customer's Bridge access on every connector (e.g. an admin took the Bridge
    product away). Never raises."""
    ok = False
    for key in configured_connectors():
        try:
            revoke(user_key(user_id), connector=key)
            ok = True
        except Exception as e:  # noqa: BLE001
            logger.error("ITL Bridge AI (%s) revoke failed for user %s: %s", key, user_id, e)
    if db is not None:
        clear_connections(db, user_id)
    return ok


def bridge_plan_ids() -> list[str]:
    """Pricing plan ids that grant ITL Bridge AI (used by the admin product filter)."""
    ids = set(BRIDGE_PLAN_CODES)
    try:
        for key in json.loads(BRIDGE_PLAN_MAP or "{}"):
            ids.add(str(key).split(":", 1)[0])
    except ValueError:
        pass
    return sorted(ids)


def _date(value: Optional[datetime]) -> Optional[str]:
    return value.date().isoformat() if value else None


def blocked_connectors(db, user_id: int) -> set[str]:
    """Connectors an admin has switched off for this customer."""
    from app.models.bridge_connection import BridgeConnectorBlock

    rows = db.query(BridgeConnectorBlock.connector).filter(BridgeConnectorBlock.user_id == user_id).all()
    return {r[0] for r in rows}


def connector_access(db, user_id: int) -> list[dict]:
    blocked = blocked_connectors(db, user_id)
    return [{"key": k, "label": c["label"], "enabled": k not in blocked} for k, c in CONNECTORS.items()]


def set_connector_enabled(db, user_id: int, connector: str, enabled: bool, admin_id: Optional[int] = None) -> bool:
    """Admin switch: turn one connector on/off for one customer, effective immediately.
    Returns True when the customer's subscription was re-synced successfully (or there was nothing to sync)."""
    from app.models.bridge_connection import BridgeConnection, BridgeConnectorBlock
    from app.services import subscription_service  # local import: subscription_service imports this module

    _connector(connector)
    row = (
        db.query(BridgeConnectorBlock)
        .filter(BridgeConnectorBlock.user_id == user_id, BridgeConnectorBlock.connector == connector)
        .first()
    )
    if enabled and row:
        db.delete(row)
    elif not enabled and not row:
        db.add(BridgeConnectorBlock(user_id=user_id, connector=connector, disabled_by_admin_id=admin_id))
    if not enabled:
        db.query(BridgeConnection).filter(
            BridgeConnection.user_id == user_id, BridgeConnection.connector == connector
        ).delete()
    db.commit()

    sub = subscription_service.get_active_for_user(db, user_id)
    return sync_subscription(db, sub) if sub else True


def sync_subscription(db, sub) -> bool:
    """Pushes a website Subscription to every configured MCP server (GST and Income Tax).
    Safe to call after every change — returns True only when every call that was needed
    succeeded; False when skipped or any failed; never raises."""
    try:
        connectors = configured_connectors()
        if not connectors or sub is None:
            return False

        code = resolve_plan_code(
            sub.plan_id, sub.billing_cycle,
            products=product_service.products_of(sub), term_years=product_service.term_years_of(sub),
        )
        if not code:
            return False

        from app.models.user import User  # local import: avoids a cycle at import time

        user = db.query(User).filter(User.id == sub.user_id).first()
        if not user:
            return False
        uid = user_key(user.id)

        if sub.status not in ("active", "suspended", "cancelled"):
            # pending / expired: nothing to push — the MCP servers block on expires_at by themselves.
            return False

        all_ok = True
        blocked = blocked_connectors(db, user.id)
        for key in connectors:
            try:
                if sub.status == "active":
                    upsert_subscription(uid, {
                        "email": user.email,
                        "name": user.name,
                        "plan": _plan_code_for(key, code),
                        "starts_at": _date(sub.start_date),
                        "expires_at": _date(sub.expiry_date),
                        # An admin-disabled connector keeps its record but is suspended there.
                        "status": "suspended" if key in blocked else "active",
                    }, connector=key)
                elif sub.status == "suspended":
                    upsert_subscription(uid, {"status": "suspended"}, connector=key)
                else:
                    revoke(uid, connector=key)
            except Exception as e:  # noqa: BLE001 — one connector being down must not stop the other
                all_ok = False
                logger.error("ITL Bridge AI (%s) sync failed for subscription %s: %s", key, getattr(sub, "id", "?"), e)
        if sub.status == "cancelled" and all_ok:
            clear_connections(db, user.id)
        return all_ok
    except Exception as e:  # noqa: BLE001 — a Bridge outage must never break the caller
        logger.error("ITL Bridge AI sync failed for subscription %s: %s", getattr(sub, "id", "?"), e)
        return False


def resync_all(db) -> dict:
    """Re-sends every active subscription. Idempotent; repairs anything a
    failed hook missed. Latest active subscription per user wins."""
    from app.models.subscription import Subscription

    rows = (
        db.query(Subscription)
        .filter(Subscription.status == "active")
        .order_by(Subscription.user_id, Subscription.expiry_date.desc())
        .all()
    )
    seen: set[int] = set()
    sent = failed = skipped = 0
    for sub in rows:
        if sub.user_id in seen:
            continue
        seen.add(sub.user_id)
        if not resolve_plan_code(
            sub.plan_id, sub.billing_cycle,
            products=product_service.products_of(sub), term_years=product_service.term_years_of(sub),
        ):
            skipped += 1
        elif sync_subscription(db, sub):
            sent += 1
        else:
            failed += 1
    return {"sent": sent, "failed": failed, "skipped": skipped}


async def nightly_resync_loop() -> None:
    """Runs resync_all once a day (~02:30 IST). Both gunicorn workers run
    this; that's harmless because the Bridge call is idempotent."""
    from app.db import SessionLocal

    def _run() -> dict:
        db = SessionLocal()
        try:
            return resync_all(db)
        finally:
            db.close()

    while True:
        now = datetime.utcnow()
        target = now.replace(hour=21, minute=0, second=0, microsecond=0)  # 02:30 IST
        if target <= now:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            result = await asyncio.to_thread(_run)
            logger.info("ITL Bridge AI nightly resync: %s", result)
        except Exception as e:  # noqa: BLE001
            logger.error("ITL Bridge AI nightly resync failed: %s", e)
