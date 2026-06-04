# Architecture — Toon Ranks Backend

## System overview

```
┌─────────────────────┐     HTTPS      ┌──────────────────────────┐
│  toonranks-frontend │ ─────────────► │                          │
│  (Vite/React)       │                │   toonranks-backend      │
│  AWS Amplify        │                │   FastAPI / uvicorn       │
│  toonranks.com      │                │   Railway                │
│  uat.toonranks.com  │                │   (this repo)            │
└─────────────────────┘                │                          │
                                       │   PORT 8000              │
┌─────────────────────┐     HTTPS      │                          │
│  toon-ranks-mobile  │ ─────────────► │                          │
│  React Native/Expo  │                └──────────┬───────────────┘
│  iOS + Android      │                           │
└─────────────────────┘                           │ asyncpg
                                       ┌──────────▼───────────────┐
                                       │  PostgreSQL               │
                                       │  Railway-managed          │
                                       │  schema: man_review       │
                                       └──────────────────────────┘
                                                  │
                              ┌───────────────────┼───────────────────┐
                              │                   │                   │
                    ┌─────────▼──────┐  ┌─────────▼──────┐  ┌───────▼────────┐
                    │   AWS S3       │  │   SendGrid      │  │  Google OAuth  │
                    │   Images       │  │   Email         │  │  (id_token     │
                    │   (covers,     │  │   (verify,      │  │   verify)      │
                    │   avatars,     │  │   reset, etc.)  │  └────────────────┘
                    │   forum media) │  └────────────────┘
                    └────────────────┘
```

## Deployment

| Environment | Frontend | Backend | Database |
|---|---|---|---|
| Production | `toonranks.com` (Amplify `main` branch, manual deploy) | Railway `main` auto-deploy | Railway PostgreSQL (prod) |
| UAT | `uat.toonranks.com` (Amplify `uat` branch, auto-deploy) | **Same** Railway backend | **Same** prod DB |

UAT shares prod data by design — it is a frontend staging environment only, not a data sandbox.

## Request lifecycle

```
Client
  │
  ▼
Cloudflare (DNS + proxy cache)
  │
  ▼
AWS Amplify / CloudFront (frontend static files)
  │
  │  API calls (AJAX)
  ▼
FastAPI (Railway)
  │
  ├── SlowAPIMiddleware (rate limiting)
  ├── CORSMiddleware (allow_origins list + EXTRA_CORS_ORIGINS env var)
  ├── redirect_www middleware (toonranks.com → www.toonranks.com)
  │
  ▼
Router → Route handler
  │
  ├── Depends(get_current_user)     — JWT decode → User ORM object
  ├── Depends(require_admin)        — role guard
  ├── Depends(get_async_session)    — async DB session
  │
  ▼
SQLAlchemy async (asyncpg driver)
  │
  ▼
PostgreSQL (man_review schema)
```

## Application layers

### `app/main.py` — App factory
- Creates the FastAPI instance
- Adds SlowAPI, CORS, and www-redirect middleware
- Registers all routers
- Runs `on_startup` DB migration (idempotent `ALTER TABLE IF NOT EXISTS` statements)

### `app/models/` — ORM layer
SQLAlchemy 2.x declarative models. All tables live in the `man_review` schema.
The `Base` is defined in `app/database.py`. Models are imported in `main.py` so
`Base.metadata.create_all` can see them.

### `app/schemas/` — Validation layer
Pydantic v2 models for request bodies and response shapes. Kept separate from ORM models.
Some schemas use `as_form()` class methods for multipart/form-data endpoints.

### `app/routes/` — Handler layer
One file per domain. Each file creates an `APIRouter` and is registered in `main.py`.
Route files should stay thin — business logic belongs in `app/utils/` or service helpers.

### `app/deps/` — Dependency layer
Reusable FastAPI dependencies for auth and role enforcement. Import from here, never
re-implement inline.

### `app/utils/` — Utility layer
Pure functions with no FastAPI dependencies where possible:
- `token_utils.py` — JWT creation and verification, `get_current_user` dependency
- `captcha.py` — reCAPTCHA v2 verification
- `email_token_utils.py` — email verification and password reset token helpers
- `forum_content.py` — image URL validation for forum posts
- `mention_utils.py` — `@username` extraction from markdown
- `notification_utils.py` — notification creation helpers

### `app/moderation/` — Moderation layer
`profanity.py` — keyword-based profanity filter. Called via `ensure_clean()` in forum routes.

## Authentication flows

### Web (email/password)
`POST /auth/signup` → email verification → `POST /auth/login` → JWT access token (3 days)

### Web (Google)
`POST /auth/google-oauth` with Google `id_token` → verify via Google API → JWT access token

### Mobile
1. User logs in on web → `POST /auth/mobile-code` → short-lived auth code (5 min)
2. Mobile app exchanges: `POST /auth/mobile-token` → JWT access token + refresh token (30 days)
3. Mobile refreshes: `POST /auth/mobile-refresh` → new JWT access token
4. Mobile logout: `POST /auth/mobile-logout` → revokes refresh token

## Image storage

All images go through `app/s3.py`. `upload_to_s3(file, filename, content_type, folder)` returns
the public S3 URL stored in the DB. `delete_from_s3(key)` removes the object.

Image types by folder convention:
- `{series_title}/` — series list cover
- `{series_id}/covers/` — series detail cover
- `avatars/{user_id}/` — user avatar
- `forum/` — forum post images (via `forum_media_routes.py`)

## Forum architecture

The forum is the most complex domain:

- `ForumCategory` → `ForumThread` → `ForumPost` (tree via `parent_id` for replies)
- `ForumSeriesRef` — links a thread or post to series (many-to-many via junction)
- `ForumReaction` — UPVOTE / DOWNVOTE per user per post (unique constraint)
- `ForumFollower` — user follows a thread (gets notified on replies)
- `ForumBookmark` — user bookmarks individual posts
- `ForumReadState` — tracks last-seen post per user per thread (unread badge)
- `ForumReport` — post reports with OPEN / REVIEWED / DISMISSED lifecycle
- `Notification` — cross-domain notification model (THREAD_REPLY, THREAD_FOLLOW_REPLY, POST_MENTION)

## Series approval state machine

```
[DRAFT]           — created by contributor; details incomplete
   │
   ▼ (contributor completes synopsis + detail cover)
[PENDING]         — waiting for admin review
   │
   ▼ (admin approves via POST /series/{id}/approve)
[APPROVED]        — visible in rankings and public listings
```

Admins submitting their own series are auto-approved on detail completion.

## Scoring system

Each series has a `SeriesDetail` row with 5 category pairs:
`{category}_total` and `{category}_count`.

A user votes 1–10 per category once. Each vote increments the total and count.

```
category_avg = total / count   (for each of the 5 categories)
final_score  = avg(story, characters, worldbuilding, art, drama_or_fight)
```

The `vote_count` on the `Series` row counts **distinct voters** (not total votes),
incremented only on a user's first vote for that series.

Rankings sort by `final_score` descending. Unscored series (no votes) always appear last
with `rank = null`.
