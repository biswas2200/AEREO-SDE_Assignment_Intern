"""Failure handling at scale: partial failures, systemic failures (early halt) and retry.

These tests run real 500-recipient jobs. The PDF generator is wrapped so that
chosen recipients fail while everyone else still gets a real PDF.

Halt rule under test (see config.HALT_WINDOW_SIZE / HALT_FAILURE_THRESHOLD):
a job stops early once at least 10 of its last 20 generation attempts failed.
"""

import io
import random
import zipfile
from pathlib import Path

import pytest

from app import config
from app.database import SessionLocal
from app.models import Certificate, Job, JobStatus
from app.services import generator
from tests.helpers import get_certificates, submit_job

JOB_SIZE = 500

# Captured before any test patches the module, so wrappers can always reach the real renderer.
REAL_GENERATE = generator.generate_certificate


def _recipients(count: int) -> list[dict]:
    return [{"name": f"Recipient {i}", "email": f"recipient{i}@example.com"} for i in range(1, count + 1)]


def _position(certificate: Certificate) -> int:
    """1-based position of a recipient in the request ("Recipient 42" -> 42)."""
    return int(certificate.recipient_name.rsplit(" ", 1)[1])


class FlakyGenerator:
    """Replaces generator.generate_certificate: fails at chosen positions, renders real PDFs otherwise."""

    def __init__(self, fails_at):
        self.fails_at = fails_at
        self.calls = 0

    def __call__(self, certificate, job):
        self.calls += 1
        if self.fails_at(_position(certificate)):
            raise RuntimeError("simulated rendering error")
        return REAL_GENERATE(certificate, job)


@pytest.fixture
def flaky_generator(monkeypatch):
    """Install a FlakyGenerator for this test and return it so the test can count calls."""

    def install(fails_at) -> FlakyGenerator:
        fake = FlakyGenerator(fails_at)
        monkeypatch.setattr(generator, "generate_certificate", fake)
        return fake

    return install


def _job(client, job_id: str) -> dict:
    return client.get(f"/api/jobs/{job_id}").json()


def _zip_names(client, job_id: str) -> set[str]:
    response = client.get(f"/api/jobs/{job_id}/download")
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert all(archive.read(name).startswith(b"%PDF") for name in archive.namelist())
        return set(archive.namelist())


def _file_path(certificate_id: str) -> Path:
    with SessionLocal() as db:
        return Path(db.get(Certificate, certificate_id).file_path)


# --- A few failures: the rest of the job is still delivered ---


def test_one_failure_in_500_still_delivers_the_other_499(client, job_payload, flaky_generator):
    flaky_generator(lambda position: position == 250)
    job_payload["recipients"] = _recipients(JOB_SIZE)

    job_id = submit_job(client, job_payload)
    job = _job(client, job_id)

    assert job["status"] == "PARTIALLY_COMPLETED"
    assert (job["succeeded"], job["failed"], job["pending"]) == (499, 1, 0)

    [bad] = get_certificates(client, job_id, status="FAILED")
    assert bad["recipient_name"] == "Recipient 250"
    assert bad["error_type"] == "GENERATION"
    assert bad["error"] == "Generation failed (RuntimeError)"

    zip_names = _zip_names(client, job_id)
    assert len(zip_names) == 499
    assert f"{bad['certificate_code']}.pdf" not in zip_names
    assert client.get(f"/api/certificates/{bad['id']}/download").status_code == 409


def test_two_random_failures_in_500_are_excluded_from_the_zip(client, job_payload, flaky_generator):
    bad_positions = set(random.Random(42).sample(range(1, JOB_SIZE + 1), 2))
    flaky_generator(lambda position: position in bad_positions)
    job_payload["recipients"] = _recipients(JOB_SIZE)

    job_id = submit_job(client, job_payload)
    job = _job(client, job_id)

    assert job["status"] == "PARTIALLY_COMPLETED"
    assert (job["succeeded"], job["failed"], job["pending"]) == (498, 2, 0)
    failed = get_certificates(client, job_id, status="FAILED")
    assert {c["recipient_name"] for c in failed} == {f"Recipient {p}" for p in bad_positions}
    zip_names = _zip_names(client, job_id)
    assert len(zip_names) == 498
    assert not {f"{c['certificate_code']}.pdf" for c in failed} & zip_names


def test_failures_at_the_start_below_the_threshold_do_not_halt(client, job_payload, flaky_generator):
    fake = flaky_generator(lambda position: position <= 5)
    job_payload["recipients"] = _recipients(JOB_SIZE)

    job = _job(client, submit_job(client, job_payload))

    assert job["status"] == "PARTIALLY_COMPLETED"
    assert (job["succeeded"], job["failed"], job["pending"]) == (495, 5, 0)
    assert fake.calls == JOB_SIZE


def test_scattered_failures_below_the_threshold_do_not_halt(client, job_payload, flaky_generator):
    # Every third certificate fails: at most 7 failures in any 20 attempts, below the threshold of 10.
    fake = flaky_generator(lambda position: position % 3 == 0)
    job_payload["recipients"] = _recipients(JOB_SIZE)

    job = _job(client, submit_job(client, job_payload))

    assert job["status"] == "PARTIALLY_COMPLETED"
    assert (job["succeeded"], job["failed"], job["pending"]) == (334, 166, 0)
    assert fake.calls == JOB_SIZE


def test_pdf_written_before_a_failure_is_not_in_the_zip(client, job_payload, monkeypatch):
    def write_then_fail(certificate, job):
        path = REAL_GENERATE(certificate, job)
        if _position(certificate) == 2:
            raise RuntimeError("post-processing failed after the PDF was written")
        return path

    monkeypatch.setattr(generator, "generate_certificate", write_then_fail)
    job_payload["recipients"] = _recipients(3)

    job_id = submit_job(client, job_payload)
    [bad] = get_certificates(client, job_id, status="FAILED")

    # The file exists on disk, but the job's database state is the source of truth.
    assert (config.OUTPUT_DIR / job_id / f"{bad['certificate_code']}.pdf").exists()
    zip_names = _zip_names(client, job_id)
    assert len(zip_names) == 2
    assert f"{bad['certificate_code']}.pdf" not in zip_names


# --- Systemic failure: the job stops early instead of failing all 500 ---


def test_job_halts_early_when_every_certificate_fails(client, job_payload, flaky_generator):
    fake = flaky_generator(lambda _: True)
    job_payload["recipients"] = _recipients(JOB_SIZE)

    job_id = submit_job(client, job_payload)
    job = _job(client, job_id)

    assert job["status"] == "HALTED"
    assert fake.calls == config.HALT_WINDOW_SIZE  # 20 attempts, not 500
    assert (job["succeeded"], job["failed"], job["pending"]) == (0, 20, 480)
    assert "retry" in job["error"].lower()
    assert len(get_certificates(client, job_id, status="PENDING")) == 480
    assert client.get(f"/api/jobs/{job_id}/download").status_code == 404  # nothing succeeded


def test_job_halts_early_when_only_one_certificate_would_pass(client, job_payload, flaky_generator):
    fake = flaky_generator(lambda position: position != 1)
    job_payload["recipients"] = _recipients(JOB_SIZE)

    job = _job(client, submit_job(client, job_payload))

    assert job["status"] == "HALTED"
    assert fake.calls == config.HALT_WINDOW_SIZE
    assert (job["succeeded"], job["failed"], job["pending"]) == (1, 19, 480)


def test_systemic_failure_mid_run_keeps_the_finished_certificates(client, job_payload, flaky_generator):
    # The first 30 PDFs succeed, then something breaks for good (e.g. the disk fills up).
    fake = flaky_generator(lambda position: position > 30)
    job_payload["recipients"] = _recipients(JOB_SIZE)

    job_id = submit_job(client, job_payload)
    job = _job(client, job_id)

    # Halts on attempt 40: attempts 21-40 hold 10 successes and 10 failures.
    assert job["status"] == "HALTED"
    assert fake.calls == 40
    assert (job["succeeded"], job["failed"], job["pending"]) == (30, 10, 460)
    successes = get_certificates(client, job_id, status="SUCCESS")
    assert _zip_names(client, job_id) == {f"{c['certificate_code']}.pdf" for c in successes}


def test_job_that_fails_on_its_last_attempts_finishes_instead_of_halting(client, job_payload, flaky_generator):
    # Exactly one window of failures and nothing left to protect: report a normal final status.
    flaky_generator(lambda _: True)
    job_payload["recipients"] = _recipients(config.HALT_WINDOW_SIZE)

    job = _job(client, submit_job(client, job_payload))

    assert job["status"] == "FAILED"
    assert (job["succeeded"], job["failed"], job["pending"]) == (0, 20, 0)


# --- Retry: resume where the job stopped, keep what already succeeded ---


