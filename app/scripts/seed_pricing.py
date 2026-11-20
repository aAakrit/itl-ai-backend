"""
One-off: set the pricing page's plans to the current catalogue.

    python -m app.scripts.seed_pricing          # from the backend root

Replaces ONLY content.pricingPlans on the CMS page with route="pricing" — FAQs,
comparison table and enterprise block are left as they are. Safe to re-run.

Plans (shown in this order):  ITL Bridge AI for 1 / 3 / 5 years (connectors only), then ITL AI (1 year, the workspace).
Prices are before GST (18% extra).
"""

from sqlalchemy.orm.attributes import flag_modified

from app.db import SessionLocal
from app.models.cms_page import CmsPage

# The bundle plans are ITL Bridge AI ONLY — they do not include the ITL AI web workspace.
BUNDLE_FEATURES = [
    "ITL Bridge AI — use ITL inside Claude, ChatGPT & Gemini",
    "GST AI and Income Tax AI connectors",
    "Priority email support",
    "18% GST Extra",
]

PLANS = [
    {
        "id": "bundle_yearly", "name": "ITL Bridge AI", "badge": "1 Year",
        "products": ["itl_bridge_ai"], "termYears": 1, "basePrice": 25200,
        "currency": "₹", "period": "1 Year", "featured": 0, "cta": "Subscribe Now",
        "description": "ITL Bridge AI for one year.", "features": BUNDLE_FEATURES,
    },
    {
        "id": "bundle_3year", "name": "ITL Bridge AI", "badge": "3 Years",
        "products": ["itl_bridge_ai"], "termYears": 3, "basePrice": 63000,
        "currency": "₹", "period": "3 Years", "featured": 0, "cta": "Subscribe Now",
        "description": "ITL Bridge AI for three years.", "features": BUNDLE_FEATURES,
    },
    {
        "id": "bundle_5year", "name": "ITL Bridge AI", "badge": "5 Years",
        "products": ["itl_bridge_ai"], "termYears": 5, "basePrice": 90000,
        "currency": "₹", "period": "5 Years", "featured": 0, "cta": "Subscribe Now",
        "description": "ITL Bridge AI for five years.", "features": BUNDLE_FEATURES,
    },
    {
        "id": "pro", "name": "ITL AI", "badge": "ITL AI",
        "products": ["itl_ai"], "termYears": 1, "basePrice": 54000, "yearlyPrice": 54000,
        "currency": "₹", "period": "1 Year", "featured": 0, "cta": "Subscribe Now",
        "description": "For active CAs and advocates.",
        "features": [
            "Unlimited queries",
            "Income Tax + GST modules",
            "Notice reply & summarizer",
            "Priority email support",
            "18% GST Extra",
        ],
    },
]


def main() -> None:
    db = SessionLocal()
    try:
        page = db.query(CmsPage).filter(CmsPage.route == "pricing").first()
        if not page:
            raise SystemExit("No CMS page with route 'pricing' found — create it in Admin > CMS first.")
        content = dict(page.content or {})
        content["pricingPlans"] = PLANS
        page.content = content
        flag_modified(page, "content")
        db.commit()
        print("Pricing plans updated:", [p["id"] for p in PLANS])
    finally:
        db.close()


if __name__ == "__main__":
    main()
