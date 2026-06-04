# Conventions — Toon Ranks Backend

Patterns used throughout this codebase. Follow these when adding or editing code.

---

## Database sessions

Two session helpers exist — **do not mix them in the same route file.**

| Helper | Source | Use in |
|---|---|---|
| `get_async_session` | `app.database` | All new routes, forum routes, series-detail routes, notifications, user routes |
| `get_db()` (local fn) | defined inside `app/routes/auth.py` and `app/routes/series_routes.py` | Only those two files |

When writing a new route, always use `get_async_session`:

```python
from app.database import get_async_session
from sqlalchemy.ext.asyncio import AsyncSession

@router.get("/example")
async def example(session: AsyncSession = Depends(get_async_session)):
    result = await session.execute(select(MyModel))
    return result.scalars().all()
```

Always `await` every DB call. Never call `.execute()`, `.commit()`, `.refresh()` without `await`.

---

## Auth and role guards

Import from `app.deps.admin` — never re-implement role checks inline.

```python
from app.deps.admin import require_admin, require_series_submitter, is_admin, can_submit_series
from app.utils.token_utils import get_current_user

# Require any authenticated user
current_user: User = Depends(get_current_user)

# Require CONTRIBUTOR or ADMIN
current_user: User = Depends(require_series_submitter)

# Require ADMIN
admin_user: User = Depends(require_admin)

# Check role inside a handler (when auth is optional)
if is_admin(current_user):
    ...
if can_submit_series(current_user):
    ...
```

**Role hierarchy:** `GENERAL` < `CONTRIBUTOR` < `ADMIN`

---

## Auth-optional endpoints

