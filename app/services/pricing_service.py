"""
Pricing resolution — reads the CMS pricing page (route="pricing") so it stays
the single source of truth for what a plan costs right now.

Each entry of content.pricingPlans[] is expected to look like:

    {
      "id": "bundle_3year",            # plan id (bundle_* ids are also the Bridge plan codes)
      "name": "ITL AI + ITL Bridge AI",
      "products": ["itl_ai", "itl_bridge_ai"],
      "termYears": 3,
      "basePrice": 63000,              # price before GST, for the whole term
      ...display fields (description, features, cta, badge, featured)...
    }

Older entries without `basePrice` (the original "pro" plan) still resolve:
their `yearlyPrice` is used, as a 1-year ITL AI plan. Monthly billing no longer
exists.

GST: 18%. Customers in the seller's state (config.SELLER_STATE) are charged
9% CGST + 9% SGST, everyone else 18% IGST. The split changes only how the tax is
shown — the total is the same.
"""

from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import SELLER_STATE
from app.services import cms_page as cms_page_service
from app.services import products as product_service

GST_RATE = Decimal("18.00")
HALF_RATE = Decimal("9.00")
TWO_PLACES = Decimal("0.01")

CANDIDATE_ID_KEYS = ["id", "planId", "slug"]
CANDIDATE_NAME_KEYS = ["name", "title", "planName"]
PRICE_KEYS = ["basePrice", "yearlyPrice", "annualPrice", "priceYearly"]


def _first_present(d: dict, keys: list[str]):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _norm_state(state: Optional[str]) -> str:
    return " ".join((state or "").lower().split())


def is_intra_state(state: Optional[str]) -> bool:
    return _norm_state(state) == _norm_state(SELLER_STATE)


def money(v) -> Decimal:
    return Decimal(str(v)).quantize(TWO_PLACES)


def tax_split(taxable: Decimal, state: Optional[str]) -> dict:
    """GST on `taxable` for a customer in `state`."""
    taxable = money(taxable)
    if is_intra_state(state):
        half = (taxable * HALF_RATE / Decimal("100")).quantize(TWO_PLACES)
        cgst, sgst, igst = half, half, Decimal("0.00")
        rates = (HALF_RATE, HALF_RATE, Decimal("0.00"))
    else:
        cgst = sgst = Decimal("0.00")
        igst = (taxable * GST_RATE / Decimal("100")).quantize(TWO_PLACES)
        rates = (Decimal("0.00"), Decimal("0.00"), GST_RATE)
    total_tax = cgst + sgst + igst
    return {
        "cgst_rate": rates[0],
        "sgst_rate": rates[1],
        "igst_rate": rates[2],
        "cgst_amount": cgst,
        "sgst_amount": sgst,
        "igst_amount": igst,
        "gst_rate": GST_RATE,
        "gst_amount": total_tax,
        "base_price": taxable,
        "payable_amount": (taxable + total_tax).quantize(TWO_PLACES),
    }


def get_cms_plans(db: Session) -> list[dict]:
    try:
        page = cms_page_service.get_page(db, "pricing")
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(status_code=503, detail="Pricing page is not configured yet.")
        raise
    content = page.get("content") if isinstance(page, dict) else getattr(page, "content", None)
    if not isinstance(content, dict):
        raise HTTPException(status_code=503, detail="Pricing page is not configured yet.")
    return content.get("pricingPlans") or []


def resolve_plan(db: Session, plan_id: str, billing_cycle: Optional[str] = None) -> dict:
    """
    Live plan lookup. `billing_cycle` is accepted for old callers and ignored —
    the plan itself defines its term.

    Returns plan_id, plan_name, products, term_years, billing_cycle, base_price
    (the list price) and the GST fields computed as IGST (use tax_split for the
    customer-specific split).
    """
    plans = get_cms_plans(db)
    plan = next((p for p in plans if str(_first_present(p, CANDIDATE_ID_KEYS)) == str(plan_id)), None)
    if not plan:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found on the pricing page.")

    name = _first_present(plan, CANDIDATE_NAME_KEYS)
    price_raw = _first_present(plan, PRICE_KEYS)
    if name is None or price_raw is None:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Pricing plan '{plan_id}' needs a name and a price. Expected one of {CANDIDATE_NAME_KEYS} "
                f"and one of {PRICE_KEYS} — got keys {list(plan.keys())}."
            ),
        )

    try:
        base_price = money(price_raw)
    except Exception:
        raise HTTPException(status_code=500, detail=f"Pricing plan '{plan_id}' has an invalid price: {price_raw!r}.")
    if base_price <= 0:
        raise HTTPException(status_code=400, detail=f"Plan '{plan_id}' is not purchasable.")

    products = product_service.validate_sellable(plan.get("products") or [product_service.ITL_AI])
    try:
        term_years = int(plan.get("termYears") or 1)
    except (TypeError, ValueError):
        term_years = 1

    amounts = tax_split(base_price, None)
    return {
        "plan_id": str(plan_id),
        "plan_name": str(name),
        "products": products,
        "term_years": term_years,
        "billing_cycle": product_service.cycle_label(term_years),
        "base_price": base_price,
        "gst_rate": amounts["gst_rate"],
        "gst_amount": amounts["gst_amount"],
        "payable_amount": amounts["payable_amount"],
    }
