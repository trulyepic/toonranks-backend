# Forum Improvements TODO — Backend

This roadmap covers every backend change required to bring the Toon Ranks forum up to the standard
of popular modern forums (Reddit, Discourse, phpBB). Features are ordered from lowest to highest
complexity. The frontend companion doc is at `toonranks-frontend/FORUM_IMPROVEMENTS_TODO.md`.

---

## Current Backend State

**Stack:** FastAPI + SQLAlchemy async + PostgreSQL on Railway. Schema is `man_review`.

**Relevant files:**
- Models: `app/models/forum_model.py`
- Routes: `app/routes/forum_routes.py`
- Media routes: `app/routes/forum_media_routes.py`
- Schemas: `app/schemas/forum_schemas.py`
- DB base: `app/database.py`
- Limiter: `app/limiter.py` (slowapi `@limiter.limit()` decorator pattern)
- Profanity: `app/moderation/profanity.py` (`ensure_clean()`)

**Current models:**

| Model | Key columns |
|---|---|
| `ForumThread` | `id`, `title`, `author_id`, `created_at`, `updated_at`, `post_count`, `last_post_at`, `locked`, `latest_first` |
| `ForumPost` | `id`, `thread_id`, `author_id`, `parent_id`, `content_markdown`, `created_at`, `updated_at`, `heart_count`, `upvote_count`, `downvote_count` |
| `ForumSeriesRef` | `id`, `thread_id`, `post_id`, `series_id` |
| `ForumReaction` | `id`, `post_id`, `user_id`, `kind` (UPVOTE/DOWNVOTE/HEART) |
| `ForumMedia` | `id`, `user_id`, `thread_id`, `post_id`, `url`, `mime_type`, `size_bytes`, `width`, `height` |

**Current endpoints:**

| Method | Path | Auth | Notes |
|---|---|---|---|
| `GET` | `/forum/threads` | None | Simple list, title search, sorted `updated_at DESC` |
| `GET` | `/forum/threads-paged` | None | Paginated with `?q=` title search; sorts by `last_post_at DESC` only |
| `POST` | `/forum/threads` | Required | Rate: `3/min; 20/hr; 60/day`. Limit: 10 threads per user |
| `GET` | `/forum/threads/{thread_id}` | None (opt) | Full thread + all posts flat |
| `GET` | `/forum/threads/{thread_id}/posts-paged` | None (opt) | Paginated nested posts |
| `PATCH` | `/forum/threads/{thread_id}` | Owner/Admin | Rate: `6/min; 40/hr; 150/day` |
| `DELETE` | `/forum/threads/{thread_id}` | Owner/Admin | Reverses all CP |
| `PATCH` | `/forum/threads/{thread_id}/lock` | Admin only | Toggles `locked` boolean |
| `PATCH` | `/forum/threads/{thread_id}/settings` | Admin only | Toggles `latest_first` |
| `POST` | `/forum/threads/{thread_id}/posts` | Required | Rate: `6/min; 40/hr; 150/day` |
| `PATCH` | `/forum/threads/{thread_id}/posts/{post_id}` | Owner/Admin | Rate: `12/min; 80/hr; 300/day` |
| `DELETE` | `/forum/threads/{thread_id}/posts/{post_id}` | Owner/Admin | Reverses CP |
| `DELETE` | `/forum/threads/{thread_id}/posts/{post_id}/mine` | Owner/Admin | Same as above, different path |
| `POST` | `/forum/threads/{thread_id}/posts/{post_id}/vote` | Required | Rate: `30/min; 1000/day` |
| `POST` | `/forum/threads/{thread_id}/posts/{post_id}/heart` | Required | Legacy alias to vote |
| `GET` | `/forum/me/threads` | Required | Signed-in user's threads, paginated |
| `GET` | `/forum/me/posts` | Required | Signed-in user's posts, paginated |
| `GET` | `/forum/me/votes` | Required | Signed-in user's voted posts, paginated |
| `GET` | `/forum/series-search` | None | Rate: `30/min; 1000/day` |
| `POST` | `/forum/media/upload` | Required | Multipart; max 300 KB image / 1 MB GIF |

**Cred score formula:**
- `+2` when user creates a thread
- `+1` when user posts a reply
- `+2` per upvote received on any post
- `-1` per downvote received on any post
- All reversed on delete

---

## Phase 1: Quick Wins — Thread Limit, View Count, and Pinning Column

