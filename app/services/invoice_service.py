"""
Payment invoice/receipt generation.

Layout matches the client's own sample receipt exactly (Billing
Information / Order Details / Payment Summary sections, same field
labels), re-skinned with ITL AI branding instead of the sample's plain
blue. Works identically for a manual/cash payment or a completed Paytm
payment — both end up as a `Payment` row with the same snapshot fields,
so this doesn't need to know which gateway produced it.
"""

import io
from datetime import datetime
from typing import Optional

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.payment import Payment
from app.services import branding

SUPPORT_PHONE_1 = "+91-9001597011"
SUPPORT_PHONE_2 = "+91-9982608890"
SUPPORT_EMAIL = "info@incometaxlibrary.com"


def _billing_cycle_label(payment: Payment) -> str:
    cycle = (payment.gateway_response or {}).get("billing_cycle")
    if cycle == "yearly":
        return "One Year Subscription"
    if cycle == "monthly":
        return "One Month Subscription"
    return f"{payment.plan_name} Subscription"


def _fmt_amount(v) -> str:
    return f"{v:,.2f}"


def _fmt_date(v: Optional[datetime]) -> str:
    if not v:
        return "—"
    return v.strftime("%A, %d %B %Y")


def build_receipt_pdf(payment: Payment) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=48, rightMargin=48, topMargin=40, bottomMargin=40)

    brand_color = colors.HexColor(f"#{branding.BRAND_COLOR_HEX}")
    title_style = ParagraphStyle("receipt_title", fontName=branding.PDF_FONT_BOLD, fontSize=22, alignment=1, textColor=brand_color, spaceAfter=18, leading=26)
    section_style = ParagraphStyle("section", fontName=branding.PDF_FONT_BOLD, fontSize=12, textColor=brand_color, spaceBefore=14, spaceAfter=6)
    label_style = ParagraphStyle("label", fontName=branding.PDF_FONT_REGULAR, fontSize=10, textColor=colors.HexColor("#374151"), leading=15)
    bold_style = ParagraphStyle("bold", fontName=branding.PDF_FONT_BOLD, fontSize=11)
    note_style = ParagraphStyle("note", fontName=branding.PDF_FONT_REGULAR, fontSize=9, textColor=colors.HexColor("#b91c1c"), leading=13)
    footer_style = ParagraphStyle("footer", fontName=branding.PDF_FONT_REGULAR, fontSize=9.5, textColor=colors.HexColor("#374151"), spaceBefore=4)

    elements = list(branding.pdf_letterhead_flowables())
    elements.append(Paragraph("Receipt", title_style))

    elements.append(Paragraph("Billing Information", section_style))
    elements.append(HRFlowable(width="100%", thickness=1.2, color=brand_color, spaceAfter=8))
    billing_table = Table(
        [
            [Paragraph(f"<b>Name:</b> {payment.customer_name or '—'}", label_style), Paragraph("<b>Company:</b> —", label_style)],
            [Paragraph(f"<b>Email:</b> {payment.customer_email or '—'}", label_style), Paragraph(f"<b>Phone:</b> {payment.customer_mobile or '—'}", label_style)],
            [Paragraph(f"<b>GSTIN:</b> {payment.customer_gstin or 'N/A'}", label_style), Paragraph("", label_style)],
        ],
        colWidths=[260, 220],
    )
    billing_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    elements.append(billing_table)
    elements.append(Paragraph(f"<b>Billing Address:</b> {payment.customer_address or '—'}", label_style))

    elements.append(Paragraph("Order Details", section_style))
    elements.append(HRFlowable(width="100%", thickness=1.2, color=brand_color, spaceAfter=8))
    order_table = Table(
        [
            [Paragraph("Order Number:", label_style), Paragraph(payment.order_id, label_style)],
            [Paragraph("Order Date:", label_style), Paragraph(_fmt_date(payment.paid_at or payment.created_at), label_style)],
        ],
        colWidths=[150, 330],
    )
    order_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    elements.append(order_table)

    elements.append(Paragraph("Payment Summary", section_style))
    elements.append(HRFlowable(width="100%", thickness=1.2, color=brand_color, spaceAfter=8))
    summary_table = Table(
        [
            [Paragraph("Product:", label_style), Paragraph(_billing_cycle_label(payment), label_style)],
            [Paragraph("Amount:", label_style), Paragraph(f"₹{_fmt_amount(payment.base_price)}", label_style)],
            [Paragraph(f"GST ({payment.gst_rate}%):", label_style), Paragraph(f"₹{_fmt_amount(payment.gst_amount)}", label_style)],
            [Paragraph("<b>Total Payable:</b>", bold_style), Paragraph(f"<b>₹{_fmt_amount(payment.payable_amount)}</b>", bold_style)],
        ],
        colWidths=[150, 330],
    )
    summary_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, -1), (-1, -1), 8)]))
    elements.append(summary_table)

    elements.append(Spacer(1, 16))
    elements.append(Paragraph(f"We thank you for being a subscriber of {branding.BRAND_SUBTITLE} ({branding.BRAND_WEBSITE}).", footer_style))
    elements.append(Paragraph(f"Your Payment Transaction ID: {payment.gateway_txn_id or '—'}.", footer_style))
    elements.append(Paragraph("Your subscription is now active." if payment.status == "success" else "Your login will be activated shortly.", footer_style))
    elements.append(Spacer(1, 10))
    elements.append(
        Paragraph(
            f"Note: If any error occurs, please contact us on {SUPPORT_PHONE_1}, {SUPPORT_PHONE_2} or email us: {SUPPORT_EMAIL}.",
            note_style,
        )
    )

    doc.build(elements)
    return buf.getvalue()


