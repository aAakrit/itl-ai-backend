"""
Product catalogue helpers.

Two sellable products exist: ITL AI and ITL Bridge AI. Bridge is NEVER sold on
its own — it always comes with ITL AI (the "ITL AI + ITL Bridge AI" bundle).
A subscription records the products it grants in `Subscription.products`
(a snapshot taken from the plan, which an admin may override).

Rows created before this column existed are read through `products_of`, which
derives the products from the old plan ids.
"""

import calendar
from datetime import datetime
from typing import Iterable, Optional

from fastapi import HTTPException

ITL_AI = "itl_ai"
BRIDGE = "itl_bridge_ai"
ALL_PRODUCTS = (ITL_AI, BRIDGE)

PRODUCT_LABELS = {ITL_AI: "ITL AI", BRIDGE: "ITL Bridge AI"}

# Bridge (MCP server) plan code per term, for the bundle.
BRIDGE_BUNDLE_CODE_BY_TERM = {1: "bundle_yearly", 3: "bundle_3year", 5: "bundle_5year"}
LEGACY_BUNDLE_IDS = {"bundle_yearly": 1, "bundle_3year": 3, "bundle_5year": 5}
LEGACY_STANDALONE_BRIDGE_IDS = {"bridge_yearly": 1, "bridge_3year": 3}


def normalize(products: Optional[Iterable[str]]) -> list[str]:
    """Validates, de-duplicates and canonically orders a product list."""
    wanted = {str(p).strip().lower() for p in (products or [])}
    unknown = wanted - set(ALL_PRODUCTS)
    if unknown:
        raise HTTPException(400, f"Unknown product(s): {', '.join(sorted(unknown))}.")
    ordered = [p for p in ALL_PRODUCTS if p in wanted]
    if not ordered:
        raise HTTPException(400, "At least one product is required.")
    return ordered


def validate_sellable(products: Optional[Iterable[str]]) -> list[str]:
    """normalize + the 'Bridge is never standalone' rule. Use for any NEW grant."""
    ordered = normalize(products)
    if BRIDGE in ordered and ITL_AI not in ordered:
        raise HTTPException(400, "ITL Bridge AI is only available together with ITL AI.")
    return ordered


def label(products: Iterable[str]) -> str:
    return " + ".join(PRODUCT_LABELS[p] for p in ALL_PRODUCTS if p in set(products))


def legacy_products_for_plan(plan_id: Optional[str]) -> list[str]:
    if plan_id in LEGACY_BUNDLE_IDS:
        return [ITL_AI, BRIDGE]
    if plan_id in LEGACY_STANDALONE_BRIDGE_IDS:
        return [BRIDGE]
    return [ITL_AI]


def products_of(sub) -> list[str]:
    stored = getattr(sub, "products", None)
    if stored:
        return [p for p in ALL_PRODUCTS if p in set(stored)]
    return legacy_products_for_plan(getattr(sub, "plan_id", None))


def term_years_of(sub) -> int:
    stored = getattr(sub, "term_years", None)
    if stored:
        return int(stored)
    pid = getattr(sub, "plan_id", None)
    return LEGACY_BUNDLE_IDS.get(pid) or LEGACY_STANDALONE_BRIDGE_IDS.get(pid) or 1


def cycle_label(term_years: int) -> str:
    return {1: "yearly", 3: "3year", 5: "5year"}.get(int(term_years), f"{int(term_years)}year")


def add_years(dt: datetime, years: int) -> datetime:
    """Calendar-correct (29 Feb safe) — 'one year' is the same date next year, not 365 days."""
    year = dt.year + years
    day = min(dt.day, calendar.monthrange(year, dt.month)[1])
    return dt.replace(year=year, day=day)
