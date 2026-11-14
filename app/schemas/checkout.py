import re
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, validator

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


class OtpRequest(BaseModel):
    email: EmailStr


class OtpVerify(BaseModel):
    email: EmailStr
    otp: str = Field(..., min_length=4, max_length=10)


class CustomerDetails(BaseModel):
    """Billing details the customer can edit in the checkout dialog."""

    name: str = Field(..., min_length=2, max_length=255)
    firm: Optional[str] = Field(None, max_length=255)
    mobile: str = Field(..., min_length=7, max_length=20)
    telephone: Optional[str] = Field(None, max_length=20)
    gstin: Optional[str] = Field(None, max_length=20)
    address: str = Field(..., min_length=3, max_length=500)
    city: str = Field(..., min_length=2, max_length=100)
    state: str = Field(..., min_length=2, max_length=100)
    pin_code: str = Field(..., min_length=4, max_length=20)

    @validator("gstin", pre=True)
    def _gstin(cls, v):
        v = (v or "").strip().upper()
        if not v:
            return None
        if not GSTIN_RE.match(v):
            raise ValueError("Enter a valid 15-character GSTIN.")
        return v

    @validator("name", "address", "city", "state", "pin_code", "mobile", pre=True)
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v


class RegisterRequest(CustomerDetails):
    password: str = Field(..., min_length=8, max_length=128)


class QuoteRequest(BaseModel):
    plan_id: str
    state: str = Field(..., min_length=2, max_length=100)
    coupon_code: Optional[str] = Field(None, max_length=40)
    salesman_id: Optional[int] = None
    # Only with a salesman: the discounted base price (before GST).
    override_base_price: Optional[Decimal] = None
    reason: Optional[str] = Field(None, max_length=500)


class InitiateRequest(QuoteRequest):
    details: CustomerDetails
    update_profile: bool = False


class ProformaRequest(QuoteRequest):
    details: CustomerDetails


# ---- admin: coupons ------------------------------------------------------

class CouponCreate(BaseModel):
    code: str
    description: Optional[str] = None
    discount_type: str = Field(..., regex="^(percent|flat)$")
    value: Decimal
    max_discount: Optional[Decimal] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    total_limit: Optional[int] = None
    per_user_limit: Optional[int] = None
    plan_ids: Optional[list[str]] = None
    is_active: bool = True


class CouponUpdate(BaseModel):
    """code and discount_type can't change once created."""

    description: Optional[str] = None
    value: Optional[Decimal] = None
    max_discount: Optional[Decimal] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    total_limit: Optional[int] = None
    per_user_limit: Optional[int] = None
    plan_ids: Optional[list[str]] = None
    is_active: Optional[bool] = None


class CouponResponse(BaseModel):
    class Config:
        orm_mode = True

    id: int
    code: str
    description: Optional[str]
    discount_type: str
    value: Decimal
    max_discount: Optional[Decimal]
    valid_from: Optional[datetime]
    valid_to: Optional[datetime]
    total_limit: Optional[int]
    per_user_limit: Optional[int]
    plan_ids: Optional[list[str]]
    is_active: bool
    times_used: int = 0
    created_at: datetime


# ---- admin: bills --------------------------------------------------------

class BillLine(BaseModel):
    particulars: str = ""
    hsn: Optional[str] = ""
    period: Optional[str] = ""
    amount: Decimal = Decimal("0")


class BillWrite(BaseModel):
    """Create / edit a bill. Totals and amount-in-words are computed by the server."""

    user_id: Optional[int] = None
    salesman_id: Optional[int] = None
    bill_date: Optional[date] = None

    customer_name: Optional[str] = None
    customer_address: Optional[str] = None
    customer_city: Optional[str] = None
    customer_pin: Optional[str] = None
    customer_state: Optional[str] = None
    customer_tele: Optional[str] = None
    customer_mobile: Optional[str] = None
    customer_email: Optional[str] = None
    customer_gstin: Optional[str] = None

    lines: Optional[list[BillLine]] = None

    # Leave all three empty to derive CGST+SGST / IGST from the customer's state.
    cgst_rate: Optional[Decimal] = None
    sgst_rate: Optional[Decimal] = None
    igst_rate: Optional[Decimal] = None

    payment_ref: Optional[str] = None
    payment_date: Optional[date] = None
    payment_amount: Optional[Decimal] = None
    bank: Optional[str] = None
    notes: Optional[str] = None
    reverse_charge: Optional[str] = None


class BillCancel(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


class BillResponse(BaseModel):
    class Config:
        orm_mode = True

    id: int
    bill_number: str
    financial_year: str
    bill_date: date
    status: str
    user_id: Optional[int]
    payment_id: Optional[int]
    salesman_id: Optional[int]
    customer_name: str
    customer_address: Optional[str]
    customer_city: Optional[str]
    customer_pin: Optional[str]
    customer_state: Optional[str]
    customer_tele: Optional[str]
    customer_mobile: Optional[str]
    customer_email: Optional[str]
    customer_gstin: Optional[str]
    lines: list
    total_before_tax: Decimal
    cgst_rate: Decimal
    cgst_amount: Decimal
    sgst_rate: Decimal
    sgst_amount: Decimal
    igst_rate: Decimal
    igst_amount: Decimal
    total_tax: Decimal
    total_after_tax: Decimal
    amount_in_words: Optional[str]
    payment_ref: Optional[str]
    payment_date: Optional[date]
    payment_amount: Optional[Decimal]
    bank: Optional[str]
    notes: Optional[str]
    reverse_charge: Optional[str]
    cancelled_at: Optional[datetime]
    cancel_reason: Optional[str]
    created_at: datetime
