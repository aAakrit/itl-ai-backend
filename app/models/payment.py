"""
Payment model.

Gateway-agnostic by design: `gateway` distinguishes Paytm vs cash today,
and a new gateway (Razorpay, Stripe, etc.) is just a new value for that
column plus a new service in app/services/ — no schema change needed.
One row per payment attempt, so retries/failures are never lost — a
failed Paytm attempt and its eventual successful retry are two rows,
giving a genuine audit trail rather than overwriting in place.
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Numeric,
    ForeignKey,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.db import Base


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # Nullable: a payment can be initiated before the subscription it will
    # activate exists yet (pending subscription created first, then payment
    # attempted against it — but the FK is still set at creation time in
    # the normal flow; nullable only covers edge cases like an abandoned
    # checkout where no subscription was ever finalized).
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=True, index=True)

    # paytm | cash | complimentary — extensible for future gateways
    gateway = Column(String(30), nullable=False, index=True)

    # pending | success | failed | refunded
    status = Column(String(20), nullable=False, default="pending", index=True)

    # ------------------------------------------------------------------
    # Order / identity
    # ------------------------------------------------------------------
    order_id = Column(String(64), unique=True, nullable=False, index=True)  # our own, sent to Paytm as ORDER_ID
    gateway_order_id = Column(String(100), nullable=True)
    gateway_txn_id = Column(String(100), nullable=True, index=True)
    gateway_response = Column(JSONB, nullable=True)  # raw callback/status payload, for audit + dispute handling

    # ------------------------------------------------------------------
    # Amount breakdown (same snapshot fields as Subscription — a payment
    # can exist without ever successfully creating/activating a
    # subscription, e.g. a failed attempt, so this isn't derived via FK)
    # ------------------------------------------------------------------
    plan_id = Column(String(100), nullable=False)
    plan_name = Column(String(255), nullable=False)
    base_price = Column(Numeric(12, 2), nullable=False)
    gst_rate = Column(Numeric(5, 2), nullable=False, default=18.00)
    gst_amount = Column(Numeric(12, 2), nullable=False)
    payable_amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(10), nullable=False, default="INR")

    # ------------------------------------------------------------------
    # Customer details snapshot (name/GSTIN/address at time of payment —
    # needed on the invoice even if the user later edits their profile)
    # ------------------------------------------------------------------
    customer_name = Column(String(255), nullable=True)
    customer_email = Column(String(255), nullable=True)
    customer_mobile = Column(String(20), nullable=True)
    customer_gstin = Column(String(20), nullable=True)
    customer_address = Column(Text, nullable=True)

    # ------------------------------------------------------------------
    # Invoice / receipt (numbers allocated on success; PDF generation is
    # a separate follow-up — see PaymentService docstring)
    # ------------------------------------------------------------------
    invoice_number = Column(String(50), nullable=True, unique=True)
    receipt_number = Column(String(50), nullable=True, unique=True)

    # Manual/cash payments only
    recorded_by_admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    payment_notes = Column(Text, nullable=True)

    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])
    subscription = relationship("Subscription", back_populates="payments")