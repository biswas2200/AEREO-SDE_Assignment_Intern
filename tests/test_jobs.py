from datetime import datetime, timedelta

from tests.helpers import get_certificates, submit_job


def test_create_job_returns_202_with_pending_job(client, job_payload):
    response = client.post("/api/jobs", json=job_payload)

    assert response.status_code == 202
    body = response.json()
    assert body["id"]
    assert body["status"] == "PENDING"
    assert body["event_name"] == job_payload["event_name"]
    assert body["total"] == 3
    assert body["succeeded"] == 0
    assert body["failed"] == 0
    assert body["completed_at"] is None


def test_create_job_stores_one_certificate_per_recipient(client, job_payload):
    job_id = submit_job(client, job_payload)

    certificates = get_certificates(client, job_id)

    assert len(certificates) == 3
    assert {c["recipient_email"] for c in certificates} == {r["email"] for r in job_payload["recipients"]}
    assert all(c["certificate_code"].startswith("CERT-") for c in certificates)
    assert len({c["certificate_code"] for c in certificates}) == 3


def test_job_status_and_progress_after_processing(client, job_payload):
    job_id = submit_job(client, job_payload)

    response = client.get(f"/api/jobs/{job_id}")

    assert response.status_code == 200
    job = response.json()
    assert job["status"] == "COMPLETED"
    assert job["total"] == 3
    assert job["succeeded"] == 3
    assert job["failed"] == 0
    assert job["progress_percent"] == 100.0
    assert job["completed_at"] is not None


def test_job_with_only_invalid_recipients_is_failed(client, job_payload):
    job_payload["recipients"] = [
        {"name": "", "email": "blank@example.com"},
        {"name": "No Email", "email": "not-an-email"},
    ]
    job_id = submit_job(client, job_payload)

    job = client.get(f"/api/jobs/{job_id}").json()

    assert job["status"] == "FAILED"
    assert job["succeeded"] == 0
    assert job["failed"] == 2
    assert job["progress_percent"] == 100.0


def test_get_unknown_job_returns_404(client):
    assert client.get("/api/jobs/does-not-exist").status_code == 404
    assert client.get("/api/jobs/does-not-exist/certificates").status_code == 404
    assert client.get("/api/jobs/does-not-exist/download").status_code == 404


def test_timestamps_are_returned_in_utc(client, job_payload):
    job_id = submit_job(client, job_payload)

    job = client.get(f"/api/jobs/{job_id}").json()
    certificate = get_certificates(client, job_id)[0]

    for value in (job["created_at"], job["completed_at"], certificate["created_at"]):
        assert datetime.fromisoformat(value).utcoffset() == timedelta(0), value
