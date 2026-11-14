"""
Bills (GST tax invoices) and their number sequence.

Numbers look like ITL/2026-27/0001 and restart every financial year (1 Apr -
31 Mar). They are handed out from `bill_sequences` under a row lock inside the
same transaction that inserts the bill, so two bills created at the same moment
can never get the same number, and a rolled-back bill never leaves a gap.
Bills are cancelled, never deleted, so the series stays continuous.
"""

from datetime import datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.db import Base


class BillSequence(Base):
    __tablename__ = "bill_sequences"

    financial_year = Column(String(9), primary_key=True)  # "2026-27"
    last_number = Column(Integer, nullable=False, default=0)


class Bill(Base):
    __tablename__ = "bills"

    id = Column(Integer, primary_key=True, index=True)
    bill_number = Column(String(40), unique=True, nullable=False, index=True)
    financial_year = Column(String(9), nullable=False, index=True)
    bill_date = Column(Date, nullable=False)
    status = Column(String(12), nullable=False, default="active", index=True)  # active | cancelled

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True, unique=True)
    salesman_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Customer block (typed on the bill — not a live link to the profile)
    customer_name = Column(String(255), nullable=False)
    customer_address = Column(Text, nullable=True)
    customer_city = Column(String(100), nullable=True)   # "Dist" on the form
    customer_pin = Column(String(20), nullable=True)
    customer_state = Column(String(100), nullable=True)
    customer_tele = Column(String(30), nullable=True)
    customer_mobile = Column(String(30), nullable=True)
    customer_email = Column(String(255), nullable=True)
    customer_gstin = Column(String(20), nullable=True)

    # [{"particulars": str, "hsn": str, "period": str, "amount": "123.00"}]
    lines = Column(JSONB, nullable=False, default=list)

    total_before_tax = Column(Numeric(12, 2), nullable=False)
    cgst_rate = Column(Numeric(5, 2), nullable=False, default=0)
    cgst_amount = Column(Numeric(12, 2), nullable=False, default=0)
    sgst_rate = Column(Numeric(5, 2), nullable=False, default=0)
    sgst_amount = Column(Numeric(12, 2), nullable=False, default=0)
    igst_rate = Column(Numeric(5, 2), nullable=False, default=0)
    igst_amount = Column(Numeric(12, 2), nullable=False, default=0)
    total_tax = Column(Numeric(12, 2), nullable=False)
    total_after_tax = Column(Numeric(12, 2), nullable=False)
    amount_in_words = Column(Text, nullable=True)

    # Payment block ("Cheque No / Date / Rs / Bank" on the paper form)
    payment_ref = Column(String(120), nullable=True)
    payment_date = Column(Date, nullable=True)
    payment_amount = Column(Numeric(12, 2), nullable=True)
    bank = Column(String(120), nullable=True)
    notes = Column(Text, nullable=True)
    reverse_charge = Column(String(60), nullable=True)

    created_by_admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    cancel_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
