# API Surface — Toon Ranks Backend

Base URL: `https://www.toonranks.com` (production) / `https://uat.toonranks.com` (UAT)
Local: `http://localhost:8000`

Auth: `Authorization: Bearer <jwt_token>` header where required.

Roles: `GENERAL` (default) · `CONTRIBUTOR` · `ADMIN`

Legend: 🔓 public · 🔑 any authenticated user · 👤 contributor+ · 🛡️ admin only

---

## Health

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | 🔓 | Returns `{"status": "ok"}` |

---

## Auth (`/auth`)

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/signup` | 🔓 | Register with email/password + reCAPTCHA. Sends verification email. |
| POST | `/auth/login` | 🔓 | Email/password login + reCAPTCHA. Returns JWT + user object. |
| POST | `/auth/google-oauth` | 🔓 | Google OAuth login/signup via `id_token`. Returns JWT + user object. |
| GET | `/auth/verify-email` | 🔓 | Verify email from token in query param `?token=`. |
| POST | `/auth/resend-verification` | 🔓 | Resend verification email by email or username. |
| POST | `/auth/forgot-password` | 🔓 | Send password reset email. |
| POST | `/auth/reset-password` | 🔓 | Reset password using emailed token. |
| POST | `/auth/mobile-code` | 🔑 | Generate short-lived auth code for mobile handoff. |
| POST | `/auth/mobile-token` | 🔓 | Exchange auth code for JWT + refresh token. |
| POST | `/auth/mobile-refresh` | 🔓 | Refresh JWT using mobile refresh token. |
| POST | `/auth/mobile-logout` | 🔓 | Revoke mobile refresh token. |
| POST | `/auth/me/avatar` | 🔑 | Upload custom avatar image (PNG/JPEG/WEBP, max 5 MB). |
| PATCH | `/auth/me/avatar/preset` | 🔑 | Switch to a colour preset avatar (`blue`, `emerald`, `amber`). |
| DELETE | `/auth/me/avatar` | 🔑 | Reset avatar to preset. |
| PATCH | `/auth/me/username` | 🔑 | Change username (rate-limited: 5/hour). |
| DELETE | `/auth/me` | 🔑 | Delete own account (cascades to votes; forum content set to anonymous). |
| GET | `/auth/users` | 🛡️ | List all users for admin panel. |
| PATCH | `/auth/users/{user_id}/role` | 🛡️ | Update a user's role. |

---

## Series (`/series`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/series/rankings` | 🔓 | Paginated ranked series list. Query: `page`, `page_size`, `type`, `genre`, `status`. |
| GET | `/series/search` | 🔓 | Full-text search across title, genre, type, author, artist, status. Query: `query`. |
| GET | `/series/` | 🔓 | Flat list of all approved series (no pagination). |
| GET | `/series/summary/{series_id}` | 🔓* | Single series with rank. *Auth optional — submitter/admin can see pending series. |
| GET | `/series/pending` | 🛡️ | List series in `PENDING` approval state. |
| GET | `/series/submissions/mine` | 👤 | List the current user's own submissions (all statuses). |
| POST | `/series/` | 👤 | Create a new series (multipart: fields + cover image). Starts in `DRAFT`. |
| PUT | `/series/{series_id}` | 🔑* | Update series. *Admin: any series. Contributor: own pending series only. Optional `where_to_read` JSON form field (see DATA_MODEL.md). |
| POST | `/series/{series_id}/approve` | 🛡️ | Approve a pending series (requires detail to be complete). |
| DELETE | `/series/{series_id}` | 🛡️ | Delete a series and its S3 cover images. |

---

## Series Details (`/series-details`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/series-details/{series_id}` | 🔓* | Get detail page data (synopsis, ratings, vote scores, `where_to_read` links). *Auth optional. |
| POST | `/series-details/` | 🔑* | Create or update synopsis + detail cover. *Admin or series owner (pre-approval). |
| POST | `/series-details/{series_id}/vote` | 🔑 | Submit a rating (1–10) for one category. One vote per category per user. |
| GET | `/series-details/me/votes` | 🔑 | Paginated list of series the current user has voted on, with scores. |

---

## Reading Lists (`/reading-lists`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/reading-lists/` | 🔑 | Get current user's reading lists. |
| POST | `/reading-lists/` | 🔑 | Create a new reading list (max 2 for non-admins). |
| PUT | `/reading-lists/{list_id}` | 🔑 | Rename a list or toggle `is_public`. |
| DELETE | `/reading-lists/{list_id}` | 🔑 | Delete a reading list. |
| POST | `/reading-lists/{list_id}/items` | 🔑 | Add a series to a list (max 35 items for non-admins). |
| DELETE | `/reading-lists/{list_id}/items/{series_id}` | 🔑 | Remove a series from a list. |
| PATCH | `/reading-lists/{list_id}/items/{series_id}` | 🔑 | Update `left_off_chapter` for a series in a list. |
| GET | `/reading-lists/public/{share_token}` | 🔓 | View a public reading list by share token. |

---

