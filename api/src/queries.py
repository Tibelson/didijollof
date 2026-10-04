"""Every SQL statement in the application.

Two rules hold throughout:

1. **Branch scope is a parameter, never an assumption.** Each branch-scoped
   function takes `branch_id` explicitly and filters on it. Callers must have
   already run `assert_branch_access`; nothing here infers a branch from a
   user, so a missing authorisation check shows up as a missing argument.

2. **Money is computed here, from snapshot prices.** The client never sends an
   amount, and historical orders read `order_items.unit_price`, never the live
   `items.price`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Sequence

import asyncpg

from db import acquire, transaction

# The one definition of stock status, used by the inventory list so the API and
# the UI can never disagree about what counts as critical.
_STATUS_SQL = """
    CASE
        WHEN bi.current_stock = 0 THEN 'out'
        WHEN bi.current_stock < bi.min_level THEN 'critical'
        WHEN bi.current_stock < bi.par_level THEN 'low'
        ELSE 'full'
    END
"""


# ---------------------------------------------------------------- users

async def get_user_by_email(email: str) -> asyncpg.Record | None:
    return await _fetchrow(
        """
        SELECT id, name, email, password_hash, role
          FROM users
         WHERE LOWER(email) = LOWER($1)
        """,
        email,
    )


async def get_user_by_id(user_id: int) -> asyncpg.Record | None:
    return await _fetchrow(
        "SELECT id, name, email, role FROM users WHERE id = $1",
        user_id,
    )


async def update_password_hash(user_id: int, password_hash: str) -> None:
    async with acquire() as conn:
        await conn.execute(
            "UPDATE users SET password_hash = $2 WHERE id = $1",
            user_id,
            password_hash,
        )


# ------------------------------------------------------------- branches

async def branches_for_user(user_id: int) -> list[asyncpg.Record]:
    """The branches this user may act on. Empty means no access to anything."""
    return await _fetch(
        """
        SELECT b.id, b.name, b.location
          FROM branches b
          JOIN user_branches ub ON ub.branch_id = b.id
         WHERE ub.user_id = $1
         ORDER BY b.name
        """,
        user_id,
    )


async def user_can_access_branch(user_id: int, branch_id: int) -> bool:
    async with acquire() as conn:
        return bool(
            await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM user_branches
                     WHERE user_id = $1 AND branch_id = $2
                )
                """,
                user_id,
                branch_id,
            )
        )


# ------------------------------------------------------------ inventory

async def list_inventory(
    branch_id: int,
    *,
    category: str | None = None,
    search: str | None = None,
) -> list[asyncpg.Record]:
    """Stock for one branch, newest count included, optionally filtered.

    `search` is matched case-insensitively anywhere in the name; the pattern is
    passed as a parameter so user input can never alter the statement.
    """
    return await _fetch(
        f"""
        SELECT i.id,
               i.name,
               i.unit,
               i.category::text              AS category,
               i.price,
               i.image_url,
               bi.current_stock,
               bi.min_level,
               bi.par_level,
               bi.counted_at,
               {_STATUS_SQL}                 AS status
          FROM branch_items bi
          JOIN items i ON i.id = bi.item_id
         WHERE bi.branch_id = $1
           AND i.is_active
           AND ($2::text IS NULL OR i.category::text = $2)
           AND ($3::text IS NULL OR i.name ILIKE '%' || $3 || '%')
         ORDER BY i.category, i.name
        """,
        branch_id,
        category,
        search,
    )


async def count_below_par(branch_id: int) -> int:
    """Drives the "FOUR THINGS RUNNING LOW" headline."""
    async with acquire() as conn:
        return int(
            await conn.fetchval(
                """
                SELECT COUNT(*)
                  FROM branch_items bi
                  JOIN items i ON i.id = bi.item_id
                 WHERE bi.branch_id = $1
                   AND i.is_active
                   AND bi.current_stock < bi.par_level
                """,
                branch_id,
            )
        )


async def set_stock_count(
    branch_id: int, item_id: int, current_stock: int, counted_by: int
) -> asyncpg.Record | None:
    """Record what the chef counted. Returns None if the item isn't stocked here."""
    return await _fetchrow(
        """
        UPDATE branch_items
           SET current_stock = $3, counted_at = NOW(), counted_by = $4
         WHERE branch_id = $1 AND item_id = $2
        RETURNING item_id, current_stock, min_level, par_level, counted_at
        """,
        branch_id,
        item_id,
        current_stock,
        counted_by,
    )


async def last_submitted_request(branch_id: int) -> asyncpg.Record | None:
    """Backs "Same as yesterday": the most recent request for this branch."""
    return await _fetchrow(
        """
        SELECT o.id,
               o.created_at,
               COUNT(oi.id)                              AS line_count,
               COALESCE(SUM(oi.quantity * oi.unit_price), 0) AS total
          FROM orders o
          LEFT JOIN order_items oi ON oi.order_id = o.id
         WHERE o.branch_id = $1
           AND o.deleted_at IS NULL
         GROUP BY o.id
         ORDER BY o.created_at DESC
         LIMIT 1
        """,
        branch_id,
    )


# ------------------------------------------------------------- requests

