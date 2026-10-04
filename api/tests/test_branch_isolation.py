"""Branch isolation.

This is the property that matters most in a multi-branch deployment: a chef at
Legon must not be able to read, count against, or order for Osu — and must not
be able to tell that Osu exists by probing ids.

Every branch-scoped route is covered in both directions, read and write.
"""

from __future__ import annotations

import pytest


async def test_chef_can_read_their_own_branch(client, chef):
    response = await client.get(
        f"/api/branches/{chef.branch_id}/inventory", cookies=chef.cookies
    )
    assert response.status_code == 200
    assert response.json()["branch"]["name"] == "Legon Outlet"


async def test_chef_cannot_read_another_branch(client, chef, other_chef):
    assert chef.branch_id != other_chef.branch_id
    response = await client.get(
        f"/api/branches/{other_chef.branch_id}/inventory", cookies=chef.cookies
    )
    assert response.status_code == 404, "Legon must not see Osu's inventory"


async def test_chef_cannot_write_a_request_to_another_branch(
    client, chef, other_chef, helpers
):
    item_id = await helpers.item_named("Chicken")
    response = await client.post(
        f"/api/branches/{other_chef.branch_id}/requests",
        json={"lines": [{"item_id": item_id, "quantity": 5, "existing_stock": 1}]},
        cookies=chef.cookies,
    )
    assert response.status_code == 404, "Legon must not order against Osu"


async def test_chef_cannot_count_stock_at_another_branch(
    client, chef, other_chef, helpers
):
    item_id = await helpers.item_named("Chicken")
    response = await client.put(
        f"/api/branches/{other_chef.branch_id}/inventory/{item_id}/count",
        json={"current_stock": 99},
        cookies=chef.cookies,
    )
    assert response.status_code == 404


async def test_chef_cannot_list_another_branch_requests(client, chef, other_chef):
    response = await client.get(
        f"/api/branches/{other_chef.branch_id}/requests", cookies=chef.cookies
    )
    assert response.status_code == 404


async def test_chef_cannot_read_another_branch_suggestions(client, chef, other_chef):
    response = await client.get(
        f"/api/branches/{other_chef.branch_id}/inventory/suggestions",
        cookies=chef.cookies,
    )
    assert response.status_code == 404


async def test_chef_cannot_read_a_request_belonging_to_another_branch(
    client, chef, other_chef, helpers
):
    """Requests are fetched by id, not nested under a branch — authorise anyway."""
    item_id = await helpers.item_named("Chicken")
    created = await client.post(
        f"/api/branches/{other_chef.branch_id}/requests",
        json={"lines": [{"item_id": item_id, "quantity": 3, "existing_stock": 0}]},
        cookies=other_chef.cookies,
    )
    assert created.status_code == 201
    foreign_id = created.json()["id"]

    mine = await client.get(f"/api/requests/{foreign_id}", cookies=chef.cookies)
    assert mine.status_code == 404

    theirs = await client.get(
        f"/api/requests/{foreign_id}", cookies=other_chef.cookies
    )
    assert theirs.status_code == 200


async def test_denial_is_indistinguishable_from_a_missing_branch(client, chef):
    """A forbidden branch and a nonexistent one must look identical.

    `request_id` is excluded because it is unique on every response by design —
    including two calls to the same URL — so it carries nothing an attacker
    could use to tell the two cases apart. Everything that could is compared.
    """
    forbidden = await client.get("/api/branches/2/inventory", cookies=chef.cookies)
    missing = await client.get("/api/branches/99999/inventory", cookies=chef.cookies)

    assert forbidden.status_code == missing.status_code == 404

    def comparable(response):
        return {k: v for k, v in response.json().items() if k != "request_id"}

    assert comparable(forbidden) == comparable(missing)
    assert forbidden.json()["detail"] == missing.json()["detail"] == "branch not found"
    # Both must actually have an id; the exclusion above must not hide its absence.
    assert forbidden.json()["request_id"] and missing.json()["request_id"]


async def test_owner_can_read_every_branch(client, owner):
    for branch_id in owner.branch_ids:
        response = await client.get(
            f"/api/branches/{branch_id}/inventory", cookies=owner.cookies
        )
        assert response.status_code == 200


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/api/branches/{bid}/inventory", None),
        ("get", "/api/branches/{bid}/requests", None),
        ("get", "/api/branches/{bid}/inventory/suggestions", None),
        ("post", "/api/branches/{bid}/requests", {"lines": []}),
    ],
)
async def test_every_branch_route_requires_a_session(client, method, path, body):
    url = path.format(bid=1)
    call = getattr(client, method)
    response = await (call(url, json=body) if body is not None else call(url))
    assert response.status_code == 401, f"{method.upper()} {url} must require auth"
