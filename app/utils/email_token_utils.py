from itsdangerous import URLSafeTimedSerializer
from fastapi import HTTPException
import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY is not set in environment variables")


EMAIL_CONFIRMATION_SALT = "email-confirmation"
PASSWORD_RESET_SALT = "password-reset"

serializer = URLSafeTimedSerializer(SECRET_KEY)

def generate_email_token(email: str) -> str:
    return serializer.dumps(email, salt=EMAIL_CONFIRMATION_SALT)

def verify_email_token(token: str, max_age: int = 3600) -> str:
    try:
        return serializer.loads(token, salt=EMAIL_CONFIRMATION_SALT, max_age=max_age)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired token")


def generate_password_reset_token(email: str, password_hash: str) -> str:
    return serializer.dumps(
        {"email": email, "password_hash": password_hash},
        salt=PASSWORD_RESET_SALT,
    )


def verify_password_reset_token(token: str, max_age: int = 1800) -> dict:
    try:
        payload = serializer.loads(token, salt=PASSWORD_RESET_SALT, max_age=max_age)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    if not isinstance(payload, dict) or not payload.get("email") or not payload.get(
        "password_hash"
    ):
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    return payload

