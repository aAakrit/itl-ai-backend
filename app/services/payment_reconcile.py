"""
Payment reconciliation — the safety net behind Paytm checkout.

A subscription is only ever activated by finalize_paytm_payment(), which runs
after a server-to-server Transaction Status call. Normally that is triggered
by the browser (return page / checkout handlers). But a browser can close, lose
connection or never receive Paytm's in-page event after the customer has really
paid — and then nothing would ever activate the plan.

This module asks Paytm about payments still "pending", so a paid order is
confirmed (and the subscription activated) even if the browser never reported
back:

  * reconcile_pending()      — one pass, optionally for a single user
  * payment_reconcile_loop() — runs it in the background every minute
                               (recent orders every minute, older ones every
                               15 minutes, nothing older than 24 hours)
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from app.models.payment import Payment
from app.services import payment_service, paytm_service

logger = logging.getLogger(__name__)

MAX_AGE = timedelta(hours=24)
RECENT = timedelta(minutes=30)
OLD_EVERY_N_CYCLES = 15
CYCLE_SECONDS = 60
BATCH = 50


async def reconcile_pending(
    db,
    *,
    user_id: Optional[int] = None,
    include_older: bool = True,
) -> dict:
    """Checks pending Paytm payments with Paytm's Transaction Status API.
    Returns {"checked": n, "confirmed": [order_id, ...]}."""

    now = datetime.utcnow()
    query = db.query(Payment).filter(
        Payment.gateway == "paytm",
        Payment.status == "pending",
        Payment.created_at >= now - MAX_AGE,
    )
    if user_id is not None:
        query = query.filter(Payment.user_id == user_id)
    if not include_older:
        query = query.filter(Payment.created_at >= now - RECENT)

    orders = [
        p.order_id
        for p in query.order_by(Payment.id.desc()).limit(BATCH).all()
        # Only orders whose initiateTransaction succeeded can ever be paid.
        if (p.gateway_response or {}).get("txn_token")
    ]

    confirmed: list[str] = []
    for order_id in orders:
        try:
            status_response = await paytm_service.verify_transaction_status(order_id)
        except paytm_service.PaytmError as exc:
            logger.warning("Reconcile: status check failed for %s: %s", order_id, exc)
            continue
        except Exception:
            logger.exception("Reconcile: unexpected error checking %s", order_id)
            continue

        try:
            payment = payment_service.finalize_paytm_payment(db, order_id, status_response)
        except Exception:
            db.rollback()
            logger.exception("Reconcile: could not finalize %s", order_id)
            continue

        if payment.status == "success":
            confirmed.append(order_id)
            logger.info("Reconcile: payment %s confirmed with Paytm — subscription activated", order_id)

    return {"checked": len(orders), "confirmed": confirmed}


async def payment_reconcile_loop() -> None:
    from app.db import SessionLocal

    cycle = 0
    while True:
        await asyncio.sleep(CYCLE_SECONDS)
        cycle += 1
        db = SessionLocal()
        try:
            await reconcile_pending(db, include_older=(cycle % OLD_EVERY_N_CYCLES == 0))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Payment reconcile cycle failed")
        finally:
            db.close()
