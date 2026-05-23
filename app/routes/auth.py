from fastapi import (APIRouter, Depends, HTTPException,
                     status, Query, Body, UploadFile, File)
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import AsyncSessionLocal
from app.email_service import send_password_reset_email, send_verification_email
from app.limiter import limiter
from app.models.user_model import User
from app.schemas.user_schemas import (
    AvatarPresetUpdate,
    ForgotPasswordRequest,
    ResendVerification,
    ResetPasswordRequest,
    SignupResponse,
    UserAdminOut,
    UserAvatarOut,
    UserCreate,
    UserLogin,
    UserOut,
    UserRoleUpdate,
)
from sqlalchemy.future import select
from passlib.hash import bcrypt
from fastapi.responses import JSONResponse
from fastapi import Request
from PIL import Image, ImageOps
from pydantic import BaseModel

from app.models.mobile_auth_code import MobileAuthCode
from app.models.mobile_refresh_token import MobileRefreshToken
from app.utils.captcha import verify_captcha
from app.utils.token_utils import create_access_token, get_current_user
from app.utils.email_token_utils import (
    generate_email_token,
    generate_password_reset_token,
    verify_email_token,
    verify_password_reset_token,
)
from google.oauth2 import id_token
from google.auth.transport import requests
from datetime import datetime, timedelta, timezone
import os
import json
import io
import hashlib
import secrets
from urllib.parse import urlencode
from urllib.request import urlopen
from jose import JWTError
from typing import Optional
from app.deps.admin import require_admin
from app.s3 import upload_to_s3

router = APIRouter()

DEFAULT_AVATAR_PRESET = "blue"
ALLOWED_AVATAR_PRESETS = {"blue", "emerald", "amber"}
ALLOWED_AVATAR_MIMES = {"image/png", "image/jpeg", "image/webp"}
MAX_AVATAR_BYTES = 5 * 1024 * 1024
AVATAR_SIZE = 256
MOBILE_AUTH_CODE_EXPIRE_SECONDS = 5 * 60
MOBILE_REFRESH_TOKEN_EXPIRE_DAYS = 30
ALLOWED_MOBILE_AUTH_REDIRECT_URIS = {"toonranks://auth/callback"}
FORGOT_PASSWORD_MESSAGE = (
    "If an account exists for that email, a password reset link has been sent."
)


class MobileAuthCodeCreate(BaseModel):
    redirect_uri: str
    state: Optional[str] = None


class MobileAuthTokenExchange(BaseModel):
    code: str


class MobileRefreshTokenExchange(BaseModel):
    refresh_token: str


class MobileLogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


def user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "avatar_url": getattr(user, "avatar_url", None),
        "avatar_preset": getattr(user, "avatar_preset", None) or DEFAULT_AVATAR_PRESET,
    }


def normalize_avatar_image(blob: bytes) -> io.BytesIO:
    try:
        with Image.open(io.BytesIO(blob)) as image:
            image = ImageOps.exif_transpose(image)
            image = ImageOps.fit(image.convert("RGB"), (AVATAR_SIZE, AVATAR_SIZE))
            out = io.BytesIO()
            image.save(out, format="WEBP", quality=88, method=6)
            out.seek(0)
            return out
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid avatar image")


def hash_mobile_auth_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def hash_mobile_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_allowed_mobile_redirect_uri(redirect_uri: str) -> bool:
    return redirect_uri in ALLOWED_MOBILE_AUTH_REDIRECT_URIS


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp_expired(expires_at: datetime) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= utc_now()


def mobile_auth_code_expired(expires_at: datetime) -> bool:
    return timestamp_expired(expires_at)


def mobile_refresh_token_expired(expires_at: datetime) -> bool:
    return timestamp_expired(expires_at)


