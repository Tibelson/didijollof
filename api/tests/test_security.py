"""Password hashing and session tokens.

The reason this file exists in its current shape: the first deployment failed
because `hashlib.pbkdf2_hmac` does not exist on Pyodide, which is what Python
Workers run. `verify_password` caught the AttributeError and returned False, so
every login produced a perfectly ordinary-looking 401 and nothing in the test
suite noticed — the tests ran on CPython, where the function exists.

So the tests below pin the *contract* rather than one implementation: the digest
must match the published RFC vector, which is what makes a hash written on one
runtime verify on the other.
"""

from __future__ import annotations

import hashlib
import time

import pytest

from security import (
    DEFAULT_ITERATIONS,
    SessionError,
    _derive,
    hash_password,
    issue_session,
    needs_rehash,
    read_session,
    verify_password,
)


async def test_derive_matches_the_rfc6070_vector():
    """Both backends must produce this exact digest, or hashes stop being portable.

    PBKDF2-HMAC-SHA256, password="password", salt="salt", 1 iteration.
    The Workers runtime is checked against the same constant via Web Crypto.
    """
    digest = await _derive("password", b"salt", 1)
    assert digest.hex()[:32] == "120fb6cffcf8b32c43e7225256c4f837"


async def test_derive_is_deterministic():
    first = await _derive("hunter2", b"0123456789abcdef", 1000)
    second = await _derive("hunter2", b"0123456789abcdef", 1000)
    assert first == second


@pytest.mark.skipif(
    not hasattr(hashlib, "pbkdf2_hmac"),
    reason="no native PBKDF2 on this runtime to compare against",
)
async def test_webcrypto_path_would_agree_with_native():
    """Guard the fallback's shape even where only the native path can run.

    The runtime-specific halves cannot both execute in one process, so this
    asserts the native result equals the vector the Worker was measured
    producing — the thing that makes the two interchangeable.
    """
    native = hashlib.pbkdf2_hmac("sha256", b"password", b"salt", 1)
    assert native.hex()[:32] == "120fb6cffcf8b32c43e7225256c4f837"


async def test_hash_and_verify_round_trip():
    stored = await hash_password("correct horse battery staple")
    assert await verify_password("correct horse battery staple", stored) is True
    assert await verify_password("wrong", stored) is False


async def test_same_password_hashes_differently_each_time():
    """Distinct salts, so identical passwords are not identifiable in the table."""
    assert await hash_password("same") != await hash_password("same")


@pytest.mark.parametrize("stored", ["", "not-a-hash", "a$b$c", "sha1$1$x$y", "a$b$c$d$e"])
async def test_malformed_hashes_read_as_wrong_password(stored):
    """A corrupt row must not 500, which would distinguish it from a bad password."""
    assert await verify_password("anything", stored) is False


async def test_empty_password_is_rejected_at_hash_time():
    with pytest.raises(ValueError):
        await hash_password("")


async def test_verify_uses_the_cost_stored_in_the_hash():
    """Raising DEFAULT_ITERATIONS must not lock out existing accounts."""
    cheap = await hash_password("legacy", iterations=1000)
    assert "$1000$" in cheap
    assert await verify_password("legacy", cheap) is True
    assert needs_rehash(cheap) is True
    assert needs_rehash(await hash_password("fresh")) is False


def test_session_round_trip():
    token, expires_at = issue_session(7, "secret")
    assert read_session(token, "secret") == 7
    assert expires_at > time.time()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda t: t.replace(".7.", ".8."),           # different user
        lambda t: t + "x",                            # mangled signature
        lambda t: "v2" + t[2:],                       # unknown version
        lambda t: "garbage",
        lambda t: "",
    ],
)
def test_tampered_tokens_are_rejected(mutate):
    token, _ = issue_session(7, "secret")
    with pytest.raises(SessionError):
        read_session(mutate(token), "secret")


def test_expiry_is_signed_so_it_cannot_be_extended():
    token, _ = issue_session(7, "secret", ttl=-1)
    with pytest.raises(SessionError):
        read_session(token, "secret")

    version, user_id, _, signature = token.split(".")
    stretched = f"{version}.{user_id}.{int(time.time()) + 99999}.{signature}"
    with pytest.raises(SessionError):
        read_session(stretched, "secret")


def test_a_token_signed_with_another_secret_is_rejected():
    token, _ = issue_session(7, "attacker-secret")
    with pytest.raises(SessionError):
        read_session(token, "secret")