Suggested branch: `backend-forum-quick-wins`

These three changes require a migration and minor route edits but no new models.

### 1a — Raise the thread limit

**File:** `app/routes/forum_routes.py`, line ~303

The limit `if existing_count >= 10` is hard-coded. Popular forums have no per-user thread cap or
use a much higher one (50–100). Ten is far too restrictive for active contributors.

- [ ] Extract the constant to the top of `forum_routes.py`:
  ```python
  MAX_THREADS_PER_USER = 50  # Raised from 10; limits thread spam without blocking real contributors
  ```
- [ ] Replace the inline `>= 10` comparison: `if existing_count >= MAX_THREADS_PER_USER`
- [ ] Update the 403 error detail to reflect the new limit:
  `f"Thread limit reached ({MAX_THREADS_PER_USER}). Delete an existing thread to create a new one."`
- [ ] Add a backend test: POST to `/forum/threads` as a user with exactly `MAX_THREADS_PER_USER`
  threads — confirm 403 is returned. With `MAX_THREADS_PER_USER - 1` threads — confirm 201.

### 1b — Thread view count

**Files:**
- `app/models/forum_model.py` — add column
- Alembic migration — add `view_count` column
- `app/routes/forum_routes.py` — increment on fetch

The `ForumThread` model has no `view_count`. Adding it lets both the thread list and detail views
show how many times a thread has been viewed.

- [ ] Add `view_count = Column(Integer, nullable=False, server_default="0", default=0)` to
  `ForumThread` in `app/models/forum_model.py`
- [ ] Create an Alembic migration:
  ```sql
  ALTER TABLE man_review.forum_threads ADD COLUMN view_count INTEGER NOT NULL DEFAULT 0;
  ```
- [ ] In `get_thread` (`GET /forum/threads/{thread_id}`), increment view count on every fetch:
  ```python
  t.view_count = (t.view_count or 0) + 1
  await db.commit()
  ```
  Do not increment for the thread author's own views — check `if viewer and viewer.id != t.author_id`.
  Alternatively, increment for all viewers including the author for simplicity in v1.
- [ ] Expose `view_count` in the `ForumThreadOut` Pydantic schema in `app/schemas/forum_schemas.py`
- [ ] Include `view_count` in `_thread_to_out()` in `forum_routes.py`
- [ ] Include `view_count` in `ThreadPostsPageOut` response (already uses `_thread_to_out`)

### 1c — Pinned thread column

**Files:**
- `app/models/forum_model.py` — add column
- Alembic migration — add `is_pinned` column
- `app/routes/forum_routes.py` — sort pinned first, admin pin/unpin endpoint
- `app/schemas/forum_schemas.py` — expose in response

Currently there is a client-side hack in the frontend that pins any thread whose title contains
"Patch Notes". This is fragile. The correct solution is an `is_pinned` flag controlled by admins.

- [ ] Add `is_pinned = Column(Boolean, nullable=False, server_default=text("false"), default=False)`
  to `ForumThread` in `app/models/forum_model.py`
- [ ] Create an Alembic migration:
  ```sql
  ALTER TABLE man_review.forum_threads ADD COLUMN is_pinned BOOLEAN NOT NULL DEFAULT FALSE;
  ```
- [ ] Expose `is_pinned` in `ForumThreadOut` Pydantic schema
- [ ] Include `is_pinned` in `_thread_to_out()` mapper
- [ ] Update thread list ordering in `list_threads_paged` to sort pinned threads first:
  ```python
  .order_by(
      ForumThread.is_pinned.desc(),
      ForumThread.last_post_at.desc(),
      ForumThread.id.desc(),
  )
  ```
  Apply the same ordering change to the legacy `list_threads` route.
- [ ] Add a new admin-only endpoint:
  ```
  PATCH /forum/threads/{thread_id}/pin
  Body: { "pinned": bool }
  Auth: Admin only (403 for non-admins)
  ```
  Implementation pattern: identical to the existing `set_thread_lock` endpoint.
  ```python
  @router.patch("/threads/{thread_id}/pin")
  async def set_thread_pin(
      thread_id: int,
      body: PinToggleIn,
      user: User = Depends(get_current_user),
      db: AsyncSession = Depends(get_async_session),
  ):
      if not _is_admin(user):
          raise HTTPException(status_code=403, detail="Admin only")
      t = await db.get(ForumThread, thread_id)
      if not t:
          raise HTTPException(status_code=404, detail="Thread not found")
      t.is_pinned = bool(body.pinned)
      await db.commit()
      await db.refresh(t)
      return {"id": t.id, "is_pinned": t.is_pinned}
  ```
  Add `class PinToggleIn(BaseModel): pinned: bool` alongside `LockToggleIn`.
