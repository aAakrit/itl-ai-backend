from uuid import uuid4

from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db import Base


class BookSection(Base):
    __tablename__ = "book_sections"

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

    parent_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "book_sections.id",
            ondelete="CASCADE",
        ),
        nullable=True,
        index=True,
    )

    title = Column(
        String(255),
        nullable=False,
    )

    slug = Column(
        String(255),
        nullable=False,
        index=True,
    )

    description = Column(
        Text,
        nullable=True,
    )

    sort_order = Column(
        Integer,
        nullable=False,
        default=0,
    )

    status = Column(
        String(20),
        nullable=False,
        default="DRAFT",
        index=True,
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

    # --------------------------
    # Relationships
    # --------------------------

    book = relationship(
        "Book",
        back_populates="sections",
    )

    parent = relationship(
        "BookSection",
        remote_side=[id],
        back_populates="children",
    )

    children = relationship(
        "BookSection",
        back_populates="parent",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="BookSection.sort_order",
    )

    contents = relationship(
        "BookContent",
        back_populates="section",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="BookContent.sort_order",
    )

    def __repr__(self):

        return (
            f"<BookSection("
            f"id={self.id}, "
            f"title='{self.title}'"
            f")>"
        )