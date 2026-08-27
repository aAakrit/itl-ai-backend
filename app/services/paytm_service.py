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

import asyncio
import base64
import hashlib
import hmac
import json
import logging
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

logger = logging.getLogger(__name__)

# Paytm's own staging/production API + JS Checkout hosts. Confirmed against
# current docs (paytmpayments.com/docs/jscheckout-initiate-payment) —
# NOT securegw(-stage).paytm.in, which is the legacy "Standard Checkout"
# host and is documented as deprecated. Using the old host is what produced
# the 503s: requests either never reached the current application layer or
# hit a sunset/redirecting edge.
BASE_URL = "https://secure.paytmpayments.com" if PAYTM_ENV == "production" else "https://securestage.paytmpayments.com"

# Paytm's fixed IV for the checksum's AES-128-CBC step — published in every
# one of their SDKs, not a secret.
_IV = b"@@@@&&&&####$$$$"

# initiateTransaction resultCode -> human meaning, straight from Paytm's
# own docs (paytmpayments.com/docs/jscheckout-initiate-payment). resultMsg
# alone is too generic to act on ("System Error" covers a whole bucket of
# causes) — pairing the numeric code with what it actually means turns the
# next failure into an immediate diagnosis instead of another guess-and-log
# round trip.
RESULT_CODE_MEANINGS = {
    "0000": "Success",
    "0002": "Success (idempotent — already processed)",
    "196": "Amount exceeds the allowed limit",
    "1001": "Request parameters are not valid",
    "1006": "Session has expired",
    "1007": "Missing mandatory element — a required field is absent from the request body",
    "1008": "Pipe character is not allowed in a field value",
    "1009": "Promo code request is not valid",
    "1011": "Invalid promo param",
    "1012": "Promo amount exceeds transaction amount",
    "2004": "SSO token is invalid",
    "2005": "Checksum provided is invalid — signature/key mismatch",
    "2007": "Transaction amount is invalid",
    "2013": "MID in the query param doesn't match the mid in the request body",
    "2014": "orderId in the query param doesn't match the orderId in the request body",
    "2023": "Repeat request is inconsistent with the original",
    "2100": "Link details are not valid",
    "00000900": "System error — Paytm's generic internal failure bucket; often a merchant-account/provisioning issue (MID not enabled for this API, key/environment mismatch, websiteName not recognized for this MID) rather than a request-formatting bug",
    # 501 is NOT documented for initiateTransaction in Paytm's own current
    # docs (paytmpayments.com/docs/api/initiate-transaction-api) — the
    # code exists elsewhere in Paytm's ecosystem with DIFFERENT meanings
    # per API (e.g. "bank declined" in a post-payment transaction-status
    # context, generic "System Error" in a refund-status context), neither
    # of which is safe to assume applies here. Recorded as observed, not
    # as a confirmed meaning — see paytm_service module docs/tests for the
    # investigation that ruled out request construction and checksum as
    # the cause before landing here.
    "501": "Undocumented for initiateTransaction specifically — observed in staging as a generic \"System Error\"; not confirmed to mean checksum, amount, or parameter issues (those have their own distinct codes). Most consistent with a merchant-account/provisioning-side cause.",
}


def describe_result_code(result_code: Optional[str]) -> str:
    if not result_code:
        return "unknown"
    return RESULT_CODE_MEANINGS.get(str(result_code), "undocumented result code")

# HTTP statuses treated as transient/infra-level and safe to retry — a
# narrow set on purpose. 500 is deliberately excluded: in practice a Paytm
# 500 is far more often an application-level rejection of the payload than
# a transient blip, so it's surfaced as a (non-retried) gateway error
# rather than silently retried.
_RETRYABLE_STATUSES = {502, 503, 504}
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = (0.5, 1.5)  # delay before attempt 2, before attempt 3


