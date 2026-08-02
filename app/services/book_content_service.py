from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

import os
import tempfile
from pathlib import Path

import fitz
import mammoth
from bs4 import BeautifulSoup
from fastapi import UploadFile

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

    @staticmethod
    async def import_document(
        file: UploadFile,
    ):
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No file uploaded.",
            )

        extension = Path(file.filename).suffix.lower()

        if extension not in {".pdf", ".docx"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only PDF and DOCX files are supported.",
            )

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=extension,
        ) as temp:

            temp.write(await file.read())
            temp_path = temp.name

        try:

            if extension == ".docx":
                return BookContentService._import_docx(
                    temp_path,
                    file.filename,
                )

            return BookContentService._import_pdf(
                temp_path,
                file.filename,
            )

        finally:

            if os.path.exists(temp_path):
                os.remove(temp_path)

    @staticmethod
    def _import_docx(
        path: str,
        filename: str,
    ):

        with open(path, "rb") as document:

            result = mammoth.convert_to_html(document)

        html = result.value

        plain_text = BookContentService._html_to_text(html)

        return {
            "title": BookContentService._extract_title(
                plain_text,
                filename,
            ),
            "html_content": html,
            "plain_text": plain_text,
            "word_count": len(plain_text.split()),
            "page_count": None,
            "file_name": filename,
            "file_type": "docx",
        }

    @staticmethod
    def _import_pdf(
        path: str,
        filename: str,
    ):

        document = fitz.open(path)

        pages = []

        for page in document:
            pages.append(page.get_text("text"))

        plain_text = "\n\n".join(pages)

        html = BookContentService._text_to_html(
            plain_text,
        )

        return {
            "title": BookContentService._extract_title(
                plain_text,
                filename,
            ),
            "html_content": html,
            "plain_text": plain_text,
            "word_count": len(plain_text.split()),
            "page_count": len(document),
            "file_name": filename,
            "file_type": "pdf",
        }

    @staticmethod
    def _html_to_text(
        html: str,
    ) -> str:

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        return soup.get_text(
            separator="\n",
            strip=True,
        )

    @staticmethod
    def _text_to_html(
        text: str,
    ) -> str:

        paragraphs = []

        for line in text.splitlines():

            line = line.strip()

            if line:
                paragraphs.append(f"<p>{line}</p>")

        return "\n".join(paragraphs)

    @staticmethod
    def _extract_title(
        text: str,
        filename: str,
    ) -> str:

        for line in text.splitlines():

            line = line.strip()

            if line:
                return line[:500]

        return Path(filename).stem