"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import Base, engine
from app.routers import certificates, jobs

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Creates missing tables on startup. A real deployment would use migrations.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Bulk Certificate Generator",
    description="Generate PDF certificates for many recipients in a single request.",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(jobs.router)
app.include_router(certificates.router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