- [ ] Add a test: PATCH `/forum/threads/{id}/pin` as admin → `is_pinned` flips. As non-admin → 403.
- [ ] Add a test: GET `/forum/threads-paged` returns pinned threads first regardless of `last_post_at`.

---

## Phase 2: Thread Sorting Options

Suggested branch: `backend-forum-thread-sorting`

The thread list currently sorts only by `last_post_at DESC`. Popular forums let users sort by
newest threads, most replies, or hot (most recent activity). This phase adds a `sort` query param
to `GET /forum/threads-paged`.

**File:** `app/routes/forum_routes.py` — `list_threads_paged` function (line ~388)

- [ ] Add a `sort` query param with an `Optional[Literal]` type:
  ```python
  sort: Optional[Literal["activity", "newest", "replies"]] = Query("activity")
  ```
  - `"activity"` (default): `ORDER BY is_pinned DESC, last_post_at DESC, id DESC` (current behavior)
  - `"newest"`: `ORDER BY is_pinned DESC, created_at DESC, id DESC`
  - `"replies"`: `ORDER BY is_pinned DESC, post_count DESC, id DESC`
- [ ] Build the order clause conditionally:
  ```python
  if sort == "newest":
      order_clause = [ForumThread.is_pinned.desc(), ForumThread.created_at.desc(), ForumThread.id.desc()]
  elif sort == "replies":
      order_clause = [ForumThread.is_pinned.desc(), ForumThread.post_count.desc(), ForumThread.id.desc()]
  else:  # activity
      order_clause = [ForumThread.is_pinned.desc(), ForumThread.last_post_at.desc(), ForumThread.id.desc()]
  stmt = stmt.order_by(*order_clause)
  ```
  Pinned threads always appear first regardless of sort selection.
- [ ] Add `sort` to the `PageOut` response so the frontend can confirm which sort is active.
  If `PageOut` is a Pydantic model in `forum_schemas.py`, add `sort: Optional[str] = None`.
- [ ] Add backend tests:
  - `?sort=activity` returns thread with most recent `last_post_at` first (excluding pinned)
  - `?sort=newest` returns thread with most recent `created_at` first (excluding pinned)
  - `?sort=replies` returns thread with highest `post_count` first (excluding pinned)
  - Pinned threads appear before all others regardless of sort

---

## Phase 3: Post Reporting

Suggested branch: `backend-forum-post-reporting`

There is currently no way for users to report individual forum posts. The issues system
(`app/routes/issues_routes.py`) handles site-level bug/feature reports, not post-level moderation
reports. This phase adds a separate `ForumReport` model and endpoint.

**Files to create/modify:**
- `app/models/forum_model.py` — add `ForumReport` model
- Alembic migration — new `man_review.forum_reports` table
- `app/routes/forum_routes.py` — new report endpoint and admin list endpoint
- `app/schemas/forum_schemas.py` — new `ForumReportOut` schema

### 3a — `ForumReport` model

Add to `app/models/forum_model.py`:

```python
class ForumReport(Base):
    __tablename__ = "forum_reports"
    __table_args__ = (
        UniqueConstraint("post_id", "reporter_id", name="uq_forum_report_post_reporter"),
        {"schema": SCHEMA},
    )

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    thread_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reporter_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reason = Column(String(500), nullable=True)  # optional free-text reason
    status = Column(String(20), nullable=False, server_default="OPEN")  # OPEN, REVIEWED, DISMISSED
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"),
        nullable=True,
    )
```

The `UniqueConstraint` prevents a user from submitting multiple reports on the same post.

### 3b — Migration