## Favourites (`/auth/favourites`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/auth/favourites/` | 🔑 | Get current user's pinned favourites. |
| POST | `/auth/favourites/` | 🔑 | Add a series to favourites (ordered, position required). |
| DELETE | `/auth/favourites/{series_id}` | 🔑 | Remove from favourites. |
| PUT | `/auth/favourites/reorder` | 🔑 | Reorder all favourites (pass full ordered list). |

---

## Forum (`/forum`)

### Categories

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/forum/categories` | 🔓 | List all visible categories with thread counts. |
| POST | `/forum/categories` | 🛡️ | Create a new category. |
| PATCH | `/forum/categories/{category_id}` | 🛡️ | Update category (name, slug, description, visibility, position). |
| DELETE | `/forum/categories/{category_id}` | 🛡️ | Delete category. |

### Threads

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/forum/threads` | 🔓* | Paginated thread list. Filters: `category_id`, `series_id`, `search`. *Auth optional for unread state. |
| GET | `/forum/threads/{thread_id}` | 🔓* | Single thread metadata. |
| POST | `/forum/threads` | 🔑 | Create thread + first post (max 50 threads per user). |
| PATCH | `/forum/threads/{thread_id}` | 🔑* | Edit thread title/first post/series refs. *Own thread or admin. |
| DELETE | `/forum/threads/{thread_id}` | 🔑* | Delete thread. *Own thread or admin. |
| PATCH | `/forum/threads/{thread_id}/settings` | 🔑* | Toggle `latest_first`. *Own thread. |
| PATCH | `/forum/threads/{thread_id}/lock` | 🛡️ | Lock/unlock thread. |
| PATCH | `/forum/threads/{thread_id}/pin` | 🛡️ | Pin/unpin thread. |
| POST | `/forum/threads/{thread_id}/view` | 🔓 | Increment view count. |

### Posts

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/forum/threads/{thread_id}/posts` | 🔓* | Paginated posts for a thread. *Auth optional for reaction state. |
| POST | `/forum/threads/{thread_id}/posts` | 🔑 | Create a post (or reply via `parent_id`). |
| PATCH | `/forum/posts/{post_id}` | 🔑* | Edit post content. *Own post or admin. |
| DELETE | `/forum/posts/{post_id}` | 🔑* | Delete post. *Own post or admin. |

### Reactions & Bookmarks

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/forum/posts/{post_id}/vote` | 🔑 | Cast UPVOTE or DOWNVOTE (or null to remove). |
| POST | `/forum/posts/{post_id}/heart` | 🔑 | Toggle legacy heart reaction. |
| POST | `/forum/posts/{post_id}/bookmark` | 🔑 | Toggle bookmark on a post. |
| GET | `/forum/bookmarks` | 🔑 | Paginated list of the current user's bookmarked posts. |

### Follow

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/forum/threads/{thread_id}/follow` | 🔑 | Toggle follow on a thread. |

### Read state

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/forum/threads/{thread_id}/mark-read` | 🔑 | Mark a thread as read up to a given post ID. |

### Reports (admin)

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/forum/posts/{post_id}/report` | 🔑 | Report a post. |
| GET | `/forum/reports` | 🛡️ | Paginated list of open/all reports. |
| PATCH | `/forum/reports/{report_id}/review` | 🛡️ | Mark a report as REVIEWED or DISMISSED. |
| DELETE | `/forum/reports/{report_id}` | 🛡️ | Delete a report. |

---

## Forum Media (`/forum/media`)

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/forum/media/upload` | 🔑 | Upload an image for use in forum posts. Returns CDN URL. Rate-limited. |

---

## Users (`/users`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/users/search` | 🔓 | Username prefix search for `@mention` autocomplete. Query: `q`, `limit`. |
| GET | `/users/leaderboard` | 🔓 | Paginated cred score leaderboard. |
| GET | `/users/{username}` | 🔓 | Public user profile (role, avatar, cred score, rank, favourites, public lists). |

---

## Notifications (`/notifications`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/notifications` | 🔑 | Paginated notifications. Query: `unread_only`. |
| GET | `/notifications/unread-count` | 🔑 | Unread badge count only (lightweight polling endpoint). |
| PATCH | `/notifications/{id}/read` | 🔑 | Mark one notification as read. |
| POST | `/notifications/read-all` | 🔑 | Mark all notifications as read. |

---

## Issues (`/issues`)

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/issues/` | 🔓 | Submit a bug report or feature request. Auth optional (anonymous allowed). |
| GET | `/issues/` | 🛡️ | List all issues for admin triage. |
| PATCH | `/issues/{issue_id}` | 🛡️ | Update issue status or admin notes. |

---

## Sitemap

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/sitemap.xml` | 🔓 | XML sitemap for SEO (series pages). |

---

## Response conventions

- **Pagination shape:** `{ items, page, page_size, total, total_pages, has_prev, has_next }`
- **Error shape:** `{ detail: "Human-readable message" }` with appropriate HTTP status
- **Auth errors:** 401 Unauthorized (missing/invalid token), 403 Forbidden (insufficient role)
- **Not found:** 404 with `detail` string
- **Conflict:** 409 (duplicate username/email on signup)
- **Rate limit:** 429 Too Many Requests
