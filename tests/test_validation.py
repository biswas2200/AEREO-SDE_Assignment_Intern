import pytest

from app import config
from app.schemas import RecipientIn
from app.services.validator import validate_recipients
from tests.helpers import get_certificates, submit_job

# --- Request-level validation: the whole request is rejected with 422 ---


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_name", ""),
        ("event_name", "   "),
        ("event_name", None),
        ("issuer_name", ""),
        ("issue_date", "2026-02-30"),
        ("issue_date", "not-a-date"),
        ("recipients", []),
        ("recipients", "not-a-list"),
    ],
)
def test_request_level_validation_returns_422(client, job_payload, field, value):
    job_payload[field] = value

    response = client.post("/api/jobs", json=job_payload)

    assert response.status_code == 422


@pytest.mark.parametrize("field", ["event_name", "issuer_name", "issue_date", "recipients"])
def test_missing_required_field_returns_422(client, job_payload, field):
    del job_payload[field]

    assert client.post("/api/jobs", json=job_payload).status_code == 422


def test_too_many_recipients_returns_422(client, job_payload):
    job_payload["recipients"] = [
        {"name": f"Person {i}", "email": f"person{i}@example.com"}
        for i in range(config.MAX_RECIPIENTS_PER_JOB + 1)
    ]

    assert client.post("/api/jobs", json=job_payload).status_code == 422


# --- Per-recipient validation: bad rows fail, the rest of the job continues ---


def test_invalid_recipients_are_marked_failed_without_rejecting_job(client, job_payload):
    job_payload["recipients"] = [
        {"name": "Asha Verma", "email": "asha@example.com"},
        {"name": "Bad Email", "email": "not-an-email"},
        {"name": "   ", "email": "blank@example.com"},
        {"name": "Asha Again", "email": "ASHA@example.com"},
        {"name": "Rohan Mehta", "email": "rohan@example.com"},
    ]

    job_id = submit_job(client, job_payload)
    job = client.get(f"/api/jobs/{job_id}").json()

    assert job["status"] == "PARTIALLY_COMPLETED"
    assert (job["total"], job["succeeded"], job["failed"]) == (5, 2, 3)

    failed = {c["recipient_email"]: c["error"] for c in get_certificates(client, job_id, status="FAILED")}
    assert failed == {
        "not-an-email": "Invalid email address",
        "blank@example.com": "Name is required",
        "asha@example.com": "Duplicate email within this job",
    }

    succeeded = {c["recipient_name"] for c in get_certificates(client, job_id, status="SUCCESS")}
    assert succeeded == {"Asha Verma", "Rohan Mehta"}


def test_validator_trims_name_and_normalises_email():
    [result] = validate_recipients(
        [RecipientIn(name="  Asha Verma  ", email="  Asha@Example.COM ", course_name="  ")]
    )

    assert result.is_valid
    assert result.name == "Asha Verma"
    assert result.email == "asha@example.com"
    assert result.course_name is None


def test_validator_rejects_name_over_max_length():
    [result] = validate_recipients(
        [RecipientIn(name="x" * (config.MAX_NAME_LENGTH + 1), email="long@example.com")]
    )

    assert result.error == f"Name must be at most {config.MAX_NAME_LENGTH} characters"


@pytest.mark.parametrize("email", ["plainaddress", "missing-at.example.com", "a@b", "a b@example.com", ""])
def test_validator_rejects_malformed_emails(email):
    [result] = validate_recipients([RecipientIn(name="Someone", email=email)])

    assert result.error == "Invalid email address"


def test_validator_only_valid_recipients_claim_an_email():
    first, second, third = validate_recipients(
        [
            RecipientIn(name="", email="shared@example.com"),
            RecipientIn(name="Valid Owner", email="shared@example.com"),
            RecipientIn(name="Late Duplicate", email="shared@example.com"),
        ]
    )

    assert first.error == "Name is required"
    assert second.is_valid
    assert third.error == "Duplicate email within this job"
