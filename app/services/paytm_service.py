"""
Paytm integration.

Credentials come from environment variables only (see app/config.py
additions) — never hardcoded, never committed.

SECURITY: the callback (`/payments/paytm/callback`) is NEVER trusted on
its own. Every callback triggers an explicit server-to-server call to
Paytm's Transaction Status API before a subscription is activated — a
forged or replayed callback cannot activate anything by itself.

CHECKSUM ALGORITHM
-------------------
Paytm's checksum is NOT a plain HMAC. It's:

    salt        = 4 random alphanumeric characters
    hashInput   = "<data>|<salt>"
    hashHex     = sha256(hashInput).hexdigest()
    signature   = AES-128-CBC(PKCS7, IV="@@@@&&&&####$$$$") of (hashHex + salt),
                  base64-encoded, using the merchant key as the AES key

Verifying means decrypting the checksum to recover the salt Paytm used —
you cannot "regenerate and compare" like an HMAC, because every fresh
checksum embeds a *new* random salt and will never equal an old one.

Two different `<data>` shapes are used depending on the API generation:
  * JSON-body APIs (initiateTransaction, order/status): `<data>` is the
    exact JSON string of the request body — Paytm's own Node SDK calls
    this `generateSignature(JSON.stringify(body), key)`.
  * The classic flat-form callback Paytm POSTs to callbackUrl: `<data>`
    is every field except CHECKSUMHASH, sorted by key, values pipe-joined
    (nulls skipped) — the `generateSignature(paramsDict, key)` variant.

Implemented directly (via `cryptography`) rather than the unmaintained
`paytmchecksum` PyPI package, which has had no recent release and
depends on the abandoned `pycrypto`.
"""

import base64
import hashlib
import hmac
import json
import random
import string
from typing import Any, Optional

import httpx

from app.config import (
    PAYTM_MID,
    PAYTM_MERCHANT_KEY,
    PAYTM_WEBSITE,
    PAYTM_CALLBACK_URL,
    PAYTM_ENV,
)

# Paytm's own staging/production API hosts.
BASE_URL = "https://securegw.paytm.in" if PAYTM_ENV == "production" else "https://securegw-stage.paytm.in"

# Paytm's fixed IV for the checksum's AES-128-CBC step — published in every
# one of their SDKs, not a secret.
_IV = b"@@@@&&&&####$$$$"


# =============================================================================
# Checksum primitives
# =============================================================================

def _key_bytes(key: str) -> bytes:
    # Paytm merchant keys are 16 bytes; normalize defensively just in case.
    return key.encode("utf-8")[:16].ljust(16, b"0")


def _aes_encrypt(plaintext: str, key: str) -> str:
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()
    cipher = Cipher(algorithms.AES(_key_bytes(key)), modes.CBC(_IV))
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(encrypted).decode("utf-8")


def _aes_decrypt(ciphertext_b64: str, key: str) -> str:
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    encrypted = base64.b64decode(ciphertext_b64)
    cipher = Cipher(algorithms.AES(_key_bytes(key)), modes.CBC(_IV))
    decryptor = cipher.decryptor()
    padded = decryptor.update(encrypted) + decryptor.finalize()
    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode("utf-8")


def _random_salt(length: int = 4) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.SystemRandom().choice(alphabet) for _ in range(length))


def _generate_signature_by_string(data: str, key: str) -> str:
    """For JSON-body APIs — Paytm's SDKs call this generateSignature(JSON.stringify(body), key)."""
    salt = _random_salt()
    hash_hex = hashlib.sha256(f"{data}|{salt}".encode("utf-8")).hexdigest()
    return _aes_encrypt(hash_hex + salt, key)


def _params_to_string(params: dict[str, Any]) -> str:
    """Sorted-by-key, pipe-joined VALUES — the classic flat-form checksum input."""
    ordered = dict(sorted(params.items()))
    return "|".join(str(v) for v in ordered.values() if v is not None and v != "null")


def _verify_signature_by_params(params: dict[str, Any], key: str, checksum: str) -> bool:
    """Decrypts the checksum to recover the salt Paytm used, recomputes the
    hash with that salt, and compares. A freshly generated checksum can
    never be compared directly — see module docstring."""
    try:
        decrypted = _aes_decrypt(checksum, key)
    except Exception:
        return False
    if len(decrypted) < 4:
        return False
    salt, expected_hash = decrypted[-4:], decrypted[:-4]
    data = _params_to_string(params)
    actual_hash = hashlib.sha256(f"{data}|{salt}".encode("utf-8")).hexdigest()
    return hmac.compare_digest(actual_hash, expected_hash)


# =============================================================================
# Initiate Transaction
# =============================================================================

async def initiate_transaction(
    *,
    order_id: str,
    amount: str,
    customer_id: str,
    email: Optional[str] = None,
    mobile: Optional[str] = None,
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

    body_json = json.dumps(body, separators=(",", ":"))
    checksum = _generate_signature_by_string(body_json, PAYTM_MERCHANT_KEY)
    payload = {"body": body, "head": {"signature": checksum}}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{BASE_URL}/theia/api/v1/initiateTransaction",
            params={"mid": PAYTM_MID, "orderId": order_id},
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def checkout_url(order_id: str) -> str:
    """Full-page hosted checkout — the frontend auto-submits a form
    (mid, orderId, txnToken) as a POST to this URL."""
    return f"{BASE_URL}/theia/api/v1/showPaymentPage?mid={PAYTM_MID}&orderId={order_id}"


# =============================================================================
# Callback verification
# =============================================================================

def verify_callback_checksum(callback_params: dict[str, Any]) -> bool:
    params = {k: v for k, v in callback_params.items() if k != "CHECKSUMHASH"}
    checksum = callback_params.get("CHECKSUMHASH", "")
    if not checksum:
        return False
    return _verify_signature_by_params(params, PAYTM_MERCHANT_KEY, checksum)


# =============================================================================
# Transaction Status (the source of truth — always called, callback alone
# is never sufficient to activate a subscription)
# =============================================================================

async def verify_transaction_status(order_id: str) -> dict:
    """POST /v3/order/status — the authoritative check."""

    body = {"mid": PAYTM_MID, "orderId": order_id}
    body_json = json.dumps(body, separators=(",", ":"))
    checksum = _generate_signature_by_string(body_json, PAYTM_MERCHANT_KEY)
    payload = {"body": body, "head": {"signature": checksum}}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{BASE_URL}/v3/order/status", json=payload)
        response.raise_for_status()
        return response.json()
