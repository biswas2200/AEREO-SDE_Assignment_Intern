"""Application settings, read from environment variables with sensible defaults."""

import os
from pathlib import Path

# Any SQLAlchemy URL works, e.g. postgresql+psycopg://user:pass@host/db
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./certificates.db")

# Generated PDFs are stored under OUTPUT_DIR/<job_id>/<certificate_code>.pdf
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output"))

MAX_RECIPIENTS_PER_JOB = 1000
MAX_NAME_LENGTH = 100
