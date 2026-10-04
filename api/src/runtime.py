"""Bridge between the Cloudflare Worker environment and plain-Python runs.

A Worker receives its bindings and secrets as an `env` object handed to the
fetch handler, not as process environment variables. Tests and local tooling
have the opposite: `os.environ` and no bindings.

Everything that needs configuration reads it through `setting()` here, so no
other module has to know which of the two it is running under.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Any

# Set per-request by the Worker entrypoint. Absent when running under pytest
# or any plain Python process.
_worker_env: ContextVar[Any | None] = ContextVar("worker_env", default=None)


def bind_env(env: Any) -> None:
    """Record the Worker env for the duration of this request."""
    _worker_env.set(env)


def worker_env() -> Any | None:
    return _worker_env.get()


def binding(name: str) -> Any | None:
    """Return a Worker binding (Hyperdrive, KV, ...) or None outside Workers."""
    env = _worker_env.get()
    if env is None:
        return None
    return getattr(env, name, None)


class MissingSetting(RuntimeError):
    """A required secret or binding was not configured."""


_MISSING = object()


def setting(name: str, default: Any = _MISSING) -> Any:
    """Read config from the Worker env first, then the process environment.

    Raises MissingSetting when there is no value and no default, because a
    Worker booting without its session secret should fail loudly at the first
    request rather than quietly issue tokens signed with an empty key.
    """
    env = _worker_env.get()
    if env is not None:
        value = getattr(env, name, None)
        if value is not None and not callable(value):
            return value
    value = os.environ.get(name)
    if value is not None:
        return value
    if default is _MISSING:
        raise MissingSetting(
            f"{name} is not set. In Workers add it with `wrangler secret put {name}`; "
            f"locally export it or put it in .env"
        )
    return default
