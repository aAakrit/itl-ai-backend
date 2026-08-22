from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


# =============================================================================
# Subscription
# =============================================================================

class SubscriptionCreateManual(BaseModel):
    """
    Admin-created subscription — complimentary, offline/cash renewal, or a
    manual correction. Pricing is still read from the live CMS pricing page
    at creation time (so the snapshot is accurate) unless `override_price`
    is given for a complimentary/discounted grant.
    """

    user_id: int
    plan_id: str = Field(..., description="Matches a CMS pricingPlans[].id")
    billing_cycle: str = Field("monthly", regex="^(monthly|yearly)$")

    source: str = Field("manual", regex="^(manual|complimentary)$")

    # Optional overrides — if omitted, computed from CMS price + 18% GST.
    override_base_price: Optional[Decimal] = None
    override_start_date: Optional[datetime] = None
    override_expiry_date: Optional[datetime] = None

    notes: Optional[str] = None


class SubscriptionUpdate(BaseModel):
    """Admin edits to an existing subscription — every field optional/partial."""

    plan_id: Optional[str] = None
    billing_cycle: Optional[str] = Field(None, regex="^(monthly|yearly)$")
    status: Optional[str] = Field(None, regex="^(pending|active|suspended|cancelled|expired)$")
    start_date: Optional[datetime] = None
    expiry_date: Optional[datetime] = None
    renewal_date: Optional[datetime] = None
    auto_renew: Optional[bool] = None
    notes: Optional[str] = None
    reason: Optional[str] = Field(None, description="Required for the audit log entry on this change.")


class SubscriptionExtend(BaseModel):
    days: int = Field(..., gt=0, le=3650)
    reason: Optional[str] = None


class SubscriptionResponse(BaseModel):
    class Config:
        orm_mode = True

    id: int
    user_id: int
    # Populated by the route from sub.user — not a Subscription column, so
    # these stay None if that transient attribute was never set.
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    plan_id: str
    plan_name: str
    billing_cycle: str
    base_price: Decimal
    gst_rate: Decimal
    gst_amount: Decimal
    payable_amount: Decimal
    status: str
    source: str
    start_date: Optional[datetime]
    expiry_date: Optional[datetime]
    renewal_date: Optional[datetime]
    auto_renew: bool
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


# =============================================================================
# Payment
# =============================================================================

class PaymentInitiateRequest(BaseModel):
    """User-initiated checkout — starts a Paytm transaction."""

    plan_id: str
    billing_cycle: str = Field("monthly", regex="^(monthly|yearly)$")


class PaymentInitiateResponse(BaseModel):
    order_id: str
    amount: Decimal
    txn_token: str
    paytm_params: dict  # everything the frontend's Paytm JS checkout needs, pre-built


class CashPaymentCreate(BaseModel):
    """Admin records an offline/cash payment — activates a subscription exactly like a successful online one."""

    user_id: int
    plan_id: str
    billing_cycle: str = Field("monthly", regex="^(monthly|yearly)$")
    override_base_price: Optional[Decimal] = None
    payment_notes: Optional[str] = None


class PaymentResponse(BaseModel):
    class Config:
        orm_mode = True

    id: int
    user_id: int
    subscription_id: Optional[int]
    gateway: str
    status: str
    order_id: str
    gateway_txn_id: Optional[str]
    plan_id: str
    plan_name: str
    base_price: Decimal
    gst_rate: Decimal
    gst_amount: Decimal
    payable_amount: Decimal
    currency: str
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer_mobile: Optional[str] = None
    invoice_number: Optional[str]
    receipt_number: Optional[str]
    payment_notes: Optional[str] = None
    paid_at: Optional[datetime]
    created_at: datetime


# =============================================================================
# AI Usage Limits
# =============================================================================

class AIUsageLimitUpdate(BaseModel):
    daily_limit: Optional[int] = None
    monthly_limit: Optional[int] = None
    yearly_limit: Optional[int] = None
    token_balance: Optional[int] = None
    reset_frequency: Optional[str] = Field(None, regex="^(daily|weekly|monthly|yearly|manual|on_renewal)$")
    reason: Optional[str] = None


class AIUsageLimitResponse(BaseModel):
    class Config:
        orm_mode = True

    user_id: int
    daily_limit: Optional[int]
    daily_used: int
    monthly_limit: Optional[int]
    monthly_used: int
    yearly_limit: Optional[int]
    yearly_used: int
    token_balance: Optional[int]
    tokens_used: int
    reset_frequency: str
    last_reset_at: datetime