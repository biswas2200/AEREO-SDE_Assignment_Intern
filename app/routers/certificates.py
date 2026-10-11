"""Endpoints for reading and downloading individual certificates."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Certificate, CertificateStatus
from app.schemas import CertificateRead

router = APIRouter(prefix="/api/certificates", tags=["certificates"])


@router.get("/{certificate_id}", response_model=CertificateRead)
def get_certificate(certificate_id: str, db: Session = Depends(get_db)):
    return _get_certificate_or_404(db, certificate_id)


@router.get("/{certificate_id}/download", response_class=FileResponse)
def download_certificate(certificate_id: str, db: Session = Depends(get_db)):
    certificate = _get_certificate_or_404(db, certificate_id)

    if certificate.status != CertificateStatus.SUCCESS:
        raise HTTPException(
            status_code=409,
            detail=f"Certificate is {certificate.status}, only SUCCESS certificates can be downloaded",
        )
    if not certificate.file_path or not Path(certificate.file_path).exists():
        raise HTTPException(status_code=404, detail="Certificate file not found")

    return FileResponse(
        certificate.file_path,
        media_type="application/pdf",
        filename=f"{certificate.certificate_code}.pdf",
    )


def _get_certificate_or_404(db: Session, certificate_id: str) -> Certificate:
    certificate = db.get(Certificate, certificate_id)
    if certificate is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    return certificate
