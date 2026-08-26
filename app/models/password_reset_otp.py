from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String

from app.db import Base


class PasswordResetOtp(Base):
    """
    A 6-digit code emailed to the user for the forgot-password flow.
    Short-lived (see OTP_TTL_MINUTES in auth.py) and single-use — `consumed_at`
    is set the moment it's successfully verified so it can't be replayed.
    """

    __tablename__ = "password_reset_otps"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)

    code_hash = Column(String, nullable=False)  # hashed, never stored/logged in plaintext
    attempts = Column(Integer, default=0, nullable=False)

    verified_at = Column(DateTime, nullable=True)
    consumed_at = Column(DateTime, nullable=True)

    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
