"""Tests that call the background processor directly instead of going through HTTP."""

from datetime import date

from app.database import SessionLocal
from app.models import Certificate, CertificateStatus, Job, JobStatus
from app.services import processor


def _create_pending_job(recipient_names: list[str]) -> str:
    """Insert a job whose certificates are all PENDING, without processing it."""
    with SessionLocal() as db:
        job = Job(
            event_name="Processor Test",
            issuer_name="AEREO Academy",
            issue_date=date(2026, 10, 1),
            total=len(recipient_names),
        )
        job.certificates = [
            Certificate(recipient_name=name, recipient_email=f"person{i}@example.com")
            for i, name in enumerate(recipient_names)
        ]
        db.add(job)
        db.commit()
        return job.id


def test_process_job_with_unknown_id_does_nothing():
    processor.process_job("does-not-exist")

    with SessionLocal() as db:
        assert db.query(Job).count() == 0


def test_unexpected_error_marks_job_failed_and_keeps_finished_certificates(monkeypatch):
    job_id = _create_pending_job(["Asha Verma", "Rohan Mehta"])

    def crash(_job):
        raise RuntimeError("database went away")

    # Fails after every certificate has been generated, outside the per-certificate try/except.
    monkeypatch.setattr(processor, "_final_status", crash)

    processor.process_job(job_id)

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job.status == JobStatus.FAILED
        assert job.completed_at is not None
        assert {c.status for c in job.certificates} == {CertificateStatus.SUCCESS}