def create_mobile_refresh_token_record(user_id: int) -> tuple[str, MobileRefreshToken]:
    token = secrets.token_urlsafe(48)
    now = utc_now()
    return token, MobileRefreshToken(
        user_id=user_id,
        token_hash=hash_mobile_refresh_token(token),
        created_at=now,
        expires_at=now + timedelta(days=MOBILE_REFRESH_TOKEN_EXPIRE_DAYS),
    )


async def get_user_for_update(current_user: User, db: AsyncSession) -> User:
    user = await db.get(User, current_user.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/mobile-code")
async def create_mobile_auth_code(
    payload: MobileAuthCodeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    redirect_uri = payload.redirect_uri.strip()
    if not is_allowed_mobile_redirect_uri(redirect_uri):
        raise HTTPException(status_code=400, detail="Invalid mobile redirect URI")

    code = secrets.token_urlsafe(32)
    expires_at = utc_now() + timedelta(
        seconds=MOBILE_AUTH_CODE_EXPIRE_SECONDS
    )
    db.add(
        MobileAuthCode(
            user_id=current_user.id,
            code_hash=hash_mobile_auth_code(code),
            redirect_uri=redirect_uri,
            state=payload.state,
            expires_at=expires_at,
        )
    )
    await db.commit()

    callback_params = {"code": code}
    if payload.state:
        callback_params["state"] = payload.state

    return {
        "code": code,
        "expires_in": MOBILE_AUTH_CODE_EXPIRE_SECONDS,
        "redirect_url": f"{redirect_uri}?{urlencode(callback_params)}",
    }


@router.post("/mobile-token")
async def exchange_mobile_auth_code(
    payload: MobileAuthTokenExchange,
    db: AsyncSession = Depends(get_db),
):
    code = payload.code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="Invalid mobile auth code")

    result = await db.execute(
        select(MobileAuthCode).where(
            MobileAuthCode.code_hash == hash_mobile_auth_code(code)
        )
    )
    auth_code = result.scalars().first()

    if (
        not auth_code
        or auth_code.used_at is not None
        or mobile_auth_code_expired(auth_code.expires_at)
    ):
        raise HTTPException(status_code=400, detail="Invalid or expired mobile auth code")

    user = await db.get(User, auth_code.user_id)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired mobile auth code")

    access_token = create_access_token(user)
    refresh_token, refresh_token_record = create_mobile_refresh_token_record(user.id)
    db.add(refresh_token_record)
    auth_code.used_at = utc_now()
    await db.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": user_to_dict(user),
    }


@router.post("/mobile-refresh")
async def refresh_mobile_access_token(
    payload: MobileRefreshTokenExchange,
    db: AsyncSession = Depends(get_db),
):
    refresh_token = payload.refresh_token.strip()
    if not refresh_token:
        raise HTTPException(status_code=400, detail="Invalid mobile refresh token")

    result = await db.execute(
        select(MobileRefreshToken).where(
            MobileRefreshToken.token_hash == hash_mobile_refresh_token(refresh_token)
        )
    )
    token_record = result.scalars().first()

    if (
        not token_record
        or token_record.revoked_at is not None
        or mobile_refresh_token_expired(token_record.expires_at)
    ):
        raise HTTPException(status_code=401, detail="Invalid or expired mobile refresh token")

    user = await db.get(User, token_record.user_id)
    if not user:
        token_record.revoked_at = utc_now()
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid or expired mobile refresh token")

    token_record.last_used_at = utc_now()
    access_token = create_access_token(user)
    await db.commit()

    return {
        "access_token": access_token,
        "user": user_to_dict(user),
    }


@router.post("/mobile-logout")
async def revoke_mobile_refresh_token(
    payload: MobileLogoutRequest,
    db: AsyncSession = Depends(get_db),
):
    refresh_token = (payload.refresh_token or "").strip()
    if not refresh_token:
        return {"message": "Logged out"}

    result = await db.execute(
        select(MobileRefreshToken).where(
            MobileRefreshToken.token_hash == hash_mobile_refresh_token(refresh_token)
        )
    )
    token_record = result.scalars().first()
    if token_record and token_record.revoked_at is None:
        token_record.revoked_at = utc_now()
        await db.commit()

    return {"message": "Logged out"}



