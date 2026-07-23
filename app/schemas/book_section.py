from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------
# Base
# --------------------------------------------------

class BookSectionBase(BaseModel):

    book_id: UUID

    parent_id: Optional[UUID] = None

    title: str = Field(
        ...,
        min_length=1,
        max_length=255,
    )

    slug: str = Field(
        ...,
        min_length=1,
        max_length=255,
    )

    description: Optional[str] = None

    sort_order: int = 0

    status: str = "DRAFT"


# --------------------------------------------------
# Create
# --------------------------------------------------

class BookSectionCreate(BookSectionBase):
    pass


# --------------------------------------------------
# Update
# --------------------------------------------------

class BookSectionUpdate(BaseModel):

    parent_id: Optional[UUID] = None

    title: Optional[str] = Field(
        default=None,
        max_length=255,
    )

    slug: Optional[str] = Field(
        default=None,
        max_length=255,
    )

    description: Optional[str] = None

    sort_order: Optional[int] = None

    status: Optional[str] = None


# --------------------------------------------------
# Response
# --------------------------------------------------

class BookSectionResponse(BookSectionBase):

    id: UUID

    created_at: datetime

    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
    )


# --------------------------------------------------
# Tree Response
# --------------------------------------------------

class BookSectionTree(BaseModel):

    id: UUID

    title: str

    slug: str

    description: Optional[str] = None

    sort_order: int

    status: str

    children: List["BookSectionTree"] = []

    model_config = ConfigDict(
        from_attributes=True,
    )


BookSectionTree.update_forward_refs()


# --------------------------------------------------
# Dropdown
# --------------------------------------------------

class BookSectionDropdown(BaseModel):

    id: UUID

    title: str

    model_config = ConfigDict(
        from_attributes=True,
    )


# --------------------------------------------------
# List Response
# --------------------------------------------------

class BookSectionListResponse(BaseModel):

    total: int

    page: int

    limit: int

    results: list[BookSectionResponse]