def build_receipt_docx(payment: Payment) -> bytes:
    doc = Document()
    branding.docx_add_letterhead(doc)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("Receipt")
    run.bold = True
    run.font.size = Pt(20)
    run.font.color.rgb = RGBColor(0x7A, 0x10, 0x25)
    doc.add_paragraph()

    def section(name: str):
        p = doc.add_paragraph()
        r = p.add_run(name)
        r.bold = True
        r.font.size = Pt(13)
        r.font.color.rgb = RGBColor(0x7A, 0x10, 0x25)

    def kv_table(rows: list[tuple[str, str]]):
        table = doc.add_table(rows=0, cols=2)
        for label, value in rows:
            cells = table.add_row().cells
            cells[0].text = label
            cells[1].text = value
        return table

    section("Billing Information")
    kv_table(
        [
            ("Name", payment.customer_name or "—"),
            ("Email", payment.customer_email or "—"),
            ("Phone", payment.customer_mobile or "—"),
            ("GSTIN", payment.customer_gstin or "N/A"),
            ("Billing Address", payment.customer_address or "—"),
        ]
    )
    doc.add_paragraph()

    section("Order Details")
    kv_table(
        [
            ("Order Number", payment.order_id),
            ("Order Date", _fmt_date(payment.paid_at or payment.created_at)),
        ]
    )
    doc.add_paragraph()

    section("Payment Summary")
    kv_table(
        [
            ("Product", _billing_cycle_label(payment)),
            ("Amount", f"₹{_fmt_amount(payment.base_price)}"),
            (f"GST ({payment.gst_rate}%)", f"₹{_fmt_amount(payment.gst_amount)}"),
            ("Total Payable", f"₹{_fmt_amount(payment.payable_amount)}"),
        ]
    )

    doc.add_paragraph()
    doc.add_paragraph(f"We thank you for being a subscriber of {branding.BRAND_SUBTITLE} ({branding.BRAND_WEBSITE}).")
    doc.add_paragraph(f"Your Payment Transaction ID: {payment.gateway_txn_id or '—'}.")
    doc.add_paragraph("Your subscription is now active." if payment.status == "success" else "Your login will be activated shortly.")
    p = doc.add_paragraph()
    r = p.add_run(
        f"Note: If any error occurs, please contact us on {SUPPORT_PHONE_1}, {SUPPORT_PHONE_2} "
        f"or email us: {SUPPORT_EMAIL}."
    )
    r.font.color.rgb = RGBColor(0xB9, 0x1C, 0x1C)
    r.font.size = Pt(9)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_receipt(payment: Payment, fmt: str = "pdf") -> tuple[bytes, str, str]:
    """Returns (file bytes, content-type, filename)."""
    filename_base = payment.invoice_number or payment.receipt_number or payment.order_id

    if fmt == "docx":
        return (
            build_receipt_docx(payment),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            f"receipt-{filename_base}.docx",
        )
    return build_receipt_pdf(payment), "application/pdf", f"receipt-{filename_base}.pdf"
