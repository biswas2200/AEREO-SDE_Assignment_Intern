"""Pydantic models for API requests and responses.

Request models perform the *request-level* validation: if the body is
structurally wrong (missing fields, wrong types, empty recipient list),
FastAPI rejects it with 422 before any endpoint code runs.
"""

from datetime import date, datetime, timezone
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app import config
from app.models import CertificateStatus, JobStatus


def _as_utc(value: datetime) -> datetime:
    """Attach UTC to timestamps read back from the database.

    Every timestamp is written in UTC, but SQLite does not store timezone
    information, so values come back "naive". Marking them as UTC makes the
    API return an explicit offset (e.g. 2026-10-01T10:00:00Z).
    """
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]


# --- Requests ---


class RecipientIn(BaseModel):
    """One recipient in a job request.

    Name and email are deliberately plain strings. Their content (blank name,
    malformed email, duplicates) is checked per recipient in
    services/validator.py, so one bad row does not reject the whole job.
    The max lengths here are only sanity limits against oversized payloads.
    """

    name: str = Field(max_length=200)
    email: str = Field(max_length=320)
    course_name: str | None = Field(default=None, max_length=200)


class JobCreate(BaseModel):
    """Body of POST /api/jobs: shared certificate details plus the recipient list."""

    # Strips surrounding spaces from the string fields of this model, so a
    # value like "   " counts as empty and fails min_length=1.
    model_config = ConfigDict(str_strip_whitespace=True)

    event_name: str = Field(min_length=1, max_length=200)
    issuer_name: str = Field(min_length=1, max_length=200)
    issue_date: date
    recipients: list[RecipientIn] = Field(min_length=1, max_length=config.MAX_RECIPIENTS_PER_JOB)


# --- Responses ---
# from_attributes=True lets these models be built straight from SQLAlchemy objects.


class JobRead(BaseModel):
    """Job status as returned by the API, including live progress."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    event_name: str
    issuer_name: str
    issue_date: date
    status: JobStatus
    total: int
    succeeded: int
    failed: int
    progress_percent: float
    created_at: UtcDatetime
    completed_at: UtcDatetime | None = None


class CertificateRead(BaseModel):
    """One certificate as returned by the API. The server-side file path is not exposed."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str
    recipient_name: str
    recipient_email: str
    course_name: str | None = None
    certificate_code: str
    status: CertificateStatus
    error: str | None = None
    created_at: UtcDatetime
