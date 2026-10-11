"""Background job runner that generates the pending certificates of a job.

`process_job` is scheduled by POST /api/jobs (and POST /api/jobs/{id}/retry)
through FastAPI's BackgroundTasks. It only needs a job id and opens its own
database session, so the same function could be called from a task queue
worker (e.g. Celery) unchanged.
"""

import logging
from collections import deque

from sqlalchemy import select

from app import config, database
from app.models import Certificate, CertificateStatus, ErrorType, Job, JobStatus, utcnow

# Imported as a module (not `from ... import generate_certificate`) so tests can
# monkeypatch generator.generate_certificate and have this code pick it up.
from app.services import generator

logger = logging.getLogger(__name__)


def process_job(job_id: str) -> None:
    """Generate every PENDING certificate of a job, one at a time.

    This runs after the HTTP response has been sent, so it opens its own
    database session. Each certificate is committed separately: clients
    polling the job see progress, and a failure only affects that certificate.
    If failures pile up (see _should_halt), the job stops early as HALTED.
    """
    db = database.SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            logger.warning("Job %s not found, nothing to process", job_id)
            return

        job.status = JobStatus.PROCESSING
        db.commit()

        # Only PENDING rows: recipients that failed validation are already FAILED,
        # and a retry never regenerates certificates that succeeded.
        pending = db.scalars(
            select(Certificate).where(
                Certificate.job_id == job_id,
                Certificate.status == CertificateStatus.PENDING,
            )
        ).all()

        # Outcomes of the most recent attempts in this run (True = failed).
        # maxlen makes the deque drop the oldest entry automatically.
        recent_failures: deque[bool] = deque(maxlen=config.HALT_WINDOW_SIZE)

        for position, certificate in enumerate(pending, start=1):
            succeeded = _generate_one(certificate, job)
            recent_failures.append(not succeeded)

            remaining = len(pending) - position
            if remaining and _should_halt(recent_failures):
                _halt(job, recent_failures, remaining)
                db.commit()
                return

            db.commit()  # one commit per certificate = live progress for pollers

        job.status = _final_status(job)
        job.completed_at = utcnow()
        db.commit()
    except Exception:
        # Deliberately broad: this is the last line of defence for a task that
        # runs with no caller to report to. Unexpected errors (e.g. the database
        # going away) end the job as FAILED instead of leaving it PROCESSING.
        # Certificates that were already committed keep their state.
        logger.exception("Job %s stopped because of an unexpected error", job_id)
        db.rollback()
        job = db.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.error = "Processing stopped because of an unexpected error. Retry the job to resume."
            job.completed_at = utcnow()
            db.commit()
    finally:
        db.close()


def _generate_one(certificate: Certificate, job: Job) -> bool:
    """Generate one PDF, record the outcome on the certificate and job counters.

    Returns True on success. Any exception from the generator is caught here,
    so one bad certificate can never stop the loop in process_job.
    """
    try:
        file_path = generator.generate_certificate(certificate, job)
    except Exception as exc:
        logger.exception("Certificate %s failed to generate", certificate.certificate_code)
        certificate.status = CertificateStatus.FAILED
        # Only the exception type goes to API clients; the full message and
        # traceback (which may include server paths) are in the log above.
        certificate.error = f"Generation failed ({type(exc).__name__})"
        certificate.error_type = ErrorType.GENERATION
        job.failed += 1
        return False

    certificate.status = CertificateStatus.SUCCESS
    certificate.file_path = str(file_path)
    job.succeeded += 1
    return True


def _should_halt(recent_failures: deque[bool]) -> bool:
    """Halt rule: at least HALT_FAILURE_THRESHOLD failures in the last HALT_WINDOW_SIZE attempts.

    With the defaults that is "10 of the last 20 failed". The window has to be
    full first, so a handful of early failures never halts a job. Because only
    the most recent attempts count, the rule also catches a problem that starts
    halfway through a job (it fires 10 attempts after the problem begins).
    """
    window_is_full = len(recent_failures) == recent_failures.maxlen
    return window_is_full and sum(recent_failures) >= config.HALT_FAILURE_THRESHOLD


def _halt(job: Job, recent_failures: deque[bool], remaining: int) -> None:
    """Stop the job early. Finished certificates keep their state; the rest stay PENDING."""
    job.status = JobStatus.HALTED
    job.error = (
        f"Stopped early: {sum(recent_failures)} of the last {len(recent_failures)} certificates "
        f"failed to generate, so {remaining} were not attempted. Fix the cause, then retry the job to resume."
    )
    job.completed_at = utcnow()
    logger.warning("Job %s halted: %s", job.id, job.error)


def _final_status(job: Job) -> JobStatus:
    """Derive the final job status from its counters once every certificate is done."""
    if job.succeeded == job.total:
        return JobStatus.COMPLETED
    if job.succeeded == 0:
        return JobStatus.FAILED
    return JobStatus.PARTIALLY_COMPLETED
