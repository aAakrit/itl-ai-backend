"""
Shared branding for every generated document (user exports, payment
receipts) — one place so "ITL AI branding" means the same thing
everywhere, matching the frontend's actual theme (src/config/theme.ts,
src/config/site.ts) rather than an independently-invented palette.

The real logo asset lives at a URL this backend has no network path to
fetch at generation time, so branding here is text/color-based — the same
"ITL AI" wordmark + "Income Tax Library" subtitle treatment the frontend's
own Logo.tsx renders — rather than an embedded raster image.

FONT: reportlab's built-in Helvetica (a base-14 PDF font) has no glyph for
₹ (U+20B9) — it silently renders as a black box/tofu. DejaVu Sans does, so
it's bundled here (app/assets/fonts/) rather than relying on whatever the
deployment server happens to have installed system-wide, and registered
once at import time for every PDF this app generates.
"""

import os

BRAND_NAME = "ITL AI"
BRAND_SUBTITLE = "Income Tax Library"
BRAND_WEBSITE = "www.incometaxlibrary.com"
BRAND_COLOR_HEX = "7A1025"  # matches frontend theme.ts `primary`
BRAND_COLOR_RGB = (0x7A, 0x10, 0x25)

_FONTS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts")
PDF_FONT_REGULAR = "Helvetica"
PDF_FONT_BOLD = "Helvetica-Bold"


def _register_unicode_fonts():
    """Registers the bundled DejaVu Sans as PDF_FONT_REGULAR/BOLD so every
    reportlab document in this app can render ₹ and other non-Latin1
    characters correctly. Falls back to Helvetica (no ₹ glyph, but never
    crashes generation) if the bundled files are somehow missing."""
    global PDF_FONT_REGULAR, PDF_FONT_BOLD

    regular_path = os.path.join(_FONTS_DIR, "DejaVuSans.ttf")
    bold_path = os.path.join(_FONTS_DIR, "DejaVuSans-Bold.ttf")

    if not (os.path.exists(regular_path) and os.path.exists(bold_path)):
        return

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    try:
        pdfmetrics.registerFont(TTFont("DejaVuSans", regular_path))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", bold_path))
        PDF_FONT_REGULAR = "DejaVuSans"
        PDF_FONT_BOLD = "DejaVuSans-Bold"
    except Exception:
        pass  # Helvetica fallback — degrades gracefully rather than 500ing receipt generation


_register_unicode_fonts()


def docx_add_letterhead(doc, subtitle: str | None = None):
    """Adds the ITL AI wordmark letterhead to the top of a python-docx Document."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(BRAND_NAME)
    run.bold = True
    run.font.size = Pt(20)
    run.font.color.rgb = RGBColor(*BRAND_COLOR_RGB)
    p.paragraph_format.space_after = Pt(2)

    p2 = doc.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run2 = p2.add_run(subtitle or BRAND_SUBTITLE)
    run2.font.size = Pt(9)
    run2.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)

    doc.add_paragraph()  # spacer
    return doc


def pdf_letterhead_flowables(subtitle: str | None = None):
    """Returns a list of reportlab flowables for the ITL AI letterhead."""
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, Spacer

    brand_style = ParagraphStyle(
        "brand",
        fontName=PDF_FONT_BOLD,
        fontSize=20,
        leading=24,  # explicit leading > fontSize — without this the
                     # following paragraph can render overlapping it
        alignment=1,  # center
        textColor=rl_colors.HexColor(f"#{BRAND_COLOR_HEX}"),
        spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        "brand_subtitle",
        fontName=PDF_FONT_REGULAR,
        fontSize=9,
        leading=12,
        alignment=1,
        textColor=rl_colors.HexColor("#6b7280"),
    )
    return [
        Paragraph(BRAND_NAME, brand_style),
        Paragraph(subtitle or BRAND_SUBTITLE, subtitle_style),
        Spacer(1, 16),
    ]


def xlsx_brand_header_fill():
    from openpyxl.styles import PatternFill

    return PatternFill(start_color=BRAND_COLOR_HEX, end_color=BRAND_COLOR_HEX, fill_type="solid")
