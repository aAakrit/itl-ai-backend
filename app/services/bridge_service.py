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

from app.config import (
    BRIDGE_ADMIN_KEY,
    BRIDGE_API_URL,
    BRIDGE_HANDOFF_SECRET,
    BRIDGE_PLAN_MAP,
    BRIDGE_USER_PREFIX,
)

logger = logging.getLogger(__name__)

RETURN_PREFIX = "https://mcp.incometaxlibrary.com/bridge/return"
BRIDGE_PLAN_CODES = {"bridge_yearly", "bridge_3year", "bundle_yearly", "bundle_3year"}
REQUEST_TIMEOUT = 10.0


class BridgeError(Exception):
    def __init__(self, message: str, status: int = 502, data: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.data = data or {}


def is_configured() -> bool:
    return bool(BRIDGE_ADMIN_KEY and BRIDGE_HANDOFF_SECRET)


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

def safe_return_url(return_url: Optional[str]) -> str:
    """Only ever redirect back to our own MCP server."""
    return return_url if return_url and return_url.startswith(RETURN_PREFIX) else RETURN_PREFIX


def _with_params(url: str, **params: str) -> str:
    return str(httpx.URL(url).copy_merge_params(params))


def allow_redirect_url(txn: str, return_url: Optional[str], user_id: int, email: str = "", name: str = "") -> str:
    if not BRIDGE_HANDOFF_SECRET:
        raise BridgeError("ITL Bridge AI is not configured.", 503)
    now = datetime.utcnow()
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
        BRIDGE_HANDOFF_SECRET,
        algorithm="HS256",
    )
    return _with_params(safe_return_url(return_url), txn=txn, token=token)


def deny_redirect_url(txn: str, return_url: Optional[str]) -> str:
    return _with_params(safe_return_url(return_url), txn=txn, error="access_denied")


# ── Website -> MCP server API ───────────────────────────────────────────

def _api(method: str, path: str, body: Optional[dict] = None, params: Optional[dict] = None) -> dict:
    if not is_configured():
        raise BridgeError("ITL Bridge AI is not configured.", 503)
    try:
        res = httpx.request(
            method,
            BRIDGE_API_URL + path,
            json=body,
            params=params,
            headers={"X-Bridge-Key": BRIDGE_ADMIN_KEY},
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


def upsert_subscription(user_id: str, sub: dict) -> dict:
    return _api("PUT", f"/subscriptions/{_q(user_id)}", sub)


def get_status(user_id: str) -> dict:
    return _api("GET", f"/subscriptions/{_q(user_id)}")


def revoke(user_id: str) -> dict:
    return _api("POST", f"/subscriptions/{_q(user_id)}/revoke")


def get_connect_links() -> dict:
    return _api("GET", "/connect-links")


def get_plans() -> list:
    return _api("GET", "/plans").get("plans", [])


def set_plan_limits(plan: str, daily_searches: Optional[int], daily_documents: Optional[int]) -> dict:
    return _api("PUT", f"/plans/{_q(plan)}", {"daily_limit": daily_searches, "daily_doc_limit": daily_documents})


def set_user_limits(user_id: str, daily_searches: Optional[int], daily_documents: Optional[int]) -> dict:
    return _api(
        "PUT",
        f"/subscriptions/{_q(user_id)}/limits",
        {"daily_limit": daily_searches, "daily_doc_limit": daily_documents},
    )


def list_subscriptions(q: str = "", status: str = "", limit: int = 50, offset: int = 0) -> dict:
    return _api("GET", "/subscriptions", params={"q": q, "status": status, "limit": limit, "offset": offset})


def get_stats() -> dict:
    return _api("GET", "/stats")


# ── Subscription sync (payment hooks) ───────────────────────────────────

def resolve_plan_code(plan_id: Optional[str], billing_cycle: Optional[str]) -> Optional[str]:
    """Maps one of this app's pricing plans to a Bridge plan code, or None
    when that plan doesn't include ITL Bridge AI."""
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


def sync_subscription(db, sub) -> bool:
    """Pushes a website Subscription to the MCP server. Safe to call after
    every change — returns True when a call was made and succeeded, False
    when skipped or failed; never raises."""
    try:
        if not is_configured() or sub is None:
            return False

        code = resolve_plan_code(sub.plan_id, sub.billing_cycle)
        if not code:
            return False

        from app.models.user import User  # local import: avoids a cycle at import time

        user = db.query(User).filter(User.id == sub.user_id).first()
        if not user:
            return False
        uid = user_key(user.id)

        if sub.status == "active":
            upsert_subscription(uid, {
                "email": user.email,
                "name": user.name,
                "plan": code,
                "starts_at": _date(sub.start_date),
                "expires_at": _date(sub.expiry_date),
                "status": "active",
            })
        elif sub.status == "suspended":
            upsert_subscription(uid, {"status": "suspended"})
        elif sub.status == "cancelled":
            revoke(uid)
        else:
            # pending / expired: nothing to push — the MCP server blocks on
            # expires_at by itself.
            return False
        return True
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
        if not resolve_plan_code(sub.plan_id, sub.billing_cycle):
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
