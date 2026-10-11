"""Database engine, session factory and the FastAPI session dependency."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app import config

is_sqlite = config.DATABASE_URL.startswith("sqlite")

# SQLite connections are bound to the thread that created them by default.
# FastAPI serves sync endpoints and background tasks from a thread pool,
# so that check has to be turned off for SQLite.
connect_args = {"check_same_thread": False} if is_sqlite else {}

# One engine (and connection pool) for the whole application.
engine = create_engine(config.DATABASE_URL, connect_args=connect_args)

# Factory for new sessions. Each request, and each background job, gets its own.
# autoflush=False: changes are only sent to the database on an explicit commit.
SessionLocal = sessionmaker(bind=engine, autoflush=False)

if is_sqlite:

    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record):
        """Run on every new SQLite connection.

        The processor commits once per certificate. In SQLite's default
        journal mode every commit is a full fsync; WAL with synchronous=NORMAL
        makes those commits cheap (~4x faster for a 1000-recipient job) and
        lets status requests read while the processor is writing.
        """
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


class Base(DeclarativeBase):
    """Parent class of all ORM models; Base.metadata knows every table."""


def get_db() -> Iterator[Session]:
    """Yield a session for one request and always close it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Endpoints declare `db: DbSession` to receive a request-scoped session.
DbSession = Annotated[Session, Depends(get_db)]
