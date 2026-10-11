"""Per-recipient validation.

Request-level problems (missing fields, wrong types) are rejected by Pydantic
with a 422 before this code runs. This module handles content problems inside
an otherwise valid request: each invalid recipient gets an error message and
is stored as a FAILED certificate, while the valid recipients are still
processed.
"""

import re
from dataclasses import dataclass

from app import config
from app.schemas import RecipientIn

# local-part@label.label[.label...]
# The local part cannot contain "@" and domain labels cannot contain ".", so
# the pattern can only match in one way. That keeps matching linear (no
# catastrophic backtracking) and rejects empty labels such as "a@b..com".
# This is a format check only; it does not prove the mailbox exists.
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$")


@dataclass
class ValidatedRecipient:
    """A recipient after cleaning. `error` is None when the recipient is valid."""

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
    and only a valid recipient "claims" an email: the first valid entry wins
    and later entries with the same email are marked as duplicates.
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
            # `course_name or None` turns a blank course name into "no course".
            ValidatedRecipient(name=name, email=email, course_name=course_name or None, error=error)
        )

    return results


def _find_error(name: str, email: str, seen_emails: set[str]) -> str | None:
    """Return the first problem found with a recipient, or None if it is valid."""
    if not name:
        return "Name is required"
    if len(name) > config.MAX_NAME_LENGTH:
        return f"Name must be at most {config.MAX_NAME_LENGTH} characters"
    if not EMAIL_PATTERN.match(email):
        return "Invalid email address"
    if email in seen_emails:
        return "Duplicate email within this job"
    return None
