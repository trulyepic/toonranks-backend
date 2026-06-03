

import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION")
AWS_BUCKET_NAME = os.getenv("AWS_BUCKET_NAME")
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")

# Additional allowed CORS origins beyond the built-in production/localhost list.
# Comma-separated, e.g. "https://uat.d44czcdkzilpz.amplifyapp.com,https://uat.toonranks.com".
# Lets us allow UAT / preview frontends without a code change.
EXTRA_CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("EXTRA_CORS_ORIGINS", "").split(",")
    if origin.strip()
]


FORUM_MEDIA_CDN_BASE = os.getenv(
    "FORUM_MEDIA_CDN_BASE",
    f"https://{AWS_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com",
)
FORUM_MEDIA_PREFIX = os.getenv("FORUM_MEDIA_PREFIX", "forum")

FORUM_IMAGE_MAX_BYTES = int(os.getenv("FORUM_IMAGE_MAX_BYTES", "307200"))
FORUM_GIF_MAX_BYTES   = int(os.getenv("FORUM_GIF_MAX_BYTES", "1048576"))

FORUM_IMAGE_MAX_W = int(os.getenv("FORUM_IMAGE_MAX_W", "1024"))
FORUM_IMAGE_MAX_H = int(os.getenv("FORUM_IMAGE_MAX_H", "1024"))
FORUM_GIF_MAX_W   = int(os.getenv("FORUM_GIF_MAX_W", "512"))
FORUM_GIF_MAX_H   = int(os.getenv("FORUM_GIF_MAX_H", "512"))

FORUM_ALLOWED_IMG_HOSTS = {
    h.strip().lower()
    for h in os.getenv("FORUM_ALLOWED_IMG_HOSTS", "").split(",")
    if h.strip()
}
# Fallback: derive host from CDN base
if not FORUM_ALLOWED_IMG_HOSTS:
    from urllib.parse import urlparse
    try:
        FORUM_ALLOWED_IMG_HOSTS = {urlparse(FORUM_MEDIA_CDN_BASE).netloc.lower()}
    except Exception:
        FORUM_ALLOWED_IMG_HOSTS = set()

FORUM_MEDIA_UPLOAD_RATE = os.getenv("FORUM_MEDIA_UPLOAD_RATE", "5/minute;60/day")