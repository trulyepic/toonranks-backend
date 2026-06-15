
import re

from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional

USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,20}$")

class UserCreate(BaseModel):
    username: str
    password: str
    email: EmailStr
    captcha_token: str
    signup_platform: Optional[str] = "web"

    # @field_validator("email")
    @classmethod
    def validate_email_domain(cls, v):
        if not (v.endswith("@gmail.com") or v.endswith("@yahoo.com")):
            raise ValueError("Only Gmail or Yahoo emails are accepted")
        return v

class UserOut(BaseModel):
    id: int
    username: str
    role: str
    avatar_url: Optional[str] = None
    avatar_preset: Optional[str] = "blue"

class UserAdminOut(UserOut):
    email: Optional[EmailStr] = None
    is_verified: bool

class UserRoleUpdate(BaseModel):
    role: str

class AvatarPresetUpdate(BaseModel):
    avatar_preset: str

class UserAvatarOut(BaseModel):
    id: int
    username: str
    role: str
    avatar_url: Optional[str] = None
    avatar_preset: str

class SignupResponse(BaseModel):
    message: str
    token: str

class UserLogin(BaseModel):
    username: str
    password: str
    captcha_token: str

class ResendVerification(BaseModel):
    email: Optional[EmailStr] = None
    username: Optional[str] = None
    captcha_token: Optional[str] = None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr
    captcha_token: Optional[str] = None


class ResetPasswordRequest(BaseModel):
    token: str
    password: str


class UsernameUpdateRequest(BaseModel):
    new_username: str

    @field_validator("new_username")
    @classmethod
    def validate_new_username(cls, v: str) -> str:
        v = v.strip()
        if not USERNAME_RE.match(v):
            raise ValueError(
                "Username must be 3–20 characters and contain only letters, "
                "numbers, underscores, or hyphens."
            )
        return v


class UsernameUpdateOut(BaseModel):
    id: int
    username: str
    role: str
    avatar_url: Optional[str] = None
    avatar_preset: Optional[str] = None

    model_config = {"from_attributes": True}


class PrivacySettingsUpdate(BaseModel):
    # Both optional so a client can update one toggle without touching the other.
    public_ratings: Optional[bool] = None
    public_posts: Optional[bool] = None


class PrivacySettingsOut(BaseModel):
    public_ratings: bool
    public_posts: bool

    model_config = {"from_attributes": True}


