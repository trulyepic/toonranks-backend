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
| `ForumThread` | `id`, `title`, `author_id`, `created_at`, `updated_at`, `post_count`, `last_post_at`, `locked`, `latest_first`, `view_count`, `is_pinned` |
| `ForumPost` | `id`, `thread_id`, `author_id`, `parent_id`, `content_markdown`, `created_at`, `updated_at`, `heart_count`, `upvote_count`, `downvote_count` |
| `ForumSeriesRef` | `id`, `thread_id`, `post_id`, `series_id` |
| `ForumReaction` | `id`, `post_id`, `user_id`, `kind` (UPVOTE/DOWNVOTE/HEART) |
| `ForumMedia` | `id`, `user_id`, `thread_id`, `post_id`, `url`, `mime_type`, `size_bytes`, `width`, `height` |
| `ForumReport` | `id`, `post_id`, `thread_id`, `reporter_id`, `reason`, `status` (OPEN/REVIEWED/DISMISSED), `reviewed_at`, `reviewed_by_id` |
| `ForumFollower` | `id`, `thread_id`, `user_id`, `created_at` |
| `ForumBookmark` | `id`, `post_id`, `thread_id`, `user_id`, `created_at` |
| `ForumCategory` | `id`, `name`, `slug`, `description`, `position`, `is_visible`, `created_at` |
| `Notification` | `id`, `user_id`, `kind`, `is_read`, `created_at`, `read_at`, `thread_id`, `post_id`, `actor_id`, `summary` |

**Current endpoints:**

| Method | Path | Auth | Notes |
|---|---|---|---|
| `GET` | `/forum/threads` | None | Simple list, title search, sorted `updated_at DESC` |
| `GET` | `/forum/threads-paged` | None | Paginated; `?q=` title search; `?sort=activity/newest/replies`; pinned first |
| `POST` | `/forum/threads` | Required | Rate: `3/min; 20/hr; 60/day`. Limit: 50 threads per user |
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
| `PATCH` | `/forum/threads/{thread_id}/pin` | Admin only | Toggles `is_pinned` boolean |
| `POST` | `/forum/threads/{thread_id}/posts/{post_id}/report` | Required | Rate: `5/hr`; blocks self-report and duplicates |
| `GET` | `/forum/reports` | Admin only | Paginated moderation queue; filterable by status |
| `PATCH` | `/forum/reports/{report_id}` | Admin only | Mark report REVIEWED or DISMISSED |
| `POST` | `/forum/threads/{thread_id}/follow` | Required | Toggle follow; rate: `30/min`; returns `{ following, follower_count }` |
| `GET` | `/forum/me/following` | Required | Paginated threads user is following; `PageOut` |
| `POST` | `/forum/threads/{thread_id}/posts/{post_id}/bookmark` | Required | Toggle bookmark; rate: `60/min`; returns `{ bookmarked }` |
| `GET` | `/forum/me/bookmarks` | Required | Paginated bookmarked posts; `PostsPageOut` |
| `GET` | `/forum/categories` | None | All visible categories ordered by position, with `thread_count` |
| `POST` | `/forum/categories` | Admin only | Create category; 409 on duplicate name/slug |
| `PATCH` | `/forum/categories/{id}` | Admin only | Update name, slug, description, position, visibility |
| `DELETE` | `/forum/categories/{id}` | Admin only | Delete only if no threads; 409 otherwise |
| `GET` | `/notifications` | Required | Paginated; `?unread_only=true`; includes `unread_count` in envelope |
| `GET` | `/notifications/unread-count` | Required | Returns `{ count }` for badge polling |
| `PATCH` | `/notifications/{id}/read` | Required | Mark single notification read |
| `POST` | `/notifications/read-all` | Required | Mark all user notifications read |

**Cred score formula:**
- `+2` when user creates a thread
- `+1` when user posts a reply
- `+2` per upvote received on any post
- `-1` per downvote received on any post
- All reversed on delete

---

## ✅ Phase 1: Quick Wins — Thread Limit, View Count, and Pinning Column

Suggested branch: `backend-forum-quick-wins` — **merged and deployed**

Migration applied: `FORUM_THREAD_COLUMNS_MIGRATION.sql`

### 1a — Raise the thread limit

- [x] `MAX_THREADS_PER_USER = 50` constant added to top of `forum_routes.py`
- [x] Inline `>= 10` replaced with `>= MAX_THREADS_PER_USER`
- [x] 403 error message updated to reflect new limit
- [x] Existing thread-limit test updated to assert against 50

