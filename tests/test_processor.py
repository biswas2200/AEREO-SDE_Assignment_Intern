"""Tests that call the background processor directly instead of going through HTTP."""

from collections import deque
from datetime import date

import pytest

from app import config
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
        assert "retry" in job.error.lower()
        assert {c.status for c in job.certificates} == {CertificateStatus.SUCCESS}


@pytest.mark.parametrize(
    ("failed", "attempts", "should_halt"),
    [
        (10, 20, True),  # threshold reached: 10 of the last 20 failed
        (20, 20, True),
        (9, 20, False),  # one below the threshold
        (0, 20, False),
        (19, 19, False),  # window not full yet, e.g. a small job
    ],
)
def test_halt_rule(failed, attempts, should_halt):
    recent_failures = deque([True] * failed + [False] * (attempts - failed), maxlen=config.HALT_WINDOW_SIZE)

    assert processor._should_halt(recent_failures) is should_halt


def test_halt_rule_only_looks_at_the_most_recent_attempts():
    recent_failures = deque(maxlen=config.HALT_WINDOW_SIZE)
    for _ in range(50):
        recent_failures.append(True)  # an old burst of failures...
    for _ in range(config.HALT_WINDOW_SIZE):
        recent_failures.append(False)  # ...pushed out by 20 successes

    assert processor._should_halt(recent_failures) is False
