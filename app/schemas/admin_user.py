from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

class UserUpdate(BaseModel):
    name: Optional[str] = None
    firm: Optional[str] = None

    mobile: Optional[str] = None
    telephone: Optional[str] = None
    fax: Optional[str] = None

    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pin_code: Optional[str] = None

    plan: Optional[str] = None

    status: Optional[str] = None

    is_admin: Optional[bool] = None
    is_staff: Optional[bool] = None

class UserListItem(BaseModel):
    id: int

    name: str
    email: str

    mobile: Optional[str] = None
    firm: Optional[str] = None

    plan: Optional[str] = None

    role: str
    status: str

    last_login: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class UserListResponse(BaseModel):
    items: list[UserListItem]

    page: int
    limit: int
    total: int

class UserDetailResponse(BaseModel):
    id: int

    name: str
    email: str

    firm: Optional[str] = None

    mobile: Optional[str] = None
    telephone: Optional[str] = None
    fax: Optional[str] = None

    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pin_code: Optional[str] = None

    plan: Optional[str] = None

    status: str

    is_admin: bool
    is_staff: bool

    created_at: datetime
    updated_at: Optional[datetime] = None
    last_login: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

class AdminActionResponse(BaseModel):
    success: bool
    message: str

class UserHistoryItem(BaseModel):
    timestamp: datetime
    action: str
    performed_by: Optional[str] = None
    description: Optional[str] = None


class UserHistoryResponse(BaseModel):
    items: list[UserHistoryItem]