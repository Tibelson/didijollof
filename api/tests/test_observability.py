"""Request tracing and error reporting.

The property being protected: when something fails, there is a reference the
user can quote and an operator can search for, and the two are the same string.
Without that, a report is "it broke sometimes" and there is nothing to look up.
"""

from __future__ import annotations

import json

import pytest

from conftest import CHEF_LEGON, PASSWORD
from observability import REQUEST_ID_HEADER, log, new_request_id


async def test_every_response_carries_a_request_id(client):
    response = await client.get("/api/health")
    assert response.headers.get(REQUEST_ID_HEADER)


async def test_request_ids_differ_between_requests(client):
    first = (await client.get("/api/health")).headers[REQUEST_ID_HEADER]
    second = (await client.get("/api/health")).headers[REQUEST_ID_HEADER]
    assert first != second


async def test_error_responses_repeat_the_id_in_the_body(client):
    """The body is what a chef can screenshot; the header is for tooling."""
    response = await client.get("/api/me")          # 401, no session
    assert response.status_code == 401
    body = response.json()
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]


async def test_validation_errors_also_carry_the_id(client, chef):
    response = await client.post(
        f"/api/branches/{chef.branch_id}/requests",
        json={"lines": [{"item_id": "not-a-number", "quantity": 1, "existing_stock": 0}]},
        cookies=chef.cookies,
    )
    assert response.status_code == 422
    assert response.json()["request_id"]


async def test_cloudflare_ray_id_is_used_when_present():
    """Matching CF's own id makes a log line findable in their dashboard too."""
    assert new_request_id({"cf-ray": "8a1b2c3d4e5f6789-LHR"}) == "8a1b2c3d4e5f6789"
    assert new_request_id({}) != new_request_id({})


async def test_unhandled_errors_do_not_leak_internals(client, monkeypatch):
    """A 500 should give a reference, not a stack trace."""
    import db

    async def boom(*_args, **_kwargs):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(db, "fetchval", boom)
    response = await client.get("/api/health/db")
    assert response.status_code == 503
    body = response.json()
    assert "secret internal detail" not in json.dumps(body)
    assert body["error"] == "RuntimeError"
    assert body["request_id"]


async def test_client_errors_are_accepted_and_capped(client):
    """Browser failures are otherwise invisible, so the endpoint is open —
    which means it must be hard to abuse."""
    response = await client.post("/api/client-error", json={
        "message": "x" * 5000,
        "stack": "y" * 50000,
        "screen": "/review",
    })
    assert response.status_code == 204


@pytest.mark.parametrize("payload", ['"a string"', "[1,2,3]", "null", "not json at all"])
async def test_client_error_endpoint_shrugs_off_junk(client, payload):
    response = await client.post(
        "/api/client-error", content=payload,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 204


def test_log_emits_one_json_object_per_line(capsys):
    log("test.event", level="info", branch_id=1, note="hello")
    line = capsys.readouterr().out.strip()
    record = json.loads(line)
    assert record["event"] == "test.event"
    assert record["branch_id"] == 1
    assert "ts" in record and "request_id" in record


def test_log_never_raises_on_unserialisable_values(capsys):
    """Logging must not be able to break the request it is describing."""
    log("test.event", weird=object())
    assert capsys.readouterr().out.strip()
