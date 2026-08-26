from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from jose import jwt
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.user import User
from app.models.session import AuthSession
from app.models.password_reset_otp import PasswordResetOtp

from app.schemas.user import UserLogin, UserRegister

from app.services import email_service
from app.services.auth_utils import hash_password, verify_password
from app.services.jwt import (
    SECRET_KEY,
    ALGORITHM,
    create_token,
)

OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5

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
def register(user: UserRegister, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):

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
        gstin=user.gstin,

        address=user.address,
        city=user.city,
        state=user.state,
        pin_code=user.pin_code,

        status="PENDING",
    )

    db.add(new_user)
    db.commit()

    background_tasks.add_task(email_service.send_registration_email, to=new_user.email, name=new_user.name)

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


# =============================================================================
# Forgot password — OTP flow
#
# request -> emails a 6-digit code (always returns success, even for an
#            unknown email, so this endpoint can't be used to enumerate
#            registered addresses)
# verify  -> checks the code without consuming it, for the UI's "OTP" step
# reset   -> re-checks the SAME code (never trusts a prior verify call by
#            itself) and only then updates the password, marking the code
#            consumed and invalidating existing sessions
# =============================================================================

class PasswordOtpRequest(BaseModel):
    email: EmailStr


class PasswordOtpVerify(BaseModel):
    email: EmailStr
    otp: str


class PasswordResetSubmit(BaseModel):
    email: EmailStr
    otp: str
    password: str


def _generate_otp() -> str:
    import secrets
    return f"{secrets.randbelow(1_000_000):06d}"


def _latest_valid_otp(db: Session, email: str) -> "PasswordResetOtp | None":
    return (
        db.query(PasswordResetOtp)
        .filter(
            PasswordResetOtp.email == email,
            PasswordResetOtp.consumed_at.is_(None),
            PasswordResetOtp.expires_at > datetime.utcnow(),
        )
        .order_by(PasswordResetOtp.created_at.desc())
        .first()
    )


@router.post("/password/otp/request")
def request_password_otp(
    payload: PasswordOtpRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == payload.email).first()

    # Always the same response whether or not the account exists — the
    # point of the generic message is to not leak which emails are
    # registered.
    generic_response = {"success": True, "message": "If that email is registered, a code has been sent."}

    if not user:
        return generic_response

    code = _generate_otp()
    otp_row = PasswordResetOtp(
        user_id=user.id,
        email=user.email,
        code_hash=hash_password(code),
        expires_at=datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES),
    )
    db.add(otp_row)
    db.commit()

    background_tasks.add_task(
        email_service.send_password_reset_otp_email,
        to=user.email,
        otp=code,
        ttl_minutes=OTP_TTL_MINUTES,
    )

    return generic_response


@router.post("/password/otp/verify")
def verify_password_otp(payload: PasswordOtpVerify, db: Session = Depends(get_db)):
    otp_row = _latest_valid_otp(db, payload.email)

    if not otp_row or otp_row.attempts >= OTP_MAX_ATTEMPTS:
        return {"ok": False}

    if not verify_password(payload.otp, otp_row.code_hash):
        otp_row.attempts += 1
        db.commit()
        return {"ok": False}

    otp_row.verified_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@router.post("/password/reset")
def reset_password(payload: PasswordResetSubmit, db: Session = Depends(get_db)):
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    otp_row = _latest_valid_otp(db, payload.email)

    if not otp_row or otp_row.attempts >= OTP_MAX_ATTEMPTS or not verify_password(payload.otp, otp_row.code_hash):
        if otp_row:
            otp_row.attempts += 1
            db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired code — please request a new one.")

    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Account not found.")

    user.password = hash_password(payload.password)
    user.updated_at = datetime.utcnow()
    otp_row.consumed_at = datetime.utcnow()

    # A password reset invalidates every existing session — anyone signed
    # in elsewhere with the old password is signed out.
    db.query(AuthSession).filter(AuthSession.user_id == user.id, AuthSession.is_active.is_(True)).update(
        {"is_active": False, "invalidated_at": datetime.utcnow(), "invalidation_reason": "password_reset"}
    )

    db.commit()

    return {"success": True, "message": "Password updated. Please sign in with your new password."}