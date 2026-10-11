"""Renders the single, fixed certificate template to a PDF using ReportLab.

ReportLab coordinates are in points (1/72 inch) with the origin at the
bottom-left corner of the page, so a larger y means higher up the page.
Landscape A4 is about 842 x 595 points.
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from app import config
from app.models import Certificate, Job

PAGE_WIDTH, PAGE_HEIGHT = landscape(A4)
CENTER_X = PAGE_WIDTH / 2
BODY_TEXT_WIDTH = PAGE_WIDTH - 160  # widest a line in the body may be
FOOTER_BLOCK_WIDTH = 190

# Built-in PDF fonts: no font files to ship, but they only cover Latin characters.
FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_ITALIC = "Helvetica-Oblique"

PRIMARY = colors.HexColor("#1F3A5F")  # dark blue: title, outer border, headline
ACCENT = colors.HexColor("#B8860B")  # gold: inner border and divider lines
MUTED = colors.HexColor("#555555")  # grey: connecting phrases and labels


def generate_certificate(certificate: Certificate, job: Job) -> Path:
    """Write the certificate PDF to OUTPUT_DIR/<job_id>/<code>.pdf and return its path.

    Raises on any rendering or file-system error. The processor catches it and
    marks only this certificate as FAILED.
    """
    job_dir = config.OUTPUT_DIR / job.id
    job_dir.mkdir(parents=True, exist_ok=True)
    file_path = job_dir / f"{certificate.certificate_code}.pdf"

    pdf = Canvas(str(file_path), pagesize=landscape(A4))
    pdf.setTitle(f"Certificate of Completion - {certificate.recipient_name}")
    pdf.setAuthor(job.issuer_name)

    _draw_border(pdf)
    _draw_body(pdf, certificate, job)
    _draw_footer(pdf, certificate, job)

    pdf.showPage()
    pdf.save()  # nothing is written to disk until save()
    return file_path


def _draw_border(pdf: Canvas) -> None:
    """Thick blue outer frame with a thin gold frame inside it."""
    pdf.setStrokeColor(PRIMARY)
    pdf.setLineWidth(4)
    pdf.rect(24, 24, PAGE_WIDTH - 48, PAGE_HEIGHT - 48)

    pdf.setStrokeColor(ACCENT)
    pdf.setLineWidth(1.5)
    pdf.rect(36, 36, PAGE_WIDTH - 72, PAGE_HEIGHT - 72)


def _draw_body(pdf: Canvas, certificate: Certificate, job: Job) -> None:
    """Title, recipient name and what the certificate was awarded for, top to bottom."""
    _draw_text(pdf, "Certificate of Completion", CENTER_X, 470, FONT_BOLD, 36, PRIMARY)
    _draw_rule(pdf, CENTER_X, 452, width=240)

    _draw_text(pdf, "This is to certify that", CENTER_X, 400, FONT_REGULAR, 16, MUTED)

    _draw_text(pdf, certificate.recipient_name, CENTER_X, 345, FONT_BOLD, 40, colors.black, BODY_TEXT_WIDTH)
    _draw_rule(pdf, CENTER_X, 330, width=420)

    _draw_text(pdf, "has successfully completed", CENTER_X, 290, FONT_REGULAR, 16, MUTED)

    # With a course name, the course is the headline and the event is context.
    headline = certificate.course_name or job.event_name
    _draw_text(pdf, headline, CENTER_X, 255, FONT_BOLD, 24, PRIMARY, BODY_TEXT_WIDTH)
    if certificate.course_name:
        _draw_text(pdf, f"as part of {job.event_name}", CENTER_X, 228, FONT_ITALIC, 14, MUTED, BODY_TEXT_WIDTH)


def _draw_footer(pdf: Canvas, certificate: Certificate, job: Job) -> None:
    """Three labelled blocks along the bottom: date (left), code (centre), issuer (right)."""
    issue_date = f"{job.issue_date.day} {job.issue_date:%B %Y}"  # e.g. "1 October 2026"
    _draw_footer_block(pdf, PAGE_WIDTH * 0.22, issue_date, "Date of Issue")
    _draw_footer_block(pdf, CENTER_X, certificate.certificate_code, "Certificate Code")
    _draw_footer_block(pdf, PAGE_WIDTH * 0.78, job.issuer_name, "Issued by")


def _draw_footer_block(pdf: Canvas, x: float, value: str, label: str) -> None:
    """A bold value on a gold line with a small grey label underneath."""
    _draw_text(pdf, value, x, 118, FONT_BOLD, 13, colors.black, FOOTER_BLOCK_WIDTH)
    _draw_rule(pdf, x, 110, width=FOOTER_BLOCK_WIDTH)
    _draw_text(pdf, label, x, 96, FONT_REGULAR, 10, MUTED)


def _draw_text(
    pdf: Canvas,
    text: str,
    x: float,
    y: float,
    font: str,
    size: int,
    color: colors.Color,
    max_width: float | None = None,
) -> None:
    """Draw text centred on x. With max_width, shrink the font until the text fits."""
    if max_width is not None:
        size = _fit_font_size(text, font, size, max_width)
    pdf.setFillColor(color)
    pdf.setFont(font, size)
    pdf.drawCentredString(x, y, text)


def _draw_rule(pdf: Canvas, center_x: float, y: float, width: float) -> None:
    """Thin gold horizontal line centred on center_x."""
    pdf.setStrokeColor(ACCENT)
    pdf.setLineWidth(1)
    pdf.line(center_x - width / 2, y, center_x + width / 2, y)


def _fit_font_size(text: str, font_name: str, max_size: int, max_width: float, min_size: int = 10) -> int:
    """Largest font size (down to min_size) at which the text fits within max_width.

    Long names are scaled down instead of running off the page. Names are
    capped at 100 characters, so even the longest still fits at min_size.
    """
    size = max_size
    while size > min_size and stringWidth(text, font_name, size) > max_width:
        size -= 1
    return size
