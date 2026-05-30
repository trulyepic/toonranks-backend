-- Toon Ranks forum thread columns migration.
-- Adds view_count and is_pinned to forum_threads.
-- Run this once against the production database before deploying the
-- backend-forum-quick-wins branch.

ALTER TABLE man_review.forum_threads
  ADD COLUMN IF NOT EXISTS view_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS is_pinned  BOOLEAN NOT NULL DEFAULT FALSE;

-- Index on is_pinned so ORDER BY is_pinned DESC is fast (sparse column, only a few rows ever pinned)
CREATE INDEX IF NOT EXISTS idx_forum_threads_is_pinned
  ON man_review.forum_threads (is_pinned)
  WHERE is_pinned = TRUE;
