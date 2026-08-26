from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from app.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    # Authentication
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=True)
    password = Column(String, nullable=False)

    # Profile
    name = Column(String(255), nullable=False)
    firm = Column(String(255))

    # Contact
    mobile = Column(String(20))
    telephone = Column(String(20))
    gstin = Column(String(20))

    address = Column(String(500))
    city = Column(String(100))
    state = Column(String(100))
    pin_code = Column(String(20))

    # Subscription (Future)
    plan = Column(String(50), nullable=True)

    # Status
    status = Column(String(20), default="PENDING", nullable=False)

    # Roles
    is_admin = Column(Boolean, default=False)
    is_staff = Column(Boolean, default=False)

    # Audit
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(Integer, nullable=True)

    last_login = Column(DateTime, nullable=True)

    deleted_at = Column(DateTime, nullable=True)