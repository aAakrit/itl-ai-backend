"""
Coupons (created by admins) and their redemptions.

A redemption row is written as "reserved" when a checkout starts, turns
"redeemed" when the payment succeeds, and "released" when the attempt fails or
is superseded. Usage limits count redeemed rows plus reservations whose payment
is still pending — see coupon_service.
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.db import Base


class Coupon(Base):
    __tablename__ = "coupons"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(40), unique=True, nullable=False, index=True)  # stored upper-case
    description = Column(Text, nullable=True)

    discount_type = Column(String(10), nullable=False)  # percent | flat
    value = Column(Numeric(12, 2), nullable=False)
    max_discount = Column(Numeric(12, 2), nullable=True)  # cap for percent coupons

    valid_from = Column(DateTime, nullable=True)
    valid_to = Column(DateTime, nullable=True)

    total_limit = Column(Integer, nullable=True)     # null = unlimited
    per_user_limit = Column(Integer, nullable=True)  # null = unlimited

    # List of pricing plan ids this coupon works on; null = every plan.
    plan_ids = Column(JSONB, nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)

    created_by_admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CouponRedemption(Base):
    __tablename__ = "coupon_redemptions"

    id = Column(Integer, primary_key=True, index=True)
    coupon_id = Column(Integer, ForeignKey("coupons.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=False, unique=True)
    discount_amount = Column(Numeric(12, 2), nullable=False)

    # reserved | redeemed | released
    status = Column(String(10), nullable=False, default="reserved", index=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
