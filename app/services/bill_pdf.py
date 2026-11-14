"""PDF layout of a bill — follows the paper bill the business already uses."""

import io
from datetime import date
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.config import SELLER_ADDRESS, SELLER_EMAIL, SELLER_GSTIN, SELLER_NAME, SELLER_PHONE, SELLER_WEBSITE
from app.services import branding

BRAND = colors.HexColor(f"#{branding.BRAND_COLOR_HEX}")
GRID = colors.HexColor("#9ca3af")
HEAD_BG = colors.HexColor("#fff8e1")


def _style(name, **kw):
    base = dict(fontName=branding.PDF_FONT_REGULAR, fontSize=9, leading=12, textColor=colors.HexColor("#111827"))
    base.update(kw)
    return ParagraphStyle(name, **base)


def _esc(v) -> str:
    s = "" if v is None else str(v)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")


def _amt(v) -> str:
    return f"{Decimal(str(v or 0)):.2f}"


def _date(v) -> str:
    return v.strftime("%d-%m-%Y") if isinstance(v, date) else ""


def build_bill_pdf(bill, *, proforma: bool = False) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=28, rightMargin=28, topMargin=28, bottomMargin=28)
    width = A4[0] - 56

    label = _style("label", textColor=colors.HexColor("#4b5563"), fontSize=8.5)
    value = _style("value")
    bold = _style("bold", fontName=branding.PDF_FONT_BOLD)
    right = _style("right", alignment=2)
    right_bold = _style("rightb", alignment=2, fontName=branding.PDF_FONT_BOLD)
    center_bold = _style("centerb", alignment=1, fontName=branding.PDF_FONT_BOLD, fontSize=8.5)

    def P(text, style=value):
        return Paragraph(_esc(text), style)

    elements = []

    head_name = _style("hname", fontName=branding.PDF_FONT_BOLD, fontSize=14, alignment=1, textColor=BRAND, leading=18)
    head = _style("head", alignment=1, fontSize=8.5, leading=11.5)
    header = Table(
        [
            [Paragraph(_esc(SELLER_NAME), head_name)],
            [Paragraph(_esc(SELLER_ADDRESS), head)],
            [Paragraph(_esc(f"E mail : {SELLER_EMAIL} | website : {SELLER_WEBSITE} | Tele. {SELLER_PHONE}"), head)],
            [Paragraph(_esc(f"GSTIN: {SELLER_GSTIN}"), _style("hg", alignment=1, fontName=branding.PDF_FONT_BOLD, fontSize=9))],
        ],
        colWidths=[width],
    )
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HEAD_BG),
        ("BOX", (0, 0), (-1, -1), 0.6, GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    elements.append(header)

    title = "PROFORMA INVOICE" if proforma else "TAX INVOICE"
    sub = "Not a tax invoice — a tax invoice is issued once payment is received." if proforma else ""
    if getattr(bill, "status", "active") == "cancelled":
        title, sub = "CANCELLED — TAX INVOICE", "This bill has been cancelled and is not valid."
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(_esc(title), _style("title", fontName=branding.PDF_FONT_BOLD, fontSize=13, alignment=1, textColor=BRAND, leading=16)))
    if sub:
        elements.append(Paragraph(_esc(sub), _style("sub", alignment=1, textColor=colors.HexColor("#b91c1c"), fontSize=8)))
    elements.append(Spacer(1, 6))

    # --- customer block ---------------------------------------------------
    c = [width * 0.14, width * 0.36, width * 0.14, width * 0.36]
    cust = Table(
        [
            [P("Bill No", label), P(bill.bill_number, bold), P("Date", label), P(_date(bill.bill_date))],
            [P("Name", label), P(bill.customer_name), "", ""],
            [P("Address", label), P(bill.customer_address), "", ""],
            [P("Dist", label), P(bill.customer_city), P("PIN", label), P(bill.customer_pin)],
            [P("State", label), P(bill.customer_state), P("Mob", label), P(bill.customer_mobile)],
            [P("Tele", label), P(bill.customer_tele), P("E-mail", label), P(bill.customer_email)],
            [P("GSTIN", label), P(bill.customer_gstin), "", ""],
        ],
        colWidths=c,
    )
    cust.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("SPAN", (1, 1), (3, 1)), ("SPAN", (1, 2), (3, 2)), ("SPAN", (1, 6), (3, 6)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(cust)

    # --- items ------------------------------------------------------------
    lines = list(bill.lines or [])
    rows = [[P("S. No", center_bold), P("Particulars", center_bold), P("HSN", center_bold), P("Subscription", center_bold), P("Amount", center_bold)]]
    for i in range(max(4, len(lines))):
        if i < len(lines):
            ln = lines[i]
            rows.append([P(i + 1), P(ln.get("particulars")), P(ln.get("hsn")), P(ln.get("period")), P(_amt(ln.get("amount")), right)])
        else:
            rows.append([P(i + 1), "", "", "", ""])
    items = Table(rows, colWidths=[width * 0.07, width * 0.45, width * 0.12, width * 0.18, width * 0.18])
    items.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(items)

    # --- totals + payment -------------------------------------------------
    pay_bits = []
    if bill.payment_ref:
        pay_bits.append(f"Ref / Cheque No: {bill.payment_ref}")
    if bill.payment_date:
        pay_bits.append(f"Date: {_date(bill.payment_date)}")
    if bill.payment_amount is not None:
        pay_bits.append(f"Rs: {_amt(bill.payment_amount)}")
    if bill.bank:
        pay_bits.append(f"Bank: {bill.bank}")
    pay_text = "   ".join(pay_bits) or ""

    def pct(r):
        r = Decimal(str(r or 0))
        return f"{r.normalize():f}" if r else "0"

    t = Table(
        [
            [P("TOTAL INVOICE AMOUNT IN WORDS", label), P("TOTAL AMOUNT (BEFORE TAX)", label), P(_amt(bill.total_before_tax), right)],
            [P(bill.amount_in_words, bold), P(f"ADD CGST @ {pct(bill.cgst_rate)}%", label), P(_amt(bill.cgst_amount), right)],
            ["", P(f"ADD SGST @ {pct(bill.sgst_rate)}%", label), P(_amt(bill.sgst_amount), right)],
            ["", P(f"ADD IGST @ {pct(bill.igst_rate)}%", label), P(_amt(bill.igst_amount), right)],
            [P(pay_text), P("TOTAL TAX AMOUNT", label), P(_amt(bill.total_tax), right)],
            [P(("Notes: " + bill.notes) if bill.notes else "Notes:", label), P("TOTAL AMOUNT AFTER TAX", bold), P(_amt(bill.total_after_tax), right_bold)],
            ["", P("GST ON REVERSE CHARGE", label), P(bill.reverse_charge or "", right)],
        ],
        colWidths=[width * 0.50, width * 0.31, width * 0.19],
    )
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("SPAN", (0, 1), (0, 3)), ("SPAN", (0, 5), (0, 6)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(t)

    elements.append(Spacer(1, 10))
    elements.append(Paragraph(_esc("This is a computer-generated document."), _style("foot", fontSize=8, textColor=colors.HexColor("#6b7280"))))

    doc.build(elements)
    return buf.getvalue()
