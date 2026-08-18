"""
Paytm integration.

Credentials come from environment variables only (see app/config.py
additions) — never hardcoded, never committed.

SECURITY: the callback (`/payments/paytm/callback`) is NEVER trusted on
its own. Every callback triggers an explicit server-to-server call to
Paytm's Transaction Status API before a subscription is activated — a
forged or replayed callback cannot activate anything by itself.

Implements Paytm's AES-based checksum scheme directly using `cryptography`
(already a common transitive dependency, added explicitly to
requirements.txt) rather than the unmaintained `paytmchecksum` PyPI
package, which has had no recent release and depends on the abandoned
`pycrypto`.
"""

import base64
import hmac
import uuid
from typing import Any

import httpx

from app.config import (
    PAYTM_MID,
    PAYTM_MERCHANT_KEY,
    PAYTM_WEBSITE,
    PAYTM_CALLBACK_URL,
    PAYTM_ENV,
)

# Paytm's own staging/production API hosts.
_BASE_URL = "https://securegw.paytm.in" if PAYTM_ENV == "production" else "https://securegw-stage.paytm.in"


# =============================================================================
# Checksum
# =============================================================================

def _generate_checksum(params: dict[str, Any], key: str) -> str:
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    ordered = "|".join(str(v) for _, v in sorted(params.items())) + "|" + uuid.uuid4().hex[:4]
    iv = b"@@@@&&&&####$$$$"[:16]
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(ordered.encode("utf-8")) + padder.finalize()
    cipher = Cipher(algorithms.AES(key.encode("utf-8")[:16].ljust(16, b"0")), modes.CBC(iv))
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(encrypted).decode("utf-8")


def _verify_checksum(params: dict[str, Any], key: str, checksum: str) -> bool:
    """
    Constant-time comparison against a freshly computed checksum of the
    same params — used on the callback before we even bother calling the
    Status API, so a tampered callback is rejected immediately.
    """
    try:
        expected = _generate_checksum(params, key)
    except Exception:
        return False
    return hmac.compare_digest(expected, checksum)


# =============================================================================
# Initiate Transaction
# =============================================================================

def _flatten_for_checksum(body: dict) -> dict:
    """Paytm's checksum is computed over top-level scalar fields only — nested dicts excluded."""
    return {k: v for k, v in body.items() if isinstance(v, (str, int, float))}


async def initiate_transaction(
    *,
    order_id: str,
    amount: str,
    customer_id: str,
    email: str | None = None,
    mobile: str | None = None,
) -> dict:
    """
    POST /theia/api/v1/initiateTransaction — returns Paytm's txnToken,
    which the frontend uses to open Paytm's checkout for this order.
    """

    body = {
        "requestType": "Payment",
        "mid": PAYTM_MID,
        "websiteName": PAYTM_WEBSITE,
        "orderId": order_id,
        "callbackUrl": PAYTM_CALLBACK_URL,
        "txnAmount": {"value": amount, "currency": "INR"},
        "userInfo": {
            "custId": customer_id,
            **({"email": email} if email else {}),
            **({"mobile": mobile} if mobile else {}),
        },
    }

    checksum = _generate_checksum(_flatten_for_checksum(body), PAYTM_MERCHANT_KEY)
    payload = {"body": body, "head": {"signature": checksum}}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{_BASE_URL}/theia/api/v1/initiateTransaction",
            params={"mid": PAYTM_MID, "orderId": order_id},
            json=payload,
        )
        response.raise_for_status()
        return response.json()


# =============================================================================
# Callback verification
# =============================================================================

def verify_callback_checksum(callback_params: dict[str, Any]) -> bool:
    params = {k: v for k, v in callback_params.items() if k != "CHECKSUMHASH"}
    checksum = callback_params.get("CHECKSUMHASH", "")
    return _verify_checksum(params, PAYTM_MERCHANT_KEY, checksum)


# =============================================================================
# Transaction Status (the source of truth — always called, callback alone
# is never sufficient to activate a subscription)
# =============================================================================

async def verify_transaction_status(order_id: str) -> dict:
    """POST /v3/order/status — the authoritative check."""

    body = {"mid": PAYTM_MID, "orderId": order_id}
    checksum = _generate_checksum(body, PAYTM_MERCHANT_KEY)
    payload = {"body": body, "head": {"signature": checksum}}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{_BASE_URL}/v3/order/status", json=payload)
        response.raise_for_status()
        return response.json()