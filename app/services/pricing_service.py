"""
Pricing resolution — reads the existing CMS pricing page
(app/services/cms_page.py, route="pricing") rather than a separate plans
table, per the explicit requirement that the CMS page stays the single
source of truth for subscription pricing.

NOTE ON FIELD NAMES: the frontend reads `content.pricingPlans` (confirmed
— see src/services/pricing.service.ts) but I could not confirm the exact
field names *within* each plan object (name/price/yearlyPrice vs other
naming) from what was available to me. This resolves defensively across
the most likely variants and raises a clear error naming exactly which
field was missing if none match — check that error message against a
real CMS pricing page save and adjust CANDIDATE_*_KEYS below if needed;
don't assume this guessed right on the first try.
"""

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.services import cms_page as cms_page_service

GST_RATE = Decimal("18.00")

CANDIDATE_ID_KEYS = ["id", "planId", "slug"]
CANDIDATE_NAME_KEYS = ["name", "title", "planName"]
MONTHLY_PRICE_KEYS = ["price", "monthlyPrice", "priceMonthly"]
YEARLY_PRICE_KEYS = ["yearlyPrice", "annualPrice", "priceYearly"]


def _first_present(d: dict, keys: list[str]):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def resolve_plan(db: Session, plan_id: str, billing_cycle: str = "monthly") -> dict:
    """
    Returns {plan_id, plan_name, base_price, gst_rate, gst_amount, payable_amount}
    for the given plan, read live from the CMS pricing page.
    """

    try:
        page = cms_page_service.get_page(db, "pricing")
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(status_code=503, detail="Pricing page is not configured yet.")
        raise

    content = page.get("content") if isinstance(page, dict) else getattr(page, "content", None)

    if not page or not isinstance(content, dict):
        raise HTTPException(status_code=503, detail="Pricing page is not configured yet.")

    plans = content.get("pricingPlans") or []

    plan = next(
        (p for p in plans if str(_first_present(p, CANDIDATE_ID_KEYS)) == str(plan_id)),
        None,
    )

    if not plan:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found on the pricing page.")

    name = _first_present(plan, CANDIDATE_NAME_KEYS)
    price_raw = _first_present(plan, YEARLY_PRICE_KEYS if billing_cycle == "yearly" else MONTHLY_PRICE_KEYS)

    if name is None or price_raw is None:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Pricing plan '{plan_id}' is missing a name or {billing_cycle} price field. "
                f"Expected one of {CANDIDATE_NAME_KEYS} for name and "
                f"{YEARLY_PRICE_KEYS if billing_cycle == 'yearly' else MONTHLY_PRICE_KEYS} for price — "
                f"got keys {list(plan.keys())}."
            ),
        )

    base_price = Decimal(str(price_raw))
    gst_amount = (base_price * GST_RATE / Decimal("100")).quantize(Decimal("0.01"))
    payable_amount = (base_price + gst_amount).quantize(Decimal("0.01"))

    return {
        "plan_id": str(plan_id),
        "plan_name": str(name),
        "base_price": base_price,
        "gst_rate": GST_RATE,
        "gst_amount": gst_amount,
        "payable_amount": payable_amount,
    }