"""Branch inventory: what is on the shelf, and what was ordered last time."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

import queries
from deps import CurrentUser, assert_branch_access, current_user
from models import (
    BranchOut,
    InventoryItemOut,
    InventoryOut,
    StockCountIn,
    SuggestionOut,
)

router = APIRouter(tags=["inventory"])

_CATEGORIES = {"produce", "protein", "spices", "packaging", "other"}


@router.get("/branches/{branch_id}/inventory", response_model=InventoryOut)
async def get_inventory(
    branch_id: int = Depends(assert_branch_access),
    category: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
    user: CurrentUser = Depends(current_user),
) -> InventoryOut:
    if category is not None and category not in _CATEGORIES:
        raise HTTPException(
            status_code=422,
            detail=f"unknown category; expected one of {sorted(_CATEGORIES)}",
        )

    search = q.strip() if q and q.strip() else None
    rows = await queries.list_inventory(branch_id, category=category, search=search)
    below_par = await queries.count_below_par(branch_id)
    branch = await _branch_for(user, branch_id)

    return InventoryOut(
        branch=branch,
        below_par=below_par,
        items=[
            InventoryItemOut(
                id=r["id"],
                name=r["name"],
                unit=r["unit"],
                category=r["category"],
                price=queries.money(r["price"]),
                image_url=r["image_url"],
                current_stock=r["current_stock"],
                min_level=r["min_level"],
                par_level=r["par_level"],
                status=r["status"],
                counted_at=r["counted_at"],
            )
            for r in rows
        ],
    )


@router.put("/branches/{branch_id}/inventory/{item_id}/count")
async def set_count(
    payload: StockCountIn,
    item_id: int,
    branch_id: int = Depends(assert_branch_access),
    user: CurrentUser = Depends(current_user),
) -> dict:
    """Record a count without submitting a request."""
    row = await queries.set_stock_count(
        branch_id, item_id, payload.current_stock, user.id
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="item is not stocked at this branch",
        )
    return {
        "item_id": row["item_id"],
        "current_stock": row["current_stock"],
        "counted_at": row["counted_at"],
    }


@router.get(
    "/branches/{branch_id}/inventory/suggestions",
    response_model=SuggestionOut | None,
)
async def suggestions(
    branch_id: int = Depends(assert_branch_access),
) -> SuggestionOut | None:
    """The branch's last request, for the "Same as yesterday" shortcut."""
    row = await queries.last_submitted_request(branch_id)
    if row is None:
        return None
    return SuggestionOut(
        request_id=row["id"],
        created_at=row["created_at"],
        line_count=row["line_count"],
        total=queries.money(row["total"]),
    )


async def _branch_for(user: CurrentUser, branch_id: int) -> BranchOut:
    for b in await queries.branches_for_user(user.id):
        if b["id"] == branch_id:
            return BranchOut(**dict(b))
    # Unreachable: assert_branch_access already proved membership.
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="branch not found")