- [ ] Create Alembic migration for `man_review.forum_reports`:
  ```sql
  CREATE TABLE man_review.forum_reports (
      id SERIAL PRIMARY KEY,
      post_id INTEGER NOT NULL REFERENCES man_review.forum_posts(id) ON DELETE CASCADE,
      thread_id INTEGER NOT NULL REFERENCES man_review.forum_threads(id) ON DELETE CASCADE,
      reporter_id INTEGER NOT NULL REFERENCES man_review.users(id) ON DELETE CASCADE,
      reason VARCHAR(500),
      status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      reviewed_at TIMESTAMPTZ,
      reviewed_by_id INTEGER REFERENCES man_review.users(id) ON DELETE SET NULL,
      CONSTRAINT uq_forum_report_post_reporter UNIQUE (post_id, reporter_id)
  );
  CREATE INDEX ON man_review.forum_reports (post_id);
  CREATE INDEX ON man_review.forum_reports (reporter_id);
  ```

### 3c — Report endpoint

Add to `app/routes/forum_routes.py`:

- [ ] `POST /forum/threads/{thread_id}/posts/{post_id}/report` — Auth required

  ```python
  class ForumReportIn(BaseModel):
      reason: Optional[str] = None  # optional free-text, max 500 chars

  @router.post("/threads/{thread_id}/posts/{post_id}/report", status_code=201)
  @limiter.limit("5/hour")
  async def report_post(
      request: Request,
      thread_id: int,
      post_id: int,
      payload: ForumReportIn,
      user: User = Depends(get_current_user),
      db: AsyncSession = Depends(get_async_session),
  ):
  ```

  Logic:
  1. Confirm the post exists and belongs to the thread (404 if not).
  2. Block self-reporting: `if post.author_id == user.id` → 403.
  3. Check for existing report by this user on this post — return 409 with
     `detail="You have already reported this post."` if duplicate.
  4. Insert `ForumReport(post_id=post_id, thread_id=thread_id, reporter_id=user.id, reason=payload.reason)`.
  5. Return `{"message": "Report submitted. Our team will review it shortly."}` with status 201.

- [ ] `GET /forum/reports` — Admin only, paginated list of open reports for moderation review:
  ```python
  @router.get("/reports")
  async def list_reports(
      status: Optional[str] = Query("OPEN"),  # OPEN, REVIEWED, DISMISSED, or None for all
      page: int = Query(1, ge=1),
      page_size: int = Query(20, ge=1, le=100),
      user: User = Depends(get_current_user),
      db: AsyncSession = Depends(get_async_session),
  ):
  ```
  Returns paginated reports with reporter username, post excerpt, thread title, and reason.

- [ ] `PATCH /forum/reports/{report_id}` — Admin only, update report status:
  ```python
  class ForumReportReviewIn(BaseModel):
      status: Literal["REVIEWED", "DISMISSED"]
  ```
  Sets `status`, `reviewed_at = func.now()`, `reviewed_by_id = user.id`.

- [ ] Add tests:
  - POST report as author of the post → 403
  - POST report twice on same post → 409
  - GET `/forum/reports` as non-admin → 403
  - PATCH report status as admin → status updates and `reviewed_at` is set

---

## Phase 4: Thread Following and Post Bookmarking

Suggested branch: `backend-forum-follow-bookmark`

**Thread following** lets users subscribe to a thread and receive notifications when new posts
arrive (notifications are wired up in Phase 6). **Post bookmarking** lets users save individual
posts to revisit later.

### 4a — `ForumFollower` model

Add to `app/models/forum_model.py`:

```python
class ForumFollower(Base):
    __tablename__ = "forum_followers"
    __table_args__ = (
        UniqueConstraint("thread_id", "user_id", name="uq_forum_follower_thread_user"),
        {"schema": SCHEMA},
    )

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

### 4b — `ForumBookmark` model

```python
class ForumBookmark(Base):
    __tablename__ = "forum_bookmarks"
    __table_args__ = (
        UniqueConstraint("post_id", "user_id", name="uq_forum_bookmark_post_user"),
        {"schema": SCHEMA},
    )

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    thread_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

### 4c — Migration

- [ ] Create Alembic migration for `man_review.forum_followers` and `man_review.forum_bookmarks`:
  ```sql
  CREATE TABLE man_review.forum_followers (
      id SERIAL PRIMARY KEY,
      thread_id INTEGER NOT NULL REFERENCES man_review.forum_threads(id) ON DELETE CASCADE,
      user_id INTEGER NOT NULL REFERENCES man_review.users(id) ON DELETE CASCADE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      CONSTRAINT uq_forum_follower_thread_user UNIQUE (thread_id, user_id)
  );

  CREATE TABLE man_review.forum_bookmarks (
      id SERIAL PRIMARY KEY,
      post_id INTEGER NOT NULL REFERENCES man_review.forum_posts(id) ON DELETE CASCADE,
      thread_id INTEGER NOT NULL REFERENCES man_review.forum_threads(id) ON DELETE CASCADE,
      user_id INTEGER NOT NULL REFERENCES man_review.users(id) ON DELETE CASCADE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      CONSTRAINT uq_forum_bookmark_post_user UNIQUE (post_id, user_id)
  );
  ```

