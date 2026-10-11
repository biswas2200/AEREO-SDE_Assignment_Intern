"""Renders the single, fixed certificate template to a PDF using ReportLab."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from app import config
from app.models import Certificate, Job

PAGE_WIDTH, PAGE_HEIGHT = landscape(A4)
CENTER_X = PAGE_WIDTH / 2

PRIMARY = colors.HexColor("#1F3A5F")
ACCENT = colors.HexColor("#B8860B")
MUTED = colors.HexColor("#555555")


def generate_certificate(certificate: Certificate, job: Job) -> Path:
    """Write the certificate PDF to OUTPUT_DIR/<job_id>/<code>.pdf and return its path."""
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
    pdf.save()
    return file_path


def _draw_border(pdf: Canvas) -> None:
    pdf.setStrokeColor(PRIMARY)
    pdf.setLineWidth(4)
    pdf.rect(24, 24, PAGE_WIDTH - 48, PAGE_HEIGHT - 48)

    pdf.setStrokeColor(ACCENT)
    pdf.setLineWidth(1.5)
    pdf.rect(36, 36, PAGE_WIDTH - 72, PAGE_HEIGHT - 72)


def _draw_body(pdf: Canvas, certificate: Certificate, job: Job) -> None:
    max_text_width = PAGE_WIDTH - 160

    pdf.setFillColor(PRIMARY)
    pdf.setFont("Helvetica-Bold", 36)
    pdf.drawCentredString(CENTER_X, 470, "Certificate of Completion")
    _draw_rule(pdf, CENTER_X, 452, width=240)

    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 16)
    pdf.drawCentredString(CENTER_X, 400, "This is to certify that")

    name = certificate.recipient_name
    pdf.setFillColor(colors.black)
    pdf.setFont("Helvetica-Bold", _fit_font_size(name, "Helvetica-Bold", 40, max_text_width))
    pdf.drawCentredString(CENTER_X, 345, name)
    _draw_rule(pdf, CENTER_X, 330, width=420)

    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 16)
    pdf.drawCentredString(CENTER_X, 290, "has successfully completed")

    # With a course name, the course is the headline and the event is context.
    headline = certificate.course_name or job.event_name
    pdf.setFillColor(PRIMARY)
    pdf.setFont("Helvetica-Bold", _fit_font_size(headline, "Helvetica-Bold", 24, max_text_width))
    pdf.drawCentredString(CENTER_X, 255, headline)

    if certificate.course_name:
        subtitle = f"as part of {job.event_name}"
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica-Oblique", _fit_font_size(subtitle, "Helvetica-Oblique", 14, max_text_width))
        pdf.drawCentredString(CENTER_X, 228, subtitle)


def _draw_footer(pdf: Canvas, certificate: Certificate, job: Job) -> None:
    issue_date = f"{job.issue_date.day} {job.issue_date:%B %Y}"
    _draw_footer_block(pdf, PAGE_WIDTH * 0.22, issue_date, "Date of Issue")
    _draw_footer_block(pdf, CENTER_X, certificate.certificate_code, "Certificate Code")
    _draw_footer_block(pdf, PAGE_WIDTH * 0.78, job.issuer_name, "Issued by")


def _draw_footer_block(pdf: Canvas, x: float, value: str, label: str) -> None:
    block_width = 190

    pdf.setFillColor(colors.black)
    pdf.setFont("Helvetica-Bold", _fit_font_size(value, "Helvetica-Bold", 13, block_width))
    pdf.drawCentredString(x, 118, value)
    _draw_rule(pdf, x, 110, width=block_width)

    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 10)
    pdf.drawCentredString(x, 96, label)


def _draw_rule(pdf: Canvas, center_x: float, y: float, width: float) -> None:
    pdf.setStrokeColor(ACCENT)
    pdf.setLineWidth(1)
    pdf.line(center_x - width / 2, y, center_x + width / 2, y)


def _fit_font_size(text: str, font_name: str, max_size: int, max_width: float, min_size: int = 10) -> int:
    """Largest font size (down to min_size) at which the text fits within max_width."""
    size = max_size
    while size > min_size and stringWidth(text, font_name, size) > max_width:
        size -= 1
    return size
