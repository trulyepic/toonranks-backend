# Toon Ranks Backend — Agent Instructions

This file is the universal AI agent entry point (Cursor, GitHub Copilot, Windsurf, Gemini, etc.).
If you are Claude Code, also read `CLAUDE.md` for the full reference.

---

## Project summary

FastAPI backend for Toon Ranks — a manga/manhwa/manhua community ranking platform.
- Language: Python 3.11+, async throughout
- Database: PostgreSQL, schema `man_review`, accessed via SQLAlchemy async
- Deployed: Railway (auto-deploy on merge to `main`)
- Storage: AWS S3 for all images
- Email: SendGrid
- Auth: JWT (HS256) + Google OAuth + mobile auth code flow

## File map

```
app/config.py        env vars
app/database.py      async engine, Base, get_async_session dependency
app/main.py          app factory, CORS, middleware, router registration
app/models/          ORM tables
app/schemas/         Pydantic I/O schemas
app/routes/          FastAPI routers
app/deps/admin.py    role-check dependencies (require_admin, require_series_submitter)
app/utils/           helpers (JWT, captcha, email tokens, forum content guard)
app/moderation/      profanity filter
tests/               pytest suite (*_test.py)
docs/                reference docs (architecture, data model, API, conventions)
```

## Non-negotiable rules

- **Never work on `main` directly** — always a branch
- **All DB calls must be async** — `await session.execute(...)`, `await session.commit()`
- **All models must include** `__table_args__ = {"schema": "man_review"}`
- **Use existing deps** — `app.deps.admin` for auth/role guards, `app.database.get_async_session` for DB sessions
- **Rate-limit public mutating endpoints** — import `limiter` from `app.limiter`, use `@limiter.limit("N/period")`
- **Run `ruff check .`** before finishing any task — max line length 100

## Key domain concepts

- **Series types:** `MANGA`, `MANHWA`, `MANHUA`
- **Series statuses:** `ONGOING`, `COMPLETE`, `HIATUS`, `UNKNOWN`, `SEASON_END`
- **Approval flow:** `DRAFT → PENDING → APPROVED` (contributor submits → admin approves)
- **User roles:** `GENERAL` (default), `CONTRIBUTOR` (can submit series), `ADMIN` (full access)
- **Scoring:** each series rated 1–10 across 5 categories; `final_score = avg(story, characters, worldbuilding, art, drama_or_fight)`
- **Cred score:** users earn points for forum activity; drives the leaderboard

## Where to find things

| Need | Look here |
|---|---|
| Full data model (tables, columns, FKs) | `docs/DATA_MODEL.md` |
| All API endpoints | `docs/API.md` |
| Coding conventions and patterns | `docs/CONVENTIONS.md` |
| System architecture | `docs/ARCHITECTURE.md` |
| How to run and test | `CONTRIBUTING.md` |

## What NOT to do

- Do not add synchronous DB calls inside async route handlers
- Do not hardcode role strings in route logic — use `app.deps.admin` helpers
- Do not skip the `man_review` schema on new models
- Do not create new migration scripts — schema changes are applied at startup in `app/main.py`
- Do not add new dependencies without updating `requirements.txt`