class PaytmError(Exception):
    """Base for anything that goes wrong talking to Paytm. Carries the raw
    status/body (when available) so callers can log or inspect it without
    parsing exception strings."""

    def __init__(self, message: str, *, status_code: Optional[int] = None, body: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class PaytmGatewayError(PaytmError):
    """Transient — Paytm's gateway itself was unavailable (5xx we retried
    and still failed, a timeout, or a connection error). The request was
    never confirmed accepted OR rejected by Paytm. Safe to retry later
    with a fresh call; the caller should NOT treat this as a declined
    payment."""


class PaytmRequestError(PaytmError):
    """Non-transient — Paytm's application layer responded and explicitly
    rejected the request (4xx, or a 5xx outside the retryable set). Retrying
    the identical request is expected to fail the same way again."""


def _safe_body_preview(response: httpx.Response, limit: int = 2000) -> str:
    """Best-effort text of a response body for logging. Paytm's error
    bodies describe Paytm-side problems (bad mid, bad signature, etc.) —
    they do not echo back the merchant key or other secrets we sent, so
    this is safe to log. Truncated defensively regardless."""
    try:
        text = response.text
    except Exception:
        return "<unreadable body>"
    return text[:limit]


async def _post_with_retry(url: str, *, json_payload: dict, params: Optional[dict] = None) -> dict:
    """POSTs to a Paytm endpoint, retrying a narrow set of transient
    failures with exponential backoff, and returns the parsed JSON body on
    success.

    Retrying is safe here specifically because every call site passes the
    *same* orderId on every attempt (generated once, before this is ever
    called) and Paytm's initiateTransaction / order-status APIs are
    idempotent per orderId at this stage — no money moves and no duplicate
    order is created by calling them again with an orderId that hasn't
    produced a completed transaction yet.
    """

    last_error: Optional[PaytmError] = None

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, params=params, json=json_payload)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_error = PaytmGatewayError(f"Network error calling Paytm: {e}")
            logger.warning("Paytm request network error (attempt %s/%s): %s — %s", attempt, _MAX_ATTEMPTS, url, e)
        else:
            if response.status_code < 400:
                try:
                    return response.json()
                except ValueError:
                    # 2xx with an unparseable body — Paytm's application
                    # layer responded but not with anything we can use.
                    # Not something a retry fixes.
                    body = _safe_body_preview(response)
                    logger.error("Paytm returned %s with a malformed body — %s: %s", response.status_code, url, body)
                    raise PaytmGatewayError(
                        "Paytm returned an unreadable response.",
                        status_code=response.status_code,
                        body=body,
                    )

            body = _safe_body_preview(response)
            logger.warning("Paytm HTTP status: %s | url: %s | response body: %s", response.status_code, url, body)

            if response.status_code in _RETRYABLE_STATUSES:
                last_error = PaytmGatewayError(
                    f"Paytm gateway returned {response.status_code}.",
                    status_code=response.status_code,
                    body=body,
                )
            else:
                # A definitive answer from Paytm's application layer —
                # retrying the same payload will not change it.
                raise PaytmRequestError(
                    f"Paytm rejected the request ({response.status_code}).",
                    status_code=response.status_code,
                    body=body,
                )

        if attempt < _MAX_ATTEMPTS:
            await asyncio.sleep(_BACKOFF_SECONDS[attempt - 1])

    # Retries exhausted — still only a transient/gateway problem, never
    # escalated to "rejected".
    raise last_error or PaytmGatewayError("Paytm gateway unavailable after retries.")


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
    """Sorted-by-key, pipe-joined VALUES — the classic flat-form checksum
    input, used for the callback Paytm posts to callbackUrl.

    Matches Paytm's own reference getStringByParams exactly: a null/missing
    value becomes an empty string IN PLACE, not a skipped entry. Skipping
    would shift every value after it by one position in the pipe-joined
    string, producing a completely different (and wrong) string the moment
    any field is null — which silently breaks verification for any
    callback that happens to have one."""
    ordered = dict(sorted(params.items()))
    return "|".join(
        "" if v is None or str(v).lower() == "null" else str(v)
        for v in ordered.values()
    )


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

    Raises PaytmGatewayError for transient failures (retried internally
    first) or PaytmRequestError if Paytm's application layer explicitly
    rejected the request — see _post_with_retry's docstring for why
    retrying with this same order_id is safe.
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

    return await _post_with_retry(
        f"{BASE_URL}/theia/api/v1/initiateTransaction",
        json_payload=payload,
        params={"mid": PAYTM_MID, "orderId": order_id},
    )


def checkout_script_url() -> str:
    """The JS Checkout SDK script — current recommended integration
    (paytmpayments.com/docs/jscheckout-invoke-payment). Renders an iframe
    on the merchant's own page rather than redirecting to a Paytm-hosted
    page; the deprecated `showPaymentPage` full-page redirect this used to
    point at is no longer the recommended flow."""
    return f"{BASE_URL}/merchantpgpui/checkoutjs/merchants/{PAYTM_MID}.js"


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
    """POST /v3/order/status — the authoritative check. Retries transient
    failures the same as initiate_transaction; this is a read-only check
    so retrying is unambiguously safe."""

    body = {"mid": PAYTM_MID, "orderId": order_id}
    body_json = json.dumps(body, separators=(",", ":"))
    checksum = _generate_signature_by_string(body_json, PAYTM_MERCHANT_KEY)
    payload = {"body": body, "head": {"signature": checksum}}

    return await _post_with_retry(f"{BASE_URL}/v3/order/status", json_payload=payload)