### 4d — Follow endpoints

Add to `app/routes/forum_routes.py`:

- [ ] `POST /forum/threads/{thread_id}/follow` — toggle follow (follow if not following, unfollow if following)
  Returns `{ "following": bool, "follower_count": int }`.
- [ ] Expose `viewer_is_following: bool` on `ForumThreadOut` when a viewer is authenticated.
  Add an optional `viewer_is_following` field to `ForumThreadOut` schema (default `False`).
  In `_thread_to_out`, accept optional `viewer_id` parameter and query `ForumFollower` for it.
- [ ] `GET /forum/me/following` — paginated list of threads the signed-in user follows.
  Response shape: same `PageOut` structure as `GET /forum/me/threads`.

### 4e — Bookmark endpoints

- [ ] `POST /forum/threads/{thread_id}/posts/{post_id}/bookmark` — toggle bookmark.
  Returns `{ "bookmarked": bool }`.
- [ ] Expose `viewer_has_bookmarked: bool` on `ForumPostOut` when viewer is authenticated.
- [ ] `GET /forum/me/bookmarks` — paginated list of bookmarked posts.
  Response: `PostsPageOut` (same shape as `/forum/me/votes`).

### 4f — Tests

- [ ] POST follow → follow created; POST again → follow removed (toggle)
- [ ] GET `/forum/me/following` returns followed threads; empty list if none
- [ ] POST bookmark → bookmark created; POST again → bookmark removed
- [ ] GET `/forum/me/bookmarks` returns bookmarked posts

---

## Phase 5: Categories / Subforums

Suggested branch: `backend-forum-categories`

This is the largest structural change. Currently all threads exist in one flat undifferentiated
list. Categories let users and admins organize threads into boards (e.g. "General Discussion",
"Series Talk", "Bug Reports", "Introductions").

### 5a — `ForumCategory` model

Add to `app/models/forum_model.py` (new model, add **before** `ForumThread`):

```python
class ForumCategory(Base):
    __tablename__ = "forum_categories"
    __table_args__ = ({"schema": SCHEMA},)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    slug = Column(String(100), nullable=False, unique=True, index=True)
    description = Column(String(500), nullable=True)
    position = Column(Integer, nullable=False, server_default="0", default=0)  # display order
    is_visible = Column(Boolean, nullable=False, server_default=text("true"), default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    threads = relationship("ForumThread", back_populates="category")
```

### 5b — `ForumThread` changes

- [ ] Add FK to `ForumThread` in `app/models/forum_model.py`:
  ```python
  category_id = Column(
      Integer,
      ForeignKey(f"{SCHEMA}.forum_categories.id", ondelete="SET NULL"),
      nullable=True,
      index=True,
  )
  category = relationship("ForumCategory", back_populates="threads")
  ```
  `nullable=True` so existing uncategorized threads are unaffected by the migration.

### 5c — Migration

- [ ] Create Alembic migration:
  ```sql
  CREATE TABLE man_review.forum_categories (
      id SERIAL PRIMARY KEY,
      name VARCHAR(100) NOT NULL UNIQUE,
      slug VARCHAR(100) NOT NULL UNIQUE,
      description VARCHAR(500),
      position INTEGER NOT NULL DEFAULT 0,
      is_visible BOOLEAN NOT NULL DEFAULT TRUE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );

  ALTER TABLE man_review.forum_threads
      ADD COLUMN category_id INTEGER REFERENCES man_review.forum_categories(id) ON DELETE SET NULL;
  CREATE INDEX ON man_review.forum_threads (category_id);

  -- Seed default categories
  INSERT INTO man_review.forum_categories (name, slug, description, position) VALUES
      ('General Discussion', 'general', 'Talk about anything Toon Ranks related', 0),
      ('Series Talk', 'series', 'Discuss specific series, share recommendations', 1),
      ('Site Feedback', 'feedback', 'Bug reports, feature requests, and suggestions', 2),
      ('Introductions', 'introductions', 'Introduce yourself to the community', 3);
  ```

### 5d — Category endpoints

