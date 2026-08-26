"""
Outgoing email.

Every email the system sends (registration, payment receipts, password
reset OTPs) goes through `send_email` below, so the From address and SMTP
credentials live in exactly one place — app/config.py.

Synchronous smtplib on purpose: FastAPI runs sync route bodies (and
BackgroundTasks) in a threadpool, so this doesn't block the event loop, and
it avoids pulling in an async SMTP dependency for what is a low-volume,
non-latency-critical send.

Failures are logged, never raised into the caller — a broken mail server
should not fail registration or a payment that already succeeded. Callers
that truly need to know whether the email went out (none currently do)
should check the boolean return value.
"""

import logging
import smtplib
from email.message import EmailMessage

from app.config import (
    EMAIL_FROM,
    EMAIL_FROM_NAME,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_USE_TLS,
)

logger = logging.getLogger(__name__)


def send_email(*, to: str, subject: str, html_body: str, text_body: str | None = None) -> bool:
    if not SMTP_PASSWORD:
        logger.warning("SMTP_PASSWORD not configured — skipping email %r to %s", subject, to)
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{EMAIL_FROM_NAME} <{EMAIL_FROM}>"
    msg["To"] = to
    msg.set_content(text_body or _strip_html(html_body))
    msg.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            if SMTP_USE_TLS:
                server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception:
        logger.exception("Failed to send email %r to %s", subject, to)
        return False


def _strip_html(html: str) -> str:
    import re

    return re.sub(r"<[^>]+>", " ", html).strip()


def _wrapper(title: str, body_html: str) -> str:
    return f"""
    <div style="font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; max-width: 560px; margin: 0 auto; color: #1f2937;">
      <p style="font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: #6366f1; font-weight: 600;">Income Tax Library</p>
      <h2 style="margin: 8px 0 20px; font-size: 20px;">{title}</h2>
      {body_html}
      <p style="margin-top: 32px; font-size: 12px; color: #9ca3af;">
        This is an automated message from Income Tax Library. If you didn't expect this email, you can ignore it.
      </p>
    </div>
    """


# =============================================================================
# Templated sends — one function per email the product actually fires
# =============================================================================

def send_registration_email(*, to: str, name: str) -> bool:
    body = f"""
      <p>Hi {name},</p>
      <p>Thanks for registering with Income Tax Library. Your account has been created and is
      <strong>awaiting admin approval</strong> — we'll let you know as soon as it's active.</p>
    """
    return send_email(to=to, subject="Welcome to Income Tax Library", html_body=_wrapper("Account created", body))


def send_password_reset_otp_email(*, to: str, otp: str, ttl_minutes: int) -> bool:
    body = f"""
      <p>Use this code to reset your password. It expires in {ttl_minutes} minutes.</p>
      <p style="font-size: 32px; font-weight: 700; letter-spacing: 0.3em; margin: 20px 0; text-align: center; background: #f3f4f6; padding: 16px; border-radius: 12px;">{otp}</p>
      <p>If you didn't request this, you can safely ignore this email — your password won't change.</p>
    """
    return send_email(
        to=to,
        subject=f"Your password reset code: {otp}",
        html_body=_wrapper("Reset your password", body),
    )


def send_payment_receipt_email(*, to: str, name: str, plan_name: str, amount: str, order_id: str) -> bool:
    body = f"""
      <p>Hi {name},</p>
      <p>We've received your payment for <strong>{plan_name}</strong>. Your subscription is now active.</p>
      <table style="width: 100%; border-collapse: collapse; margin-top: 16px;">
        <tr><td style="padding: 6px 0; color: #6b7280;">Order ID</td><td style="padding: 6px 0; text-align: right;">{order_id}</td></tr>
        <tr><td style="padding: 6px 0; color: #6b7280;">Plan</td><td style="padding: 6px 0; text-align: right;">{plan_name}</td></tr>
        <tr><td style="padding: 6px 0; color: #6b7280;">Amount paid</td><td style="padding: 6px 0; text-align: right; font-weight: 600;">₹{amount}</td></tr>
      </table>
    """
    return send_email(
        to=to,
        subject="Payment received — receipt",
        html_body=_wrapper("Payment successful", body),
    )
