"""
Subscription model.

WHY THIS EXISTS
----------------
`User.plan` (app/models/user.py) was already a placeholder column marked
"# Subscription (Future)" — this table is that future. It represents a
user's *entitlement*: which plan, for how long, and how it started
(online payment, manual/cash, or complimentary).

Pricing is deliberately NOT duplicated into a separate "plans" table.
The existing CMS page at route="pricing" (see app/models/cms_page.py,
content.pricingPlans[]) is kept as the single source of truth for the
current price of a plan. This table stores a SNAPSHOT of the plan
name/price/GST/payable amount *at the moment of purchase* — so that if
an admin edits the CMS pricing page next month, every subscription
created before that edit still reflects what the user actually agreed
to and paid. Only the live "what does this plan cost right now" lookup
goes through CMS; everything historical is frozen here.
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    Numeric,
    ForeignKey,
    Text,
)
from sqlalchemy.orm import relationship

from app.db import Base


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # ------------------------------------------------------------------
    # Plan identity + pricing snapshot (frozen at purchase/creation time —
    # deliberately duplicated from the CMS pricing page, not a live FK,
    # so historical invoices/subscriptions never drift when pricing changes)
    # ------------------------------------------------------------------
    plan_id = Column(String(100), nullable=False)  # matches CMS pricingPlans[].id
    plan_name = Column(String(255), nullable=False)
    billing_cycle = Column(String(20), nullable=False, default="monthly")  # monthly | yearly

    base_price = Column(Numeric(12, 2), nullable=False)
    gst_rate = Column(Numeric(5, 2), nullable=False, default=18.00)
    gst_amount = Column(Numeric(12, 2), nullable=False)
    payable_amount = Column(Numeric(12, 2), nullable=False)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    # pending | active | suspended | cancelled | expired
    status = Column(String(20), nullable=False, default="pending", index=True)

    # online (Paytm) | manual | complimentary
    source = Column(String(20), nullable=False, default="online")

    start_date = Column(DateTime, nullable=True)
    expiry_date = Column(DateTime, nullable=True, index=True)
    renewal_date = Column(DateTime, nullable=True)
    auto_renew = Column(Boolean, default=False)

    # Set when an admin created/edited this outside the normal payment flow
    # (manual subscription, validity override, plan change, suspend, etc).
    created_by_admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])
    payments = relationship("Payment", back_populates="subscription")