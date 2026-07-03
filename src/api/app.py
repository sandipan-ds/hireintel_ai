"""FastAPI application for HireIntel AI Weight Configuration System."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.api import pages, roles, weights
from src.models.database import init_db

# Create FastAPI app
app = FastAPI(
    title="HireIntel AI - Weight Configuration API",
    description="API for configuring recruiter weights for candidate evaluation",
    version="1.0.0",
)

# Mount static files
app.mount("/static", StaticFiles(directory="src/static"), name="static")

# Include routers
app.include_router(roles.router)
app.include_router(weights.router)
app.include_router(pages.router)


@app.on_event("startup")
def startup_event() -> None:
    """Initialize database on startup."""
    init_db()


@app.get("/health")
def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "healthy", "service": "hireintel-weight-config"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api.app:app", host="0.0.0.0", port=8000, reload=True)