Add to `app/routes/forum_routes.py` (or a new `app/routes/forum_category_routes.py`):

- [ ] `GET /forum/categories` — Public. Returns all visible categories ordered by `position`.
  Include `thread_count` (count of threads in each category) in the response.
  ```python
  class ForumCategoryOut(BaseModel):
      id: int
      name: str
      slug: str
      description: Optional[str]
      position: int
      thread_count: int
  ```
- [ ] `POST /forum/categories` — Admin only. Create a new category.
  Body: `{ "name": str, "slug": str, "description": Optional[str], "position": Optional[int] }`
- [ ] `PATCH /forum/categories/{category_id}` — Admin only. Update name, description, position, visibility.
- [ ] `DELETE /forum/categories/{category_id}` — Admin only. Only allowed if the category has no threads
  (or move threads to uncategorized first). Return 409 if threads still reference it.

### 5e — Filter threads by category

- [ ] Add `category_id: Optional[int] = None` and `category_slug: Optional[str] = None` query params
  to `GET /forum/threads-paged`.
- [ ] When `category_slug` is provided, look up the category by slug and filter threads by `category_id`.
  `category_slug` is preferred over `category_id` for clean URLs.
- [ ] Add `category_id` as an optional field on `CreateThreadIn` so clients can assign a category at
  creation time.
- [ ] Add `category_id` and `category_name` to `ForumThreadOut` response.
- [ ] Include `category_id` handling in the `update_thread` endpoint so admins can re-categorize threads.

### 5f — Tests

- [ ] GET `/forum/categories` returns all visible categories with thread counts
- [ ] POST category as non-admin → 403
- [ ] POST `/forum/threads` with `category_id` → thread is assigned to that category
- [ ] GET `/forum/threads-paged?category_slug=general` → only threads in that category
- [ ] DELETE category with threads → 409

---

## Phase 6: User @-mention Parsing and Notification System

Suggested branch: `backend-forum-notifications`

This is the highest-complexity phase. A notification system requires a new `Notification` model,
a way to parse `@username` mentions in post content, and endpoints for reading/clearing
notifications.

### 6a — `Notification` model

Create `app/models/notification_model.py`:

```python
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, func
from app.database import Base

SCHEMA = "man_review"

class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = ({"schema": SCHEMA},)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind = Column(String(30), nullable=False)
    # Kind values: THREAD_REPLY, POST_MENTION, POST_UPVOTE, THREAD_FOLLOW_REPLY
    is_read = Column(Boolean, nullable=False, server_default="false", default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    read_at = Column(DateTime(timezone=True), nullable=True)

    # Contextual FKs (nullable — only relevant kind fields are set)
    thread_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_threads.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    post_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_posts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    actor_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Human-readable summary so notification can render without joining every table
    summary = Column(String(300), nullable=True)
```

### 6b — Migration

- [ ] Create Alembic migration for `man_review.notifications`:
  ```sql
  CREATE TABLE man_review.notifications (
      id SERIAL PRIMARY KEY,
      user_id INTEGER NOT NULL REFERENCES man_review.users(id) ON DELETE CASCADE,
      kind VARCHAR(30) NOT NULL,
      is_read BOOLEAN NOT NULL DEFAULT FALSE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      read_at TIMESTAMPTZ,
      thread_id INTEGER REFERENCES man_review.forum_threads(id) ON DELETE CASCADE,
      post_id INTEGER REFERENCES man_review.forum_posts(id) ON DELETE CASCADE,
      actor_id INTEGER REFERENCES man_review.users(id) ON DELETE SET NULL,
      summary VARCHAR(300)
  );
  CREATE INDEX ON man_review.notifications (user_id, is_read);
  CREATE INDEX ON man_review.notifications (created_at DESC);
  ```

### 6c — @-mention parsing utility

Create `app/utils/mention_utils.py`:

```python
import re
from typing import List

MENTION_RE = re.compile(r"@([A-Za-z0-9_-]{3,20})")

def extract_mentions(text: str) -> List[str]:
    """Return list of unique lowercased usernames mentioned in text."""
    return list({m.lower() for m in MENTION_RE.findall(text)})
```

### 6d — Notification trigger helpers

Create `app/utils/notification_utils.py`:

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.notification_model import Notification
from app.models.user_model import User
from app.models.forum_model import ForumThread, ForumPost, ForumFollower
from app.utils.mention_utils import extract_mentions

