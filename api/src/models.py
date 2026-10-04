"""Request and response shapes.

Money never appears on an inbound model. The client sends quantities and
counts; the server prices them. That keeps the price snapshot authoritative and
means a tampered payload cannot change what a request is worth.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


# ------------------------------------------------------------- inbound

class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class StockCountIn(BaseModel):
    current_stock: int = Field(ge=0, le=1_000_000)


class RequestLineIn(BaseModel):
    item_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100_000)
    existing_stock: int = Field(ge=0, le=1_000_000)


class RequestIn(BaseModel):
    lines: list[RequestLineIn] = Field(min_length=1, max_length=200)


# ------------------------------------------------------------ outbound

class BranchOut(BaseModel):
    id: int
    name: str
    location: str


class MeOut(BaseModel):
    id: int
    name: str
    email: str
    role: str
    branches: list[BranchOut]


class InventoryItemOut(BaseModel):
    id: int
    name: str
    unit: str
    category: str
    price: float
    image_url: str | None = None
    current_stock: int
    min_level: int
    par_level: int
    status: str
    counted_at: datetime | None = None

    @property
    def suggested_quantity(self) -> int:
        return max(self.par_level - self.current_stock, 0)


class InventoryOut(BaseModel):
    branch: BranchOut
    below_par: int
    items: list[InventoryItemOut]


class SuggestionOut(BaseModel):
    """Backs "Same as yesterday" — None when the branch has no history."""

    request_id: int
    created_at: datetime
    line_count: int
    total: float


class RequestSummaryOut(BaseModel):
    id: int
    created_at: datetime
    status: str
    requested_by: str
    line_count: int
    item_count: int
    total: float


class RequestLineOut(BaseModel):
    item_id: int
    name: str
    unit: str
    category: str
    quantity: int
    existing_stock: int
    unit_price: float
    line_total: float


class RequestDetailOut(BaseModel):
    id: int
    branch_id: int
    branch_name: str
    created_at: datetime
    status: str
    requested_by: str
    review_note: str | None = None
    reviewed_at: datetime | None = None
    lines: list[RequestLineOut]
    total: float
