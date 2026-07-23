from pydantic import BaseModel, EmailStr


class UserRegister(BaseModel):
    email: EmailStr
    password: str

    name: str

    mobile: str

    telephone: str | None = None
    fax: str | None = None

    firm: str | None = None

    address: str | None = None

    city: str
    state: str
    pin_code: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    name: str | None = None

    mobile: str | None = None
    telephone: str | None = None
    fax: str | None = None

    firm: str | None = None

    address: str | None = None

    city: str | None = None
    state: str | None = None
    pin_code: str | None = None

    status: str | None = None

    is_admin: bool | None = None
    is_staff: bool | None = None