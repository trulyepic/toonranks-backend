-- Cred Points migration.
-- Run this directly on the Railway DB BEFORE deploying the backend changes.
-- Otherwise all Rankers will have cred_score = 0 on launch.

-- Step 1: Add the column (existing rows get 0 by default)
ALTER TABLE man_review.users
    ADD COLUMN IF NOT EXISTS cred_score INTEGER NOT NULL DEFAULT 0;

-- Step 2: Backfill using the full Cred Points formula:
--   (forum_upvotes_received x 2) - (forum_downvotes_received x 1) + (series_rated_count x 1)
--   series_rated_count = distinct series the user has ever rated (any category)
UPDATE man_review.users u
SET cred_score = GREATEST(0,
    COALESCE((
        SELECT (SUM(fp.upvote_count) * 2) - SUM(fp.downvote_count)
        FROM man_review.forum_posts fp
        WHERE fp.author_id = u.id
    ), 0)
    +
    COALESCE((
        SELECT COUNT(DISTINCT uv.series_id)
        FROM man_review.user_votes uv
        WHERE uv.user_id = u.id
    ), 0)
);
