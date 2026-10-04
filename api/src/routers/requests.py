"""Purchase requests: submit one, list them, read one back."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

import queries
from deps import CurrentUser, assert_branch_access, current_user
from models import (
    RequestDetailOut,
    RequestIn,
    RequestLineOut,
    RequestSummaryOut,
)

router = APIRouter(tags=["requests"])

_STATUSES = {"active", "approved", "completed", "rejected"}


@router.post(
    "/branches/{branch_id}/requests",
    response_model=RequestDetailOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_request(
    payload: RequestIn,
    branch_id: int = Depends(assert_branch_access),
    user: CurrentUser = Depends(current_user),
) -> RequestDetailOut:
    lines = [(l.item_id, l.quantity, l.existing_stock) for l in payload.lines]
    try:
        order_id = await queries.create_request(branch_id, user.id, lines)
    except queries.UnknownItems as exc:
        raise HTTPException(
            status_code=422,
            detail=f"items not stocked at this branch: {exc.item_ids}",
        ) from None
    except queries.DuplicateItems:
        raise HTTPException(
            status_code=422,
            detail="the same item appears more than once",
        ) from None
    except queries.EmptyRequest:
        raise HTTPException(
            status_code=422,
            detail="a request needs at least one item",
        ) from None

    return await _detail(order_id)


@router.get(
    "/branches/{branch_id}/requests",
    response_model=list[RequestSummaryOut],
)
async def list_requests(
    branch_id: int = Depends(assert_branch_access),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[RequestSummaryOut]:
    if status_filter is not None and status_filter not in _STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"unknown status; expected one of {sorted(_STATUSES)}",
        )
    rows = await queries.list_requests(branch_id, status=status_filter, limit=limit)
    return [
        RequestSummaryOut(
            id=r["id"],
            created_at=r["created_at"],
            status=r["status"],
            requested_by=r["requested_by"],
            line_count=r["line_count"],
            item_count=r["item_count"],
            total=queries.money(r["total"]),
        )
        for r in rows
    ]


@router.get("/requests/{request_id}", response_model=RequestDetailOut)
async def get_request(
    request_id: int,
    user: CurrentUser = Depends(current_user),
) -> RequestDetailOut:
    """Read one request.

    This route is not nested under a branch, so it authorises by loading the
    request first and checking the caller against *its* branch. Same 404-not-403
    rule as elsewhere: a chef probing ids learns nothing about other branches.
    """
    row = await queries.get_request(request_id)
    if row is None or not await queries.user_can_access_branch(
        user.id, row["branch_id"]
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="request not found"
        )
    return await _detail(request_id)


async def _detail(order_id: int) -> RequestDetailOut:
    row = await queries.get_request(order_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="request not found"
        )
    line_rows = await queries.get_request_lines(order_id)
    lines = [
        RequestLineOut(
            item_id=l["item_id"],
            name=l["name"],
            unit=l["unit"],
            category=l["category"],
            quantity=l["quantity"],
            existing_stock=l["existing_stock"],
            unit_price=queries.money(l["unit_price"]),
            line_total=queries.money(l["line_total"]),
        )
        for l in line_rows
    ]
    return RequestDetailOut(
        id=row["id"],
        branch_id=row["branch_id"],
        branch_name=row["branch_name"],
        created_at=row["created_at"],
        status=row["status"],
        requested_by=row["requested_by"],
        review_note=row["review_note"],
        reviewed_at=row["reviewed_at"],
        lines=lines,
        total=round(sum(l.line_total for l in lines), 2),
    )