@router.post("/signup", response_model=SignupResponse)
@limiter.limit("5/minute")
async def signup(request: Request, user: UserCreate, db: AsyncSession = Depends(get_db)):
    await verify_captcha(user.captcha_token, request=request)

    username_norm = user.username.strip()
    email_norm = str(user.email).strip().lower()

    # Check username OR email conflict in a single round-trip
    result = await db.execute(
        select(User).where(
            (User.username == username_norm) | (func.lower(User.email) == email_norm)
        )
    )
    existing = result.scalars().all()

    if any((u.email or "").strip().lower() == email_norm for u in existing):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

    if any(u.username == username_norm for u in existing):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

    hashed = bcrypt.hash(user.password)
    new_user = User(
        username=username_norm,
        password=hashed,
        email=email_norm,           # store normalized email
        is_verified=False,
        avatar_preset=DEFAULT_AVATAR_PRESET,
        registered_at=datetime.now(timezone.utc),
    )

    try:
        db.add(new_user)
        await db.flush()  # Write to DB without committing yet
        token = generate_email_token(email_norm)
        send_verification_email(email_norm, token)
        await db.commit()  # Commit only if email sending succeeded
        await db.refresh(new_user)
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Signup failed during email sending")

    return SignupResponse(
        message=(
            "User created successfully. Please check your inbox and Spam folder "
            "for the verification email."
        ),
        token=token,
    )


# @router.post("/signup", response_model=SignupResponse)
# async def signup(user: UserCreate, db: AsyncSession = Depends(get_db)):
#     # 🔍 Check if the username already exists
#     result = await db.execute(select(User).where(User.username == user.username))
#     existing_user = result.scalar_one_or_none()
#
#     if existing_user:
#         raise HTTPException(
#             status_code=status.HTTP_409_CONFLICT,
#             detail="Username already exists"
#         )
#
#     # ✅ Create user
#     hashed = bcrypt.hash(user.password)
#     new_user = User(
#         username=user.username,
#         password=hashed,
#         email=str(user.email),
#         is_verified=False
#     )
#     db.add(new_user)
#     await db.commit()
#     await db.refresh(new_user)
#
#     token = generate_email_token(str(user.email))
#     send_verification_email(str(user.email), token)
#     # return new_user
#     return SignupResponse(
#         message="User created successfully. Please verify your email.",
#         token=token
#     )


