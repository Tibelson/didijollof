"""Submitting requests: server-side pricing, price snapshots, validation."""

from __future__ import annotations


async def test_inventory_exposes_the_statuses_the_ui_renders(client, chef):
    body = (
        await client.get(
            f"/api/branches/{chef.branch_id}/inventory", cookies=chef.cookies
        )
    ).json()
    statuses = {item["status"] for item in body["items"]}
    assert statuses == {"out", "critical", "low", "full"}
    assert body["below_par"] > 0


async def test_inventory_can_be_filtered_and_searched(client, chef):
    base = f"/api/branches/{chef.branch_id}/inventory"

    protein = (
        await client.get(base, params={"category": "protein"}, cookies=chef.cookies)
    ).json()
    assert {i["category"] for i in protein["items"]} == {"protein"}

    found = (
        await client.get(base, params={"q": "chick"}, cookies=chef.cookies)
    ).json()
    assert [i["name"] for i in found["items"]] == ["Chicken"]

    bad = await client.get(base, params={"category": "nope"}, cookies=chef.cookies)
    assert bad.status_code == 422


async def test_search_cannot_inject_sql(client, chef):
    """A wildcard-laden search is data, not syntax."""
    response = await client.get(
        f"/api/branches/{chef.branch_id}/inventory",
        params={"q": "'; DROP TABLE items; --"},
        cookies=chef.cookies,
    )
    assert response.status_code == 200
    assert response.json()["items"] == []

    # The table is still there.
    again = await client.get(
        f"/api/branches/{chef.branch_id}/inventory", cookies=chef.cookies
    )
    assert len(again.json()["items"]) > 0


