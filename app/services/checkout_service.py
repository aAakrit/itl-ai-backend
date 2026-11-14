"""
Public checkout — everything the pricing-page dialog needs, for visitors who are
NOT logged in (new customers, or customers whose account is still awaiting approval
and therefore can't log in yet).

Identity: the visitor proves they own an e-mail address with a one-time code
(CheckoutOtp). That yields a short-lived CHECKOUT TOKEN that is only good for the
/checkout/* endpoints — it is not a login session. Nothing about an existing
account (profile, subscription, payments) is shown before that proof, and the
"send code" step answers identically whether or not the address is registered.

Price rules (all enforced here, never trusted from the browser):
  * list price comes from the CMS plan;
  * a coupon OR a salesman price edit — never both;
  * a salesman price edit needs a chosen salesman, a reason, and may not go below
    (100 - MAX_SALESMAN_DISCOUNT_PCT)% of list. Deeper discounts are done by an
    admin (Admin > Bills / record cash payment);
  * the amount sent to Paytm is always the server's own computation.
"""

import logging
import secrets
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from jose import JWTError, jwt
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import (
    CHECKOUT_OTP_TTL_MINUTES,
    CHECKOUT_TOKEN_MINUTES,
    MAX_SALESMAN_DISCOUNT_PCT,
)
from app.models.checkout_otp import CheckoutOtp
from app.models.payment import Payment
from app.models.subscription import Subscription
from app.models.user import User
from app.services import coupon_service, notification_service, pricing_service, subscription_service
from app.services import products as product_service
from app.services.auth_utils import hash_password, verify_password
from app.services.jwt import ALGORITHM, SECRET_KEY

logger = logging.getLogger(__name__)

