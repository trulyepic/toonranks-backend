-- Phase 4: Forum Follow & Bookmark Tables
-- Run this on the Railway DB console BEFORE merging/deploying the branch.

-- ────────────────────────────────────────────────────────────
-- 1. Thread followers
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS man_review.forum_followers (
    id          SERIAL PRIMARY KEY,
    thread_id   INT NOT NULL REFERENCES man_review.forum_threads(id) ON DELETE CASCADE,
    user_id     INT NOT NULL REFERENCES man_review.users(id)         ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_forum_follower_thread_user UNIQUE (thread_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_forum_followers_thread_id ON man_review.forum_followers(thread_id);
CREATE INDEX IF NOT EXISTS ix_forum_followers_user_id   ON man_review.forum_followers(user_id);

-- ────────────────────────────────────────────────────────────
-- 2. Post bookmarks
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS man_review.forum_bookmarks (
    id          SERIAL PRIMARY KEY,
    post_id     INT NOT NULL REFERENCES man_review.forum_posts(id)    ON DELETE CASCADE,
    thread_id   INT NOT NULL REFERENCES man_review.forum_threads(id)  ON DELETE CASCADE,
    user_id     INT NOT NULL REFERENCES man_review.users(id)          ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_forum_bookmark_post_user UNIQUE (post_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_forum_bookmarks_post_id   ON man_review.forum_bookmarks(post_id);
CREATE INDEX IF NOT EXISTS ix_forum_bookmarks_thread_id ON man_review.forum_bookmarks(thread_id);
CREATE INDEX IF NOT EXISTS ix_forum_bookmarks_user_id   ON man_review.forum_bookmarks(user_id);
