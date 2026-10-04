"""Cloudflare Worker entrypoint.

`workers.asgi` bridges the Worker's native request into ASGI and hands it to
FastAPI. The Worker env — Hyperdrive binding and secrets — is bound into a
context variable for the life of the request so configuration lookups anywhere
in the app can find it (see runtime.py).
"""

from workers import WorkerEntrypoint, asgi

from app import app
from runtime import bind_env


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        bind_env(self.env)
        return await asgi.fetch(app, request, self.env)
