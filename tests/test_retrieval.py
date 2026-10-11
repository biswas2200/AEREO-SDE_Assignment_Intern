import io
import zipfile
from pathlib import Path

from app.database import SessionLocal
from app.models import Certificate, Job, JobStatus
from tests.helpers import get_certificates, submit_job


def _submit_job_with_one_invalid_recipient(client, job_payload):
    job_payload["recipients"].append({"name": "Bad Email", "email": "not-an-email"})
    return submit_job(client, job_payload)


def test_list_certificates_filters_by_status(client, job_payload):
    job_id = _submit_job_with_one_invalid_recipient(client, job_payload)

    assert len(get_certificates(client, job_id)) == 4
    assert {c["status"] for c in get_certificates(client, job_id, status="SUCCESS")} == {"SUCCESS"}
    assert len(get_certificates(client, job_id, status="SUCCESS")) == 3
    assert [c["recipient_email"] for c in get_certificates(client, job_id, status="FAILED")] == ["not-an-email"]


def test_list_certificates_with_unknown_status_returns_422(client, job_payload):
    job_id = submit_job(client, job_payload)

    response = client.get(f"/api/jobs/{job_id}/certificates", params={"status": "DONE"})

    assert response.status_code == 422


def test_get_single_certificate(client, job_payload):
    job_id = submit_job(client, job_payload)
    certificate = get_certificates(client, job_id)[0]

    response = client.get(f"/api/certificates/{certificate['id']}")

    assert response.status_code == 200
    assert response.json() == certificate
    assert "file_path" not in response.json()


def test_download_single_certificate_returns_pdf(client, job_payload):
    job_id = submit_job(client, job_payload)
    certificate = get_certificates(client, job_id)[0]

    response = client.get(f"/api/certificates/{certificate['id']}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert f'{certificate["certificate_code"]}.pdf' in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")


def test_download_failed_certificate_returns_409(client, job_payload):
    job_id = _submit_job_with_one_invalid_recipient(client, job_payload)
    [failed] = get_certificates(client, job_id, status="FAILED")

    response = client.get(f"/api/certificates/{failed['id']}/download")

    assert response.status_code == 409


def test_download_certificate_with_missing_file_returns_404(client, job_payload):
    job_id = submit_job(client, job_payload)
    certificate = get_certificates(client, job_id)[0]
    with SessionLocal() as db:
        Path(db.get(Certificate, certificate["id"]).file_path).unlink()

    response = client.get(f"/api/certificates/{certificate['id']}/download")

    assert response.status_code == 404


def test_unknown_certificate_returns_404(client):
    assert client.get("/api/certificates/does-not-exist").status_code == 404
    assert client.get("/api/certificates/does-not-exist/download").status_code == 404


def test_download_job_zip_contains_only_successful_certificates(client, job_payload):
    job_id = _submit_job_with_one_invalid_recipient(client, job_payload)
    success_codes = {c["certificate_code"] for c in get_certificates(client, job_id, status="SUCCESS")}

    response = client.get(f"/api/jobs/{job_id}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {f"{code}.pdf" for code in success_codes}
        for name in archive.namelist():
            assert archive.read(name).startswith(b"%PDF")


def test_download_job_zip_while_processing_returns_409(client, job_payload):
    job_id = submit_job(client, job_payload)
    with SessionLocal() as db:
        db.get(Job, job_id).status = JobStatus.PROCESSING
        db.commit()

    assert client.get(f"/api/jobs/{job_id}/download").status_code == 409


def test_download_job_zip_without_successful_certificates_returns_404(client, job_payload):
    job_payload["recipients"] = [{"name": "Bad Email", "email": "not-an-email"}]
    job_id = submit_job(client, job_payload)

    assert client.get(f"/api/jobs/{job_id}/download").status_code == 404
