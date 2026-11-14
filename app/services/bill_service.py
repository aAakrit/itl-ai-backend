"""
Bills (GST tax invoices).

Created in two ways:
  * automatically when a payment succeeds (online or cash) — create_for_payment
  * by an admin on the Bills screen, e.g. for a salesman's customer — create_bill

Totals, tax amounts and the amount in words are always computed here from the
line items and tax rates — client-sent totals are never trusted.

NUMBERING — ITL/<financial-year>/<running no>, e.g. ITL/2026-27/0001.
The counter lives in `bill_sequences` (one row per financial year). `_next_number`
takes a row lock (SELECT ... FOR UPDATE) that is held until the surrounding
transaction ends, and the bill is inserted in that same transaction. So:
  * two simultaneous bills queue on the lock and get consecutive numbers;
  * if the bill insert fails and rolls back, the counter increment rolls back too
    (no gaps);
  * bills.bill_number is also UNIQUE, as a last line of defence.
Never commit between _next_number and inserting the bill.
"""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import SUBSCRIPTION_HSN
from app.models.bill import Bill, BillSequence
from app.models.payment import Payment
from app.models.user import User
from app.services import pricing_service, products as product_service
from app.services.number_words import rupees_in_words

logger = logging.getLogger(__name__)

TWO_PLACES = Decimal("0.01")
MAX_LINES = 10

CUSTOMER_FIELDS = [
    "customer_name", "customer_address", "customer_city", "customer_pin", "customer_state",
    "customer_tele", "customer_mobile", "customer_email", "customer_gstin",
]
PLAIN_FIELDS = ["payment_ref", "payment_date", "payment_amount", "bank", "notes", "reverse_charge", "salesman_id"]


def today_ist() -> date:
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()


def financial_year_of(d: date) -> str:
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def format_number(fy: str, n: int) -> str:
    return f"ITL/{fy}/{n:04d}"


def _next_number(db: Session, fy: str) -> str:
    # Make sure the year's counter row exists (race-safe), then lock it.
    db.execute(pg_insert(BillSequence).values(financial_year=fy, last_number=0).on_conflict_do_nothing())
    seq = (
        db.query(BillSequence)
        .filter(BillSequence.financial_year == fy)
        .with_for_update()
        .populate_existing()
        .one()
    )
    seq.last_number += 1
    db.flush()
    return format_number(fy, seq.last_number)


def _money(v) -> Decimal:
    try:
        return Decimal(str(v if v not in (None, "") else 0)).quantize(TWO_PLACES)
    except Exception:
        raise HTTPException(400, f"Invalid amount: {v!r}.")


def normalize_lines(lines: list[dict]) -> list[dict]:
    out = []
    for line in lines or []:
        particulars = (line.get("particulars") or "").strip()
        amount = _money(line.get("amount"))
        if not particulars and amount == 0:
            continue  # blank row on the form
        if not particulars:
            raise HTTPException(400, "Every bill line with an amount needs a description.")
        if amount < 0:
            raise HTTPException(400, "Line amounts can't be negative.")
        out.append({
            "particulars": particulars,
            "hsn": (line.get("hsn") or "").strip(),
            "period": (line.get("period") or "").strip(),
            "amount": str(amount),
        })
    if not out:
        raise HTTPException(400, "Add at least one line to the bill.")
    if len(out) > MAX_LINES:
        raise HTTPException(400, f"A bill can have at most {MAX_LINES} lines.")
    return out


def compute_totals(lines: list[dict], rates: dict) -> dict:
    before = sum((Decimal(line["amount"]) for line in lines), Decimal("0.00")).quantize(TWO_PLACES)
    if before <= 0:
        raise HTTPException(400, "The bill total must be greater than zero.")
    cgst_rate, sgst_rate, igst_rate = (Decimal(str(rates[k])) for k in ("cgst_rate", "sgst_rate", "igst_rate"))
    for r in (cgst_rate, sgst_rate, igst_rate):
        if r < 0 or r > 28:
            raise HTTPException(400, "Tax rates must be between 0 and 28.")
    if igst_rate > 0 and (cgst_rate > 0 or sgst_rate > 0):
        raise HTTPException(400, "Use either CGST + SGST or IGST on a bill — not both.")

    def pct(rate: Decimal) -> Decimal:
        return (before * rate / Decimal("100")).quantize(TWO_PLACES)

    cgst, sgst, igst = pct(cgst_rate), pct(sgst_rate), pct(igst_rate)
    tax = cgst + sgst + igst
    after = before + tax
    return {
        "total_before_tax": before,
        "cgst_rate": cgst_rate, "cgst_amount": cgst,
        "sgst_rate": sgst_rate, "sgst_amount": sgst,
        "igst_rate": igst_rate, "igst_amount": igst,
        "total_tax": tax,
        "total_after_tax": after,
        "amount_in_words": rupees_in_words(after),
    }


def _rates_for(data: dict, before: Decimal) -> dict:
    """Rates the admin typed, or the state-based default when none were given."""
    given = {k: data.get(k) for k in ("cgst_rate", "sgst_rate", "igst_rate")}
    if all(v is None for v in given.values()):
        split = pricing_service.tax_split(before, data.get("customer_state"))
        return {k: split[k] for k in given}
    return {k: (v if v is not None else 0) for k, v in given.items()}


