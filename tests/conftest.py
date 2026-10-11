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
    yield
    engine.dispose()
    shutil.rmtree(TEST_DIR, ignore_errors=True)


@pytest.fixture
def client(tmp_path, monkeypatch):
    """API client backed by a fresh database and a per-test output directory.

    TestClient runs background tasks before the request call returns, so a
    job submitted through this client is fully processed by the time the
    test makes its assertions.
    """
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def job_payload():
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

