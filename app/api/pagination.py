"""Reusable pagination building blocks for list endpoints (AD-021).

`PaginationParams` is a FastAPI dependency class exposing `limit`/`offset`
query params with the shared defaults/bounds, and `Page[T]` is the generic
response envelope every paginated endpoint returns. Both are
entity-agnostic on purpose: this module has no knowledge of projects,
tasks, or any other model, so `groups-rbac`'s upcoming `GET /groups`,
`/members`, and `/invites` endpoints can adopt the exact same shape without
duplicating this plumbing.
"""

from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")


class PaginationParams:
    """FastAPI dependency carrying page size/offset for a list endpoint.

    Used as `Annotated[PaginationParams, Depends()]` (or
    `= Depends()`) on a router handler; FastAPI resolves `limit`/`offset`
    from query params using the `Query(...)` bounds declared below.
    """

    def __init__(
        self,
        limit: int = Query(50, ge=1, le=100, description="Max items per page (1-100)."),
        offset: int = Query(0, ge=0, description="Number of items to skip."),
    ) -> None:
        self.limit = limit
        self.offset = offset


class Page(BaseModel, Generic[T]):
    """Generic response envelope for paginated list endpoints:
    `{"items": [...], "total": N, "limit": L, "offset": O}`. `total` is the
    full matching count regardless of `limit`, so clients can tell whether
    more pages exist.
    """

    items: list[T]
    total: int
    limit: int
    offset: int
