from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ----------------------------------------
# Base
# ----------------------------------------

class BookBase(BaseModel):
    name: str = Field(
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

    cover_image: Optional[str] = None

    status: str = "DRAFT"

    sort_order: int = 0


# ----------------------------------------
# Create
# ----------------------------------------

class BookCreate(BookBase):
    pass


# ----------------------------------------
# Update
# ----------------------------------------

class BookUpdate(BaseModel):

    name: Optional[str] = Field(
        default=None,
        max_length=255,
    )

    slug: Optional[str] = Field(
        default=None,
        max_length=255,
    )

    description: Optional[str] = None

    cover_image: Optional[str] = None

    status: Optional[str] = None

    sort_order: Optional[int] = None


# ----------------------------------------
# Response
# ----------------------------------------

class BookResponse(BookBase):

    id: UUID

    created_at: datetime

    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
    )


# ----------------------------------------
# Dropdown
# ----------------------------------------

class BookDropdown(BaseModel):

    id: UUID

    name: str

    model_config = ConfigDict(
        from_attributes=True,
    )


# ----------------------------------------
# List Response
# ----------------------------------------

class BookListResponse(BaseModel):

    total: int

    page: int

    limit: int

    results: list[BookResponse]