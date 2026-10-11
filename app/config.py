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

# Early halt ("circuit breaker"): a job stops once at least HALT_FAILURE_THRESHOLD
# of its last HALT_WINDOW_SIZE generation attempts failed. A failure rate that
# high points to a systemic problem (disk full, broken font) rather than bad
# data, so continuing would only produce more failures. Finished certificates
# are kept, and POST /api/jobs/{id}/retry resumes the job.
HALT_WINDOW_SIZE = 20
HALT_FAILURE_THRESHOLD = 10
