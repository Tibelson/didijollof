"""Test fixtures.

Every test runs against a real Postgres with the real migrations applied, not
a mock or SQLite stand-in. The constraints, the enums and the price snapshot
are a large part of what we are asserting, and none of them exist in a fake.

The database is rebuilt per test so ordering can never matter.
"""

from __future__ import annotations

import os
import pathlib
import sys

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations"

TEST_DATABASE_URL = os.environ.setdefault(
    "DATABASE_URL", "postgresql://didi:didi@localhost:55432/didi"
)
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
        for name in ("0001_init.sql", "0002_seed.sql"):
            await conn.execute((MIGRATIONS / name).read_text())
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
