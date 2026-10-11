"""Endpoints for submitting generation jobs and following their progress."""

import io
import zipfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Certificate, CertificateStatus, Job, JobStatus
from app.schemas import CertificateRead, JobCreate, JobRead
from app.services.processor import process_job
from app.services.validator import validate_recipients

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("", response_model=JobRead, status_code=202)
def create_job(payload: JobCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Store the job with one certificate row per recipient and start generation in the background."""
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
            )
        )

    db.add(job)
    db.commit()

    background_tasks.add_task(process_job, job.id)
    return job


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: str, db: Session = Depends(get_db)):
    return _get_job_or_404(db, job_id)


@router.get("/{job_id}/certificates", response_model=list[CertificateRead])
def list_job_certificates(
    job_id: str,
    status: CertificateStatus | None = None,
    db: Session = Depends(get_db),
):
    """List a job's certificates, optionally filtered by status (?status=FAILED)."""
    _get_job_or_404(db, job_id)

    query = select(Certificate).where(Certificate.job_id == job_id)
    if status is not None:
        query = query.where(Certificate.status == status)
    return db.scalars(query.order_by(Certificate.created_at)).all()


@router.get("/{job_id}/download")
def download_job_certificates(job_id: str, db: Session = Depends(get_db)):
    """Download every successfully generated certificate of a finished job as a zip."""
    job = _get_job_or_404(db, job_id)
    if job.status in (JobStatus.PENDING, JobStatus.PROCESSING):
        raise HTTPException(status_code=409, detail="Job is still processing, try again once it has finished")

    certificates = db.scalars(
        select(Certificate).where(
            Certificate.job_id == job_id,
            Certificate.status == CertificateStatus.SUCCESS,
        )
    ).all()
    files = [
        (certificate.certificate_code, Path(certificate.file_path))
        for certificate in certificates
        if certificate.file_path and Path(certificate.file_path).exists()
    ]
    if not files:
        raise HTTPException(status_code=404, detail="No generated certificates are available for this job")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for code, path in files:
            archive.write(path, arcname=f"{code}.pdf")

    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="certificates-{job_id}.zip"'},
    )


def _get_job_or_404(db: Session, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
