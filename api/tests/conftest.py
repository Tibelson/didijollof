"""Test fixtures.

Every test runs against a real Postgres with the real migrations applied, not
a mock or SQLite stand-in. The constraints, the enums and the price snapshot
are a large part of what we are asserting, and none of them exist in a fake.

The database is rebuilt per test so ordering can never matter.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import sys
import urllib.parse

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations"

def _test_database_url() -> str:
    """Resolve the test database, and refuse to destroy anything that isn't one.

    `fresh_database` runs DROP SCHEMA public CASCADE before every test. That is
    fine against a throwaway container and catastrophic against anything else.

    Two protections, learned the hard way after this suite was pointed at the
    production Neon database by an ambient DATABASE_URL and wiped it:

    1. It reads DIDI_TEST_DATABASE_URL, not DATABASE_URL. A shell that has
       sourced .env.local for some unrelated task can no longer silently
       redirect the tests at production.
    2. The host must look local. Anything else aborts the run unless
       DIDI_ALLOW_DESTRUCTIVE_TESTS=1 is set deliberately.
    """
    url = os.environ.get(
        "DIDI_TEST_DATABASE_URL", "postgresql://didi:didi@localhost:55432/didi"
    )
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    local = {"localhost", "127.0.0.1", "::1", "db", "postgres"}
    if host not in local and os.environ.get("DIDI_ALLOW_DESTRUCTIVE_TESTS") != "1":
        raise SystemExit(
            f"\nREFUSING TO RUN: the test database host is {host!r}, which is not local.\n"
            f"These tests DROP SCHEMA before every test and would destroy it.\n\n"
            f"Use a disposable database (make db-up), or set\n"
            f"DIDI_ALLOW_DESTRUCTIVE_TESTS=1 if you are certain.\n"
        )
    return url


TEST_DATABASE_URL = _test_database_url()

# The app reads DATABASE_URL; pin it to the test database so nothing in the
# app can reach whatever else the environment had set.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("SESSION_SECRET", "test-secret")

CHEF_LEGON = "chef@didijollof.com"
CHEF_OSU = "chef.osu@didijollof.com"
OWNER = "owner@didijollof.com"
PASSWORD = "didi1234"


@pytest_asyncio.fixture(autouse=True)
async def fresh_database():
    """Drop and rebuild the schema, then re-seed, before each test."""
    import db

    await db.close_pool()
    conn = await asyncpg.connect(TEST_DATABASE_URL)
    try:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        # Applied directly rather than through scripts/migrate.py — this runs
        # before every test and the runner's bookkeeping would dominate. The
        # tracking rows are still written so the database is left in the state
        # the runner expects, instead of a schema it thinks is unmigrated.
        await conn.execute(
            "CREATE TABLE schema_migrations ("
            " filename TEXT PRIMARY KEY, checksum TEXT NOT NULL,"
            " applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
        )
        for path in sorted(MIGRATIONS.glob("*.sql")):
            await conn.execute(path.read_text())
            await conn.execute(
                "INSERT INTO schema_migrations (filename, checksum) VALUES ($1, $2)",
                path.name,
                hashlib.sha256(path.read_bytes()).hexdigest()[:16],
            )
    finally:
        await conn.close()
    yield
    await db.close_pool()


@pytest_asyncio.fixture
async def client():
    from app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="https://test.local"
    ) as c:
        yield c


@pytest_asyncio.fixture
async def chef(client):
    """Signed-in chef at Legon, with their branch id attached."""
    return await _sign_in(client, CHEF_LEGON)


@pytest_asyncio.fixture
async def other_chef(client):
    """Signed-in chef at Osu — the one Legon must never be able to touch."""
    return await _sign_in(client, CHEF_OSU)


@pytest_asyncio.fixture
async def owner(client):
    return await _sign_in(client, OWNER)


class Session:
    """A signed-in user plus the cookie jar needed to act as them."""

    def __init__(self, profile: dict, cookies: dict):
        self.profile = profile
        self.cookies = cookies

    @property
    def branch_id(self) -> int:
        return self.profile["branches"][0]["id"]

    @property
    def branch_ids(self) -> list[int]:
        return [b["id"] for b in self.profile["branches"]]


async def _sign_in(client: AsyncClient, email: str) -> Session:
    response = await client.post(
        "/api/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return Session(response.json(), dict(response.cookies))


async def item_named(name: str) -> int:
    conn = await asyncpg.connect(TEST_DATABASE_URL)
    try:
        return await conn.fetchval("SELECT id FROM items WHERE name = $1", name)
    finally:
        await conn.close()


async def set_item_price(name: str, price: str) -> None:
    conn = await asyncpg.connect(TEST_DATABASE_URL)
    try:
        await conn.execute(
            "UPDATE items SET price = $2::numeric WHERE name = $1", name, price
        )
    finally:
        await conn.close()


@pytest.fixture
def helpers():
    return type("helpers", (), {
        "item_named": staticmethod(item_named),
        "set_item_price": staticmethod(set_item_price),
    })
