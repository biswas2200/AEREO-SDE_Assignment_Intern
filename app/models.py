"""SQLAlchemy models for generation jobs and their certificates.

A Job is one bulk request. It owns one Certificate row per recipient, created
up front when the job is submitted, so the job always knows its total and
every recipient's state can be tracked individually.
"""

import enum
import secrets
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    """Current time in UTC. All timestamps in the database are UTC."""
    return datetime.now(UTC)


def new_uuid() -> str:
    """Random UUID4 as a string, used for job and certificate ids."""
    return str(uuid.uuid4())


def new_certificate_code() -> str:
    """Human-readable code printed on the certificate, e.g. CERT-1A2B-3C4D-5E6F.

    48 random bits keep collisions negligible even across millions of
    certificates (32 bits would make one likely at around 100k). The unique
    constraint on the column is the final guard.
    """
    raw = secrets.token_hex(6).upper()
    return f"CERT-{raw[:4]}-{raw[4:8]}-{raw[8:]}"


class JobStatus(enum.StrEnum):
    """Lifecycle of a job: PENDING -> PROCESSING -> one of the final states below.

    A retry moves a finished job back to PENDING.
    """

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"  # every certificate succeeded
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"  # some succeeded, some failed
    FAILED = "FAILED"  # none succeeded, or the job crashed
    HALTED = "HALTED"  # stopped early because too many recent attempts failed; retry resumes it


class CertificateStatus(enum.StrEnum):
    """Lifecycle of one certificate: PENDING -> SUCCESS or FAILED."""

    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"  # invalid recipient data, or PDF generation raised an error


class ErrorType(enum.StrEnum):
    """Why a certificate failed, which decides whether retrying it makes sense."""

    VALIDATION = "VALIDATION"  # bad recipient data: retrying would fail again
    GENERATION = "GENERATION"  # PDF generation raised: may succeed on retry


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    event_name: Mapped[str] = mapped_column(String(200))
    issuer_name: Mapped[str] = mapped_column(String(200))
    issue_date: Mapped[date] = mapped_column(Date)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.PENDING)

    # Counters kept on the job so a status request is a single-row read
    # instead of counting certificate rows on every poll.
    total: Mapped[int] = mapped_column(Integer, default=0)
    succeeded: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)

    # Job-level explanation when the job was halted or crashed.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Deleting a job also deletes its certificate rows.
    certificates: Mapped[list["Certificate"]] = relationship(back_populates="job", cascade="all, delete-orphan")

    @property
    def pending(self) -> int:
        """Certificates not attempted yet (non-zero while running, or after a halt)."""
        return self.total - self.succeeded - self.failed

    @property
    def progress_percent(self) -> float:
        """Share of certificates that reached a final state (SUCCESS or FAILED)."""
        if self.total == 0:
            return 0.0
        return round((self.succeeded + self.failed) / self.total * 100, 1)


class Certificate(Base):
    __tablename__ = "certificates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # Indexed because certificates are almost always looked up by their job.
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    recipient_name: Mapped[str] = mapped_column(String(200))
    recipient_email: Mapped[str] = mapped_column(String(320))
    course_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    certificate_code: Mapped[str] = mapped_column(String(20), unique=True, default=new_certificate_code)
    status: Mapped[CertificateStatus] = mapped_column(Enum(CertificateStatus), default=CertificateStatus.PENDING)
    # Human-readable reason and its category, set only when status is FAILED.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_type: Mapped[ErrorType | None] = mapped_column(Enum(ErrorType), nullable=True)
    # Location of the generated PDF on disk, set only when status is SUCCESS.
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[Job] = relationship(back_populates="certificates")