@router.post("/google-oauth")
async def google_oauth(payload: dict, db: AsyncSession = Depends(get_db)):
    token = payload.get("token")
    if not token:
        raise HTTPException(status_code=400, detail="Missing token")

    try:
        google_client_id = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
        id_info = id_token.verify_oauth2_token(token, requests.Request(), google_client_id)
    except Exception as verify_err:
        print(f"[google-oauth] verify_oauth2_token failed: {verify_err!r}")
        try:
            qs = urlencode({"id_token": token})
            with urlopen(f"https://oauth2.googleapis.com/tokeninfo?{qs}", timeout=10) as resp:
                id_info = json.loads(resp.read().decode("utf-8"))

            if id_info.get("aud") != google_client_id:
                raise HTTPException(status_code=401, detail="Invalid Google token")
            if id_info.get("email_verified") not in ("true", True):
                raise HTTPException(status_code=401, detail="Google email is not verified")
        except HTTPException:
            raise
        except Exception as fallback_err:
            print(f"[google-oauth] tokeninfo fallback failed: {fallback_err!r}")
            raise HTTPException(status_code=401, detail="Invalid Google token")

    try:
        email = id_info["email"].strip().lower()
        username = id_info.get("name", email.split("@")[0]).strip()

        result = await db.execute(
            select(User).where(func.lower(User.email) == email)
        )
        user = result.scalars().first()

        if not user:
            user = User(
                email=email,
                username=username,
                password="",
                is_verified=True,
                role="GENERAL",
                avatar_preset=DEFAULT_AVATAR_PRESET,
                registered_at=datetime.now(timezone.utc),
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

        access_token = create_access_token(user)

        return {
            "access_token": access_token,
            "user": user_to_dict(user),
        }
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Google token")




@router.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, user: UserLogin, db: AsyncSession = Depends(get_db)):
    try:
        await verify_captcha(user.captcha_token, request=request)
    except HTTPException as he:
        # Keep this: shows exact captcha failure reason from verify_captcha
        print(f"[LOGIN] Captcha verification failed -> {he.detail}")
        raise
    except Exception as e:
        print(f"[LOGIN] Unexpected captcha error -> {e}")
        raise HTTPException(status_code=500, detail=f"CAPTCHA verification error: {e}")

    if not user.username.strip() or not user.password.strip():
        raise HTTPException(status_code=400, detail="Username and password are required")

    result = await db.execute(select(User).where(User.username == user.username))
    db_user = result.scalar_one_or_none()

    if not db_user or not bcrypt.verify(user.password, db_user.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not db_user.is_verified:
        raise HTTPException(status_code=403, detail="Email not verified")

    try:
        access_token = create_access_token(db_user)
    except Exception as e:
        print(f"[LOGIN] Token creation failed -> {e}")
        raise HTTPException(status_code=500, detail=f"Token creation failed: {e}")

    return JSONResponse({
        "access_token": access_token,
        "user": user_to_dict(db_user)
    })


@router.post("/forgot-password")
@limiter.limit("3/minute")
async def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    if payload.captcha_token:
        try:
            await verify_captcha(payload.captcha_token, request=request)
        except Exception:
            return {"message": FORGOT_PASSWORD_MESSAGE}

    email = str(payload.email).strip().lower()
    result = await db.execute(select(User).where(func.lower(User.email) == email))
    user = result.scalar_one_or_none()

    if not user:
        return {"message": FORGOT_PASSWORD_MESSAGE}

    try:
        token = generate_password_reset_token(str(user.email), str(user.password))
        send_password_reset_email(str(user.email), token)
    except Exception:
        return {"message": FORGOT_PASSWORD_MESSAGE}

    return {"message": FORGOT_PASSWORD_MESSAGE}


@router.post("/reset-password")
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    new_password = payload.password.strip()
    if len(new_password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters",
        )

    reset_payload = verify_password_reset_token(payload.token)
    email = str(reset_payload["email"]).strip().lower()
    result = await db.execute(select(User).where(func.lower(User.email) == email))
    user = result.scalar_one_or_none()

    if not user or str(user.password) != str(reset_payload["password_hash"]):
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user.password = bcrypt.hash(new_password)
    await db.commit()

    return {"message": "Password reset successful. You can now log in."}



# @router.post("/login")
# async def login(user: UserCreate, db: AsyncSession = Depends(get_db)):
#     result = await db.execute(select(User).where(User.username == user.username))
#     db_user = result.scalar_one_or_none()
#
#     if not db_user or not bcrypt.verify(user.password, db_user.password):
#         raise HTTPException(status_code=401, detail="Invalid credentials")
#
#     if not db_user.is_verified:
#         raise HTTPException(status_code=403, detail="Email not verified")
#
#     # ✅ Create JWT
#     # token_data = {"sub": db_user.username, "role": db_user.role, "id": db_user.id,}
#     # access_token = create_access_token(data=token_data)
#     access_token = create_access_token(db_user)
#
#     return JSONResponse({
#         "access_token": access_token,
#         "user": {
#             "id": db_user.id,
#             "username": db_user.username,
#             "role": db_user.role
#         }
#     })


@router.get("/verify-email")
async def verify_email(token: str = Query(...), db: AsyncSession = Depends(get_db)):
    email = verify_email_token(token)
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_verified:
        return {"message": "Email already verified"}

    user.is_verified = True
    await db.commit()

    return {"message": "Email verification successful"}



@router.post("/resend-verification")
@limiter.limit("3/minute")
async def resend_verification(
    request: Request,
    payload: ResendVerification,
    db: AsyncSession = Depends(get_db),
):
    # (Optional) require CAPTCHA; flip this on if you get abuse
    if payload.captcha_token:
        try:
            await verify_captcha(payload.captcha_token, request=request)
        except Exception:
            # Don’t reveal granularity; generic message prevents probing
            return {"message": "If an account exists, a new verification link has been sent."}

    if not payload.email and not payload.username:
        raise HTTPException(status_code=400, detail="Provide email or username")

    # Lookup by email first (if provided), else username
    user = None
    if payload.email:
        result = await db.execute(select(User).where(User.email == str(payload.email)))
        user = result.scalar_one_or_none()
    if not user and payload.username:
        result = await db.execute(select(User).where(User.username == payload.username))
        user = result.scalar_one_or_none()

    # Always return a generic message to avoid user-enumeration
    if not user:
        return {"message": "If an account exists, a new verification link has been sent."}

    if user.is_verified:
        return {"message": "Email is already verified. You can log in."}

    try:
        token = generate_email_token(str(user.email))
        send_verification_email(str(user.email), token)
    except Exception:
        # Don’t leak details; stay generic
        return {"message": "If an account exists, a new verification link has been sent."}

    return {
        "message": (
            "Verification email sent. Please check your inbox and Spam folder. "
            "If it lands in Spam, mark it as Not Spam."
        )
    }


@router.get("/users", response_model=list[UserAdminOut])
async def list_users_for_admin(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).order_by(User.username.asc()))
    return result.scalars().all()


