"""FastAPI application for HireIntel AI Weight Configuration System."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.api import dashboard, pages, recruiter, roles, scoring, weights
from src.models.database import init_db

# Create FastAPI app
app = FastAPI(
    title="HireIntel AI - Weight Configuration API",
    description="API for configuring recruiter weights for candidate evaluation",
    version="1.0.0",
)

# Mount static files
app.mount("/static", StaticFiles(directory="src/static"), name="static")

# Database synchronization middleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request

class GDriveDBSyncMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.method in ("POST", "PUT", "DELETE"):
            if response.status_code < 400:
                try:
                    from src.services.gdrive_syncer import backup_db_to_gdrive
                    import threading
                    threading.Thread(target=backup_db_to_gdrive, daemon=True).start()
                except Exception as e:
                    print(f"Failed to trigger DB backup: {e}")
        return response

app.add_middleware(GDriveDBSyncMiddleware)

# Include routers
app.include_router(roles.router)
app.include_router(weights.router)
app.include_router(scoring.router)
app.include_router(dashboard.router)
app.include_router(recruiter.router)
app.include_router(pages.router)  # pages last (catches / route)


@app.on_event("startup")
def startup_event() -> None:
    """Initialize database on startup."""
    try:
        from src.services.gdrive_syncer import restore_db_from_gdrive
        restore_db_from_gdrive()
    except Exception as e:
        print(f"Error restoring SQLite DB from GDrive: {e}")
    init_db()


@app.get("/health")
def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "healthy", "service": "hireintel-weight-config"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api.app:app", host="0.0.0.0", port=8000, reload=True)
