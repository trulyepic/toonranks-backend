from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import asyncio


from sqlalchemy import text

from app.routes import series_routes, auth, series_detail, reading_list_routes, issues_routes, forum_routes, \
    forum_media_routes, favourite_routes, user_routes
from app.models import user_favourite  # noqa: F401 — registers model with Base

from fastapi.responses import RedirectResponse, JSONResponse
from app.routes import series_routes, auth, series_detail

from app.database import Base, engine

# 🔒 Rate limiting setup

from app.limiter import limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.routes import sitemap

app = FastAPI(title="Toon Ranks API")

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok"}

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please slow down."}
    )

# Redirect bare toonranks.com -> www.toonranks.com for canonical consistency.
@app.middleware("http")
async def redirect_www(request: Request, call_next):
    host = request.headers.get("host", "")
    path = request.url.path

    # Do NOT redirect sitemap endpoints (let Amplify proxy succeed)
    if path.startswith("/sitemap") or path.startswith("/sitemaps/"):
        return await call_next(request)

    if host == "toonranks.com":
        new_url = request.url.replace(netloc="www.toonranks.com")
        return RedirectResponse(str(new_url), status_code=301)
    return await call_next(request)

# ✅ Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://toonranks.com",
        "https://www.toonranks.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Include your routers
app.include_router(series_routes.router)
app.include_router(auth.router, prefix="/auth")
app.include_router(series_detail.router)
app.include_router(reading_list_routes.router)
app.include_router(issues_routes.router)
app.include_router(forum_routes.router)
app.include_router(sitemap.router)
app.include_router(forum_media_routes.router)
app.include_router(favourite_routes.router, prefix="/auth")
app.include_router(user_routes.router)

# ✅ Run DB init on startup
@app.on_event("startup")
async def on_startup():
    # Tiny retry so a momentary DB disconnect doesn't crash the app.
    for attempt in range(2):
        try:
            async with engine.begin() as conn:
                # Ensure schema exists
                await conn.execute(text('CREATE SCHEMA IF NOT EXISTS "man_review";'))
                await conn.run_sync(Base.metadata.create_all)
                await conn.execute(
                    text(
                        """
                        ALTER TABLE IF EXISTS man_review.reading_list_items
                        ADD COLUMN IF NOT EXISTS left_off_chapter VARCHAR(50)
                        """
                    )
                )
                await conn.execute(
                    text(
                        """
                        ALTER TABLE IF EXISTS man_review.series
                        ADD COLUMN IF NOT EXISTS approval_status VARCHAR(20)
                        """
                    )
                )
                await conn.execute(
                    text(
                        """
                        ALTER TABLE IF EXISTS man_review.series
                        ADD COLUMN IF NOT EXISTS submitted_by_id INTEGER
                        """
                    )
                )
                await conn.execute(
                    text(
                        """
                        ALTER TABLE IF EXISTS man_review.series
                        ADD COLUMN IF NOT EXISTS approved_by_id INTEGER
                        """
                    )
                )
                await conn.execute(
                    text(
                        """
                        ALTER TABLE IF EXISTS man_review.series
                        ADD COLUMN IF NOT EXISTS approved_at VARCHAR(40)
                        """
                    )
                )
                await conn.execute(
                    text(
                        """
                        ALTER TABLE IF EXISTS man_review.users
                        ADD COLUMN IF NOT EXISTS avatar_url VARCHAR
                        """
                    )
                )
                await conn.execute(
                    text(
                        """
                        ALTER TABLE IF EXISTS man_review.users
                        ADD COLUMN IF NOT EXISTS avatar_preset VARCHAR
                        """
                    )
                )
                await conn.execute(
                    text(
                        """
                        UPDATE man_review.users
                        SET avatar_preset = 'blue'
                        WHERE avatar_preset IS NULL
                        """
                    )
                )
                await conn.execute(
                    text(
                        """
                        ALTER TABLE IF EXISTS man_review.users
                        ADD COLUMN IF NOT EXISTS signup_platform VARCHAR(10)
                        NOT NULL DEFAULT 'web'
                        """
                    )
                )
                await conn.execute(
                    text(
                        """
                        ALTER TABLE IF EXISTS man_review.users
                        ADD COLUMN IF NOT EXISTS auth_provider VARCHAR(10)
                        NOT NULL DEFAULT 'email'
                        """
                    )
                )
                await conn.execute(
                    text(
                        """
                        UPDATE man_review.users
                        SET auth_provider = 'google'
                        WHERE (password IS NULL OR password = '')
                        AND auth_provider = 'email'
                        """
                    )
                )
                await conn.execute(
                    text(
                        """
                        UPDATE man_review.series
                        SET approval_status = 'APPROVED'
                        WHERE approval_status IS NULL
                        """
                    )
                )
                await conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS man_review.user_favourites (
                            id SERIAL PRIMARY KEY,
                            user_id INTEGER NOT NULL
                                REFERENCES man_review.users(id) ON DELETE CASCADE,
                            series_id INTEGER NOT NULL
                                REFERENCES man_review.series(id) ON DELETE CASCADE,
                            position INTEGER NOT NULL,
                            CONSTRAINT uq_user_favourite_series
                                UNIQUE (user_id, series_id)
                        )
                        """
                    )
                )
                await conn.execute(
                    text(
                        """
                        CREATE INDEX IF NOT EXISTS ix_user_favourites_user_id
                            ON man_review.user_favourites (user_id)
                        """
                    )
                )
            break  # success
        except Exception as e:
            if attempt == 0:
                # Log + retry once after a short pause
                print(f"[startup] DB init failed, retrying once: {e!r}")
                await asyncio.sleep(0.5)
            else:
                # On the second failure, don't crash the app.
                # Tables should already exist from previous runs.
                print(f"[startup] Skipping DB init due to error: {e!r}")
