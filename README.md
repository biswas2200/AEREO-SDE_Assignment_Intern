# Bulk Certificate Generator

[![CI](https://github.com/biswas2200/AEREO-SDE_Assignment_Intern/actions/workflows/ci.yml/badge.svg)](https://github.com/biswas2200/AEREO-SDE_Assignment_Intern/actions/workflows/ci.yml)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=biswas2200_AEREO-SDE_Assignment_Intern&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=biswas2200_AEREO-SDE_Assignment_Intern)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=biswas2200_AEREO-SDE_Assignment_Intern&metric=coverage)](https://sonarcloud.io/summary/new_code?id=biswas2200_AEREO-SDE_Assignment_Intern)

A FastAPI backend that generates PDF certificates for many recipients in a single request. A client submits one job with up to 1000 recipients, the API validates each recipient, generates a certificate for every valid one in the background, and exposes endpoints to track progress and download the results individually or as a zip.

**Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.x, SQLite (configurable), Pydantic v2, ReportLab, pytest.

## Project structure

```
app/
  main.py               FastAPI app, router registration, table creation on startup
  config.py             Settings read from environment variables
  database.py           Engine, session factory, SQLite WAL settings, DbSession dependency
  models.py             Job and Certificate tables, status and error-type enums
  schemas.py            Request/response models (request-level validation)
  routers/
    jobs.py             Submit jobs, poll status, list certificates, zip download
    certificates.py     Single certificate metadata and PDF download
  services/
    validator.py        Per-recipient validation (name, email, duplicates)
    generator.py        The certificate template, rendered with ReportLab
    processor.py        Background job runner, including the early-halt rule
tests/                  pytest suite (temporary SQLite DB and output dir)
sample_request.json     Example job with valid and invalid recipients
requirements.txt        Direct dependencies (pinned)
requirements.lock       Every transitive dependency, pinned with hashes (used by CI)
pyproject.toml          pytest and coverage settings
sonar-project.properties  SonarCloud project settings
.github/workflows/ci.yml  CI: tests, coverage and SonarCloud analysis
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configuration

| Variable       | Default                      | Purpose                                     |
|----------------|------------------------------|---------------------------------------------|
| `DATABASE_URL` | `sqlite:///./certificates.db` | Any SQLAlchemy URL (Postgres needs a driver such as `psycopg`) |
| `OUTPUT_DIR`   | `./output`                   | Where PDFs are written: `OUTPUT_DIR/<job_id>/<certificate_code>.pdf` |

Tables are created automatically on startup. There are no migrations, so after pulling a version that changes the tables, delete the local `certificates.db` (and its `-wal`/`-shm` files) and let the app recreate it.

## Running the application

```bash
uvicorn app.main:app --reload
```

The API runs on `http://localhost:8000`. Interactive docs (Swagger UI) are at `http://localhost:8000/docs`: expand an endpoint, click **Try it out**, edit the request and click **Execute**. For `POST /api/jobs`, paste the contents of `sample_request.json` as the body. Swagger lists the possible error responses for every endpoint.

## Running the tests

```bash
pytest -v
```

With a coverage report (the suite covers 100% of `app/`):

```bash
pytest --cov --cov-report=term-missing
```

The tests use a temporary SQLite database and a per-test output directory, so they never touch local data. FastAPI's `TestClient` runs background tasks before the request returns, which keeps the tests deterministic without sleeps or polling.

`tests/test_failure_scenarios.py` runs full 500- and 1000-recipient jobs, wrapping the PDF generator so chosen recipients fail while the rest get real PDFs. It covers isolated failures (and that they are left out of the zip), the halt rule, retry, and progress being visible after every certificate. To check that the suite catches real bugs, 23 deliberate bugs were introduced one at a time (e.g. letting one failure stop the job, building the zip from the output folder, an off-by-one in the halt rule). Every one of them makes at least one test fail.

## API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/jobs` | Submit a generation job. Returns `202 Accepted` with the job. |
| `GET`  | `/api/jobs/{job_id}` | Job status, counters (`succeeded`, `failed`, `pending`), `progress_percent` and a job-level `error`. |
| `GET`  | `/api/jobs/{job_id}/certificates` | All certificates of the job. Optional `?status=PENDING\|SUCCESS\|FAILED`. |
| `GET`  | `/api/jobs/{job_id}/download` | Zip of every successfully generated PDF. |
| `POST` | `/api/jobs/{job_id}/retry` | Resume a finished job: regenerate generation failures and unattempted certificates. Returns `202`. |
| `GET`  | `/api/certificates/{certificate_id}` | Metadata of one certificate. |
| `GET`  | `/api/certificates/{certificate_id}/download` | The PDF of one certificate. |
| `GET`  | `/health` | Liveness check. |

Error responses:

| Code | When |
|------|------|
| `404` | Unknown job or certificate id; the PDF file is missing on disk; a finished job has no successful certificates to zip |
| `409` | Downloading a certificate that is not `SUCCESS`; downloading a zip or retrying while the job is still `PENDING`/`PROCESSING`; retrying a job with nothing to retry |
| `422` | Malformed request (see validation below) |

### Request body

```json
{
  "event_name": "AEREO Drone Tech Summit 2026",
  "issuer_name": "AEREO Academy",
  "issue_date": "2026-10-01",
  "recipients": [
    { "name": "Asha Verma", "email": "asha.verma@example.com", "course_name": "UAV Flight Fundamentals" },
    { "name": "Neha Iyer", "email": "neha.iyer@example.com" }
  ]
}
```

| Field | Rules |
|-------|-------|
| `event_name`, `issuer_name` | Required, 1-200 characters after trimming |
| `issue_date` | Required, a real date in `YYYY-MM-DD` form |
| `recipients` | Required, 1-1000 entries |
| `recipients[].name` | Required; blank or over 100 characters fails that recipient only |
| `recipients[].email` | Required; an invalid or duplicate email fails that recipient only |
| `recipients[].course_name` | Optional, up to 200 characters |

`course_name` is optional per recipient. When it is present the certificate headlines the course and mentions the event underneath; otherwise the event name is the headline.

## Usage walkthrough

These commands use `sample_request.json`, which has 5 recipients: 3 valid, 1 with an invalid email and 1 with a duplicate email.

**1. Submit a job**

```bash
curl -s -X POST http://localhost:8000/api/jobs -H "Content-Type: application/json" -d @sample_request.json
```

```json
{
  "id": "ee39dfb1-3dc5-44f3-9be4-e8e5591c0def",
  "event_name": "AEREO Drone Tech Summit 2026",
  "issuer_name": "AEREO Academy",
  "issue_date": "2026-10-01",
  "status": "PENDING",
  "total": 5,
  "succeeded": 0,
  "failed": 2,
  "pending": 3,
  "progress_percent": 40.0,
  "error": null,
  "created_at": "2026-10-11T20:06:48.451288Z",
  "completed_at": null
}
```

The two invalid recipients are already counted as failed, so progress starts at 40%. To keep the id in a shell variable:

```bash
JOB_ID=$(curl -s -X POST http://localhost:8000/api/jobs -H "Content-Type: application/json" -d @sample_request.json | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
```

**2. Poll the job status**

```bash
curl -s http://localhost:8000/api/jobs/$JOB_ID
```

Repeat until `status` is no longer `PENDING` or `PROCESSING`. A small job like this one finishes almost immediately.

```json
{
  "id": "ee39dfb1-3dc5-44f3-9be4-e8e5591c0def",
  "status": "PARTIALLY_COMPLETED",
  "total": 5,
  "succeeded": 3,
  "failed": 2,
  "pending": 0,
  "progress_percent": 100.0,
  "completed_at": "2026-10-11T20:06:48.486254Z",
  "...": "..."
}
```

**3. See which recipients failed and why**

```bash
curl -s "http://localhost:8000/api/jobs/$JOB_ID/certificates?status=FAILED"
```

```json
[
  {
    "id": "97df5a76-3c41-4514-a2b5-6a0f56f44820",
    "recipient_name": "Vikram Singh",
    "recipient_email": "vikram.singh@example",
    "certificate_code": "CERT-7939-E25B-62A4",
    "status": "FAILED",
    "error": "Invalid email address",
    "error_type": "VALIDATION",
    "...": "..."
  },
  {
    "id": "0bd80e97-a851-49fa-b4bb-81e92b3b9a89",
    "recipient_name": "Asha V.",
    "recipient_email": "asha.verma@example.com",
    "certificate_code": "CERT-5F15-3C00-3AA7",
    "status": "FAILED",
    "error": "Duplicate email within this job",
    "error_type": "VALIDATION",
    "...": "..."
  }
]
```

**4. Download one certificate**

Take a certificate id from `GET /api/jobs/$JOB_ID/certificates?status=SUCCESS`, then:

```bash
curl -OJ http://localhost:8000/api/certificates/<certificate_id>/download
```

This saves the PDF as `<certificate_code>.pdf`.

**5. Download all certificates of the job as a zip**

```bash
curl -o certificates.zip http://localhost:8000/api/jobs/$JOB_ID/download
```

The zip contains one `<certificate_code>.pdf` per successful certificate.

**6. Retry**

```bash
curl -s -X POST http://localhost:8000/api/jobs/$JOB_ID/retry
```

For this job, retry returns `409`: its two failures are validation failures, which a retry would not fix. Retry is meant for generation failures and halted jobs; see [Failure handling](#failure-handling) for a demo.

## Job and certificate lifecycle

```
Job:          PENDING -> PROCESSING -> COMPLETED            (every certificate succeeded)
                                    -> PARTIALLY_COMPLETED  (some succeeded, some failed)
                                    -> FAILED               (none succeeded, or the job crashed)
                                    -> HALTED               (stopped early: too many recent failures)
              any finished state --retry--> PENDING

Certificate:  PENDING -> SUCCESS
              PENDING -> FAILED     (error_type GENERATION: PDF generation raised an error)
              FAILED                (error_type VALIDATION: set at submission)
              FAILED (GENERATION) --retry--> PENDING
```

`progress_percent` is `(succeeded + failed) / total * 100`, i.e. the share of certificates that reached a final state, and `pending` is `total - succeeded - failed`. Timestamps are stored in UTC and returned with an explicit offset (`...Z`).

## Failure handling

**Isolated failures.** Each PDF is generated inside its own `try/except`. A failure marks only that certificate `FAILED` (`error_type: GENERATION`) and the job moves on. In a 500-certificate job with one failure, the other 499 are generated and delivered. The zip only ever contains certificates whose status is `SUCCESS`, even if a failed attempt left a file on disk. Clients get the exception type in `error` (e.g. `Generation failed (OSError)`); the full message and traceback go to the server log, so internal paths are not exposed.

**Systemic failures: early halt.** If generation keeps failing (disk full, missing font, broken renderer), finishing the job would only add more failures. The processor keeps the outcomes of the last 20 attempts and stops the job as soon as

```
failures in the last 20 attempts >= 10        (HALT_WINDOW_SIZE = 20, HALT_FAILURE_THRESHOLD = 10)
```

The job becomes `HALTED` with an explanatory `error`. Certificates that already succeeded are kept and stay downloadable, and the rest stay `PENDING`. How this plays out on a 500-recipient job (each case is a test in `tests/test_failure_scenarios.py`):

| Scenario | Attempts made | Result |
|----------|---------------|--------|
| 1 failure (position 250) | 500 | `PARTIALLY_COMPLETED`, 499 in the zip |
| 2 random failures | 500 | `PARTIALLY_COMPLETED`, 498 in the zip |
| First 5 fail | 500 | `PARTIALLY_COMPLETED` (5 < 10, below the threshold) |
| Every third fails (~33%) | 500 | `PARTIALLY_COMPLETED` (at most 7 failures in any 20) |
| Everything fails | 20 | `HALTED`, 480 never attempted |
| Only 1 of 500 would pass | 20 | `HALTED` after 20 attempts, no need to wait for all 500 |
| First 30 pass, then an outage | 40 | `HALTED`; the 30 finished PDFs are kept and downloadable |

The window has to be full before the rule applies, so small jobs and a few early failures never halt a job. Because only recent attempts count, an outage that starts halfway through is detected 10 attempts after it begins. If the threshold is reached on the very last certificate, the job simply finishes with its normal final status.

**Retry.** `POST /api/jobs/{job_id}/retry` resumes a finished job. It moves certificates that failed during generation back to `PENDING` and runs the processor again, which only picks up `PENDING` certificates. Successful certificates are not regenerated, and validation failures are not retried because the same data would fail again. The job-level `error` is cleared and the counters are adjusted.

To see the halt and retry against a real server, make every PDF write fail by pointing `OUTPUT_DIR` at a regular file instead of a directory:

```bash
touch /tmp/not-a-directory
OUTPUT_DIR=/tmp/not-a-directory uvicorn app.main:app
```

In a second terminal, submit a job with 100 recipients (the halt rule needs at least 20 attempts, so `sample_request.json` is too small), then check it:

```bash
python3 -c "import json; print(json.dumps({'event_name': 'Outage demo', 'issuer_name': 'AEREO Academy', 'issue_date': '2026-10-01', 'recipients': [{'name': f'Recipient {i}', 'email': f'recipient{i}@example.com'} for i in range(1, 101)]}))" > /tmp/outage_request.json
JOB_ID=$(curl -s -X POST http://localhost:8000/api/jobs -H "Content-Type: application/json" -d @/tmp/outage_request.json | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
curl -s http://localhost:8000/api/jobs/$JOB_ID
```

Run the last command again after a second or two: the job is `HALTED` with `failed: 20` and `pending: 80`. Wait until it shows `HALTED` before stopping the server; stopping it mid-run leaves the job `PROCESSING` (see Known limitations). Now "fix the cause": stop the server (Ctrl+C), start it again with the default `OUTPUT_DIR`, and resume the job from the second terminal:

```bash
uvicorn app.main:app
```

```bash
curl -s -X POST http://localhost:8000/api/jobs/$JOB_ID/retry
curl -s http://localhost:8000/api/jobs/$JOB_ID
```

The retry returns `202` and the job starts again from `PENDING`. A couple of seconds later, `curl -s http://localhost:8000/api/jobs/$JOB_ID` shows `COMPLETED` with all 100 certificates. Nothing is lost across the restart because all job state is in the database.

## Validation

Validation happens at two levels.

**Request level (whole request rejected with 422).** Handled by Pydantic in `schemas.py`. It rejects a request that is structurally wrong: `event_name`/`issuer_name` missing or blank, `issue_date` not a valid date, `recipients` missing, empty or longer than 1000, or a recipient missing `name`/`email`. Nothing is stored.

**Recipient level (only that recipient fails).** Handled by `services/validator.py`. These are content problems inside an otherwise valid request:

- name is blank after trimming whitespace, or longer than 100 characters
- email is not in `local@domain.tld` form (no spaces, no empty domain labels such as `a@b..com`)
- email already used by an earlier valid recipient in the same job (case-insensitive)

Each invalid recipient is stored as a `FAILED` certificate with an `error` message, and the rest of the job continues. A single bad row in a 1000-person list should not force the client to resubmit everything, and the failure reasons come back through the same status endpoints as everything else.

## Design decisions

| Area | Decision | Reasoning and trade-off |
|------|----------|-------------------------|
| Processing model | FastAPI `BackgroundTasks`, `202 Accepted` + polling | Generating synchronously inside the request would keep the HTTP connection open for the whole batch, risk proxy timeouts and give no progress. Celery + Redis would add durability, retries and horizontal scaling, but also a broker, worker processes and more deployment work than this scale needs. `BackgroundTasks` keeps the async API contract (submit, then poll) with no extra infrastructure. `process_job` takes only a job id and opens its own DB session, so moving it to a Celery task later is a small change. |
| Commit granularity | Commit after every certificate | Clients polling the job see live progress, and if the process dies mid-job, everything finished so far is kept. The cost is one commit per certificate (see WAL below). |
| SQLite tuning | WAL journal + `synchronous=NORMAL` | With the default journal each commit is a full fsync. Measured on a 1000-recipient job: ~14s before vs ~3.4s after (PDF rendering itself is under 1s). WAL also lets status requests read while the processor writes. In this mode a power loss can drop the last few commits, but the database stays consistent. |
| Database | SQLite via SQLAlchemy, URL from `DATABASE_URL` | Zero setup for running and reviewing the project. All access goes through SQLAlchemy, so switching to Postgres is a config change plus a driver. |
| Validation | Two levels (see above) | Malformed requests fail fast with 422; bad individual rows never block the valid ones. |
| Certificate rows | All rows created at submission | `total` is known up front, progress is meaningful from the first poll, and invalid recipients are visible with their reason alongside the generated ones. |
| Failure isolation | `try/except` around each PDF | One certificate failing (bad data, renderer error) marks only that certificate `FAILED` with the error; the loop moves on. |
| Systemic failures | Halt when 10 of the last 20 attempts failed | A sliding window catches both "everything fails from the start" (stops after 20 attempts instead of grinding through the whole job) and "something broke halfway" (stops 10 attempts later). It ignores occasional failures. A failure *rate* over the whole job would react too slowly to a mid-job outage, and a plain consecutive-failure counter would miss a renderer that fails 2 times out of 3. |
| Retry | Explicit `POST /retry`, resumes from `PENDING` | Retrying straight away inside the job would just hit the same systemic problem again. The client retries once the cause is fixed, and because finished certificates are never touched, a retry costs only the work that is left. |
| Error details | Exception type to clients, full detail to logs | Raw exception text can contain server paths and other internals. |
| Template | ReportLab canvas, one fixed landscape A4 layout | Pure Python with no system dependencies (HTML-to-PDF tools need native libraries). Long names and titles are scaled down to fit the page. |
| Certificate code | `CERT-XXXX-XXXX-XXXX` (48 random bits), unique column | Grouped so it is easy to read off a printed certificate, random so codes can't be guessed sequentially. 48 bits keeps collisions negligible even across millions of certificates (32 bits would make one likely at around 100k); the unique constraint is the final guard. |
| Storage | PDFs on local disk, path stored in DB | Simple and enough for a single node. The file path is never exposed through the API. |
| Zip download | Built in memory per request | A certificate is ~2-3 KB, so a 1000-certificate zip is ~1.4 MB. Fine at this size; larger jobs should stream or pre-build the archive. |

## CI and code quality

`.github/workflows/ci.yml` runs on every push to `main` and on pull requests:

1. installs `requirements.lock` on Python 3.12 with `--require-hashes --only-binary :all:` (every package pinned and verified, no setup scripts run)
2. runs the test suite with coverage (`coverage.xml`)
3. runs a SonarCloud analysis with that coverage report

Actions are pinned to full commit SHAs. After changing `requirements.txt`, regenerate the lock file:

```bash
uv pip compile requirements.txt --generate-hashes --universal --python-version 3.11 -o requirements.lock
```

To connect SonarCloud:

1. Import the repository on [sonarcloud.io](https://sonarcloud.io) and check that the organization and project key match `sonar-project.properties`.
2. In SonarCloud, turn off **Automatic Analysis** for the project (Administration > Analysis Method). CI-based analysis is needed to upload coverage, and the two cannot run together.
3. Create a token in SonarCloud and add it to the GitHub repository as the `SONAR_TOKEN` secret (Settings > Secrets and variables > Actions).

Until the secret exists, the SonarCloud step is skipped and CI only runs the tests.

## Known limitations

- Background tasks run inside the API process. If the server restarts mid-job, that job stays `PROCESSING`. The retry endpoint refuses running jobs, because without a heartbeat it cannot tell a dead job from a live one. Such a job can be resumed by calling `process_job(job_id)` directly.
- PDF generation runs in the API's thread pool, so several very large jobs at once compete with request handling.
- The built-in Helvetica font covers Latin characters only. Names in other scripts (Devanagari, CJK, etc.) need a registered TTF font.
- Email validation is a format check only; there is no deliverability or MX check.
- No authentication or rate limiting. Job ids are random UUIDs, but that is not access control.
- `GET /api/jobs/{id}/certificates` is not paginated (bounded by the 1000-recipient limit).
- Tables are created with `create_all`; there are no migrations.

## Future scope

- **Celery + Redis workers** so jobs survive restarts, scale across machines and retry transient failures automatically with backoff. A worker heartbeat would also let interrupted jobs be detected and resumed.
- **Object storage (S3)** for PDFs, with pre-signed download URLs instead of serving files from the API.
- **Email delivery** of certificates to recipients once generated.
- **Authentication** (API keys or JWT) with jobs scoped to the owning organization.
- **Docker / docker-compose** for the API, worker, Redis and Postgres.
- Alembic migrations, CSV upload for recipient lists, pagination and an idempotency key on job submission.