@router.patch("/users/{user_id}/role", response_model=UserAdminOut)
async def update_user_role(
    user_id: int,
    payload: UserRoleUpdate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    allowed_roles = {"GENERAL", "CONTRIBUTOR", "ADMIN"}
    next_role = (payload.role or "").strip().upper()
    if next_role not in allowed_roles:
        raise HTTPException(status_code=400, detail="Invalid role")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.role = next_role
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/me/avatar", response_model=UserAvatarOut)
async def upload_my_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if file.content_type not in ALLOWED_AVATAR_MIMES:
        raise HTTPException(status_code=400, detail="Unsupported avatar image type")

    blob = await file.read()
    if not blob:
        raise HTTPException(status_code=400, detail="Avatar image is empty")
    if len(blob) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=400, detail="Avatar image is too large")

    avatar_url = upload_to_s3(
        normalize_avatar_image(blob),
        filename="avatar.webp",
        content_type="image/webp",
        folder="avatars",
        subfolder=str(current_user.id),
    )

    user = await get_user_for_update(current_user, db)
    user.avatar_url = avatar_url
    user.avatar_preset = user.avatar_preset or DEFAULT_AVATAR_PRESET
    await db.commit()
    await db.refresh(user)
    return user_to_dict(user)


@router.patch("/me/avatar/preset", response_model=UserAvatarOut)
async def select_my_avatar_preset(
    payload: AvatarPresetUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    next_preset = (payload.avatar_preset or "").strip().lower()
    if next_preset not in ALLOWED_AVATAR_PRESETS:
        raise HTTPException(status_code=400, detail="Invalid avatar preset")

    user = await get_user_for_update(current_user, db)
    user.avatar_url = None
    user.avatar_preset = next_preset
    await db.commit()
    await db.refresh(user)
    return user_to_dict(user)


@router.delete("/me/avatar", response_model=UserAvatarOut)
async def reset_my_avatar(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user = await get_user_for_update(current_user, db)
    user.avatar_url = None
    user.avatar_preset = user.avatar_preset or DEFAULT_AVATAR_PRESET
    await db.commit()
    await db.refresh(user)
    return user_to_dict(user)
