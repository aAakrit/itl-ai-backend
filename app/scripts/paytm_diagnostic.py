"""
Standalone Paytm initiateTransaction diagnostic — NOT part of the app.

Run manually, on the server, with the real .env loaded:

    python scripts/paytm_diagnostic.py
    python scripts/paytm_diagnostic.py --amount 1.00
    python scripts/paytm_diagnostic.py --amount 63720.00   # reproduce the exact reported amount

What this deliberately does NOT do:
  * touch the database (no Payment/Subscription rows — safe to run repeatedly)
  * touch pricing_service or the CMS pricing page
  * change any production pricing/config — it only READS the same
    PAYTM_MID / PAYTM_MERCHANT_KEY / PAYTM_WEBSITE / PAYTM_ENV /
    PAYTM_CALLBACK_URL your app already uses via app.config, exactly the
    way the real /payments/initiate route does

It calls the exact same app.services.paytm_service.initiate_transaction
used in production — this is not a reimplementation, so a pass/fail here
is directly meaningful for the real integration.

Order IDs are prefixed "DIAG-" so they're obviously identifiable (and
discardable) in the Paytm dashboard's order list.
"""

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import PAYTM_CALLBACK_URL, PAYTM_ENV, PAYTM_MERCHANT_KEY, PAYTM_MID, PAYTM_WEBSITE  # noqa: E402
from app.services import paytm_service  # noqa: E402


def mask(value: str, keep: int = 4) -> str:
    if not value:
        return "<empty>"
    return "*" * max(0, len(value) - keep) + value[-keep:]


async def main(amount: str):
    print("=" * 70)
    print("Paytm initiateTransaction diagnostic")
    print("=" * 70)

    # --- Config sanity, without ever printing the merchant key -----------
    print(f"PAYTM_ENV        = {PAYTM_ENV!r}")
    print(f"BASE_URL         = {paytm_service.BASE_URL}")
    print(f"PAYTM_MID        = {mask(PAYTM_MID)}")
    print(f"PAYTM_WEBSITE    = {PAYTM_WEBSITE!r}")
    key_len = len(PAYTM_MERCHANT_KEY.strip().encode("utf-8")) if PAYTM_MERCHANT_KEY else 0
    key_len_flag = "OK" if key_len == 16 else "!!! MUST BE EXACTLY 16 — THIS WILL FAIL !!!"
    print(f"PAYTM_MERCHANT_KEY present? {'yes' if PAYTM_MERCHANT_KEY else 'NO — MISSING'} (value never printed)")
    print(f"PAYTM_MERCHANT_KEY length (after stripping whitespace): {key_len} bytes  [{key_len_flag}]")
    print(f"PAYTM_CALLBACK_URL = {PAYTM_CALLBACK_URL!r}")
    print()

    if not PAYTM_MID or not PAYTM_MERCHANT_KEY:
        print("ABORT: PAYTM_MID or PAYTM_MERCHANT_KEY is not set in this environment.")
        return

    order_id = f"DIAG-{uuid.uuid4().hex[:16].upper()}"
    print(f"Using throwaway order_id: {order_id}")
    print(f"Amount: {amount}")
    print()

    try:
        result = await paytm_service.initiate_transaction(
            order_id=order_id,
            amount=amount,
            customer_id="diag-script",
            email="diagnostic@example.com",
            mobile="9999999999",
        )
    except paytm_service.PaytmConfigError as e:
        print("RESULT: PaytmConfigError — a LOCAL config problem, never reached Paytm")
        print(f"  {e}")
        return
    except paytm_service.PaytmGatewayError as e:
        print("RESULT: PaytmGatewayError (transient — gateway unreachable/erroring)")
        print(f"  status_code = {e.status_code}")
        print(f"  body        = {(e.body or '')[:1000]}")
        return
    except paytm_service.PaytmRequestError as e:
        print("RESULT: PaytmRequestError (Paytm's application layer rejected the request)")
        print(f"  status_code = {e.status_code}")
        print(f"  body        = {(e.body or '')[:1000]}")
        return

    body = result.get("body", {}) if isinstance(result, dict) else {}
    result_info = body.get("resultInfo", {}) if isinstance(body, dict) else {}
    result_code = result_info.get("resultCode")

    print("RESULT: HTTP-level success — reached Paytm's application layer")
    print(f"  resultStatus = {result_info.get('resultStatus')}")
    print(f"  resultCode   = {result_code}  ({paytm_service.describe_result_code(result_code)})")
    print(f"  resultMsg    = {result_info.get('resultMsg')}")
    print()
    print("Full response body:")
    print(json.dumps(body, indent=2))

    if result_info.get("resultStatus") == "S" and body.get("txnToken"):
        print()
        print("SUCCESS — txnToken issued. The integration works at this amount;")
        print("if the original ₹63720 attempt still fails, the cause is amount-specific")
        print("(e.g. a staging transaction limit) rather than merchant config.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amount", default="1.00", help="Transaction amount, e.g. 1.00 (default) or 63720.00")
    args = parser.parse_args()
    asyncio.run(main(args.amount))