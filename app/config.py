import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

SECRET_KEY = os.getenv("SECRET_KEY")

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 8000))

APP_ENV = os.getenv("APP_ENV", "development")
DEBUG = os.getenv("DEBUG", "False").lower() == "true"

AI_MAIN_URL = os.getenv("AI_MAIN_URL")
AI_PREMIUM_URL = os.getenv("AI_PREMIUM_URL")
AI_FREE_URL = os.getenv("AI_FREE_URL")
AI_NOTICE_URL = os.getenv("AI_NOTICE_URL")
AI_SUMMARIZER_URL = os.getenv("AI_SUMMARIZER_URL")
AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", 180))

# Income Tax services (module "income-tax"). Optional: a module only switches
# to the IT service when its URL is set, otherwise it keeps using the GST
# service exactly as before.
#   AI_IT_ASK_URL      IT Ask Bot            e.g. http://localhost:5033
#   AI_IT_CASELAW_URL  IT Case Law Research  e.g. http://localhost:5034
AI_IT_ASK_URL = os.getenv("AI_IT_ASK_URL") or None
AI_IT_CASELAW_URL = os.getenv("AI_IT_CASELAW_URL") or None

# Streamed research (SSE): max seconds of silence from the AI service before
# the stream is treated as dead. The service sends a keep-alive every ~15 s.
AI_STREAM_READ_TIMEOUT = int(os.getenv("AI_STREAM_READ_TIMEOUT", 90))

# Stream the GST Ask Bot too? Off by default: the stream endpoint is a v1-style
# call, while GST conversations get their memory from vendor v2 sessions, so
# streaming could drop earlier-turn context there. The Income Tax Ask Bot takes
# `history` directly, so it always streams (when its URL is configured).
AI_STREAM_GST = os.getenv("AI_STREAM_GST", "false").lower() == "true"
AI_RENDER_MARKDOWN = (
    os.getenv("AI_RENDER_MARKDOWN", "true").lower() == "true"
)


PAYTM_MID = os.getenv("PAYTM_MID", "")
PAYTM_MERCHANT_KEY = os.getenv("PAYTM_MERCHANT_KEY", "")
PAYTM_CALLBACK_URL = os.getenv("PAYTM_CALLBACK_URL", "")
PAYTM_ENV = os.getenv("PAYTM_ENV", "staging").lower()
PAYTM_WEBSITE = os.getenv("PAYTM_WEBSITE") or ("DEFAULT" if PAYTM_ENV == "production" else "WEBSTAGING")

# Optional override of Paytm's API / checkout-script host, e.g. the legacy
# "https://securegw.paytm.in" that the previous (working) ITL site used in
# production. Leave empty to use the current default for PAYTM_ENV.
PAYTM_BASE_URL = os.getenv("PAYTM_BASE_URL", "").strip().rstrip("/")

# Where the Paytm callback route redirects the browser back to once a
# payment is finalized — the frontend's own return/receipt page.
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://www.incometaxlibrary.in/")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "info.incometaxlibrary@gmail.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
EMAIL_FROM = os.getenv("EMAIL_FROM", "info.incometaxlibrary@gmail.com")
EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "Income Tax Library")


# ITL Bridge AI (MCP server) — see app/services/bridge_service.py
BRIDGE_API_URL = os.getenv("BRIDGE_API_URL", "https://mcp.incometaxlibrary.com/bridge/api").rstrip("/")
BRIDGE_ADMIN_KEY = os.getenv("BRIDGE_ADMIN_KEY", "")
BRIDGE_HANDOFF_SECRET = os.getenv("BRIDGE_HANDOFF_SECRET", "")
# Bridge user ids must be unique across both ITL websites: "com:<id>" for
# incometaxlibrary.com users, "in:<id>" for incometaxlibrary.in users.
BRIDGE_USER_PREFIX = os.getenv("BRIDGE_USER_PREFIX", "in")
# JSON object mapping this app's pricing plan -> Bridge plan code, e.g.
# {"pro:yearly": "bridge_yearly", "enterprise": "bundle_yearly"}. Keys are
# "<plan_id>:<billing_cycle>" (checked first) or just "<plan_id>". A plan
# that is not mapped (and is not itself a Bridge plan code) is not synced.
BRIDGE_PLAN_MAP = os.getenv("BRIDGE_PLAN_MAP", "{}")


# ---------------------------------------------------------------------------
# Billing / checkout
# ---------------------------------------------------------------------------
# Seller details printed on every bill (tax invoice / proforma).
SELLER_NAME = os.getenv("SELLER_NAME", "Income Tax Library")
SELLER_ADDRESS = os.getenv("SELLER_ADDRESS", "141, Alkapuri Niwaru Road Jhotwara, Jaipur 302012 Rajasthan.")
SELLER_EMAIL = os.getenv("SELLER_EMAIL", "info@incometaxlibrary.com")
SELLER_WEBSITE = os.getenv("SELLER_WEBSITE", "www.incometaxlibrary.in")
SELLER_PHONE = os.getenv("SELLER_PHONE", "09001597011")
SELLER_GSTIN = os.getenv("SELLER_GSTIN", "08ALNPB6217G1Z7")
# Customers in this state get CGST + SGST; everyone else gets IGST.
SELLER_STATE = os.getenv("SELLER_STATE", "Rajasthan")
# HSN / SAC printed against the subscription line.
SUBSCRIPTION_HSN = os.getenv("SUBSCRIPTION_HSN", "998439")

# Every successful payment (online or cash) is e-mailed here so the account can be approved.
PAYMENT_ALERT_EMAIL = os.getenv("PAYMENT_ALERT_EMAIL", "bhaawani.singh@gmail.com")

# A salesman may discount a plan by at most this much on the public checkout.
# Anything deeper is done by an admin (Admin > Bills / cash payment).
MAX_SALESMAN_DISCOUNT_PCT = int(os.getenv("MAX_SALESMAN_DISCOUNT_PCT", 50))

CHECKOUT_TOKEN_MINUTES = int(os.getenv("CHECKOUT_TOKEN_MINUTES", 60))
CHECKOUT_OTP_TTL_MINUTES = int(os.getenv("CHECKOUT_OTP_TTL_MINUTES", 10))


# ITL Bridge AI — the Income Tax connector (second MCP server, own host, own subscriptions).
# It uses the SAME hand-off secret as the GST connector but its OWN admin key.
BRIDGE_IT_API_URL = os.getenv("BRIDGE_IT_API_URL", "https://mcp-it.incometaxlibrary.com/bridge/api").rstrip("/")
BRIDGE_IT_ADMIN_KEY = os.getenv("BRIDGE_IT_ADMIN_KEY", "")
BRIDGE_IT_HANDOFF_SECRET = os.getenv("BRIDGE_IT_HANDOFF_SECRET", "") or BRIDGE_HANDOFF_SECRET
BRIDGE_IT_RETURN_URL = os.getenv("BRIDGE_IT_RETURN_URL", "https://mcp-it.incometaxlibrary.com/bridge/return")
# Optional JSON {"bundle_yearly": "<IT plan code>", ...} if the IT server names its plans differently.
# Anything not listed is sent with the same plan code as the GST connector.
BRIDGE_IT_PLAN_MAP = os.getenv("BRIDGE_IT_PLAN_MAP", "{}")
