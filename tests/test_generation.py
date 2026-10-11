"""PDF generation and isolation of individual generation failures."""

from datetime import date

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
    assert by_name["Rohan Mehta"]["error"] == "Generation failed: simulated rendering error"
    assert by_name["Asha Verma"]["status"] == "SUCCESS"
    assert by_name["Neha Iyer"]["status"] == "SUCCESS"
