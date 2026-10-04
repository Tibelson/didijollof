"""Structured logging and request tracing.

Cloudflare's Workers Logs capture anything written to stdout. Plain English
strings are unsearchable once there are a few thousand of them, so everything
here is emitted as one JSON object per line. The dashboard and `wrangler tail`
can then filter on real fields — `event = "request.failed"`, a specific
`request_id`, one branch, one route.

The thing that makes support tractable is the request id. Every response
carries it in the `X-Request-Id` header, and any error response repeats it in
the body, so a chef can read eight characters off their screen over the phone
and that is enough to find the exact failure.

Deliberately not logged: passwords, session tokens, cookie values, or the
contents of a request body. A log that leaks a credential is worse than no log.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
import uuid
from contextvars import ContextVar

# Set per request, read by log() without threading it through every call.
_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_context: ContextVar[dict] = ContextVar("log_context", default={})

REQUEST_ID_HEADER = "X-Request-Id"


def current_request_id() -> str:
    return _request_id.get()


def bind_request(request_id: str) -> None:
    _request_id.set(request_id)
    _context.set({})


def add_context(**fields) -> None:
    """Attach fields to every subsequent log line for this request."""
    _context.set({**_context.get(), **fields})


def new_request_id(headers) -> str:
    """Prefer Cloudflare's ray id so a log line can be matched to CF's own.

    Short and lowercase because its real job is to be read aloud or typed back
    by someone describing a problem.
    """
    ray = headers.get("cf-ray") if headers else None
    if ray:
        return ray.split("-")[0][:16]
    return uuid.uuid4().hex[:12]


def log(event: str, level: str = "info", **fields) -> None:
    """Emit one structured line. Never raises — logging must not break a request."""
    try:
        payload = {
            "ts": round(time.time(), 3),
            "level": level,
            "event": event,
            "request_id": _request_id.get(),
            **_context.get(),
            **fields,
        }
        stream = sys.stderr if level in ("error", "warning") else sys.stdout
        print(json.dumps(payload, default=str), file=stream, flush=True)
    except Exception:  # pragma: no cover - logging must never be the failure
        pass


def log_exception(event: str, exc: BaseException, **fields) -> None:
    """Log an exception with its type, message and a trimmed traceback."""
    frames = traceback.format_exception(type(exc), exc, exc.__traceback__)
    log(
        event,
        level="error",
        error_type=type(exc).__name__,
        error=str(exc)[:500],
        # The tail is where the cause is; the head is framework plumbing.
        traceback="".join(frames)[-2000:],
        **fields,
    )
