"""Sign-in, sessions, and what an unauthenticated caller can reach."""

from __future__ import annotations

import time

import pytest

from conftest import CHEF_LEGON, PASSWORD
from security import SESSION_COOKIE, issue_session


async def test_login_succeeds_and_sets_a_session_cookie(client):
    response = await client.post(
        "/api/auth/login", json={"email": CHEF_LEGON, "password": PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == CHEF_LEGON
    assert body["role"] == "chef"
    assert [b["name"] for b in body["branches"]] == ["Legon Outlet"]

    cookie = response.cookies.get(SESSION_COOKIE)
    assert cookie, "login must set a session cookie"

    # The cookie must not be readable by scripts or sent cross-site.
    raw = response.headers["set-cookie"].lower()
    assert "httponly" in raw
    assert "samesite=lax" in raw
    assert "secure" in raw


async def test_login_rejects_a_wrong_password(client):
    response = await client.post(
        "/api/auth/login", json={"email": CHEF_LEGON, "password": "wrong"}
    )
    assert response.status_code == 401
    assert response.cookies.get(SESSION_COOKIE) is None


async def test_login_rejects_an_unknown_email_the_same_way(client):
    """Unknown email and wrong password must be indistinguishable."""
    unknown = await client.post(
        "/api/auth/login", json={"email": "nobody@didijollof.com", "password": "x"}
    )
    wrong = await client.post(
        "/api/auth/login", json={"email": CHEF_LEGON, "password": "x"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


async def test_login_timing_does_not_leak_account_existence(client):
    """An unknown email must cost the same as a wrong password.

    Asserted by measurement, not by inspection: an earlier version hashed the
    dummy at 1,000 iterations against real hashes at 100,000, so unknown
    accounts answered ~100x faster. The status codes matched perfectly and the
    leak was wide open, which is exactly why this test times the real thing.
    """
    import statistics
    import time

    async def median_ms(email, rounds=7):
        samples = []
        for _ in range(rounds):
            started = time.perf_counter()
            await client.post(
                "/api/auth/login", json={"email": email, "password": "wrong-password"}
            )
            samples.append((time.perf_counter() - started) * 1000)
        return statistics.median(samples)

    known = await median_ms(CHEF_LEGON)
    unknown = await median_ms("definitely-not-a-user@didijollof.com")

    ratio = max(known, unknown) / max(min(known, unknown), 0.001)
    assert ratio < 3, (
        f"login timing distinguishes accounts: known={known:.1f}ms "
        f"unknown={unknown:.1f}ms (ratio {ratio:.1f}x). The dummy hash cost "
        f"must match security.DEFAULT_ITERATIONS."
    )


async def test_dummy_hash_cost_matches_real_hashes():
    """The equaliser silently stops working if the two costs drift apart."""
    from routers.auth import _DUMMY_HASH
    from security import DEFAULT_ITERATIONS

    scheme, iterations, _, _ = _DUMMY_HASH.split("$")
    assert scheme == "pbkdf2_sha256"
    assert int(iterations) == DEFAULT_ITERATIONS, (
        "regenerate _DUMMY_HASH in routers/auth.py — see the note above it"
    )


async def test_me_requires_a_session(client):
    assert (await client.get("/api/me")).status_code == 401


async def test_me_returns_the_signed_in_user(client, chef):
    response = await client.get("/api/me", cookies=chef.cookies)
    assert response.status_code == 200
    assert response.json()["name"] == "Mr Fred"


async def test_owner_is_mapped_to_every_branch(client, owner):
    names = {b["name"] for b in owner.profile["branches"]}
    assert names == {"Legon Outlet", "Osu Outlet", "Airport Outlet"}


@pytest.mark.parametrize(
    "cookie",
    [
        "garbage",
        "v1.1.9999999999.wrongsignature",
        "",
    ],
)
async def test_forged_session_cookies_are_rejected(client, cookie):
    response = await client.get("/api/me", cookies={SESSION_COOKIE: cookie})
    assert response.status_code == 401


async def test_expired_session_is_rejected(client):
    expired, _ = issue_session(1, "test-secret", ttl=-10)
    response = await client.get("/api/me", cookies={SESSION_COOKIE: expired})
    assert response.status_code == 401


async def test_session_signed_with_another_secret_is_rejected(client):
    forged, _ = issue_session(1, "attacker-secret")
    response = await client.get("/api/me", cookies={SESSION_COOKIE: forged})
    assert response.status_code == 401


async def test_extending_a_session_expiry_is_rejected(client, chef):
    """The expiry is inside the signed payload, so editing it breaks the MAC."""
    token = chef.cookies[SESSION_COOKIE]
    version, user_id, _, signature = token.split(".")
    tampered = f"{version}.{user_id}.{int(time.time()) + 999_999}.{signature}"
    response = await client.get("/api/me", cookies={SESSION_COOKIE: tampered})
    assert response.status_code == 401


async def test_logout_clears_the_cookie(client, chef):
    response = await client.post("/api/auth/logout", cookies=chef.cookies)
    assert response.status_code == 204
    assert 'didi_session=""' in response.headers["set-cookie"] or \
           "didi_session=;" in response.headers["set-cookie"]
