"""Shared pytest fixtures.

Every test runs against a temporary SQLite database (emptied before each test)
and its own temporary PDF output directory, so tests never touch local data
and never depend on each other.
"""

import os
import shutil
import tempfile

# The engine is created when app.database is imported, so the test database
# URL has to be in place before any app module is imported below.
TEST_DIR = tempfile.mkdtemp(prefix="certgen-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DIR}/test.db"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402
from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_dir():
    """Remove the temporary database directory once the whole test session ends."""
    yield
    engine.dispose()
    shutil.rmtree(TEST_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def fresh_database(tmp_path, monkeypatch):
    """Empty tables and a per-test PDF output directory, so tests never share state."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")


@pytest.fixture
def client():
    """API client for the app (the autouse fresh_database fixture resets state first).

    TestClient runs background tasks before the request call returns, so a
    job submitted through this client is fully processed by the time the
    test makes its assertions.
    """
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def job_payload():
    """A valid job request with three recipients. Tests modify it as needed."""
    return {
        "event_name": "AEREO Drone Tech Summit 2026",
        "issuer_name": "AEREO Academy",
        "issue_date": "2026-10-01",
        "recipients": [
            {"name": "Asha Verma", "email": "asha@example.com", "course_name": "UAV Flight Basics"},
            {"name": "Rohan Mehta", "email": "rohan@example.com"},
            {"name": "Neha Iyer", "email": "neha@example.com", "course_name": "Aerial Mapping"},
        ],
    }

