#!/usr/bin/env python3
"""Local dev server: the API and the PWA on one origin, like the Worker.

Workers Static Assets serves `web/` for anything that is not /api/*, and the
Worker handles the rest. This mirrors that so local behaviour matches
production — same origin, so the session cookie works the same way.

    python3 scripts/dev.py          # http://localhost:8787

For running on Cloudflare itself use `pywrangler dev` from api/.
"""

from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api" / "src"))

os.environ.setdefault("DATABASE_URL", "postgresql://didi:didi@localhost:55432/didi")
os.environ.setdefault("SESSION_SECRET", "dev-secret-not-for-production")
# Plain HTTP locally, so the Secure cookie flag has to come off.
os.environ.setdefault("DIDI_INSECURE_COOKIES", "1")

import uvicorn  # noqa: E402
from starlette.staticfiles import StaticFiles  # noqa: E402
from starlette.responses import FileResponse  # noqa: E402

from app import app  # noqa: E402

WEB = ROOT / "web"


class SpaStatic(StaticFiles):
    """Serve web/, falling back to index.html so deep links work on reload."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 404 and not path.startswith("api"):
            return FileResponse(WEB / "index.html")
        return response


# Mounted last so every /api route wins.
app.mount("/", SpaStatic(directory=str(WEB), html=True), name="web")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8787, log_level="info")