async def test_totals_are_computed_server_side(client, chef, helpers):
    chicken = await helpers.item_named("Chicken")   # 45.00 / pc
    packs = await helpers.item_named("Takeaway packs")  # 9.00 / pack

    response = await client.post(
        f"/api/branches/{chef.branch_id}/requests",
        json={
            "lines": [
                {"item_id": chicken, "quantity": 24, "existing_stock": 2},
                {"item_id": packs, "quantity": 55, "existing_stock": 12},
            ]
        },
        cookies=chef.cookies,
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["total"] == 24 * 45.0 + 55 * 9.0 == 1575.0
    by_name = {l["name"]: l for l in body["lines"]}
    assert by_name["Chicken"]["line_total"] == 1080.0
    assert by_name["Takeaway packs"]["line_total"] == 495.0
    assert body["status"] == "active"


async def test_a_price_change_does_not_rewrite_past_requests(
    client, chef, helpers
):
    """The snapshot is the whole point: history must not drift."""
    chicken = await helpers.item_named("Chicken")
    created = await client.post(
        f"/api/branches/{chef.branch_id}/requests",
        json={"lines": [{"item_id": chicken, "quantity": 10, "existing_stock": 2}]},
        cookies=chef.cookies,
    )
    request_id = created.json()["id"]
    assert created.json()["total"] == 450.0

    await helpers.set_item_price("Chicken", "90.00")

    after = await client.get(f"/api/requests/{request_id}", cookies=chef.cookies)
    assert after.json()["total"] == 450.0, "a later price change must not alter history"
    assert after.json()["lines"][0]["unit_price"] == 45.0

    # But a new request prices at the new rate.
    fresh = await client.post(
        f"/api/branches/{chef.branch_id}/requests",
        json={"lines": [{"item_id": chicken, "quantity": 10, "existing_stock": 2}]},
        cookies=chef.cookies,
    )
    assert fresh.json()["total"] == 900.0


async def test_submitting_records_the_stock_counts(client, chef, helpers):
    """The chef counted while building the list; don't make them do it twice."""
    chicken = await helpers.item_named("Chicken")
    await client.post(
        f"/api/branches/{chef.branch_id}/requests",
        json={"lines": [{"item_id": chicken, "quantity": 20, "existing_stock": 7}]},
        cookies=chef.cookies,
    )
    inventory = (
        await client.get(
            f"/api/branches/{chef.branch_id}/inventory", cookies=chef.cookies
        )
    ).json()
    item = next(i for i in inventory["items"] if i["id"] == chicken)
    assert item["current_stock"] == 7
    assert item["counted_at"] is not None


async def test_an_item_not_stocked_at_the_branch_is_rejected(client, chef):
    response = await client.post(
        f"/api/branches/{chef.branch_id}/requests",
        json={"lines": [{"item_id": 999_999, "quantity": 1, "existing_stock": 0}]},
        cookies=chef.cookies,
    )
    assert response.status_code == 422


async def test_duplicate_lines_are_rejected(client, chef, helpers):
    chicken = await helpers.item_named("Chicken")
    response = await client.post(
        f"/api/branches/{chef.branch_id}/requests",
        json={
            "lines": [
                {"item_id": chicken, "quantity": 1, "existing_stock": 0},
                {"item_id": chicken, "quantity": 2, "existing_stock": 0},
            ]
        },
        cookies=chef.cookies,
    )
    assert response.status_code == 422


async def test_invalid_quantities_are_rejected(client, chef, helpers):
    chicken = await helpers.item_named("Chicken")
    for bad in ({"quantity": 0}, {"quantity": -5}, {"existing_stock": -1}):
        line = {"item_id": chicken, "quantity": 1, "existing_stock": 0, **bad}
        response = await client.post(
            f"/api/branches/{chef.branch_id}/requests",
            json={"lines": [line]},
            cookies=chef.cookies,
        )
        assert response.status_code == 422, f"{bad} should be rejected"


async def test_an_empty_request_is_rejected(client, chef):
    response = await client.post(
        f"/api/branches/{chef.branch_id}/requests",
        json={"lines": []},
        cookies=chef.cookies,
    )
    assert response.status_code == 422


async def test_a_failed_request_leaves_nothing_behind(client, chef, helpers):
    """One bad line must roll the whole thing back, not half-write it."""
    chicken = await helpers.item_named("Chicken")
    before = (
        await client.get(
            f"/api/branches/{chef.branch_id}/requests", cookies=chef.cookies
        )
    ).json()

    failed = await client.post(
        f"/api/branches/{chef.branch_id}/requests",
        json={
            "lines": [
                {"item_id": chicken, "quantity": 5, "existing_stock": 1},
                {"item_id": 999_999, "quantity": 5, "existing_stock": 1},
            ]
        },
        cookies=chef.cookies,
    )
    assert failed.status_code == 422

    after = (
        await client.get(
            f"/api/branches/{chef.branch_id}/requests", cookies=chef.cookies
        )
    ).json()
    assert len(after) == len(before), "a rejected request must not be persisted"


async def test_history_lists_newest_first_with_totals(client, chef, helpers):
    chicken = await helpers.item_named("Chicken")
    beef = await helpers.item_named("Beef")
    for item_id, qty in ((chicken, 2), (beef, 4)):
        await client.post(
            f"/api/branches/{chef.branch_id}/requests",
            json={"lines": [{"item_id": item_id, "quantity": qty, "existing_stock": 1}]},
            cookies=chef.cookies,
        )

    history = (
        await client.get(
            f"/api/branches/{chef.branch_id}/requests", cookies=chef.cookies
        )
    ).json()
    assert len(history) == 2
    assert history[0]["created_at"] >= history[1]["created_at"]
    assert history[0]["total"] == 4 * 25.0
    assert history[0]["requested_by"] == "Mr Fred"

    pending = (
        await client.get(
            f"/api/branches/{chef.branch_id}/requests",
            params={"status": "active"},
            cookies=chef.cookies,
        )
    ).json()
    assert len(pending) == 2


async def test_suggestions_reflect_the_last_request(client, chef, helpers):
    url = f"/api/branches/{chef.branch_id}/inventory/suggestions"
    assert (await client.get(url, cookies=chef.cookies)).json() is None

    chicken = await helpers.item_named("Chicken")
    await client.post(
        f"/api/branches/{chef.branch_id}/requests",
        json={"lines": [{"item_id": chicken, "quantity": 6, "existing_stock": 1}]},
        cookies=chef.cookies,
    )

    suggestion = (await client.get(url, cookies=chef.cookies)).json()
    assert suggestion["line_count"] == 1
    assert suggestion["total"] == 270.0
