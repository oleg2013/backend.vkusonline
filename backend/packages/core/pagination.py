from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginationParams(BaseModel):
    page: int = 1
    per_page: int = 20

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page

    @property
    def limit(self) -> int:
        return self.per_page


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    per_page: int
    pages: int

    @classmethod
    def create(
        cls,
        items: list[Any],
        total: int,
        page: int,
        per_page: int,
    ) -> PaginatedResponse:
        pages = max(1, (total + per_page - 1) // per_page)
        return cls(items=items, total=total, page=page, per_page=per_page, pages=pages)
