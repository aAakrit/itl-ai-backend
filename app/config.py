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

# Paytm — credentials only from env, never hardcoded.
PAYTM_MID = os.getenv("PAYTM_MID", "")
PAYTM_MERCHANT_KEY = os.getenv("PAYTM_MERCHANT_KEY", "")
PAYTM_WEBSITE = os.getenv("PAYTM_WEBSITE", "WEBSTAGING")
PAYTM_CALLBACK_URL = os.getenv("PAYTM_CALLBACK_URL", "")
PAYTM_ENV = os.getenv("PAYTM_ENV", "staging").lower()