async def create_request(
    branch_id: int,
    user_id: int,
    lines: Sequence[tuple[int, int, int]],
) -> int:
    """Create a request from (item_id, quantity, existing_stock) triples.

    The whole thing is one transaction: price snapshots, the order, its lines
    and the stock counts either all land or none do. A half-written request
    whose totals don't match its lines would be worse than a failed submit.

    Raises UnknownItems if any item is not stocked at this branch — which also
    stops a caller slipping another branch's item into the list.
    """
    if not lines:
        raise EmptyRequest("a request needs at least one line")

    item_ids = [item_id for item_id, _, _ in lines]
    if len(set(item_ids)) != len(item_ids):
        raise DuplicateItems("the same item appears more than once")

    async with transaction() as conn:
        # Lock the prices we are about to snapshot so a concurrent price edit
        # cannot land between reading and writing them.
        priced = await conn.fetch(
            """
            SELECT i.id, i.price
              FROM items i
              JOIN branch_items bi ON bi.item_id = i.id AND bi.branch_id = $1
             WHERE i.id = ANY($2::int[])
               AND i.is_active
             FOR UPDATE OF i
            """,
            branch_id,
            item_ids,
        )
        prices = {row["id"]: row["price"] for row in priced}
        missing = sorted(set(item_ids) - set(prices))
        if missing:
            raise UnknownItems(missing)

        order_id = await conn.fetchval(
            """
            INSERT INTO orders (user_id, branch_id, status)
            VALUES ($1, $2, 'active')
            RETURNING id
            """,
            user_id,
            branch_id,
        )

        await conn.executemany(
            """
            INSERT INTO order_items (order_id, item_id, quantity, existing_stock, unit_price)
            VALUES ($1, $2, $3, $4, $5)
            """,
            [
                (order_id, item_id, quantity, existing_stock, prices[item_id])
                for item_id, quantity, existing_stock in lines
            ],
        )

        # Submitting a request is also a stock count: the chef just told us what
        # is on the shelf, so record it rather than make them count twice.
        await conn.executemany(
            """
            UPDATE branch_items
               SET current_stock = $3, counted_at = NOW(), counted_by = $4
             WHERE branch_id = $1 AND item_id = $2
            """,
            [
                (branch_id, item_id, existing_stock, user_id)
                for item_id, _, existing_stock in lines
            ],
        )
        return int(order_id)


async def list_requests(
    branch_id: int, *, status: str | None = None, limit: int = 50
) -> list[asyncpg.Record]:
    return await _fetch(
        """
        SELECT o.id,
               o.created_at,
               o.status::text                                AS status,
               u.name                                        AS requested_by,
               COUNT(oi.id)                                  AS line_count,
               COALESCE(SUM(oi.quantity), 0)                 AS item_count,
               COALESCE(SUM(oi.quantity * oi.unit_price), 0) AS total
          FROM orders o
          JOIN users u ON u.id = o.user_id
          LEFT JOIN order_items oi ON oi.order_id = o.id
         WHERE o.branch_id = $1
           AND o.deleted_at IS NULL
           AND ($2::text IS NULL OR o.status::text = $2)
         GROUP BY o.id, u.name
         ORDER BY o.created_at DESC
         LIMIT $3
        """,
        branch_id,
        status,
        limit,
    )


async def get_request(order_id: int) -> asyncpg.Record | None:
    """Fetch one request. Includes branch_id so the caller can authorise it."""
    return await _fetchrow(
        """
        SELECT o.id,
               o.branch_id,
               o.created_at,
               o.status::text AS status,
               o.review_note,
               o.reviewed_at,
               u.name         AS requested_by,
               b.name         AS branch_name
          FROM orders o
          JOIN users u ON u.id = o.user_id
          JOIN branches b ON b.id = o.branch_id
         WHERE o.id = $1
           AND o.deleted_at IS NULL
        """,
        order_id,
    )


async def get_request_lines(order_id: int) -> list[asyncpg.Record]:
    return await _fetch(
        """
        SELECT oi.item_id,
               i.name,
               i.unit,
               i.category::text AS category,
               oi.quantity,
               oi.existing_stock,
               oi.unit_price,
               (oi.quantity * oi.unit_price) AS line_total
          FROM order_items oi
          JOIN items i ON i.id = oi.item_id
         WHERE oi.order_id = $1
         ORDER BY i.category, i.name
        """,
        order_id,
    )


# -------------------------------------------------------------- errors

class RequestError(Exception):
    """Base for request-construction problems that map to a 4xx."""


class EmptyRequest(RequestError):
    pass


class DuplicateItems(RequestError):
    pass


class UnknownItems(RequestError):
    def __init__(self, item_ids: Iterable[int]) -> None:
        self.item_ids = list(item_ids)
        super().__init__(f"items not stocked at this branch: {self.item_ids}")


# ------------------------------------------------------------- helpers

async def _fetch(sql: str, *args: Any) -> list[asyncpg.Record]:
    async with acquire() as conn:
        return await conn.fetch(sql, *args)


async def _fetchrow(sql: str, *args: Any) -> asyncpg.Record | None:
    async with acquire() as conn:
        return await conn.fetchrow(sql, *args)


def money(value: Decimal | int | float | None) -> float:
    """Decimal -> float at the JSON boundary, with None treated as zero."""
    return float(value or 0)
