# Data Model — Toon Ranks Backend

All tables live in the **`man_review`** PostgreSQL schema.

---

## Entity relationship overview

```
users
  ├── reading_lists ──── reading_list_items ──── series
  ├── user_favourites ── series
  ├── user_votes ─────── series (category ratings)
  ├── forum_threads ──── forum_posts ──────────── forum_reactions
  │       │                   │
  │       │               forum_series_refs ───── series
  │   forum_series_refs
  ├── forum_followers ── forum_threads
  ├── forum_bookmarks ── forum_posts
  ├── forum_read_states  forum_threads
  ├── notifications
  ├── mobile_auth_codes
  ├── mobile_refresh_tokens
  └── issues (anonymous or linked)

series
  └── series_details (1:1)
```

---

## Table reference

### `users`

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `username` | varchar unique | display name, case-sensitive |
| `password` | varchar | bcrypt hash; empty string for Google OAuth accounts |
| `email` | varchar unique nullable | stored lowercased |
| `is_verified` | boolean | must be true to log in (email flow) |
| `role` | varchar | `GENERAL` (default), `CONTRIBUTOR`, `ADMIN` |
| `avatar_url` | varchar nullable | S3 URL; takes precedence over preset |
| `avatar_preset` | varchar nullable | `blue`, `emerald`, `amber`; fallback when no URL |
| `signup_platform` | varchar | `web` or `mobile` |
| `auth_provider` | varchar | `email` or `google` |
| `registered_at` | timestamptz nullable | |
| `cred_score` | integer default 0 | community reputation; drives leaderboard |

### `series`

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `title` | varchar not null | |
| `genre` | varchar | free text (e.g. "Action", "Romance") |
| `type` | enum | `MANGA`, `MANHWA`, `MANHUA` |
| `status` | enum nullable | `ONGOING`, `COMPLETE`, `HIATUS`, `UNKNOWN`, `SEASON_END` |
| `author` | varchar | |
| `artist` | varchar | |
| `cover_url` | varchar | S3 URL — list/card thumbnail |
| `vote_count` | integer | **distinct voter count**, not total votes |
| `approval_status` | varchar | `DRAFT`, `PENDING`, `APPROVED` — see state machine |
| `submitted_by_id` | integer nullable FK → users | null for legacy data |
| `approved_by_id` | integer nullable FK → users | admin who approved |
| `approved_at` | varchar nullable | ISO 8601 timestamp string |

Only `APPROVED` series appear in public rankings and searches.

### `series_details`

One-to-one with `series` (cascades on delete).

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `series_id` | integer unique FK → series | |
| `synopsis` | varchar | long-form description |
| `series_cover_url` | varchar | S3 URL — detail page banner (different from list cover) |
| `story_total` | integer | sum of all story votes |
| `story_count` | integer | number of story votes |
| `characters_total` | integer | |
| `characters_count` | integer | |
| `worldbuilding_total` | integer | |
| `worldbuilding_count` | integer | |
| `art_total` | integer | |
| `art_count` | integer | |
| `drama_or_fight_total` | integer | |
| `drama_or_fight_count` | integer | |

**Scoring formula:**
```
avg_category = total / count   (0 if count == 0)
final_score  = (story_avg + characters_avg + worldbuilding_avg + art_avg + drama_avg) / 5
```

### `user_votes`

Unique constraint on `(user_id, series_id, category)` — one vote per user per category.

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `user_id` | integer FK → users | |
| `series_id` | integer FK → series | |
| `category` | varchar | `Story`, `Characters`, `World Building`, `Art`, `Drama / Fighting` |
| `score` | integer | 1–10 |

### `reading_lists`

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `user_id` | integer FK → users CASCADE | |
| `name` | varchar | unique per user |
| `is_public` | boolean default false | |
| `share_token` | UUID unique | auto-generated; used for public share links |

Max 2 lists per non-admin user. Max 35 items per list for non-admins.

### `reading_list_items`

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `list_id` | integer FK → reading_lists CASCADE | |
| `series_id` | integer FK → series CASCADE | |
| `left_off_chapter` | varchar(50) nullable | e.g. "Chapter 42" |

Unique constraint: `(list_id, series_id)`.

### `user_favourites`

Pinned series displayed on a user's public profile (up to 6 per user).

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `user_id` | integer FK → users CASCADE | |
| `series_id` | integer FK → series CASCADE | |
| `position` | integer | display order, 0-indexed |

Unique constraint: `(user_id, series_id)`.

### `forum_categories`

Top-level boards that threads are organised into.

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `name` | varchar(100) unique | |
| `slug` | varchar(100) unique | URL-safe, lowercase, hyphens only |
| `description` | varchar(500) nullable | |
| `position` | integer default 0 | display order |
| `is_visible` | boolean default true | hides category without deleting |
| `created_at` | timestamptz | |

### `forum_threads`

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `title` | varchar(200) | |
| `author_id` | integer nullable FK → users SET NULL | null if user deleted |
| `category_id` | integer nullable FK → forum_categories SET NULL | |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |
| `post_count` | integer | denormalized; updated on post create/delete |
| `last_post_at` | timestamptz | denormalized; updated on new post |
| `locked` | boolean default false | prevents new posts when true |
| `latest_first` | boolean default false | thread-level sort preference |
| `view_count` | integer default 0 | incremented on thread open |
| `is_pinned` | boolean default false | pinned threads sort first |

### `forum_posts`

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `thread_id` | integer FK → forum_threads CASCADE | |
| `author_id` | integer nullable FK → users SET NULL | null if user deleted |
| `parent_id` | integer nullable FK → forum_posts CASCADE | null = top-level post; non-null = reply |
| `content_markdown` | text | raw markdown |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |
| `heart_count` | integer | legacy; kept for migration compatibility |
| `upvote_count` | integer | denormalized reaction count |
| `downvote_count` | integer | denormalized reaction count |

