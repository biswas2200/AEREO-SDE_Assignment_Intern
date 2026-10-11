"""Unit tests for model helpers that do not need the API or a database."""

import re

from app.models import Job, new_certificate_code


def test_certificate_code_is_grouped_for_readability():
    code = new_certificate_code()

    assert re.fullmatch(r"CERT-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}", code)


def test_certificate_codes_do_not_repeat():
    codes = {new_certificate_code() for _ in range(10_000)}

    assert len(codes) == 10_000


def test_progress_percent_counts_finished_certificates():
    job = Job(total=3, succeeded=1, failed=1)

    assert job.progress_percent == 66.7


def test_progress_percent_is_zero_for_a_job_without_certificates():
    job = Job(total=0, succeeded=0, failed=0)

    assert job.progress_percent == 0.0
