# Toon Ranks — Backend (CLAUDE.md)

AI coding assistant entry point. Read this before touching any code.

---

## What this project is

Toon Ranks is a community ranking and review platform for manga, manhwa, and manhua. This repo is the **FastAPI backend** that powers both the web frontend (`toonranks-frontend`) and the React Native mobile app (`toon-ranks-mobile`).

Key facts:
- REST API only — no GraphQL, no WebSocket
- Single PostgreSQL database (`man_review` schema) shared by **all environments** including UAT
- Deployed on **Railway** (auto-deploys on merge to `main`)
- No Docker; Railway uses Nixpacks to detect and build Python automatically
- S3 (AWS) is used exclusively for image storage (covers, avatars, forum media)
- SendGrid handles transactional email

---

## Repo layout

```
app/
  config.py          — env var loading (DATABASE_URL, SECRET_KEY, ANTHROPIC_API_KEY, etc.)
  database.py        — SQLAlchemy async engine + AsyncSessionLocal + Base
  main.py            — FastAPI app, CORS, middleware, startup DB migration, router registration
  limiter.py         — slowapi rate limiter singleton
  s3.py              — S3 upload/delete helpers
  email_service.py   — SendGrid email helpers

  models/            — SQLAlchemy ORM models (one file per table)
  schemas/           — Pydantic request/response schemas
  routes/            — FastAPI routers (one file per domain)
  deps/              — FastAPI dependency functions (auth, role checks)
  utils/             — Pure helper functions (JWT, email tokens, captcha, forum content)
  moderation/        — Content moderation (profanity filter)

tests/               — pytest test suite
docs/                — Architecture, data model, API surface, conventions
```

---

## How to run locally

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt   # adds pytest, ruff, httpx

# 3. Copy and fill in env vars
cp .env.example .env                  # (create .env.example if missing — see env vars below)

# 4. Start the dev server (auto-reload)
uvicorn app.main:app --reload --port 8000

# API docs available at:
# http://localhost:8000/docs       (Swagger UI)
# http://localhost:8000/redoc      (ReDoc)
```

---

## How to run tests

```bash
# All tests (no DB required — mocked)
pytest

# Verbose with output
pytest -v -s

# Specific file
pytest tests/auth_test.py

# Integration tests only (requires TEST_DATABASE_URL)
pytest -m integration

# Lint
ruff check .

# Lint + auto-fix
ruff check . --fix
```

---

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | **Yes** | `postgresql://user:pass@host/db` (asyncpg driver added automatically) |
| `SECRET_KEY` | **Yes** | JWT signing key — min 32 chars |
| `ALGORITHM` | No | JWT algorithm, defaults to `HS256` |
| `AWS_ACCESS_KEY_ID` | Yes (for uploads) | S3 access |
| `AWS_SECRET_ACCESS_KEY` | Yes (for uploads) | S3 secret |
| `AWS_REGION` | Yes (for uploads) | e.g. `us-east-1` |
| `AWS_BUCKET_NAME` | Yes (for uploads) | S3 bucket name |
| `GOOGLE_CLIENT_ID` | Yes (for Google OAuth) | OAuth 2.0 web client ID |
| `SENDGRID_API_KEY` | Yes (for email) | SendGrid API key |
| `RECAPTCHA_SECRET_KEY` | Yes (for captcha) | reCAPTCHA v2 secret |
| `EXTRA_CORS_ORIGINS` | No | Comma-separated extra origins (e.g. `https://uat.toonranks.com`) |
| `FORUM_MEDIA_CDN_BASE` | No | CDN base URL for forum images; defaults to S3 URL |
| `FORUM_MEDIA_PREFIX` | No | S3 prefix for forum uploads, default `forum` |
| `FORUM_IMAGE_MAX_BYTES` | No | Max forum image bytes, default 307200 (300 KB) |
| `FORUM_GIF_MAX_BYTES` | No | Max forum GIF bytes, default 1048576 (1 MB) |

---

## Critical rules — read before writing any code

1. **Never work directly on `main`.** Create a branch. Branch naming: `backend-<short-desc>` (e.g. `backend-fix-vote-count`).
2. **Never commit or push** unless the user explicitly asks.
3. **All database access is async.** Use `await db.execute(...)`, `await db.commit()`, etc. Never call sync SQLAlchemy methods.
4. **Session dependency:** use `get_async_session` from `app.database` for most routes. Only `series_routes` and `auth` use the local `get_db()` helper — don't mix them in new code; prefer `get_async_session`.
5. **Schema is `man_review`.** Every model has `__table_args__ = {"schema": "man_review"}`. Never omit this.
6. **Role system:** `GENERAL` < `CONTRIBUTOR` < `ADMIN`. Use deps from `app.deps.admin` (`require_admin`, `require_series_submitter`, `is_admin`, `can_submit_series`). Never hard-code role strings in route logic.
7. **Approval state machine:** Series go `DRAFT → PENDING → APPROVED`. Never set `approval_status` arbitrarily — follow the flow in `series_detail.py` and `series_routes.py`.
8. **Rate limiting:** use `@limiter.limit("N/period")` + `request: Request` param on any public-facing mutating endpoint. See `auth.py` for examples.
9. **Do not delete commented-out code** unless the user asks — it may be intentional reference.
10. **Tests live in `tests/`** — file pattern `*_test.py`. Add a test for every new route or utility function.
11. **Ruff is the linter.** Run `ruff check .` before considering work done. Line length is 100.
12. **S3 uploads are synchronous** (`upload_to_s3`, `delete_from_s3` in `app/s3.py`). They block — keep them out of tight loops.

---

## Key patterns to follow

See `docs/CONVENTIONS.md` for the full reference. Short version:

- New route file → add router to `app/main.py` via `app.include_router(...)`
- New model → also add to `startup` in `main.py` if schema migration is needed at boot
- Auth-optional endpoints → manually extract token from `Authorization` header (see `series_routes.get_series_summary` for the pattern)
- Pagination → always return `page`, `page_size`, `total`, `total_pages`, `has_prev`, `has_next`
- Error responses → raise `HTTPException` with a clear `detail` string; never return raw dicts for errors

---

## Related repos

| Repo | Purpose | Deployment |
|---|---|---|
| `toonranks-frontend` | Vite/React web app | AWS Amplify |
| `toon-ranks-mobile` | React Native / Expo mobile app | EAS (Google Play closed testing) |
| `toonranks-backend` | **This repo** — FastAPI API | Railway |

For the full system picture see `docs/ARCHITECTURE.md`.
