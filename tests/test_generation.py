"""PDF generation and isolation of individual generation failures."""

from datetime import date

from reportlab.pdfbase.pdfmetrics import stringWidth
from sqlalchemy import select

from app import config
from app.database import SessionLocal
from app.models import Certificate, Job
from app.services import generator
from tests.helpers import get_certificates, submit_job


def test_generated_certificate_is_valid_pdf(client, job_payload):
    job_id = submit_job(client, job_payload)

    with SessionLocal() as db:
        certificates = db.scalars(select(Certificate).where(Certificate.job_id == job_id)).all()

    assert len(certificates) == 3
    for certificate in certificates:
        pdf_path = config.OUTPUT_DIR / job_id / f"{certificate.certificate_code}.pdf"
        assert certificate.file_path == str(pdf_path)
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 0
        assert pdf_path.read_bytes().startswith(b"%PDF")


def test_generator_handles_long_names(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path)
    job = Job(id="job-1", event_name="Event", issuer_name="Issuer", issue_date=date(2026, 10, 1))
    certificate = Certificate(
        recipient_name="A Very Long Recipient Name " * 3,
        recipient_email="long@example.com",
        certificate_code="CERT-TEST0001",
    )

    pdf_path = generator.generate_certificate(certificate, job)

    assert pdf_path == tmp_path / "job-1" / "CERT-TEST0001.pdf"
    assert pdf_path.read_bytes().startswith(b"%PDF")


def test_one_generation_failure_does_not_stop_other_certificates(client, job_payload, monkeypatch):
    real_generate = generator.generate_certificate

    def generate_or_fail(certificate, job):
        if certificate.recipient_name == "Rohan Mehta":
            raise RuntimeError("simulated rendering error")
        return real_generate(certificate, job)

    monkeypatch.setattr(generator, "generate_certificate", generate_or_fail)

    job_id = submit_job(client, job_payload)
    job = client.get(f"/api/jobs/{job_id}").json()

    assert job["status"] == "PARTIALLY_COMPLETED"
    assert (job["succeeded"], job["failed"], job["progress_percent"]) == (2, 1, 100.0)

    by_name = {c["recipient_name"]: c for c in get_certificates(client, job_id)}
    assert by_name["Rohan Mehta"]["status"] == "FAILED"
    assert by_name["Rohan Mehta"]["error"] == "Generation failed (RuntimeError)"
    assert by_name["Asha Verma"]["status"] == "SUCCESS"
    assert by_name["Neha Iyer"]["status"] == "SUCCESS"


def test_short_text_keeps_the_maximum_font_size():
    assert generator._fit_font_size("Asha Verma", generator.FONT_BOLD, 40, generator.BODY_TEXT_WIDTH) == 40


def test_long_text_is_shrunk_until_it_fits():
    name = "Maximilian Alexander Christopher Montgomery-Wellington the Third"

    size = generator._fit_font_size(name, generator.FONT_BOLD, 40, generator.BODY_TEXT_WIDTH)

    assert 10 < size < 40
    assert stringWidth(name, generator.FONT_BOLD, size) <= generator.BODY_TEXT_WIDTH
    assert stringWidth(name, generator.FONT_BOLD, size + 1) > generator.BODY_TEXT_WIDTH


def test_font_size_never_drops_below_the_minimum():
    assert generator._fit_font_size("x" * 1000, generator.FONT_BOLD, 40, generator.BODY_TEXT_WIDTH) == 10


def test_generation_error_does_not_leak_internal_details(client, job_payload, monkeypatch):
    def fail_with_a_path(_certificate, _job):
        raise NotADirectoryError("[Errno 20] Not a directory: '/srv/internal/output'")

    monkeypatch.setattr(generator, "generate_certificate", fail_with_a_path)

    job_id = submit_job(client, job_payload)
    certificate = get_certificates(client, job_id)[0]

    assert certificate["error"] == "Generation failed (NotADirectoryError)"
    assert "/srv/internal" not in certificate["error"]