When an endpoint is public but has richer behaviour for authenticated users
(e.g. returning the viewer's own vote), extract the token manually:

```python
@router.get("/example/{id}")
async def example(
    id: int,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
):
    user = None
    token = request.headers.get("authorization", "").replace("Bearer ", "")
    if token:
        try:
            user = await get_current_user(token=token, session=session)
        except Exception:
            pass
    # user is None for unauthenticated, User object for authenticated
```

See `series_routes.get_series_summary` and `series_detail.get_series_detail` for examples.

---

## Rate limiting

Apply to any public-facing mutating endpoint or sensitive read endpoint.

```python
from app.limiter import limiter
from fastapi import Request

@router.post("/example")
@limiter.limit("5/minute")
async def example(request: Request, ...):
    ...
```

The `request: Request` parameter is **required** by slowapi — add it even if the handler
doesn't use it directly.

Common limits used in the codebase:
- Signup / login: `5/minute`
- Forgot password / resend verification: `3/minute`
- Username update: `5/hour`
- User search: `30/minute`

---

## Pagination

Every list endpoint that could grow large must be paginated. Standard response shape:

```python
class MyPageOut(BaseModel):
    items: List[MyItemOut]
    page: int
    page_size: int
    total: int
    total_pages: int
    has_prev: bool
    has_next: bool
```

Standard query params: `page: int = Query(1, ge=1)`, `page_size: int = Query(20, ge=1, le=100)`.

Offset calculation:
```python
offset = (page - 1) * page_size
total_pages = max(1, math.ceil(total / page_size))
```

---

## Error handling

Always raise `HTTPException` with a clear `detail` string. Never return raw dicts for errors.

```python
from fastapi import HTTPException

raise HTTPException(status_code=404, detail="Series not found")
raise HTTPException(status_code=403, detail="Admin access required")
raise HTTPException(status_code=409, detail="Username already taken")
```

For security-sensitive flows (password reset, forgot password), always return a generic
message that does not confirm whether an account exists:
```python
GENERIC = "If an account exists for that email, a link has been sent."
return {"message": GENERIC}
```

---

## New router file checklist

1. Create `app/routes/my_feature_routes.py`
2. Define `router = APIRouter(prefix="/my-feature", tags=["my-feature"])`
3. Register in `app/main.py`: `app.include_router(my_feature_routes.router)`
4. Add Pydantic schemas to `app/schemas/my_feature_schemas.py`
5. If a new DB table is needed, create `app/models/my_feature_model.py` with `__table_args__ = {"schema": "man_review"}`
6. Add idempotent `CREATE TABLE IF NOT EXISTS` or `ALTER TABLE IF NOT EXISTS` to the `on_startup` handler in `app/main.py`
7. Write tests in `tests/my_feature_routes_test.py`

---

## New model checklist

```python
from sqlalchemy import Column, Integer, String, ForeignKey
from app.database import Base

class MyModel(Base):
    __tablename__ = "my_table"
    __table_args__ = {"schema": "man_review"}   # ← NEVER omit this

    id = Column(Integer, primary_key=True, index=True)
    # ... columns
```

Schema migrations are applied at startup in `main.py` (`on_startup`), not via Alembic.
Add an idempotent SQL statement to the startup block for any new column or table.

---

## S3 image uploads

```python
from app.s3 import upload_to_s3, delete_from_s3

# Upload
url = upload_to_s3(
    file.file,          # file-like object
    file.filename,      # original filename (used for extension)
    file.content_type,  # MIME type
    folder="my-folder", # S3 key prefix
    subfolder="optional-sub",
)

# Delete (extract key from stored URL first)
from urllib.parse import urlparse
key = urlparse(cover_url).path.lstrip("/")
delete_from_s3(key)
```

`upload_to_s3` is **synchronous** — it blocks the event loop. Avoid calling it in tight loops.
Use it once per request. For batch operations, consider `asyncio.to_thread(upload_to_s3, ...)`.

---

## Denormalized counters

Some columns are intentionally denormalized for query performance:

| Column | On which model | What it tracks | Where it's updated |
|---|---|---|---|
| `vote_count` | `Series` | Distinct voter count | `series_detail.vote_series_detail` |
| `post_count` | `ForumThread` | Total post count | `forum_routes` on create/delete |
| `last_post_at` | `ForumThread` | Time of last post | `forum_routes` on post create |
| `upvote_count` | `ForumPost` | Total upvotes | `forum_routes` on reaction change |
| `downvote_count` | `ForumPost` | Total downvotes | `forum_routes` on reaction change |
| `heart_count` | `ForumPost` | Legacy hearts | `forum_routes` on heart toggle |

When updating these, always do it in the same transaction as the triggering action.

---

## Forum post content pipeline

When a user creates or edits a forum post, content is validated before saving:

1. **`reject_disallowed_images(markdown)`** — validates any inline images: http(s) only,
   safe extensions (.png/.jpg/.jpeg/.webp/.gif), optional HEAD check for size/type.
2. **`ensure_clean(content)`** — basic profanity filter (keyword regex).
3. Content is stored as raw markdown — no server-side rendering.

Import from the appropriate utils:
```python
from app.utils.forum_content import reject_disallowed_images
from app.moderation.profanity import ensure_clean
```

---

## Notifications

Use the helpers in `app/utils/notification_utils.py`:

```python
from app.utils.notification_utils import notify_mentions, notify_thread_reply

# After saving a post
await notify_mentions(content, thread_id, post_id, actor_id=current_user.id, db=session)
await notify_thread_reply(thread_id, post_id, actor_id=current_user.id, db=session)
await session.commit()  # commit after adding notification rows
```

Notification kinds: `THREAD_REPLY`, `THREAD_FOLLOW_REPLY`, `POST_MENTION`.

---

## Linting

```bash
ruff check .          # check
ruff check . --fix    # auto-fix safe issues
```

Config is in `pyproject.toml`. Line length: **100**. Target: Python 3.9+.
Ruff catches syntax errors, undefined names, unused imports (`F` rules) and style (`E9` rules).

---

## Test conventions

- Test files: `tests/*_test.py`
- Use fixtures from `tests/conftest.py` (async test client, mock DB, etc.)
- Mark integration tests with `@pytest.mark.integration` — they require a live DB
- Mark regression tests with `@pytest.mark.regression`
- Tests must not require real AWS, SendGrid, or reCAPTCHA keys — mock external calls