def _clean_customer(data: dict) -> dict:
    out = {}
    for f in CUSTOMER_FIELDS:
        v = data.get(f)
        out[f] = v.strip() if isinstance(v, str) and v.strip() else None
    if out.get("customer_gstin"):
        out["customer_gstin"] = out["customer_gstin"].upper()
    if not out.get("customer_name"):
        raise HTTPException(400, "Customer name is required.")
    return out


def create_bill(
    db: Session,
    data: dict,
    *,
    created_by: Optional[int] = None,
    user_id: Optional[int] = None,
    payment_id: Optional[int] = None,
    commit: bool = True,
) -> Bill:
    customer = _clean_customer(data)
    lines = normalize_lines(data.get("lines"))
    before = sum((Decimal(line["amount"]) for line in lines), Decimal("0.00"))
    totals = compute_totals(lines, _rates_for({**data, **customer}, before))

    bill_date = data.get("bill_date") or today_ist()
    fy = financial_year_of(bill_date)

    bill = Bill(
        bill_number=_next_number(db, fy),  # takes the sequence lock — keep everything below in this transaction
        financial_year=fy,
        bill_date=bill_date,
        status="active",
        user_id=user_id if user_id is not None else data.get("user_id"),
        payment_id=payment_id,
        created_by_admin_id=created_by,
        lines=lines,
        **customer,
        **totals,
    )
    for f in PLAIN_FIELDS:
        if f in data and data[f] not in ("",):
            setattr(bill, f, data[f])
    db.add(bill)
    db.flush()
    if commit:
        db.commit()
        db.refresh(bill)
    return bill


def update_bill(db: Session, bill_id: int, data: dict) -> Bill:
    bill = get(db, bill_id)
    if bill.status == "cancelled":
        raise HTTPException(400, "A cancelled bill can't be edited.")

    merged = {f: data.get(f, getattr(bill, f)) for f in CUSTOMER_FIELDS}
    customer = _clean_customer(merged)
    lines = normalize_lines(data["lines"]) if "lines" in data and data["lines"] is not None else bill.lines
    before = sum((Decimal(line["amount"]) for line in lines), Decimal("0.00"))

    rate_keys = ("cgst_rate", "sgst_rate", "igst_rate")
    if any(data.get(k) is not None for k in rate_keys):
        rates = {k: (data.get(k) if data.get(k) is not None else 0) for k in rate_keys}
    elif "customer_state" in data and data.get("customer_state") != bill.customer_state:
        rates = _rates_for({**customer}, before)  # state changed: re-derive CGST/SGST vs IGST
    else:
        rates = {k: getattr(bill, k) for k in rate_keys}
    totals = compute_totals(lines, rates)

    for k, v in {**customer, **totals}.items():
        setattr(bill, k, v)
    bill.lines = lines
    if data.get("bill_date"):
        bill.bill_date = data["bill_date"]  # the number keeps its original financial year
    for f in PLAIN_FIELDS:
        if f in data:
            setattr(bill, f, data[f] if data[f] != "" else None)
    db.commit()
    db.refresh(bill)
    return bill


def cancel_bill(db: Session, bill_id: int, reason: Optional[str]) -> Bill:
    bill = get(db, bill_id)
    if bill.status == "cancelled":
        return bill
    bill.status = "cancelled"
    bill.cancelled_at = datetime.utcnow()
    bill.cancel_reason = (reason or "").strip() or None
    db.commit()
    db.refresh(bill)
    return bill


def get(db: Session, bill_id: int) -> Bill:
    bill = db.query(Bill).filter(Bill.id == bill_id).first()
    if not bill:
        raise HTTPException(404, "Bill not found.")
    return bill


def get_for_payment(db: Session, payment_id: int) -> Optional[Bill]:
    return db.query(Bill).filter(Bill.payment_id == payment_id).first()


def list_bills(
    db: Session,
    *,
    page: int,
    limit: int,
    search: Optional[str] = None,
    financial_year: Optional[str] = None,
    status: Optional[str] = None,
) -> dict:
    q = db.query(Bill)
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(or_(
            Bill.bill_number.ilike(like), Bill.customer_name.ilike(like),
            Bill.customer_email.ilike(like), Bill.customer_mobile.ilike(like), Bill.customer_gstin.ilike(like),
        ))
    if financial_year:
        q = q.filter(Bill.financial_year == financial_year)
    if status:
        q = q.filter(Bill.status == status)
    total = q.count()
    items = q.order_by(Bill.created_at.desc(), Bill.id.desc()).offset((page - 1) * limit).limit(limit).all()
    return {"items": items, "total": total, "page": page, "limit": limit}


# --------------------------------------------------------------------------
# From a payment / for previews
# --------------------------------------------------------------------------

def subscription_line(plan_name: str, term_years: int, amount) -> dict:
    term = "One Year" if int(term_years) == 1 else f"{int(term_years)} Year"
    return {
        "particulars": f"{term} Subscription — {plan_name}",
        "hsn": SUBSCRIPTION_HSN,
        "period": "",
        "amount": str(_money(amount)),
    }


