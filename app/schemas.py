"""Pydantic models for API requests and responses."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app import config
from app.models import CertificateStatus, JobStatus


class RecipientIn(BaseModel):
    # Name and email are deliberately plain strings. Their content (blank name,
    # malformed email, duplicates) is checked per recipient in
    # services/validator.py, so one bad row does not reject the whole job.
    # The max lengths here are only sanity limits against oversized payloads.
    name: str = Field(max_length=200)
    email: str = Field(max_length=320)
    course_name: str | None = Field(default=None, max_length=200)


class JobCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    event_name: str = Field(min_length=1, max_length=200)
    issuer_name: str = Field(min_length=1, max_length=200)
    issue_date: date
    recipients: list[RecipientIn] = Field(min_length=1, max_length=config.MAX_RECIPIENTS_PER_JOB)


class JobRead(BaseModel):
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
    created_at: datetime
    completed_at: datetime | None


class CertificateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str
    recipient_name: str
    recipient_email: str
    course_name: str | None
    certificate_code: str
    status: CertificateStatus
    error: str | None
    created_at: datetime