def test_retry_resumes_a_halted_job_without_regenerating_finished_certificates(
    client, job_payload, flaky_generator
):
    flaky_generator(lambda position: position > 30)
    job_payload["recipients"] = _recipients(JOB_SIZE)
    job_id = submit_job(client, job_payload)
    finished = {c["id"]: _file_path(c["id"]).stat().st_mtime_ns for c in get_certificates(client, job_id, "SUCCESS")}

    fixed = flaky_generator(lambda _: False)  # the cause has been fixed
    response = client.post(f"/api/jobs/{job_id}/retry")

    assert response.status_code == 202
    job = _job(client, job_id)
    assert job["status"] == "COMPLETED"
    assert (job["succeeded"], job["failed"], job["pending"]) == (500, 0, 0)
    assert job["error"] is None
    assert fixed.calls == 470  # 10 failed + 460 never attempted; the 30 good ones are untouched
    assert {cid: _file_path(cid).stat().st_mtime_ns for cid in finished} == finished
    assert len(_zip_names(client, job_id)) == 500


def test_retry_only_regenerates_generation_failures(client, job_payload, flaky_generator):
    recipients = _recipients(50)
    recipients[9]["email"] = "not-an-email"
    recipients[19]["email"] = "also-not-an-email"
    job_payload["recipients"] = recipients
    flaky_generator(lambda position: position in {5, 6})
    job_id = submit_job(client, job_payload)

    job = _job(client, job_id)
    assert (job["succeeded"], job["failed"]) == (46, 4)
    error_types = sorted(c["error_type"] for c in get_certificates(client, job_id, status="FAILED"))
    assert error_types == ["GENERATION", "GENERATION", "VALIDATION", "VALIDATION"]

    fixed = flaky_generator(lambda _: False)
    assert client.post(f"/api/jobs/{job_id}/retry").status_code == 202

    job = _job(client, job_id)
    assert job["status"] == "PARTIALLY_COMPLETED"
    assert (job["succeeded"], job["failed"], job["pending"]) == (48, 2, 0)
    assert fixed.calls == 2
    assert {c["error_type"] for c in get_certificates(client, job_id, status="FAILED")} == {"VALIDATION"}


def test_retry_of_a_running_job_returns_409(client, job_payload):
    job_id = submit_job(client, job_payload)
    with SessionLocal() as db:
        db.get(Job, job_id).status = JobStatus.PROCESSING
        db.commit()

    assert client.post(f"/api/jobs/{job_id}/retry").status_code == 409


def test_retry_with_nothing_to_retry_returns_409(client, job_payload):
    job_id = submit_job(client, job_payload)  # every certificate succeeds

    assert client.post(f"/api/jobs/{job_id}/retry").status_code == 409


def test_retry_of_unknown_job_returns_404(client):
    assert client.post("/api/jobs/does-not-exist/retry").status_code == 404


# --- Progress and size limits ---


def test_progress_is_committed_after_every_certificate(client, job_payload, monkeypatch):
    seen_by_poller = []

    def record_progress(certificate, job):
        # A separate session sees only committed data, like a client polling the job.
        with SessionLocal() as poller:
            stored = poller.get(Job, job.id)
            seen_by_poller.append(stored.succeeded + stored.failed)
        return REAL_GENERATE(certificate, job)

    monkeypatch.setattr(generator, "generate_certificate", record_progress)
    job_payload["recipients"] = _recipients(25)

    submit_job(client, job_payload)

    assert seen_by_poller == list(range(25))


def test_job_with_the_maximum_of_1000_recipients(client, job_payload):
    job_payload["recipients"] = _recipients(config.MAX_RECIPIENTS_PER_JOB)

    job_id = submit_job(client, job_payload)
    job = _job(client, job_id)

    assert job["status"] == "COMPLETED"
    assert (job["succeeded"], job["failed"], job["pending"]) == (1000, 0, 0)
    assert len(_zip_names(client, job_id)) == 1000


def test_zip_relies_on_certificate_status_not_on_a_recorded_file(client, job_payload, flaky_generator):
    flaky_generator(lambda position: position == 2)
    job_payload["recipients"] = _recipients(3)
    job_id = submit_job(client, job_payload)
    [bad] = get_certificates(client, job_id, status="FAILED")
    good = get_certificates(client, job_id, status="SUCCESS")[0]

    # Simulate a failed certificate that still has a file on record (e.g. a partial write).
    with SessionLocal() as db:
        db.get(Certificate, bad["id"]).file_path = str(_file_path(good["id"]))
        db.commit()

    zip_names = _zip_names(client, job_id)
    assert len(zip_names) == 2
    assert f"{bad['certificate_code']}.pdf" not in zip_names
