"""FastAPI application.

Mounted at /api by the Worker; the PWA is served from the same origin as static
assets, so there is no CORS configuration and session cookies are first-party.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from observability import (
    REQUEST_ID_HEADER,
    add_context,
    bind_request,
    current_request_id,
    log,
    log_exception,
    new_request_id,
)
from routers import auth, inventory, requests
from runtime import MissingSetting

app = FastAPI(
    title="Didi Jollof",
    description="Kitchen stock and replenishment, per branch.",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

for router in (auth.router, inventory.router, requests.router):
    app.include_router(router, prefix="/api")


@app.middleware("http")
async def trace_requests(request: Request, call_next):
    """Give every request an id, time it, and make sure nothing escapes unlogged.

    The id goes out on every response so a failure can be traced from a
    screenshot. Slow and failed requests are logged; successful fast ones are
    not, because a line per healthy request is noise that buries the failures.
    """
    request_id = new_request_id(request.headers)
    bind_request(request_id)
    add_context(method=request.method, path=request.url.path)

    started = time.monotonic()
    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = round((time.monotonic() - started) * 1000, 1)
        log_exception("request.failed", exc, duration_ms=duration_ms)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Something went wrong. Quote this reference if you report it.",
                "request_id": request_id,
            },
            headers={REQUEST_ID_HEADER: request_id},
        )

    duration_ms = round((time.monotonic() - started) * 1000, 1)
    response.headers[REQUEST_ID_HEADER] = request_id
    if response.status_code >= 500:
        log("request.error", level="error",
            status=response.status_code, duration_ms=duration_ms)
    elif response.status_code >= 400:
        log("request.rejected", level="warning",
            status=response.status_code, duration_ms=duration_ms)
    elif duration_ms > 1500:
        log("request.slow", level="warning",
            status=response.status_code, duration_ms=duration_ms)
    return response


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Expected refusals (401/404/422). The middleware logs them; this shapes them."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "request_id": current_request_id()},
        headers={**(exc.headers or {}), REQUEST_ID_HEADER: current_request_id()},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """A malformed payload is a client bug; log which fields, never their values."""
    log("request.invalid", level="warning",
        fields=[".".join(str(p) for p in e.get("loc", [])) for e in exc.errors()][:10])
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "request_id": current_request_id()},
        headers={REQUEST_ID_HEADER: current_request_id()},
    )


@app.exception_handler(MissingSetting)
async def missing_setting_handler(_: Request, exc: MissingSetting) -> JSONResponse:
    """A misconfigured deployment should say so clearly, not 500 anonymously."""
    log("config.missing", level="error", error=str(exc))
    return JSONResponse(
        status_code=500,
        content={
            "detail": "server is not fully configured",
            "error": str(exc),
            "request_id": current_request_id(),
        },
        headers={REQUEST_ID_HEADER: current_request_id()},
    )


# --------------------------------------------------------------------- ops

@app.get("/api/health", tags=["ops"])
async def health() -> dict:
    """Liveness only — deliberately does not touch the database.

    A health check that queries Postgres turns a database blip into a failing
    Worker. Database reachability is reported by /api/health/db instead.
    """
    return {"status": "ok", "version": app.version}


@app.get("/api/health/db", tags=["ops"])
async def health_db() -> JSONResponse:
    import db

    started = time.monotonic()
    try:
        await db.fetchval("SELECT 1")
    except Exception as exc:
        log_exception("health.db_unreachable", exc)
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "error": type(exc).__name__,
                "request_id": current_request_id(),
            },
        )
    return JSONResponse(content={
        "status": "ok",
        "latency_ms": round((time.monotonic() - started) * 1000, 1),
    })


@app.post("/api/client-error", tags=["ops"], status_code=204)
async def client_error(request: Request) -> None:
    """Record a browser-side failure so it is debuggable like a server one.

    A chef's phone throwing a JavaScript error is otherwise invisible: nothing
    reaches the server, and asking someone mid-service to open a developer
    console is not a plan.

    Unauthenticated on purpose — the errors most worth catching include ones
    that happen before sign-in. Every field is length-capped and only written
    to the log, never stored, so the worst a flood can do is make noise.
    """
    try:
        payload = await request.json()
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None

    def clip(key: str, limit: int) -> str:
        value = payload.get(key)
        return str(value)[:limit] if value is not None else ""

    log(
        "client.error",
        level="error",
        message=clip("message", 300),
        source=clip("source", 200),
        stack=clip("stack", 1200),
        screen=clip("screen", 60),
        app_version=clip("version", 40),
        user_agent=request.headers.get("user-agent", "")[:200],
    )
    return None