### `forum_series_refs`

Links a thread or post to one or more series (e.g. "this post is about Berserk and Vinland Saga").

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `thread_id` | integer FK → forum_threads CASCADE | always set |
| `post_id` | integer nullable FK → forum_posts CASCADE | null = thread-level ref |
| `series_id` | integer FK → series CASCADE | |

### `forum_reactions`

One reaction per user per post. Unique constraint: `(post_id, user_id)`.

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `post_id` | integer FK → forum_posts CASCADE | |
| `user_id` | integer FK → users CASCADE | |
| `kind` | varchar(20) | `UPVOTE`, `DOWNVOTE` (legacy `HEART` may exist) |
| `created_at` | timestamptz | |

### `forum_followers`

User subscribes to a thread to receive reply notifications.

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `thread_id` | integer FK → forum_threads CASCADE | |
| `user_id` | integer FK → users CASCADE | |
| `created_at` | timestamptz | |

Unique: `(thread_id, user_id)`.

### `forum_bookmarks`

User saves an individual post to revisit later.

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `post_id` | integer FK → forum_posts CASCADE | |
| `thread_id` | integer FK → forum_threads CASCADE | denormalized for fast list queries |
| `user_id` | integer FK → users CASCADE | |
| `created_at` | timestamptz | |

Unique: `(post_id, user_id)`.

### `forum_read_states`

Tracks how far a user has read in each thread (drives unread badge).

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `thread_id` | integer FK → forum_threads CASCADE | |
| `user_id` | integer FK → users CASCADE | |
| `last_seen_post_id` | integer nullable FK → forum_posts SET NULL | |
| `last_seen_at` | timestamptz | |

Unique: `(thread_id, user_id)`.

### `forum_reports`

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `post_id` | integer FK → forum_posts CASCADE | |
| `thread_id` | integer FK → forum_threads CASCADE | |
| `reporter_id` | integer FK → users CASCADE | |
| `reason` | varchar(500) nullable | |
| `status` | varchar(20) | `OPEN`, `REVIEWED`, `DISMISSED` |
| `created_at` | timestamptz | |
| `reviewed_at` | timestamptz nullable | |
| `reviewed_by_id` | integer nullable FK → users SET NULL | |

Unique: `(post_id, reporter_id)`.

### `notifications`

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `user_id` | integer FK → users CASCADE | recipient |
| `kind` | varchar(30) | `THREAD_REPLY`, `THREAD_FOLLOW_REPLY`, `POST_MENTION` |
| `is_read` | boolean default false | |
| `created_at` | timestamptz | |
| `read_at` | timestamptz nullable | |
| `thread_id` | integer nullable FK → forum_threads CASCADE | context |
| `post_id` | integer nullable FK → forum_posts CASCADE | context |
| `actor_id` | integer nullable FK → users SET NULL | who triggered it |
| `summary` | varchar(300) nullable | human-readable (e.g. "replied to your thread") |

### `mobile_auth_codes`

Short-lived one-time codes for the mobile auth handoff flow.

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `user_id` | integer FK → users CASCADE | |
| `code_hash` | varchar(128) unique | SHA-256 of the raw code |
| `redirect_uri` | varchar(255) | must be in allowlist |
| `state` | varchar(255) nullable | PKCE state |
| `expires_at` | timestamptz | 5 minutes from creation |
| `used_at` | timestamptz nullable | set on exchange; non-null = used |

### `mobile_refresh_tokens`

Long-lived tokens for mobile token refresh (30-day expiry).

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `user_id` | integer FK → users CASCADE | |
| `token_hash` | varchar(128) unique | SHA-256 of the raw token |
| `created_at` | timestamptz | |
| `expires_at` | timestamptz | 30 days from creation |
| `last_used_at` | timestamptz nullable | updated on each refresh |
| `revoked_at` | timestamptz nullable | set on logout; non-null = revoked |

### `issues`

User-submitted bug reports and feature requests.

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `type` | enum | `BUG`, `FEATURE`, `CONTENT`, `OTHER` |
| `title` | varchar(200) | |
| `description` | text | |
| `page_url` | varchar(1024) nullable | page where the issue occurred |
| `email` | varchar(320) nullable | contact email (anonymous reporters) |
| `screenshot_url` | varchar(2048) nullable | S3 or external URL |
| `user_id` | integer nullable FK → users | null for anonymous |
| `user_agent` | varchar(512) nullable | |
| `status` | enum | `OPEN`, `IN_PROGRESS`, `FIXED`, `WONT_FIX` |
| `admin_notes` | text nullable | internal admin notes |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

---

## Enum values reference

| Enum | Values |
|---|---|
| Series type | `MANGA`, `MANHWA`, `MANHUA` |
| Series status | `ONGOING`, `COMPLETE`, `HIATUS`, `UNKNOWN`, `SEASON_END` |
| Approval status | `DRAFT`, `PENDING`, `APPROVED` |
| User role | `GENERAL`, `CONTRIBUTOR`, `ADMIN` |
| Vote category | `Story`, `Characters`, `World Building`, `Art`, `Drama / Fighting` |
| Reaction kind | `UPVOTE`, `DOWNVOTE` (legacy: `HEART`) |
| Notification kind | `THREAD_REPLY`, `THREAD_FOLLOW_REPLY`, `POST_MENTION` |
| Issue type | `BUG`, `FEATURE`, `CONTENT`, `OTHER` |
| Issue status | `OPEN`, `IN_PROGRESS`, `FIXED`, `WONT_FIX` |
| Report status | `OPEN`, `REVIEWED`, `DISMISSED` |
