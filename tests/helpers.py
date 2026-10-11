"""Small helpers shared by the API tests."""


def submit_job(client, payload):
    """Submit a job and return the job id (processing has already finished)."""
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 202, response.text
    return response.json()["id"]


def get_certificates(client, job_id, status=None):
    params = {"status": status} if status else None
    response = client.get(f"/api/jobs/{job_id}/certificates", params=params)
    assert response.status_code == 200, response.text
    return response.json()