OTP_MAX_ATTEMPTS = 5
OTP_MAX_PER_HOUR = 5
BLOCKED_STATUSES = {"SUSPENDED", "DELETED"}


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def find_user(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(func.lower(User.email) == normalize_email(email)).first()


# --------------------------------------------------------------------------
# E-mail proof + token
# --------------------------------------------------------------------------

def create_otp(db: Session, email: str) -> str:
    """Stores a fresh code for `email` and returns it (the route e-mails it)."""
    email = normalize_email(email)
    since = datetime.utcnow() - timedelta(hours=1)
    recent = db.query(func.count(CheckoutOtp.id)).filter(CheckoutOtp.email == email, CheckoutOtp.created_at >= since).scalar() or 0
    if recent >= OTP_MAX_PER_HOUR:
        raise HTTPException(429, "Too many codes requested. Please try again in a little while.")

    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(CheckoutOtp(
        email=email,
        code_hash=hash_password(code),
        expires_at=datetime.utcnow() + timedelta(minutes=CHECKOUT_OTP_TTL_MINUTES),
    ))
    db.commit()
    return code


def verify_otp(db: Session, email: str, otp: str) -> str:
    """Checks the code and returns a checkout token."""
    email = normalize_email(email)
    row = (
        db.query(CheckoutOtp)
        .filter(
            CheckoutOtp.email == email,
            CheckoutOtp.consumed_at.is_(None),
            CheckoutOtp.expires_at > datetime.utcnow(),
        )
        .order_by(CheckoutOtp.created_at.desc())
        .first()
    )
    if not row or row.attempts >= OTP_MAX_ATTEMPTS:
        raise HTTPException(400, "Invalid or expired code — please request a new one.")
    if not verify_password(otp.strip(), row.code_hash):
        row.attempts += 1
        db.commit()
        raise HTTPException(400, "Invalid or expired code — please request a new one.")

    row.consumed_at = datetime.utcnow()
    db.commit()

    now = datetime.utcnow()
    return jwt.encode(
        {"sub": email, "scope": "checkout", "iat": now, "exp": now + timedelta(minutes=CHECKOUT_TOKEN_MINUTES)},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


class CheckoutSession:
    def __init__(self, email: str, user: Optional[User]):
        self.email = email
        self.user = user


def session_from_token(db: Session, token: Optional[str]) -> CheckoutSession:
    if not token:
        raise HTTPException(401, "Please verify your email to continue.")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(401, "Your verification expired — please verify your email again.")
    if payload.get("scope") != "checkout" or not payload.get("sub"):
        raise HTTPException(401, "Invalid verification token.")
    email = payload["sub"]
    user = find_user(db, email)
    if user and (user.status in BLOCKED_STATUSES or user.deleted_at is not None):
        raise HTTPException(403, "This account can't make purchases online. Please contact support.")
    return CheckoutSession(email, user)


# --------------------------------------------------------------------------
# Profile / account
# --------------------------------------------------------------------------

def _profile_dict(user: User) -> dict:
    return {
        "name": user.name, "firm": user.firm, "mobile": user.mobile, "telephone": user.telephone,
        "gstin": user.gstin, "address": user.address, "city": user.city, "state": user.state,
        "pin_code": user.pin_code,
    }


def profile(db: Session, session: CheckoutSession) -> dict:
    user = session.user
    out: dict = {"email": session.email, "exists": user is not None, "status": user.status if user else None,
                 "user": None, "subscription": None, "last_payment": None}
    if not user:
        return out
    out["user"] = _profile_dict(user)

    now = datetime.utcnow()
    sub = (
        db.query(Subscription)
        .filter(Subscription.user_id == user.id, Subscription.status == "active")
        .order_by(Subscription.expiry_date.desc())
        .first()
    )
    if sub:
        out["subscription"] = {
            "plan_name": sub.plan_name,
            "products": product_service.products_of(sub),
            "expiry_date": sub.expiry_date,
            "expired": bool(sub.expiry_date and sub.expiry_date <= now),
        }
    pay = db.query(Payment).filter(Payment.user_id == user.id).order_by(Payment.created_at.desc(), Payment.id.desc()).first()
    if pay:
        out["last_payment"] = {
            "plan_name": pay.plan_name, "amount": pay.payable_amount, "status": pay.status,
            "date": pay.paid_at or pay.created_at, "order_id": pay.order_id,
        }
    return out


def register_account(db: Session, session: CheckoutSession, payload) -> User:
    """Creates the account for a verified e-mail. Stays PENDING until an admin approves it."""
    if session.user:
        raise HTTPException(409, "An account with this email already exists.")
    user = User(
        email=session.email,
        password=hash_password(payload.password),
        name=payload.name,
        firm=payload.firm,
        mobile=payload.mobile,
        telephone=payload.telephone,
        gstin=payload.gstin,
        address=payload.address,
        city=payload.city,
        state=payload.state,
        pin_code=payload.pin_code,
        status="PENDING",
        signup_source="itl_ai",
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with this email already exists.")
    db.refresh(user)
    try:
        notification_service.notify_user_pending_approval(db, user)
    except Exception:
        logger.exception("Couldn't create the pending-approval notification for user %s", user.id)
    return user


def apply_profile_update(db: Session, user: User, details: dict) -> None:
    user.name = details["name"]
    user.firm = details.get("firm")
    user.mobile = details["mobile"]
    user.telephone = details.get("telephone")
    user.gstin = details.get("gstin")
    user.address = details["address"]
    user.city = details["city"]
    user.state = details["state"]
    user.pin_code = details["pin_code"]
    user.updated_at = datetime.utcnow()
    db.commit()


# --------------------------------------------------------------------------
# Salesmen
# --------------------------------------------------------------------------

def _salesman_query(db: Session):
    return db.query(User).filter(
        User.is_staff.is_(True), User.is_admin.is_(False), User.status == "APPROVED", User.deleted_at.is_(None)
    )


def list_salesmen(db: Session) -> list[dict]:
    """Public list — id and name only (no contact details)."""
    return [{"id": u.id, "name": u.name} for u in _salesman_query(db).order_by(User.name).all()]


# --------------------------------------------------------------------------
# Quote
# --------------------------------------------------------------------------

def build_quote(
    db: Session,
    *,
    plan_id: str,
    state: str,
    user_id: Optional[int],
    coupon_code: Optional[str] = None,
    salesman_id: Optional[int] = None,
    override_base_price: Optional[Decimal] = None,
    reason: Optional[str] = None,
) -> dict:
    plan = pricing_service.resolve_plan(db, plan_id)
    list_price: Decimal = plan["base_price"]

    if user_id is not None:
        subscription_service.check_purchase_allowed(db, user_id, plan["products"])

    coupon_code = (coupon_code or "").strip() or None
    has_override = override_base_price is not None
    if coupon_code and has_override:
        raise HTTPException(400, "A coupon can't be combined with a special price. Please use one or the other.")
    if has_override and not salesman_id:
        raise HTTPException(400, "Select a salesman to set a special price.")
    if salesman_id and not _salesman_query(db).filter(User.id == salesman_id).first():
        raise HTTPException(400, "The selected salesman is not available.")

    floor = (list_price * Decimal(100 - MAX_SALESMAN_DISCOUNT_PCT) / Decimal(100)).quantize(Decimal("0.01"))
    discount = Decimal("0.00")
    source: Optional[str] = None
    coupon = None
    reason = (reason or "").strip() or None

    if has_override:
        price = pricing_service.money(override_base_price)
        if price > list_price:
            raise HTTPException(400, "The special price can't be higher than the plan price.")
        if price < floor:
            raise HTTPException(
                400,
                f"A salesman can discount at most {MAX_SALESMAN_DISCOUNT_PCT}% (minimum ₹{floor:.2f}). "
                "For a bigger discount please contact an admin.",
            )
        if price < list_price:
            if not reason or len(reason) < 3:
                raise HTTPException(400, "Please give a reason for the special price.")
            discount = list_price - price
            source = "salesman"
    elif coupon_code:
        coupon, discount = coupon_service.evaluate(db, coupon_code, plan_id=plan["plan_id"], list_price=list_price, user_id=user_id)
        source = "coupon"

    taxable = (list_price - discount).quantize(Decimal("0.01"))
    if taxable < Decimal("1.00"):
        raise HTTPException(400, "The payable amount is too low to process online.")

    split = pricing_service.tax_split(taxable, state)
    return {
        **split,
        "plan": plan,
        "list_price": list_price,
        "discount_amount": discount,
        "discount_source": source,
        "coupon": coupon,
        "salesman_id": salesman_id,
        "reason": reason if source == "salesman" else None,
        "min_allowed_price": floor,
    }


def quote_public(q: dict) -> dict:
    plan = q["plan"]
    return {
        "plan_id": plan["plan_id"],
        "plan_name": plan["plan_name"],
        "products": plan["products"],
        "term_years": plan["term_years"],
        "list_price": q["list_price"],
        "discount_amount": q["discount_amount"],
        "discount_source": q["discount_source"],
        "coupon_code": q["coupon"].code if q["coupon"] else None,
        "salesman_id": q["salesman_id"],
        "min_allowed_price": q["min_allowed_price"],
        "base_price": q["base_price"],
        "cgst_rate": q["cgst_rate"], "cgst_amount": q["cgst_amount"],
        "sgst_rate": q["sgst_rate"], "sgst_amount": q["sgst_amount"],
        "igst_rate": q["igst_rate"], "igst_amount": q["igst_amount"],
        "gst_amount": q["gst_amount"],
        "payable_amount": q["payable_amount"],
    }


# --------------------------------------------------------------------------
# Orders
# --------------------------------------------------------------------------

def get_own_payment(db: Session, session: CheckoutSession, order_id: str) -> Payment:
    payment = db.query(Payment).filter(Payment.order_id == order_id).first()
    if not payment or not session.user or payment.user_id != session.user.id:
        raise HTTPException(404, "Payment not found.")
    return payment
