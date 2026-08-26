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
AI_RENDER_MARKDOWN = (
    os.getenv("AI_RENDER_MARKDOWN", "true").lower() == "true"
)


PAYTM_MID = os.getenv("PAYTM_MID", "")
PAYTM_MERCHANT_KEY = os.getenv("PAYTM_MERCHANT_KEY", "")
PAYTM_WEBSITE = os.getenv("PAYTM_WEBSITE", "WEBSTAGING")
PAYTM_CALLBACK_URL = os.getenv("PAYTM_CALLBACK_URL", "")
PAYTM_ENV = os.getenv("PAYTM_ENV", "staging").lower()

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