from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models.book import Book
from app.models.book_content import BookContent
from app.models.book_section import BookSection
from app.schemas.book_content import (
    BookContentCreate,
    BookContentUpdate,
)


class BookContentService:

    @staticmethod
    def create(
        db: Session,
        payload: BookContentCreate,
    ) -> BookContent:

        book = db.get(Book, payload.book_id)

        if not book:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Book not found.",
            )

        section = db.get(BookSection, payload.section_id)

        if not section:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Section not found.",
            )

        if section.book_id != payload.book_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Section does not belong to the selected book.",
            )

        existing = db.scalar(
            select(BookContent).where(
                BookContent.book_id == payload.book_id,
                BookContent.section_id == payload.section_id,
                or_(
                    BookContent.title == payload.title,
                    BookContent.slug == payload.slug,
                ),
            )
        )

        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Content already exists.",
            )

        content = BookContent(**payload.dict(exclude_unset=True))

        db.add(content)
        db.commit()
        db.refresh(content)

        return content

    @staticmethod
    def get(
        db: Session,
        content_id: UUID,
    ) -> BookContent:

        content = db.scalar(
            select(BookContent)
            .options(
                joinedload(BookContent.book),
                joinedload(BookContent.section),
            )
            .where(BookContent.id == content_id)
        )

        if not content:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Content not found.",
            )

        return content

    @staticmethod
    def list(
        db: Session,
        page: int = 1,
        limit: int = 20,
        book_id: UUID | None = None,
        section_id: UUID | None = None,
        search: str | None = None,
        status_filter: str | None = None,
    ):

        query = (
            select(BookContent)
            .options(
                joinedload(BookContent.book),
                joinedload(BookContent.section),
            )
        )

        if book_id:
            query = query.where(
                BookContent.book_id == book_id
            )

        if section_id:
            query = query.where(
                BookContent.section_id == section_id
            )

        if status_filter:
            query = query.where(
                BookContent.status == status_filter
            )

        if search:
            query = query.where(
                or_(
                    BookContent.title.ilike(f"%{search}%"),
                    BookContent.reference_no.ilike(f"%{search}%"),
                    BookContent.summary.ilike(f"%{search}%"),
                    BookContent.plain_text.ilike(f"%{search}%"),
                )
            )

        total = db.scalar(
            select(func.count()).select_from(query.subquery())
        )

        contents = db.scalars(
            query.order_by(
                BookContent.sort_order,
                BookContent.title,
            )
            .offset((page - 1) * limit)
            .limit(limit)
        ).all()

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "results": contents,
        }

    @staticmethod
    def update(
        db: Session,
        content_id: UUID,
        payload: BookContentUpdate,
    ) -> BookContent:

        content = BookContentService.get(
            db,
            content_id,
        )

        data = payload.dict(exclude_unset=True)

        if "section_id" in data:

            section = db.get(
                BookSection,
                data["section_id"],
            )

            if not section:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Section not found.",
                )

            if section.book_id != content.book_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Section belongs to another book.",
                )

        if "slug" in data:

            existing = db.scalar(
                select(BookContent).where(
                    BookContent.slug == data["slug"],
                    BookContent.id != content.id,
                )
            )

            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Slug already exists.",
                )

        if "title" in data:

            existing = db.scalar(
                select(BookContent).where(
                    BookContent.title == data["title"],
                    BookContent.section_id == (
                        data.get(
                            "section_id",
                            content.section_id,
                        )
                    ),
                    BookContent.id != content.id,
                )
            )

            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Title already exists in this section.",
                )

        for key, value in data.items():
            setattr(content, key, value)

        db.commit()
        db.refresh(content)

        return content

    @staticmethod
    def delete(
        db: Session,
        content_id: UUID,
    ):

        content = BookContentService.get(
            db,
            content_id,
        )

        db.delete(content)

        db.commit()

    @staticmethod
    def increment_view_count(
        db: Session,
        content_id: UUID,
    ) -> BookContent:

        content = BookContentService.get(
            db,
            content_id,
        )

        content.view_count += 1

        db.commit()

        db.refresh(content)

        return content

    @staticmethod
    def by_section(
        db: Session,
        section_id: UUID,
    ):

        return (
            db.scalars(
                select(BookContent)
                .where(
                    BookContent.section_id == section_id
                )
                .order_by(
                    BookContent.sort_order,
                    BookContent.title,
                )
            )
            .all()
        )