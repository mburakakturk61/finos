from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """GET liste endpointleri için ortak sayfalama zarfı."""

    items: list[T]
    total: int
    limit: int
    offset: int
