"""Per-recipient validation.

Request-level problems (missing fields, wrong types) are rejected by Pydantic
with a 422. This module handles content problems inside an otherwise valid
request: each invalid recipient gets an error message and is stored as a
FAILED certificate, while the valid recipients are still processed.
"""

import re
from dataclasses import dataclass

from app import config
from app.schemas import RecipientIn

# Intentionally simple: something@something.tld with no spaces.
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class ValidatedRecipient:
    name: str
    email: str
    course_name: str | None
    error: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.error is None


def validate_recipients(recipients: list[RecipientIn]) -> list[ValidatedRecipient]:
    """Clean every recipient and attach an error message to the invalid ones.

    The output keeps the input order. Emails are compared case-insensitively,
    and only a valid recipient "claims" an email, so the first valid entry
    wins and later entries with the same email are marked as duplicates.
    """
    seen_emails: set[str] = set()
    results = []

    for recipient in recipients:
        name = recipient.name.strip()
        email = recipient.email.strip().lower()
        course_name = recipient.course_name.strip() if recipient.course_name else None

        error = _find_error(name, email, seen_emails)
        if error is None:
            seen_emails.add(email)

        results.append(
            ValidatedRecipient(name=name, email=email, course_name=course_name or None, error=error)
        )

    return results


def _find_error(name: str, email: str, seen_emails: set[str]) -> str | None:
    if not name:
        return "Name is required"
    if len(name) > config.MAX_NAME_LENGTH:
        return f"Name must be at most {config.MAX_NAME_LENGTH} characters"
    if not EMAIL_PATTERN.match(email):
        return "Invalid email address"
    if email in seen_emails:
        return "Duplicate email within this job"
    return None
