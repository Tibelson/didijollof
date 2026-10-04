#!/usr/bin/env python3
"""Apply pending SQL migrations, once each, in order.

    python3 scripts/migrate.py            # apply anything pending
    python3 scripts/migrate.py --check    # list pending, exit 1 if any
    python3 scripts/migrate.py --baseline # record existing files as applied

Each file runs inside its own transaction, so a failure leaves the database on
the last good migration rather than half-way through a broken one. Migration
files must therefore NOT contain their own BEGIN/COMMIT — the runner owns the
transaction, and a COMMIT inside the file would end it early and defeat that.

A checksum is stored with each applied file. Editing a migration that has
already run is almost always a mistake — the database will not match what the
file now says — so the runner refuses to continue and tells you to write a new
migration instead.

--baseline exists for a database that was set up by hand before this runner.
It records the files as applied WITHOUT executing them, which is right when the
schema is already there and wrong in every other situation, so it refuses to
run if the migrations table already has rows.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import pathlib
import sys

import asyncpg

ROOT = pathlib.Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "migrations"

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename    TEXT PRIMARY KEY,
    checksum    TEXT NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit(
            "DATABASE_URL is not set.\n"
            "  local : postgresql://didi:didi@localhost:55432/didi\n"
            "  Neon  : use the DIRECT (non-pooler) string"
        )
    return url


def migration_files() -> list[pathlib.Path]:
    return sorted(MIGRATIONS.glob("*.sql"))


def checksum(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


async def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "apply"
    if mode not in ("apply", "--check", "--baseline"):
        sys.exit(f"unknown argument {mode!r}; expected --check or --baseline")

    files = migration_files()
    if not files:
        print("no migrations found")
        return 0

    conn = await asyncpg.connect(database_url())
    try:
        await conn.execute(CREATE_TABLE)
        recorded = {
            row["filename"]: row["checksum"]
            for row in await conn.fetch("SELECT filename, checksum FROM schema_migrations")
        }

        # A migration that changed after being applied means the database no
        # longer matches the file. Stop rather than guess.
        drifted = [
            f.name for f in files
            if f.name in recorded and recorded[f.name] != checksum(f)
        ]
        if drifted:
            print("ERROR: these migrations changed after they were applied:")
            for name in drifted:
                print(f"  {name}")
            print("\nThe database no longer matches the file. Write a new migration")
            print("rather than editing one that has already run.")
            return 2

        pending = [f for f in files if f.name not in recorded]

        if mode == "--check":
            if pending:
                print(f"{len(pending)} migration(s) pending:")
                for f in pending:
                    print(f"  {f.name}")
                return 1
            print(f"up to date ({len(recorded)} applied)")
            return 0

        if mode == "--baseline":
            if recorded:
                print("ERROR: schema_migrations already has rows; baseline is only")
                print("for a database built by hand before this runner existed.")
                return 2
            for f in files:
                await conn.execute(
                    "INSERT INTO schema_migrations (filename, checksum) VALUES ($1, $2)",
                    f.name, checksum(f),
                )
                print(f"  baselined {f.name} (not executed)")
            print(f"\nrecorded {len(files)} migration(s) as already applied")
            return 0

        if not pending:
            print(f"up to date ({len(recorded)} applied)")
            return 0

        for f in pending:
            sql = f.read_text(encoding="utf-8")
            if _manages_own_transaction(sql):
                print(f"ERROR: {f.name} contains BEGIN/COMMIT.")
                print("The runner wraps each migration in a transaction; remove them.")
                return 2
            print(f"applying {f.name} …", end=" ", flush=True)
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (filename, checksum) VALUES ($1, $2)",
                    f.name, checksum(f),
                )
            print("ok")

        print(f"\napplied {len(pending)} migration(s)")
        return 0
    finally:
        await conn.close()


def _manages_own_transaction(sql: str) -> bool:
    lines = [
        line.strip().rstrip(";").upper()
        for line in sql.splitlines()
        if line.strip() and not line.strip().startswith("--")
    ]
    return any(line in ("BEGIN", "COMMIT", "START TRANSACTION") for line in lines)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
