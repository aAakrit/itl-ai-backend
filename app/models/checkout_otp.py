"""One-time e-mail codes that prove mailbox ownership at checkout (separate from password-reset codes)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from app.db import Base


class CheckoutOtp(Base):
    __tablename__ = "checkout_otps"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, index=True)  # lower-cased
    code_hash = Column(String, nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