async def notify_mentions(
    content: str,
    thread_id: int,
    post_id: int,
    actor_id: int,
    db: AsyncSession,
):
    """Parse @mentions in content and create NOTIFICATION records."""
    usernames = extract_mentions(content)
    for username in usernames:
        target = (await db.execute(
            select(User).where(User.username.ilike(username))
        )).scalars().first()
        if target and target.id != actor_id:
            db.add(Notification(
                user_id=target.id,
                kind="POST_MENTION",
                thread_id=thread_id,
                post_id=post_id,
                actor_id=actor_id,
                summary=f"mentioned you in a thread",
            ))

async def notify_thread_reply(
    thread_id: int,
    post_id: int,
    actor_id: int,
    db: AsyncSession,
):
    """Notify the thread author and all followers when a new reply is posted."""
    thread = await db.get(ForumThread, thread_id)
    if not thread:
        return

    notified: set[int] = {actor_id}  # never notify the replier about their own reply

    # Notify thread author
    if thread.author_id and thread.author_id not in notified:
        db.add(Notification(
            user_id=thread.author_id,
            kind="THREAD_REPLY",
            thread_id=thread_id,
            post_id=post_id,
            actor_id=actor_id,
            summary="replied to your thread",
        ))
        notified.add(thread.author_id)

    # Notify followers
    followers = (await db.execute(
        select(ForumFollower).where(ForumFollower.thread_id == thread_id)
    )).scalars().all()
    for f in followers:
        if f.user_id not in notified:
            db.add(Notification(
                user_id=f.user_id,
                kind="THREAD_FOLLOW_REPLY",
                thread_id=thread_id,
                post_id=post_id,
                actor_id=actor_id,
                summary="posted in a thread you follow",
            ))
            notified.add(f.user_id)
```

### 6e — Wire notification triggers

- [ ] In `create_post` in `forum_routes.py`, after `await db.flush()` and before `await db.commit()`:
  ```python
  from app.utils.notification_utils import notify_thread_reply, notify_mentions
  await notify_thread_reply(thread_id, post.id, user.id, db)
  await notify_mentions(payload.content_markdown, thread_id, post.id, user.id, db)
  ```
- [ ] In `update_post`, after editing: re-parse mentions in the new content to catch newly added
  `@mentions`. Do not double-notify for mentions that were already in the original content.

### 6f — Notification endpoints

Create `app/routes/notification_routes.py`:

- [ ] `GET /notifications` — Auth required. Returns paginated unread notifications for the signed-in
  user, newest first. Include `unread_count` in the response envelope.
  ```python
  class NotificationOut(BaseModel):
      id: int
      kind: str
      is_read: bool
      created_at: str
      thread_id: Optional[int]
      post_id: Optional[int]
      actor_username: Optional[str]
      summary: Optional[str]
  ```
- [ ] `PATCH /notifications/{notification_id}/read` — Mark a single notification as read.
- [ ] `POST /notifications/read-all` — Mark all of the signed-in user's notifications as read.
- [ ] `GET /notifications/unread-count` — Returns `{ "count": int }`. Lightweight endpoint for
  polling the notification badge count without loading all notifications.
- [ ] Register the router in `app/main.py` (wherever other routers are registered).

### 6g — Tests

- [ ] POST a reply with `@username` → notification row created for that user
- [ ] Replying to your own thread creates a THREAD_REPLY notification for the thread author
- [ ] Followers receive THREAD_FOLLOW_REPLY notifications
- [ ] PATCH read → `is_read` and `read_at` set
- [ ] POST read-all → all user's notifications marked read
- [ ] GET `/notifications/unread-count` → correct count before and after read-all

---

## Phase 7: Read State Tracking

Suggested branch: `backend-forum-read-tracking`

Tracks the last post a user has seen in each thread so the frontend can show "new posts" badges
and the user's last-read position.

### 7a — `ForumReadState` model

Add to `app/models/forum_model.py`:

```python
class ForumReadState(Base):
    __tablename__ = "forum_read_states"
    __table_args__ = (
        UniqueConstraint("thread_id", "user_id", name="uq_forum_read_state"),
        {"schema": SCHEMA},
    )

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    last_seen_post_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_posts.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

### 7b — Migration

