"""Endpoints for submitting generation jobs and following their progress.

Endpoints are plain `def` functions (not `async def`): FastAPI runs them in a
thread pool, so blocking database and file work never stalls the event loop.
"""

import io
import zipfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import DbSession
from app.models import Certificate, CertificateStatus, ErrorType, Job, JobStatus
from app.schemas import CertificateRead, JobCreate, JobRead
from app.services.processor import process_job
from app.services.validator import validate_recipients

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

JOB_NOT_FOUND = "Job not found"
JOB_STILL_PROCESSING = "Job is still processing, try again once it has finished"
NO_CERTIFICATES_TO_DOWNLOAD = "No generated certificates are available for this job"
NOTHING_TO_RETRY = "Job has no failed generations or unattempted certificates to retry"


@router.post("", response_model=JobRead, status_code=202)
def create_job(payload: JobCreate, background_tasks: BackgroundTasks, db: DbSession):
    """Store the job with one certificate row per recipient and start generation in the background.

    Returns 202 Accepted straight away; poll GET /api/jobs/{job_id} for progress.
    """
    recipients = validate_recipients(payload.recipients)

    job = Job(
        event_name=payload.event_name,
        issuer_name=payload.issuer_name,
        issue_date=payload.issue_date,
        total=len(recipients),
        # Invalid recipients are already final, so they count as failed straight away.
        failed=sum(1 for recipient in recipients if not recipient.is_valid),
    )
    for recipient in recipients:
        job.certificates.append(
            Certificate(
                recipient_name=recipient.name,
                recipient_email=recipient.email,
                course_name=recipient.course_name,
                status=CertificateStatus.PENDING if recipient.is_valid else CertificateStatus.FAILED,
                error=recipient.error,
                error_type=None if recipient.is_valid else ErrorType.VALIDATION,
            )
        )

    db.add(job)  # the cascade on Job.certificates saves the certificate rows too
    db.commit()

    # Runs after the response has been sent. Only the id is passed: the task
    # opens its own session because this request's session will be closed.
    background_tasks.add_task(process_job, job.id)
    return job


@router.get("/{job_id}", response_model=JobRead, responses={404: {"description": JOB_NOT_FOUND}})
def get_job(job_id: str, db: DbSession):
    """Current status, success/failure counters and progress of a job."""
    return _get_job_or_404(db, job_id)


@router.get(
    "/{job_id}/certificates",
    response_model=list[CertificateRead],
    responses={404: {"description": JOB_NOT_FOUND}},
)
def list_job_certificates(job_id: str, db: DbSession, status: CertificateStatus | None = None):
    """List a job's certificates, optionally filtered by status (e.g. ?status=FAILED)."""
    _get_job_or_404(db, job_id)

    query = select(Certificate).where(Certificate.job_id == job_id)
    if status is not None:
        query = query.where(Certificate.status == status)
    return db.scalars(query.order_by(Certificate.created_at)).all()


@router.get(
    "/{job_id}/download",
    response_class=Response,
    responses={
        200: {"content": {"application/zip": {}}, "description": "Zip of the generated PDFs"},
        404: {"description": f"{JOB_NOT_FOUND}, or {NO_CERTIFICATES_TO_DOWNLOAD.lower()}"},
        409: {"description": JOB_STILL_PROCESSING},
    },
)
def download_job_certificates(job_id: str, db: DbSession):
    """Download every successfully generated certificate of a finished job as one zip."""
    job = _get_job_or_404(db, job_id)
    if job.status in (JobStatus.PENDING, JobStatus.PROCESSING):
        raise HTTPException(status_code=409, detail=JOB_STILL_PROCESSING)

    certificates = db.scalars(
        select(Certificate).where(
            Certificate.job_id == job_id,
            Certificate.status == CertificateStatus.SUCCESS,
        )
    ).all()
    # Skip any file that has been removed from disk instead of failing the whole zip.
    files = [
        (certificate.certificate_code, Path(certificate.file_path))
        for certificate in certificates
        if certificate.file_path and Path(certificate.file_path).exists()
    ]
    if not files:
        raise HTTPException(status_code=404, detail=NO_CERTIFICATES_TO_DOWNLOAD)

    # Built in memory: each PDF is a few KB, so even 1000 certificates is ~1.4 MB.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for code, path in files:
            archive.write(path, arcname=f"{code}.pdf")

    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="certificates-{job_id}.zip"'},
    )


@router.post(
    "/{job_id}/retry",
    response_model=JobRead,
    status_code=202,
    responses={
        404: {"description": JOB_NOT_FOUND},
        409: {"description": f"{JOB_STILL_PROCESSING}, or {NOTHING_TO_RETRY.lower()}"},
    },
)
def retry_job(job_id: str, background_tasks: BackgroundTasks, db: DbSession):
    """Resume a finished job: regenerate failed certificates and any that were never attempted.

    Certificates that already succeeded are kept as they are. Validation
    failures are not retried, because the same data would fail again.
    """
    job = _get_job_or_404(db, job_id)
    if job.status in (JobStatus.PENDING, JobStatus.PROCESSING):
        raise HTTPException(status_code=409, detail=JOB_STILL_PROCESSING)

    retryable = db.scalars(
        select(Certificate).where(
            Certificate.job_id == job_id,
            Certificate.status == CertificateStatus.FAILED,
            Certificate.error_type == ErrorType.GENERATION,
        )
    ).all()
    # job.pending covers certificates left untouched by a halt or a crash.
    if not retryable and job.pending == 0:
        raise HTTPException(status_code=409, detail=NOTHING_TO_RETRY)

    for certificate in retryable:
        certificate.status = CertificateStatus.PENDING
        certificate.error = None
        certificate.error_type = None
    job.failed -= len(retryable)
    job.status = JobStatus.PENDING
    job.error = None
    job.completed_at = None
    db.commit()

    # process_job only picks up PENDING certificates, so it resumes where the job stopped.
    background_tasks.add_task(process_job, job.id)
    return job


def _get_job_or_404(db: Session, job_id: str) -> Job:
    """Load a job by primary key or stop the request with a 404."""
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=JOB_NOT_FOUND)
    return job