def _payment_notes(payment: Payment) -> Optional[str]:
    if payment.discount_amount and Decimal(payment.discount_amount) > 0 and payment.list_price is not None:
        how = f"coupon {payment.coupon_code}" if payment.discount_source == "coupon" else "special price"
        return f"List price ₹{Decimal(payment.list_price):.2f}, discount ₹{Decimal(payment.discount_amount):.2f} ({how})."
    return None


def create_for_payment(db: Session, payment: Payment) -> Bill:
    """
    Tax invoice for a successful payment. Idempotent. Runs inside the caller's
    transaction (no commit) so the bill and the payment succeed or fail together.
    """
    existing = get_for_payment(db, payment.id)
    if existing:
        return existing

    paid_on = ((payment.paid_at or datetime.utcnow()) + timedelta(hours=5, minutes=30)).date()
    split = pricing_service.tax_split(Decimal(payment.base_price), payment.customer_state)
    if split["payable_amount"] != Decimal(payment.payable_amount):
        logger.warning(
            "Bill for payment %s: recomputed total %s differs from charged %s",
            payment.id, split["payable_amount"], payment.payable_amount,
        )

    data = {
        "customer_name": payment.customer_name,
        "customer_address": payment.customer_address,
        "customer_city": payment.customer_city,
        "customer_pin": payment.customer_pin,
        "customer_state": payment.customer_state,
        "customer_mobile": payment.customer_mobile,
        "customer_email": payment.customer_email,
        "customer_gstin": payment.customer_gstin,
        "lines": [subscription_line(payment.plan_name, payment.term_years or 1, payment.base_price)],
        "cgst_rate": split["cgst_rate"], "sgst_rate": split["sgst_rate"], "igst_rate": split["igst_rate"],
        "bill_date": paid_on,
        "payment_ref": payment.gateway_txn_id or payment.order_id,
        "payment_date": paid_on,
        "payment_amount": payment.payable_amount,
        "bank": {"paytm": "Paytm", "cash": "Cash"}.get(payment.gateway, payment.gateway),
        "notes": _payment_notes(payment),
        "salesman_id": payment.salesman_id,
    }
    bill = create_bill(
        db, data,
        created_by=payment.recorded_by_admin_id,
        user_id=payment.user_id,
        payment_id=payment.id,
        commit=False,
    )
    payment.invoice_number = bill.bill_number
    return bill


def prefill(db: Session, *, user_id: Optional[int] = None, plan_id: Optional[str] = None) -> dict:
    """Starting values for the admin Bills form (nothing is saved)."""
    data: dict = {"bill_date": today_ist(), "lines": [], "customer_name": ""}
    if user_id:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(404, "User not found.")
        data.update({
            "user_id": user.id,
            "customer_name": user.name,
            "customer_address": user.address,
            "customer_city": user.city,
            "customer_pin": user.pin_code,
            "customer_state": user.state,
            "customer_tele": user.telephone,
            "customer_mobile": user.mobile,
            "customer_email": user.email,
            "customer_gstin": user.gstin,
        })
    if plan_id:
        plan = pricing_service.resolve_plan(db, plan_id)
        data["lines"] = [subscription_line(plan["plan_name"], plan["term_years"], plan["base_price"])]
        split = pricing_service.tax_split(plan["base_price"], data.get("customer_state"))
        data.update({k: split[k] for k in ("cgst_rate", "sgst_rate", "igst_rate")})
    return data


def draft_from_quote(details: dict, plan: dict, quote: dict) -> SimpleNamespace:
    """An unnumbered, unsaved bill for the pre-payment PROFORMA."""
    taxable = quote["base_price"]
    return SimpleNamespace(
        bill_number="PROFORMA",
        bill_date=today_ist(),
        status="active",
        customer_name=details.get("name"),
        customer_address=details.get("address"),
        customer_city=details.get("city"),
        customer_pin=details.get("pin_code"),
        customer_state=details.get("state"),
        customer_tele=details.get("telephone"),
        customer_mobile=details.get("mobile"),
        customer_email=details.get("email"),
        customer_gstin=details.get("gstin"),
        lines=[subscription_line(plan["plan_name"], plan["term_years"], taxable)],
        total_before_tax=taxable,
        cgst_rate=quote["cgst_rate"], cgst_amount=quote["cgst_amount"],
        sgst_rate=quote["sgst_rate"], sgst_amount=quote["sgst_amount"],
        igst_rate=quote["igst_rate"], igst_amount=quote["igst_amount"],
        total_tax=quote["gst_amount"],
        total_after_tax=quote["payable_amount"],
        amount_in_words=rupees_in_words(quote["payable_amount"]),
        payment_ref=None, payment_date=None, payment_amount=None, bank=None,
        notes=(
            f"List price ₹{quote['list_price']:.2f}, discount ₹{quote['discount_amount']:.2f}."
            if quote["discount_amount"] and quote["discount_amount"] > 0 else None
        ),
        reverse_charge=None,
    )