### 1b — Thread view count

- [x] `view_count` column added to `ForumThread` model
- [x] Migration SQL created (`FORUM_THREAD_COLUMNS_MIGRATION.sql`)
- [x] `get_thread` increments `view_count` on fetch, skips author's own views
- [x] `get_thread_posts_paged` increments on page 1 only
- [x] `view_count` exposed in `ForumThreadOut` schema and `_thread_to_out()` mapper

### 1c — Pinned thread column

- [x] `is_pinned` column added to `ForumThread` model
- [x] Migration SQL created (`FORUM_THREAD_COLUMNS_MIGRATION.sql`)
- [x] `is_pinned` exposed in `ForumThreadOut` schema and `_thread_to_out()` mapper
- [x] `list_threads_paged` and `list_threads` both sort `is_pinned DESC` first
- [x] `PATCH /forum/threads/{id}/pin` admin-only endpoint added
- [x] `PinToggleIn` Pydantic model added alongside `LockToggleIn`

---

## ✅ Phase 2: Thread Sorting Options

Suggested branch: `backend-forum-thread-sorting` — **merged and deployed**

No migration required.

- [x] `sort` query param added to `GET /forum/threads-paged`: `activity` (default), `newest`, `replies`
- [x] Order clause built conditionally; pinned threads always surface first regardless of sort
- [x] `sort` field added to `PageOut` response schema so frontend can confirm active sort

---

## ✅ Phase 3: Post Reporting

Suggested branch: `backend-forum-post-reporting` — **merged and deployed**

Migration applied: `FORUM_REPORTS_MIGRATION.sql`

### 3a — `ForumReport` model
- [x] `ForumReport` model added to `app/models/forum_model.py` with `post_id`, `thread_id`, `reporter_id`, `reason`, `status` (OPEN/REVIEWED/DISMISSED), `reviewed_at`, `reviewed_by_id`
- [x] `UniqueConstraint("post_id", "reporter_id")` prevents duplicate reports per user

### 3b — Migration
- [x] `FORUM_REPORTS_MIGRATION.sql` created — `man_review.forum_reports` table with indexes on `post_id`, `reporter_id`, and `status`

### 3c — Endpoints
- [x] `POST /forum/threads/{id}/posts/{post_id}/report` — rate-limited 5/hour; blocks self-reporting (403); blocks duplicates (409); returns 201 on success
- [x] `GET /forum/reports?status=OPEN` — admin only; paginated; includes `post_excerpt`, `thread_title`, `reporter_username` in response
- [x] `PATCH /forum/reports/{id}` — admin only; sets status to REVIEWED or DISMISSED with timestamp and reviewer recorded
- [x] `ForumReportIn`, `ForumReportReviewIn`, `ForumReportOut`, `ForumReportsPageOut` schemas added to `forum_schemas.py`

---

## ✅ Phase 4: Thread Following and Post Bookmarking

Suggested branch: `backend-forum-follow-bookmark` — **complete, pending merge**

Migration applied: `FORUM_FOLLOW_BOOKMARK_MIGRATION.sql`

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

- [x] Create migration SQL for `man_review.forum_followers` and `man_review.forum_bookmarks`:
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

- [x] `POST /forum/threads/{thread_id}/follow` — toggle follow (follow if not following, unfollow if following)
  Returns `{ "following": bool, "follower_count": int }`.
- [x] Expose `viewer_is_following: bool` on `ForumThreadOut` when a viewer is authenticated.
  Add an optional `viewer_is_following` field to `ForumThreadOut` schema (default `False`).
  In `_thread_to_out`, accept optional `viewer_id` parameter and query `ForumFollower` for it.
- [x] `GET /forum/me/following` — paginated list of threads the signed-in user follows.
  Response shape: same `PageOut` structure as `GET /forum/me/threads`.

### 4e — Bookmark endpoints

- [x] `POST /forum/threads/{thread_id}/posts/{post_id}/bookmark` — toggle bookmark.
  Returns `{ "bookmarked": bool }`.
- [x] Expose `viewer_has_bookmarked: bool` on `ForumPostOut` when viewer is authenticated.
- [x] `GET /forum/me/bookmarks` — paginated list of bookmarked posts.
  Response: `PostsPageOut` (same shape as `/forum/me/votes`).

### 4f — Tests

