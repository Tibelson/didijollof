"""Database access.

In production the connection string comes from the Hyperdrive binding, which
pools and warms connections upstream so a short-lived Worker can open one per
request without paying a full Postgres handshake. Locally it comes from
DATABASE_URL and we keep a real asyncpg pool, because there is no Hyperdrive
in front to do it for us.

Routes never build SQL. They call the functions in `queries.py`, which take an
explicit branch id that the caller has already authorised.
"""

from __future__ import annotations

import contextlib
from typing import Any, AsyncIterator

import asyncpg

from runtime import binding, setting

_pool: asyncpg.Pool | None = None


def connection_string() -> str:
    """Hyperdrive's string in Workers, DATABASE_URL everywhere else."""
    hyperdrive = binding("HYPERDRIVE")
    if hyperdrive is not None:
        url = getattr(hyperdrive, "connectionString", None)
        if url:
            return url
    return setting("DATABASE_URL")


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            connection_string(),
            min_size=1,
            max_size=5,
            # asyncpg caches prepared statements per connection; Hyperdrive and
            # most Postgres poolers multiplex, so the cache can be invalidated
            # under us. Disabling it trades a little speed for correctness.
            statement_cache_size=0,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@contextlib.asynccontextmanager
async def acquire() -> AsyncIterator[asyncpg.Connection]:
    """Yield a connection.

    Under Workers each request opens its own connection through Hyperdrive and
    closes it again; there is no process to hold a pool between invocations.
    """
    if binding("HYPERDRIVE") is not None:
        conn = await asyncpg.connect(connection_string(), statement_cache_size=0)
        try:
            yield conn
        finally:
            await conn.close()
        return

    pool = await _get_pool()
    async with pool.acquire() as conn:
        yield conn


@contextlib.asynccontextmanager
async def transaction() -> AsyncIterator[asyncpg.Connection]:
    """Yield a connection inside a transaction, rolling back on error."""
    async with acquire() as conn:
        async with conn.transaction():
            yield conn


async def fetch(sql: str, *args: Any) -> list[asyncpg.Record]:
    async with acquire() as conn:
        return await conn.fetch(sql, *args)


async def fetchrow(sql: str, *args: Any) -> asyncpg.Record | None:
    async with acquire() as conn:
        return await conn.fetchrow(sql, *args)


async def fetchval(sql: str, *args: Any) -> Any:
    async with acquire() as conn:
        return await conn.fetchval(sql, *args)
