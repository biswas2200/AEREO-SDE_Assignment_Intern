"""Background job runner that generates the pending certificates of a job.

`process_job` is scheduled by POST /api/jobs through FastAPI's BackgroundTasks.
It only needs a job id and opens its own database session, so the same
function could be called from a task queue worker (e.g. Celery) unchanged.
"""

import logging

from sqlalchemy import select

from app import database
from app.models import Certificate, CertificateStatus, Job, JobStatus, utcnow

# Imported as a module (not `from ... import generate_certificate`) so tests can
# monkeypatch generator.generate_certificate and have this code pick it up.
from app.services import generator

logger = logging.getLogger(__name__)


def process_job(job_id: str) -> None:
    """Generate every PENDING certificate of a job, one at a time.

    This runs after the HTTP response has been sent, so it opens its own
    database session. Each certificate is committed separately: clients
    polling the job see progress, and a failure only affects that certificate.
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
        # and re-running a job never regenerates certificates that succeeded.
        pending = db.scalars(
            select(Certificate).where(
                Certificate.job_id == job_id,
                Certificate.status == CertificateStatus.PENDING,
            )
        ).all()

        for certificate in pending:
            _generate_one(certificate, job)
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
            job.completed_at = utcnow()
            db.commit()
    finally:
        db.close()


def _generate_one(certificate: Certificate, job: Job) -> None:
    """Generate one PDF and record the outcome on the certificate and job counters.

    Any exception from the generator is caught here, so one bad certificate
    can never stop the loop in process_job.
    """
    try:
        file_path = generator.generate_certificate(certificate, job)
    except Exception as exc:
        logger.exception("Certificate %s failed to generate", certificate.certificate_code)
        certificate.status = CertificateStatus.FAILED
        certificate.error = f"Generation failed: {exc}"
        job.failed += 1
    else:
        # `else` runs only when the try block raised nothing.
        certificate.status = CertificateStatus.SUCCESS
        certificate.file_path = str(file_path)
        job.succeeded += 1


def _final_status(job: Job) -> JobStatus:
    """Derive the final job status from its counters once every certificate is done."""
    if job.succeeded == job.total:
        return JobStatus.COMPLETED
    if job.succeeded == 0:
        return JobStatus.FAILED
    return JobStatus.PARTIALLY_COMPLETED
