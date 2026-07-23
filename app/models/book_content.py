from uuid import uuid4

from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db import Base


class BookContent(Base):
    __tablename__ = "book_contents"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    book_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "books.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    section_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "book_sections.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    title = Column(
        String(500),
        nullable=False,
        index=True,
    )

    slug = Column(
        String(500),
        nullable=False,
        index=True,
    )

    reference_no = Column(
        String(255),
        nullable=True,
        index=True,
    )

    summary = Column(
        Text,
        nullable=True,
    )

    keywords = Column(
        ARRAY(String),
        nullable=False,
        default=list,
    )

    html_content = Column(
        Text,
        nullable=False,
    )

    plain_text = Column(
        Text,
        nullable=False,
    )

    status = Column(
        String(20),
        nullable=False,
        default="DRAFT",
        index=True,
    )

    version = Column(
        Integer,
        nullable=False,
        default=1,
    )

    sort_order = Column(
        Integer,
        nullable=False,
        default=0,
    )

    view_count = Column(
        Integer,
        nullable=False,
        default=0,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # -----------------------------------
    # Relationships
    # -----------------------------------

    book = relationship(
        "Book",
        back_populates="contents",
    )

    section = relationship(
        "BookSection",
        back_populates="contents",
    )

    def __repr__(self):

        return (
            f"<BookContent("
            f"id={self.id}, "
            f"title='{self.title}'"
            f")>"
        )