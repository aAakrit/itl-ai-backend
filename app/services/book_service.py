from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.book import Book
from app.schemas.book import BookCreate
from app.schemas.book import BookUpdate


class BookService:

    @staticmethod
    def create(
        db: Session,
        payload: BookCreate,
    ) -> Book:

        existing = db.scalar(
            select(Book).where(
                or_(
                    Book.name == payload.name,
                    Book.slug == payload.slug,
                )
            )
        )

        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Book already exists.",
            )

        book = Book(
            name=payload.name,
            slug=payload.slug,
            description=payload.description,
            cover_image=payload.cover_image,
            status=payload.status,
            sort_order=payload.sort_order,
        )

        db.add(book)
        db.commit()
        db.refresh(book)

        return book

    @staticmethod
    def get(
        db: Session,
        book_id: UUID,
    ) -> Book:

        book = db.get(Book, book_id)

        if not book:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Book not found.",
            )

        return book

    @staticmethod
    def list(
        db: Session,
        page: int = 1,
        limit: int = 20,
        search: str | None = None,
        status_filter: str | None = None,
    ):

        query = select(Book)

        if search:
            query = query.where(
                or_(
                    Book.name.ilike(f"%{search}%"),
                    Book.slug.ilike(f"%{search}%"),
                    Book.description.ilike(f"%{search}%"),
                )
            )

        if status_filter:
            query = query.where(
                Book.status == status_filter
            )

        total = db.scalar(
            select(func.count()).select_from(query.subquery())
        )

        books = db.scalars(
            query.order_by(Book.sort_order, Book.name)
            .offset((page - 1) * limit)
            .limit(limit)
        ).all()

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "results": books,
        }

    @staticmethod
    def update(
        db: Session,
        book_id: UUID,
        payload: BookUpdate,
    ) -> Book:

        book = BookService.get(db, book_id)

        data = payload.dict(exclude_unset=True)

        if "name" in data:

            existing = db.scalar(
                select(Book).where(
                    Book.name == data["name"],
                    Book.id != book_id,
                )
            )

            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Book name already exists.",
                )

        if "slug" in data:

            existing = db.scalar(
                select(Book).where(
                    Book.slug == data["slug"],
                    Book.id != book_id,
                )
            )

            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Book slug already exists.",
                )

        for key, value in data.items():
            setattr(book, key, value)

        db.commit()
        db.refresh(book)

        return book

    @staticmethod
    def delete(
        db: Session,
        book_id: UUID,
    ) -> None:

        book = BookService.get(db, book_id)

        db.delete(book)
        db.commit()