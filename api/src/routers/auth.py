"""Sign in, sign out, and who am I."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

import queries
from deps import CurrentUser, current_user, session_secret
from models import BranchOut, LoginIn, MeOut
from security import (
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    hash_password,
    issue_session,
    needs_rehash,
    verify_password,
)

router = APIRouter(tags=["auth"])

# Burned when the email is unknown, so a missing account costs the same time as
# a wrong password and account existence cannot be read off the response time.
#
# Two constraints make this a literal rather than a computed value:
#
#  - Its cost must match DEFAULT_ITERATIONS. An earlier version used 1,000
#    iterations against real hashes at 100,000, so unknown emails answered ~100x
#    faster and the equaliser leaked precisely what it was meant to hide.
#  - Workers forbid randomness at import time: startup state is snapshotted and
#    replayed across instances, so a generated salt here would be identical
#    everywhere. The salt below is fixed and public — this hash guards nothing,
#    it only burns equivalent CPU.
#
# Regenerate if DEFAULT_ITERATIONS changes; test_login_timing_does_not_leak
# fails if the two drift apart.
_DUMMY_HASH = (
    "pbkdf2_sha256$100000$ZGlkaS10aW1pbmctZXF1YQ$"
    "_HcnXB1Iu_xgaEeIVTYIGLPgdM0y6MDrN1MJoewmdAE"
)


@router.post("/auth/login", response_model=MeOut)
async def login(payload: LoginIn, response: Response) -> MeOut:
    record = await queries.get_user_by_email(payload.email)

    stored = record["password_hash"] if record else _DUMMY_HASH
    ok = await verify_password(payload.password, stored)
    if record is None or not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="email or password is incorrect",
        )

    # Opportunistically upgrade the stored hash when the cost has been raised.
    if needs_rehash(stored):
        await queries.update_password_hash(
            record["id"], await hash_password(payload.password)
        )

    token, _ = issue_session(record["id"], session_secret())
    _set_session_cookie(response, token)

    branches = await queries.branches_for_user(record["id"])
    return MeOut(
        id=record["id"],
        name=record["name"],
        email=record["email"],
        role=record["role"],
        branches=[BranchOut(**dict(b)) for b in branches],
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=True
    )


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUser = Depends(current_user)) -> MeOut:
    branches = await queries.branches_for_user(user.id)
    return MeOut(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role,
        branches=[BranchOut(**dict(b)) for b in branches],
    )


def _secure_cookies() -> bool:
    """Secure everywhere except an explicitly-flagged plain-HTTP dev server.

    Workers always serve over TLS, so this is True in production. It is only
    relaxed for `scripts/dev.py`, which runs on http://127.0.0.1.
    """
    from runtime import setting

    return setting("DIDI_INSECURE_COOKIES", "") != "1"


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,            # unreadable from JavaScript, so XSS cannot lift it
        secure=_secure_cookies(),  # HTTPS only; Workers always serve over TLS
        samesite="lax",           # survives navigation, blocks cross-site POSTs
        path="/",
    )
