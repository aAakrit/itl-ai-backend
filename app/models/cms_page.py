from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.db import Base


class CmsPage(Base):
    __tablename__ = "cms_pages"

    id = Column(Integer, primary_key=True, index=True)

    route = Column(String(150), unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=False)

    content = Column(JSONB, nullable=False)

    status = Column(String(20), default="published")

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )