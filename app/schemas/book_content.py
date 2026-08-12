from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------
# Base
# --------------------------------------------------

class BookContentBase(BaseModel):

    book_id: UUID

    section_id: UUID

    title: str = Field(
        ...,
        min_length=1,
        max_length=500,
    )

    slug: str = Field(
        ...,
        min_length=1,
        max_length=500,
    )

    reference_no: Optional[str] = Field(
        default=None,
        max_length=255,
    )

    attachment_path: Optional[str] = None

    attachment_filename: Optional[str] = None

    attachment_content_type: Optional[str] = None

    attachment_size: Optional[int] = None

    page_count: Optional[int] = None
    
    summary: Optional[str] = None

    keywords: List[str] = []

    html_content: str

    plain_text: str

    status: str = "DRAFT"

    version: int = 1

    sort_order: int = 0


# --------------------------------------------------
# Create
# --------------------------------------------------

class BookContentCreate(BookContentBase):
    pass


# --------------------------------------------------
# Update
# --------------------------------------------------

class BookContentUpdate(BaseModel):

    section_id: Optional[UUID] = None

    title: Optional[str] = Field(
        default=None,
        max_length=500,
    )

    slug: Optional[str] = Field(
        default=None,
        max_length=500,
    )

    reference_no: Optional[str] = Field(
        default=None,
        max_length=255,
    )

    summary: Optional[str] = None

    keywords: Optional[List[str]] = None

    html_content: Optional[str] = None

    plain_text: Optional[str] = None

    status: Optional[str] = None

    version: Optional[int] = None

    sort_order: Optional[int] = None


# --------------------------------------------------
# Response
# --------------------------------------------------

class BookContentResponse(BookContentBase):

    id: UUID

    view_count: int

    created_at: datetime

    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
    )


# --------------------------------------------------
# Dropdown
# --------------------------------------------------

class BookContentDropdown(BaseModel):

    id: UUID

    title: str

    model_config = ConfigDict(
        from_attributes=True,
    )


# --------------------------------------------------
# Search Result
# --------------------------------------------------

class BookContentSearchResult(BaseModel):

    id: UUID

    title: str

    reference_no: Optional[str]

    summary: Optional[str]

    section_id: UUID

    book_id: UUID

    model_config = ConfigDict(
        from_attributes=True,
    )


# --------------------------------------------------
# List Response
# --------------------------------------------------

class BookContentListResponse(BaseModel):

    total: int

    page: int

    limit: int

    results: List[BookContentResponse]