- [ ] Create Alembic migration:
  ```sql
  CREATE TABLE man_review.forum_read_states (
      id SERIAL PRIMARY KEY,
      thread_id INTEGER NOT NULL REFERENCES man_review.forum_threads(id) ON DELETE CASCADE,
      user_id INTEGER NOT NULL REFERENCES man_review.users(id) ON DELETE CASCADE,
      last_seen_post_id INTEGER REFERENCES man_review.forum_posts(id) ON DELETE SET NULL,
      last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      CONSTRAINT uq_forum_read_state UNIQUE (thread_id, user_id)
  );
  CREATE INDEX ON man_review.forum_read_states (user_id);
  ```

### 7c — Read state endpoints

Add to `app/routes/forum_routes.py`:

- [ ] `POST /forum/threads/{thread_id}/mark-read` — Auth required.
  Body: `{ "last_seen_post_id": int }`.
  Upserts the `ForumReadState` row for the signed-in user and thread.
  Returns `{ "thread_id": int, "last_seen_post_id": int, "last_seen_at": str }`.
  This is called by the frontend each time a user scrolls through posts.

- [ ] Expose `has_unread: bool` and `unread_count: Optional[int]` on `ForumThreadOut` when a viewer
  is authenticated. In `_thread_to_out`, accept an optional `viewer_id` parameter and query
  `ForumReadState` to determine whether there are posts after `last_seen_post_id`.
  - `has_unread = last_seen_post_id < most_recent_post_id` (or True if no read state exists)
  - `unread_count = count of posts with id > last_seen_post_id`

### 7d — Tests

- [ ] POST mark-read → read state upserted
- [ ] GET thread list as authenticated viewer → `has_unread: true` for threads with new posts since
  last visit; `false` for threads fully read

---

## Phase 8: Full-text Post Content Search

Suggested branch: `backend-forum-fulltext-search`

Currently `GET /forum/threads-paged` only searches thread **titles** via `title.ilike(f"%{q}%")`.
Users cannot search for a specific post or keyword within thread bodies.

**File:** `app/routes/forum_routes.py`

- [ ] Add `search_posts: bool = Query(False)` to `GET /forum/threads-paged`.
  When `q` is provided and `search_posts=True`, the query should also search post content:
  ```python
  from sqlalchemy import exists

  if q and search_posts:
      post_match = exists().where(
          ForumPost.thread_id == ForumThread.id,
          ForumPost.content_markdown.ilike(f"%{q}%"),
      )
      filters.append(or_(ForumThread.title.ilike(f"%{q}%"), post_match))
  elif q:
      filters.append(ForumThread.title.ilike(f"%{q}%"))
  ```
  This surfaces threads that contain the search term in any post, even if the title doesn't match.

- [ ] Add a separate post-level search endpoint for searching within a specific thread:
  `GET /forum/threads/{thread_id}/posts/search?q=keyword&page=1&page_size=20`
  Returns matching posts in `PostsPageOut` format with the same viewer auth pattern.

- [ ] **Optional — PostgreSQL full-text search:** For production scale, consider adding
  `tsvector` columns and `GIN` indexes to both `forum_threads.title` and
  `forum_posts.content_markdown`. A dedicated migration can add:
  ```sql
  ALTER TABLE man_review.forum_posts
      ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (
          to_tsvector('english', coalesce(content_markdown, ''))
      ) STORED;
  CREATE INDEX ON man_review.forum_posts USING GIN (search_vector);
  ```
  The route would then use `ForumPost.search_vector.match(q)` instead of `ilike`.
  Skip this in the first pass — `ilike` is sufficient until search load is measurable.

- [ ] Add tests:
  - `?q=keyword&search_posts=false` → only threads with keyword in title match
  - `?q=keyword&search_posts=true` → threads with keyword in any post content also match
  - GET post search within thread → only posts matching keyword returned

---

## Later / Post-Launch

- [ ] Admin thread management: `PATCH /forum/threads/{id}/move` (re-assign category). No merge/split
  needed for v1.
- [ ] Expose `author_id` on `ForumThreadOut` (currently only `author_username` is returned) to make
  building moderator tools easier.
- [ ] Periodic job to purge `Notification` rows older than 90 days (Railway cron or a scheduled task).
- [ ] Consider caching category list in Redis/memory since categories change rarely.
- [ ] Rate limit the `mark-read` endpoint at `60/minute` to prevent abuse as a tracking beacon.
- [ ] Email digest notifications (weekly summary of forum activity) — requires an email sending
  strategy beyond the current hCaptcha/verification emails.
