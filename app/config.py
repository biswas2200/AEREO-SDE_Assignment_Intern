"""Application settings, read from environment variables with sensible defaults.

Values are read once at import time. Code that may be redirected in tests
(e.g. OUTPUT_DIR) reads them as `config.OUTPUT_DIR` at call time, so a test
can monkeypatch the attribute.
"""

import os
from pathlib import Path

# Any SQLAlchemy URL works, e.g. postgresql+psycopg://user:pass@host/db
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./certificates.db")

# Generated PDFs are stored under OUTPUT_DIR/<job_id>/<certificate_code>.pdf
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output"))

# Upper bound on recipients in one request (enforced with a 422).
MAX_RECIPIENTS_PER_JOB = 1000

# Longest recipient name that still fits nicely on the certificate.
MAX_NAME_LENGTH = 100
