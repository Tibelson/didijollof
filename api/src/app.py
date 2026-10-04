"""FastAPI application.

Mounted at /api by the Worker; the PWA is served from the same origin as static
assets, so there is no CORS configuration and session cookies are first-party.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from routers import auth, inventory, requests
from runtime import MissingSetting

log = logging.getLogger("didi")

app = FastAPI(
    title="Didi Jollof",
    description="Kitchen stock and replenishment, per branch.",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

for router in (auth.router, inventory.router, requests.router):
    app.include_router(router, prefix="/api")


@app.get("/api/health", tags=["ops"])
async def health() -> dict:
    """Liveness only — deliberately does not touch the database.

    A health check that queries Postgres turns a database blip into a failing
    Worker. Database reachability is reported by /api/health/db instead.
    """
    return {"status": "ok"}


@app.get("/api/health/db", tags=["ops"])
async def health_db() -> JSONResponse:
    import db

    try:
        await db.fetchval("SELECT 1")
    except Exception as exc:  # surfaced, not swallowed
        log.exception("database health check failed")
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "error": type(exc).__name__},
        )
    return JSONResponse(content={"status": "ok"})


@app.exception_handler(MissingSetting)
async def missing_setting_handler(_: Request, exc: MissingSetting) -> JSONResponse:
    """A misconfigured deployment should say so clearly, not 500 anonymously."""
    log.error("missing configuration: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "server is not fully configured", "error": str(exc)},
    )
