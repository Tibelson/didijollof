"""Authentication and the branch-access chokepoint.

`assert_branch_access` is the single place that decides whether a caller may
touch a branch's data. Every branch-scoped route depends on it, and `branch_id`
is always a path parameter — never read from a request body — so a route either
authorises the branch it operates on or fails to compile into a usable
signature.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Cookie, Depends, HTTPException, Path, status

import queries
from runtime import setting
from security import SESSION_COOKIE, SessionError, read_session


@dataclass(frozen=True)
class CurrentUser:
    id: int
    name: str
    email: str
    role: str


def session_secret() -> str:
    return setting("SESSION_SECRET")


async def current_user(
    didi_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> CurrentUser:
    """Resolve the signed session cookie to a user, or 401."""
    if not didi_session:
        raise _unauthorised("not signed in")
    try:
        user_id = read_session(didi_session, session_secret())
    except SessionError as exc:
        raise _unauthorised(str(exc)) from None

    record = await queries.get_user_by_id(user_id)
    if record is None:
        # Valid signature, but the account is gone. Treat as signed out.
        raise _unauthorised("account no longer exists")
    return CurrentUser(
        id=record["id"],
        name=record["name"],
        email=record["email"],
        role=record["role"],
    )


async def assert_branch_access(
    branch_id: int = Path(..., gt=0),
    user: CurrentUser = Depends(current_user),
) -> int:
    """Return branch_id if the caller is mapped to it, else 404.

    404 rather than 403: a chef at Legon should not be able to discover which
    branch ids exist by probing for the difference between "forbidden" and
    "not found".
    """
    if not await queries.user_can_access_branch(user.id, branch_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="branch not found",
        )
    return branch_id


def require_role(*roles: str):
    """Dependency factory gating a route on the caller's role."""

    async def _check(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="not permitted for this role",
            )
        return user

    return _check


def _unauthorised(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "cookie"},
    )
