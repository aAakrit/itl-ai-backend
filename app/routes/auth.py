from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from jose import jwt
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.user import User
from app.models.session import AuthSession

from app.schemas.user import UserLogin, UserRegister

from app.services.auth_utils import hash_password, verify_password
from app.services.jwt import (
    SECRET_KEY,
    ALGORITHM,
    create_token,
)

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

@router.post("/register")
def register(user: UserRegister, db: Session = Depends(get_db)):

    existing = db.query(User).filter(User.email == user.email).first()

    if existing:
        raise HTTPException(
            status_code=400,
            detail="User already exists"
        )

    new_user = User(
        email=user.email,
        password=hash_password(user.password),

        name=user.name,

        firm=user.firm,

        mobile=user.mobile,
        telephone=user.telephone,
        fax=user.fax,

        address=user.address,
        city=user.city,
        state=user.state,
        pin_code=user.pin_code,

        status="PENDING",
    )

    db.add(new_user)
    db.commit()

    return {
        "success": True,
        "message": "Registration successful. Awaiting admin approval.",
        "user": {
            "id": new_user.id,
            "email": new_user.email,
            "status": new_user.status,
        }
    }

@router.post("/login")
def login(
    user: UserLogin,
    request: Request,
    db: Session = Depends(get_db),
):

    db_user = (
        db.query(User)
        .filter(User.email == user.email)
        .first()
    )

    if not db_user:
        raise HTTPException(
            status_code=400,
            detail="Invalid credentials",
        )

    if not verify_password(
        user.password,
        db_user.password,
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid credentials",
        )

    if db_user.status == "PENDING":
        raise HTTPException(
            status_code=403,
            detail="Account awaiting approval",
        )

    if db_user.status == "SUSPENDED":
        raise HTTPException(
            status_code=403,
            detail="Account suspended",
        )

    if db_user.status == "DELETED":
        raise HTTPException(
            status_code=403,
            detail="Account deleted",
        )

    db.query(AuthSession).filter(
        AuthSession.user_id == db_user.id,
        AuthSession.is_active == True,
    ).update(
        {
            "is_active": False,
            "invalidated_at": datetime.utcnow(),
            "invalidation_reason": "new_login",
        }
    )

    token, jti = create_token(db_user.id)

    session = AuthSession(
        user_id=db_user.id,
        token_jti=jti,
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent"),
    )

    db_user.last_login = datetime.utcnow()

    db.add(session)
    db.commit()

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": db_user.id,
            "email": db_user.email,
            "name": db_user.name,
            "is_admin": db_user.is_admin,
            "is_staff": db_user.is_staff,
        },
    }


@router.post("/logout")
def logout(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):

    payload = jwt.decode(
        token,
        SECRET_KEY,
        algorithms=[ALGORITHM],
    )

    jti = payload.get("jti")

    session = (
        db.query(AuthSession)
        .filter(
            AuthSession.token_jti == jti,
            AuthSession.is_active == True,
        )
        .first()
    )

    if session:
        session.is_active = False
        session.invalidated_at = datetime.utcnow()
        session.invalidation_reason = "logout"

        db.commit()

    return {
        "message": "Logged out"
    }


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):

    try:

        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
        )

        user_id = int(payload.get("sub"))
        jti = payload.get("jti")

        session = (
            db.query(AuthSession)
            .filter(
                AuthSession.token_jti == jti,
                AuthSession.is_active == True,
            )
            .first()
        )

        if not session:
            raise HTTPException(
                401,
                "Session expired"
            )

        if session.created_at < datetime.utcnow() - timedelta(hours=8):

            session.is_active = False
            session.invalidated_at = datetime.utcnow()
            session.invalidation_reason = "timeout"

            db.commit()

            raise HTTPException(
                401,
                "Session expired"
            )

        user = (
            db.query(User)
            .filter(User.id == user_id)
            .first()
        )

        if user.status != "APPROVED":
            raise HTTPException(
                status_code=401,
                detail="Account is inactive",
            )

        if not user:
            raise HTTPException(
                401,
                "User not found"
            )

        return user

    except Exception:

        raise HTTPException(
            401,
            "Invalid token"
        )


@router.get("/me")
def me(
    user: User = Depends(get_current_user),
):

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "firm": user.firm,
        "mobile": user.mobile,
        "status": user.status,
        "is_admin": user.is_admin,
        "is_staff": user.is_staff,
        "plan": user.plan,
    }


def require_admin(
    user: User = Depends(get_current_user),
):
    if not user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Admin only",
        )

    return user