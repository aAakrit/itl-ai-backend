from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.book import Book
from app.models.book_section import BookSection
from app.schemas.book_section import (
    BookSectionCreate,
    BookSectionUpdate,
)


class BookSectionService:

    @staticmethod
    def create(
        db: Session,
        payload: BookSectionCreate,
    ) -> BookSection:

        book = db.get(Book, payload.book_id)

        if not book:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Book not found.",
            )

        if payload.parent_id:

            parent = db.get(BookSection, payload.parent_id)

            if not parent:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Parent section not found.",
                )

            if parent.book_id != payload.book_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Parent section belongs to another book.",
                )

        existing = db.scalar(
            select(BookSection).where(
                BookSection.book_id == payload.book_id,
                BookSection.parent_id == payload.parent_id,
                or_(
                    BookSection.title == payload.title,
                    BookSection.slug == payload.slug,
                ),
            )
        )

        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Section already exists.",
            )

        data = payload.dict(exclude_unset=True)
        section = BookSection(**data)

        db.add(section)
        db.commit()
        db.refresh(section)

        return section

    @staticmethod
    def get(
        db: Session,
        section_id: UUID,
    ) -> BookSection:

        section = db.scalar(
            select(BookSection)
            .options(
                selectinload(BookSection.children),
                selectinload(BookSection.contents),
            )
            .where(BookSection.id == section_id)
        )

        if not section:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Section not found.",
            )

        return section

    @staticmethod
    def list(
        db: Session,
        book_id: UUID,
        page: int = 1,
        limit: int = 20,
        parent_id: UUID | None = None,
        search: str | None = None,
    ):

        query = select(BookSection).where(
            BookSection.book_id == book_id
        )

        if parent_id is None:
            query = query.where(BookSection.parent_id.is_(None))
        else:
            query = query.where(BookSection.parent_id == parent_id)

        if search:
            query = query.where(
                or_(
                    BookSection.title.ilike(f"%{search}%"),
                    BookSection.slug.ilike(f"%{search}%"),
                )
            )

        total = db.scalar(
            select(func.count()).select_from(query.subquery())
        )

        sections = db.scalars(
            query.order_by(
                BookSection.sort_order,
                BookSection.title,
            )
            .offset((page - 1) * limit)
            .limit(limit)
        ).all()

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "results": sections,
        }

    @staticmethod
    def update(
        db: Session,
        section_id: UUID,
        payload: BookSectionUpdate,
    ) -> BookSection:

        section = BookSectionService.get(db, section_id)

        data = payload.dict(exclude_unset=True)

        if "parent_id" in data:

            if data["parent_id"] == section.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Section cannot be its own parent.",
                )

            if data["parent_id"]:

                parent = db.get(BookSection, data["parent_id"])

                if not parent:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Parent section not found.",
                    )

                if parent.book_id != section.book_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Parent belongs to another book.",
                    )

        if "slug" in data:

            existing = db.scalar(
                select(BookSection).where(
                    BookSection.slug == data["slug"],
                    BookSection.book_id == section.book_id,
                    BookSection.id != section.id,
                )
            )

            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Slug already exists.",
                )

        if "title" in data:

            existing = db.scalar(
                select(BookSection).where(
                    BookSection.title == data["title"],
                    BookSection.book_id == section.book_id,
                    BookSection.parent_id == (
                        data.get("parent_id", section.parent_id)
                    ),
                    BookSection.id != section.id,
                )
            )

            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Section title already exists.",
                )

        for key, value in data.items():
            setattr(section, key, value)

        db.commit()
        db.refresh(section)

        return section

    @staticmethod
    def delete(
        db: Session,
        section_id: UUID,
    ):

        section = BookSectionService.get(db, section_id)

        db.delete(section)
        db.commit()

    @staticmethod
    def get_tree(
        db: Session,
        book_id: UUID,
    ):

        return (
            db.scalars(
                select(BookSection)
                .options(
                    selectinload(BookSection.children)
                )
                .where(
                    BookSection.book_id == book_id,
                    BookSection.parent_id.is_(None),
                )
                .order_by(BookSection.sort_order)
            )
            .unique()
            .all()
        )