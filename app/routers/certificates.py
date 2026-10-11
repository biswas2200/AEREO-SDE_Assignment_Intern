"""Endpoints for reading and downloading individual certificates."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import DbSession
from app.models import Certificate, CertificateStatus
from app.schemas import CertificateRead

router = APIRouter(prefix="/api/certificates", tags=["certificates"])

CERTIFICATE_NOT_FOUND = "Certificate not found"
CERTIFICATE_FILE_NOT_FOUND = "Certificate file not found"
CERTIFICATE_NOT_READY = "Only certificates with status SUCCESS can be downloaded"


@router.get(
    "/{certificate_id}",
    response_model=CertificateRead,
    responses={404: {"description": CERTIFICATE_NOT_FOUND}},
)
def get_certificate(certificate_id: str, db: DbSession):
    """Metadata of a single certificate, including its status and error (if any)."""
    return _get_certificate_or_404(db, certificate_id)


@router.get(
    "/{certificate_id}/download",
    response_class=FileResponse,
    responses={
        200: {"content": {"application/pdf": {}}, "description": "The certificate PDF"},
        404: {"description": f"{CERTIFICATE_NOT_FOUND}, or its file is missing"},
        409: {"description": CERTIFICATE_NOT_READY},
    },
)
def download_certificate(certificate_id: str, db: DbSession):
    """Download the PDF of one certificate."""
    certificate = _get_certificate_or_404(db, certificate_id)

    # 409 Conflict: the certificate exists but is not in a downloadable state.
    if certificate.status != CertificateStatus.SUCCESS:
        raise HTTPException(
            status_code=409,
            detail=f"Certificate is {certificate.status}. {CERTIFICATE_NOT_READY}",
        )
    if not certificate.file_path or not Path(certificate.file_path).exists():
        raise HTTPException(status_code=404, detail=CERTIFICATE_FILE_NOT_FOUND)

    # FileResponse streams the file from disk and sets Content-Disposition
    # so browsers and `curl -OJ` save it as <certificate_code>.pdf.
    return FileResponse(
        certificate.file_path,
        media_type="application/pdf",
        filename=f"{certificate.certificate_code}.pdf",
    )


def _get_certificate_or_404(db: Session, certificate_id: str) -> Certificate:
    """Load a certificate by primary key or stop the request with a 404."""
    certificate = db.get(Certificate, certificate_id)
    if certificate is None:
        raise HTTPException(status_code=404, detail=CERTIFICATE_NOT_FOUND)
    return certificate
