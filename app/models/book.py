from uuid import uuid4

from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db import Base


class Book(Base):
    __tablename__ = "books"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    name = Column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )

    slug = Column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )

    description = Column(
        Text,
        nullable=True,
    )

    cover_image = Column(
        Text,
        nullable=True,
    )

    status = Column(
        String(20),
        nullable=False,
        default="DRAFT",
        index=True,
    )

    sort_order = Column(
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

    sections = relationship(
        "BookSection",
        back_populates="book",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="BookSection.sort_order",
    )

    contents = relationship(
        "BookContent",
        back_populates="book",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="BookContent.created_at",
    )

    def __repr__(self):

        return f"<Book(id={self.id}, name='{self.name}')>"