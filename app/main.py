from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import ORJSONResponse

from app.db import Base, engine

# Import models so SQLAlchemy registers them
from app.models.user import User
from app.models.session import AuthSession
from app.models.subscription import Subscription
from app.models.payment import Payment
from app.models.ai_usage import AIUsageLimit
from app.models.audit_log import AuditLog
from app.models.password_reset_otp import PasswordResetOtp
from app.models.notification import Notification

# Routes
from app.routes.auth import router as auth_router
from app.routes.cms_page import router as cms_page_router
from app.routes.admin_user import router as admin_user
from app.routes.books import router as admin_books
from app.routes.ai import router as ai_router
from app.routes.subscription import router as admin_subscription_router
from app.routes.payment import router as admin_payment_router
from app.routes.payment import checkout_router as payment_checkout_router
from app.routes.notification import router as admin_notification_router
from app.routes.admin_logs import router as admin_logs_router
from app.models.ai import (
    AIConversation,
    AIProviderSession,
    AIMessage,
    AIAttachment,
    AIFeedback,
)

# Exception Handlers
from app.core.exception_handlers import register_exception_handlers

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="ITL AI Backend",
    version="1.0.0",
    default_response_class=ORJSONResponse,
)

register_exception_handlers(app)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
        "http://162.219.30.161:8080",
        "https://www.incometaxlibrary.in",
        "https://incometaxlibrary.in",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip
app.add_middleware(
    GZipMiddleware,
    minimum_size=1000,
)


@app.get("/")
def root():
    return {
        "message": "ITL AI Backend Running"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }


app.include_router(auth_router)
app.include_router(cms_page_router)
app.include_router(admin_user)
app.include_router(admin_books)
app.include_router(ai_router)
app.include_router(admin_subscription_router)
app.include_router(admin_payment_router)
app.include_router(payment_checkout_router)
app.include_router(admin_notification_router)
app.include_router(admin_logs_router)
