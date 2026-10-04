"""Password hashing and session tokens, standard library only.

Python Workers run on Pyodide, where C-extension packages (bcrypt, passlib,
PyJWT, cryptography) are unreliable or unavailable. Everything here is built
from hashlib/hmac/secrets, which ship with the runtime.

Both primitives are versioned so the algorithm can change without a migration:
password hashes carry their scheme and cost in the stored string, and session
tokens carry a format version. Nothing outside this module should know how
either is encoded.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

# --------------------------------------------------------------------------
# passwords
# --------------------------------------------------------------------------

_SCHEME = "pbkdf2_sha256"
_SALT_BYTES = 16

# PBKDF2 cost is a direct charge against the Worker's CPU budget on every
# login, so this is deliberately lower than a long-lived server would use.
# Tuned against the measurement in scripts/bench_hash.py — raise it as the
# budget allows, and needs_rehash() will upgrade stored hashes on next login.
DEFAULT_ITERATIONS = 100_000


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


async def _derive(password: str, salt: bytes, iterations: int) -> bytes:
    """PBKDF2-HMAC-SHA256, using whichever implementation the runtime has.

    CPython has `hashlib.pbkdf2_hmac`. Pyodide — which Python Workers run on —
    does not: it is an OpenSSL-backed function absent from the Wasm build, and
    reaching for it there raises AttributeError.

    So on Workers we call the runtime's own Web Crypto instead. The two agree
    byte-for-byte (checked against the RFC 6070 vector in test_security.py), so
    a hash written by one verifies under the other and nothing has to be
    re-hashed when moving between local and deployed.

    Web Crypto is also far faster: 100k iterations is ~1 ms on the Worker versus
    ~40 ms in CPython, because it is native rather than interpreted.
    """
    native = getattr(hashlib, "pbkdf2_hmac", None)
    if native is not None:
        return native("sha256", password.encode("utf-8"), salt, iterations)
    return await _derive_webcrypto(password.encode("utf-8"), salt, iterations)


async def _derive_webcrypto(password: bytes, salt: bytes, iterations: int) -> bytes:
    from js import Object, Uint8Array, crypto  # type: ignore[import-not-found]
    from pyodide.ffi import to_js  # type: ignore[import-not-found]

    def js_obj(value: dict):
        return to_js(value, dict_converter=Object.fromEntries)

    def buf(raw: bytes):
        return Uint8Array.new(list(raw))

    key = await crypto.subtle.importKey(
        "raw", buf(password), js_obj({"name": "PBKDF2"}), False, to_js(["deriveBits"])
    )
    bits = await crypto.subtle.deriveBits(
        js_obj(
            {
                "name": "PBKDF2",
                "salt": buf(salt),
                "iterations": iterations,
                "hash": "SHA-256",
            }
        ),
        key,
        256,
    )
    return bytes(Uint8Array.new(bits).to_py())


async def hash_password(password: str, *, iterations: int = DEFAULT_ITERATIONS) -> str:
    """Return a self-describing hash: scheme$iterations$salt$digest."""
    if not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = await _derive(password, salt, iterations)
    return f"{_SCHEME}${iterations}${_b64e(salt)}${_b64e(digest)}"


async def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of a password against a stored hash.

    Returns False rather than raising on a malformed hash: a corrupt row must
    read as "wrong password", never as a 500 that distinguishes it from a real
    failure.

    The cost is read from the stored hash, not from DEFAULT_ITERATIONS, so
    raising the default does not lock anyone out — `needs_rehash` upgrades them
    on their next successful login.
    """
    try:
        scheme, raw_iterations, salt_b64, digest_b64 = stored.split("$")
        if scheme != _SCHEME:
            return False
        expected = _b64d(digest_b64)
        actual = await _derive(password, _b64d(salt_b64), int(raw_iterations))
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(actual, expected)


def needs_rehash(stored: str, *, iterations: int = DEFAULT_ITERATIONS) -> bool:
    """True when a stored hash is below current cost and should be upgraded."""
    try:
        scheme, raw_iterations, _, _ = stored.split("$")
    except (ValueError, AttributeError):
        return True
    return scheme != _SCHEME or int(raw_iterations) < iterations


# --------------------------------------------------------------------------
# session tokens
# --------------------------------------------------------------------------

SESSION_COOKIE = "didi_session"
SESSION_TTL_SECONDS = 12 * 60 * 60  # one long shift

_TOKEN_VERSION = "v1"


class SessionError(Exception):
    """Raised when a session token is absent, malformed, forged or expired."""


def issue_session(user_id: int, secret: str, *, ttl: int = SESSION_TTL_SECONDS,
                  now: int | None = None) -> tuple[str, int]:
    """Return (token, expires_at). Token is `v1.<user_id>.<exp>.<signature>`."""
    issued = int(time.time()) if now is None else now
    expires_at = issued + ttl
    payload = f"{_TOKEN_VERSION}.{user_id}.{expires_at}"
    return f"{payload}.{_sign(payload, secret)}", expires_at


def read_session(token: str, secret: str, *, now: int | None = None) -> int:
    """Return the user id in a valid token, else raise SessionError.

    The signature is checked before the expiry is trusted, since the expiry is
    part of the signed payload — reading it from an unverified token would let
    anyone extend their own session.
    """
    if not token:
        raise SessionError("missing session token")
    try:
        version, raw_user_id, raw_expiry, signature = token.split(".")
    except (ValueError, AttributeError):
        raise SessionError("malformed session token") from None
    if version != _TOKEN_VERSION:
        raise SessionError("unsupported session token version")

    payload = f"{version}.{raw_user_id}.{raw_expiry}"
    if not hmac.compare_digest(_sign(payload, secret), signature):
        raise SessionError("bad session signature")

    try:
        expires_at = int(raw_expiry)
        user_id = int(raw_user_id)
    except ValueError:
        raise SessionError("malformed session token") from None

    current = int(time.time()) if now is None else now
    if current >= expires_at:
        raise SessionError("session expired")
    return user_id


def _sign(payload: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256)
    return _b64e(digest.digest())
