# Bulk Certificate Generator

A FastAPI backend that generates PDF certificates for many recipients in a single request. A client submits one job with up to 1000 recipients, the API validates each recipient, generates a certificate for every valid one in the background, and exposes endpoints to track progress and download the results individually or as a zip.

**Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.x, SQLite (configurable), Pydantic v2, ReportLab, pytest.

## Project structure

```
app/
  main.py               FastAPI app, router registration, table creation on startup
  config.py             Settings read from environment variables
  database.py           Engine, session factory, get_db dependency
  models.py             Job and Certificate tables, status enums
  schemas.py            Request/response models (request-level validation)
  routers/
    jobs.py             Submit jobs, poll status, list certificates, zip download
    certificates.py     Single certificate metadata and PDF download
  services/
    validator.py        Per-recipient validation (name, email, duplicates)
    generator.py        The certificate template, rendered with ReportLab
    processor.py        Background job runner
tests/                  pytest suite (temporary SQLite DB and output dir)
sample_request.json     Example job with valid and invalid recipients
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

Tables are created automatically on startup.

## Running the application

```bash
uvicorn app.main:app --reload
```

The API runs on `http://localhost:8000`. Interactive docs (Swagger UI) are at `http://localhost:8000/docs`.

## Running the tests

```bash
pytest -v
```

The tests use a temporary SQLite database and a per-test output directory, so they never touch local data. FastAPI's `TestClient` runs background tasks before the request returns, which keeps the tests deterministic without sleeps or polling.

## API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/jobs` | Submit a generation job. Returns `202 Accepted` with the job. |
| `GET`  | `/api/jobs/{job_id}` | Job status, counters and `progress_percent`. |
| `GET`  | `/api/jobs/{job_id}/certificates` | All certificates of the job. Optional `?status=PENDING\|SUCCESS\|FAILED`. |
| `GET`  | `/api/jobs/{job_id}/download` | Zip of every successfully generated PDF. |
| `GET`  | `/api/certificates/{certificate_id}` | Metadata of one certificate. |
| `GET`  | `/api/certificates/{certificate_id}/download` | The PDF of one certificate. |
| `GET`  | `/health` | Liveness check. |

Error responses:

| Code | When |
|------|------|
| `404` | Unknown job or certificate id; the PDF file is missing on disk; a finished job has no successful certificates to zip |
| `409` | Downloading a certificate that is not `SUCCESS`; downloading a job zip while the job is still `PENDING`/`PROCESSING` |
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

`course_name` is optional per recipient. When it is present the certificate headlines the course and mentions the event underneath; otherwise the event name is the headline.

## Usage walkthrough

These commands use `sample_request.json`, which has 5 recipients: 3 valid, 1 with an invalid email and 1 with a duplicate email.

**1. Submit a job**

```bash
curl -s -X POST http://localhost:8000/api/jobs -H "Content-Type: application/json" -d @sample_request.json
```

```json
{
  "id": "b69c0c20-c086-412c-9437-fafa18caab29",
  "event_name": "AEREO Drone Tech Summit 2026",
  "issuer_name": "AEREO Academy",
  "issue_date": "2026-10-01",
  "status": "PENDING",
  "total": 5,
  "succeeded": 0,
  "failed": 2,
  "progress_percent": 40.0,
  "created_at": "2026-10-11T19:44:34.550950",
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

```json
{
  "id": "b69c0c20-c086-412c-9437-fafa18caab29",
  "status": "PARTIALLY_COMPLETED",
  "total": 5,
  "succeeded": 3,
  "failed": 2,
  "progress_percent": 100.0,
  "completed_at": "2026-10-11T19:44:34.625437",
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
    "id": "9fec9a6c-c7ee-4140-b5d5-bbbbf4f0ddb8",
    "recipient_name": "Vikram Singh",
    "recipient_email": "vikram.singh@example",
    "certificate_code": "CERT-EB434D47",
    "status": "FAILED",
    "error": "Invalid email address",
    "...": "..."
  },
  {
    "id": "38e5f0d3-c3e1-44c5-8f7c-1f63115410ab",
    "recipient_name": "Asha V.",
    "recipient_email": "asha.verma@example.com",
    "certificate_code": "CERT-5B3CFD48",
    "status": "FAILED",
    "error": "Duplicate email within this job",
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

## Job and certificate lifecycle

```
Job:          PENDING -> PROCESSING -> COMPLETED            (every certificate succeeded)
                                    -> PARTIALLY_COMPLETED  (some succeeded, some failed)
                                    -> FAILED               (none succeeded)

Certificate:  PENDING -> SUCCESS
              PENDING -> FAILED     (PDF generation raised an error)
              FAILED                (set at submission when recipient validation fails)
```

`progress_percent` is `(succeeded + failed) / total * 100`, i.e. the share of certificates that reached a final state. Timestamps are stored and returned in UTC.

## Validation

Validation happens at two levels.

**Request level (whole request rejected with 422).** Handled by Pydantic in `schemas.py`. It rejects a request that is structurally wrong: `event_name`/`issuer_name` missing or blank, `issue_date` not a valid date, `recipients` missing, empty or longer than 1000, or a recipient missing `name`/`email`. Nothing is stored.

**Recipient level (only that recipient fails).** Handled by `services/validator.py`. These are content problems inside an otherwise valid request:

- name is blank after trimming whitespace, or longer than 100 characters
- email is not in `local@domain.tld` form
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
| Template | ReportLab canvas, one fixed landscape A4 layout | Pure Python with no system dependencies (HTML-to-PDF tools need native libraries). Long names and titles are scaled down to fit the page. |
| Certificate code | `CERT-` + 8 random hex chars, unique column | Short enough to print and read out, random so codes can't be guessed sequentially, and a unique constraint guards against collisions. |
| Storage | PDFs on local disk, path stored in DB | Simple and enough for a single node. The file path is never exposed through the API. |
| Zip download | Built in memory per request | A certificate is ~2-3 KB, so a 1000-certificate zip is ~1.4 MB. Fine at this size; larger jobs should stream or pre-build the archive. |

## Known limitations

- Background tasks run inside the API process. If the server restarts mid-job, that job stays `PROCESSING`. Its remaining certificates stay `PENDING`, so a resume or retry endpoint could re-run them, but nothing does that automatically yet.
- PDF generation runs in the API's thread pool, so several very large jobs at once compete with request handling.
- The built-in Helvetica font covers Latin characters only. Names in other scripts (Devanagari, CJK, etc.) need a registered TTF font.
- Email validation is a format check only; there is no deliverability or MX check.
- No authentication or rate limiting. Job ids are random UUIDs, but that is not access control.
- `GET /api/jobs/{id}/certificates` is not paginated (bounded by the 1000-recipient limit).
- Tables are created with `create_all`; there are no migrations.
- Generation error messages are returned to the client as-is.

## Future scope

- **Celery + Redis workers** so jobs survive restarts, scale across machines and retry transient failures automatically.
- **Retry endpoint** (`POST /api/jobs/{id}/retry`) to re-run only the `FAILED`/`PENDING` certificates of a job.
- **Object storage (S3)** for PDFs, with pre-signed download URLs instead of serving files from the API.
- **Email delivery** of certificates to recipients once generated.
- **Authentication** (API keys or JWT) with jobs scoped to the owning organization.
- **Docker / docker-compose** for the API, worker, Redis and Postgres.
- Alembic migrations, CSV upload for recipient lists, pagination and an idempotency key on job submission.
