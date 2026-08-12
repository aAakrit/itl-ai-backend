from typing import Optional
from uuid import UUID

from app.schemas.book_content import BookContentCreate, BookContentUpdate
from app.schemas.book_section import BookSectionCreate, BookSectionUpdate
from app.utils.storage import read_file
from fastapi import APIRouter, Depends, Query, File, UploadFile, Response, HTTPException
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.models.user import User
from app.routes.auth import require_admin
from app.schemas.book import (
    BookCreate,
    BookUpdate,
)
from app.services.book_service import BookService
from app.services.book_section_service import BookSectionService
from app.services.book_content_service import BookContentService


router = APIRouter(
    prefix="/admin/books",
    tags=["Books"],
)


# ------------------------------------------------------------------
# Database
# ------------------------------------------------------------------


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()



# ==================================================================
#
# BOOK CONTENT
#
# ==================================================================


# ------------------------------------------------------------------
# List Content
# ------------------------------------------------------------------

@router.get("/contents")
def get_contents(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    book_id: UUID | None = None,
    section_id: UUID | None = None,
    search: Optional[str] = None,
    status: Optional[str] = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    return BookContentService.list(
        db=db,
        page=page,
        limit=limit,
        book_id=book_id,
        section_id=section_id,
        search=search,
        status_filter=status,
    )


# ------------------------------------------------------------------
# Content Detail
# ------------------------------------------------------------------

@router.get("/contents/{content_id}")
def get_content(
    content_id: UUID,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    return BookContentService.get(
        db=db,
        content_id=content_id,
    )


# ------------------------------------------------------------------
# Create Content
# ------------------------------------------------------------------

@router.post("/contents")
def create_content(
    payload: BookContentCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    return BookContentService.create(
        db=db,
        payload=payload,
    )


# ------------------------------------------------------------------
# Update Content
# ------------------------------------------------------------------

@router.put("/contents/{content_id}")
def update_content(
    content_id: UUID,
    payload: BookContentUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    return BookContentService.update(
        db=db,
        content_id=content_id,
        payload=payload,
    )


# ------------------------------------------------------------------
# Delete Content
# ------------------------------------------------------------------

@router.delete("/contents/{content_id}")
def delete_content(
    content_id: UUID,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    BookContentService.delete(
        db=db,
        content_id=content_id,
    )

    return {
        "success": True,
        "message": "Content deleted successfully.",
    }


# ------------------------------------------------------------------
# Content By Section
# ------------------------------------------------------------------

@router.get("/sections/{section_id}/contents")
def get_contents_by_section(
    section_id: UUID,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    return BookContentService.by_section(
        db=db,
        section_id=section_id,
    )


# ------------------------------------------------------------------
# Increment View Count
# ------------------------------------------------------------------

@router.post("/contents/{content_id}/view")
def increment_view(
    content_id: UUID,
    db: Session = Depends(get_db),
):

    return BookContentService.increment_view_count(
        db=db,
        content_id=content_id,
    )

@router.post("/contents/import")
async def import_content(
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return await BookContentService.import_document(
        file=file,
    )

@router.get("/contents/{content_id}/pdf")
def get_content_pdf(
    content_id: UUID,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    content = BookContentService.get(
        db,
        content_id,
    )

    if not content.attachment_path:
        raise HTTPException(
            status_code=404,
            detail="No document found.",
        )

    data = read_file(content.attachment_path)

    return Response(
        content=data,
        media_type=content.attachment_content_type,
        headers={
            "Content-Disposition":
                f'inline; filename="{content.attachment_filename}"'
        },
    )


# ==================================================================
#
# BOOKS
#
# ==================================================================


# ------------------------------------------------------------------
# List Books
# ------------------------------------------------------------------

@router.get("")
def get_books(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    status: Optional[str] = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    return BookService.list(
        db=db,
        page=page,
        limit=limit,
        search=search,
        status_filter=status,
    )


# ------------------------------------------------------------------
# Get Book
# ------------------------------------------------------------------

@router.get("/{book_id}")
def get_book(
    book_id: UUID,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    return BookService.get(
        db=db,
        book_id=book_id,
    )


# ------------------------------------------------------------------
# Create Book
# ------------------------------------------------------------------

@router.post("")
def create_book(
    payload: BookCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    return BookService.create(
        db=db,
        payload=payload,
    )


# ------------------------------------------------------------------
# Update Book
# ------------------------------------------------------------------

@router.put("/{book_id}")
def update_book(
    book_id: UUID,
    payload: BookUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    return BookService.update(
        db=db,
        book_id=book_id,
        payload=payload,
    )


# ------------------------------------------------------------------
# Delete Book
# ------------------------------------------------------------------

@router.delete("/{book_id}")
def delete_book(
    book_id: UUID,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    BookService.delete(
        db=db,
        book_id=book_id,
    )

    return {
        "success": True,
        "message": "Book deleted successfully.",
    }

# ==================================================================
#
# BOOK SECTIONS
#
# ==================================================================


# ------------------------------------------------------------------
# List Sections
# ------------------------------------------------------------------

@router.get("/{book_id}/sections")
def get_sections(
    book_id: UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    parent_id: UUID | None = None,
    search: Optional[str] = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    return BookSectionService.list(
        db=db,
        book_id=book_id,
        page=page,
        limit=limit,
        parent_id=parent_id,
        search=search,
    )


# ------------------------------------------------------------------
# Section Detail
# ------------------------------------------------------------------

@router.get("/sections/{section_id}")
def get_section(
    section_id: UUID,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    return BookSectionService.get(
        db=db,
        section_id=section_id,
    )


# ------------------------------------------------------------------
# Create Section
# ------------------------------------------------------------------

@router.post("/sections")
def create_section(
    payload: BookSectionCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    return BookSectionService.create(
        db=db,
        payload=payload,
    )


# ------------------------------------------------------------------
# Update Section
# ------------------------------------------------------------------

@router.put("/sections/{section_id}")
def update_section(
    section_id: UUID,
    payload: BookSectionUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    return BookSectionService.update(
        db=db,
        section_id=section_id,
        payload=payload,
    )


# ------------------------------------------------------------------
# Delete Section
# ------------------------------------------------------------------

@router.delete("/sections/{section_id}")
def delete_section(
    section_id: UUID,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    BookSectionService.delete(
        db=db,
        section_id=section_id,
    )

    return {
        "success": True,
        "message": "Section deleted successfully.",
    }


# ------------------------------------------------------------------
# Section Tree
# ------------------------------------------------------------------

@router.get("/{book_id}/tree")
def get_book_tree(
    book_id: UUID,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    return BookSectionService.get_tree(
        db=db,
        book_id=book_id,
    )


# ------------------------------------------------------------------
# Section Dropdown
# ------------------------------------------------------------------

@router.get("/{book_id}/sections/dropdown")
def get_section_dropdown(
    book_id: UUID,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):

    sections = BookSectionService.get_tree(
        db=db,
        book_id=book_id,
    )

    return sections