- [x] Existing `/me/posts` and `/me/votes` tests updated to account for new bookmark query in `_post_to_out`
- [ ] POST follow → follow created; POST again → follow removed (toggle)
- [ ] GET `/forum/me/following` returns followed threads; empty list if none
- [ ] POST bookmark → bookmark created; POST again → bookmark removed
- [ ] GET `/forum/me/bookmarks` returns bookmarked posts

---

## ✅ Phase 5: Categories / Subforums

Suggested branch: `backend-forum-categories` — **complete, pending merge**

Migration applied: `FORUM_CATEGORIES_MIGRATION.sql`

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

- [x] Add FK to `ForumThread` in `app/models/forum_model.py`:
  `nullable=True` so existing uncategorized threads are unaffected by the migration.

### 5c — Migration

- [x] Created `FORUM_CATEGORIES_MIGRATION.sql` — creates `man_review.forum_categories` table, adds `category_id` FK to `forum_threads`, seeds 4 default categories

### 5d — Category endpoints

- [x] `GET /forum/categories` — Public. Returns all visible categories ordered by `position` with `thread_count`
- [x] `POST /forum/categories` — Admin only. Validates unique name + slug; returns 409 on duplicate
- [x] `PATCH /forum/categories/{category_id}` — Admin only. Update name, slug, description, position, visibility
- [x] `DELETE /forum/categories/{category_id}` — Admin only. Returns 409 if threads still belong to category

### 5e — Filter threads by category

- [x] `category_slug` and `category_id` query params added to `GET /forum/threads-paged`; slug takes priority
- [x] Unknown slug returns empty page (not 404) so frontend doesn't crash on bad slug
- [x] `category_id` added to `CreateThreadIn`; validated against DB on create
- [x] `category_id` and `category_name` added to `ForumThreadOut` and populated in `_thread_to_out`
- [x] `category_id` handling in `update_thread`: pass `0` to unset, any valid id to re-assign

### 5f — Tests

- [x] All 18 existing tests still pass (no regressions)
- [ ] GET `/forum/categories` returns all visible categories with thread counts
- [ ] POST category as non-admin → 403
- [ ] POST `/forum/threads` with `category_id` → thread is assigned to that category
- [ ] GET `/forum/threads-paged?category_slug=general` → only threads in that category
- [ ] DELETE category with threads → 409

---

## ✅ Phase 6: User @-mention Parsing and Notification System

Suggested branch: `backend-forum-notifications` — **complete, pending merge**

Migration applied: `FORUM_NOTIFICATIONS_MIGRATION.sql`

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

- [x] Created `FORUM_NOTIFICATIONS_MIGRATION.sql` — `man_review.notifications` table with indexes on `(user_id, is_read)` and `created_at DESC`
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

- [x] Created `app/utils/mention_utils.py` — `extract_mentions(text)` returns deduplicated lowercased usernames from `@username` patterns (3–20 chars)

### 6d — Notification trigger helpers

- [x] Created `app/utils/notification_utils.py`:
  - `notify_thread_reply` — notifies thread author (THREAD_REPLY) and all followers (THREAD_FOLLOW_REPLY); never notifies the replier
  - `notify_mentions` — parses `@mentions` and creates POST_MENTION notifications for each mentioned user (skips self-mentions)

### 6e — Wire notification triggers

- [x] `create_post` now calls `notify_thread_reply` and `notify_mentions` after flush, before commit
- [ ] `update_post` mention re-parsing (skipped for v1 — avoids double-notify complexity; deferred to post-launch)

### 6f — Notification endpoints

Created `app/routes/notification_routes.py`, registered in `app/main.py`:

- [x] `GET /notifications` — Auth required; paginated; supports `?unread_only=true`; includes `unread_count` in envelope
- [x] `GET /notifications/unread-count` — Returns `{ "count": int }` for badge polling
- [x] `PATCH /notifications/{id}/read` — Marks single notification read; sets `read_at` timestamp
- [x] `POST /notifications/read-all` — Marks all user's unread notifications read in one UPDATE

### 6g — Tests

- [x] Existing `test_create_post_returns_author_avatar_metadata` updated for new followers query
- [x] All 18 tests pass
- [ ] POST reply with `@username` → POST_MENTION notification created
- [ ] THREAD_REPLY and THREAD_FOLLOW_REPLY creation on reply
- [ ] PATCH read / POST read-all / GET unread-count

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
