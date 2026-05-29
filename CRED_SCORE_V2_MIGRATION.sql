-- Cred Points formula v2 — full recalculation.
-- Run this on the Railway RDS BEFORE deploying the updated backend.
-- It recalculates every user's cred_score from scratch using the new formula.
--
-- Formula:
--   (forum_upvotes_received × 2)
-- - (forum_downvotes_received × 1)
-- + (threads_created × 2)
-- + (replies_posted × 1)         -- replies only, NOT the first/OP post of each thread
-- + (series_rated × 1)           -- distinct series rated, any category

UPDATE man_review.users u
SET cred_score = GREATEST(0,

    -- Upvotes received × 2  minus  downvotes received × 1
    COALESCE((
        SELECT (SUM(fp.upvote_count) * 2) - SUM(fp.downvote_count)
        FROM man_review.forum_posts fp
        WHERE fp.author_id = u.id
    ), 0)

    +

    -- Thread creation × 2
    COALESCE((
        SELECT COUNT(*) * 2
        FROM man_review.forum_threads ft
        WHERE ft.author_id = u.id
    ), 0)

    +

    -- Replies × 1  (posts that are NOT the first/OP post of their thread)
    COALESCE((
        SELECT COUNT(*)
        FROM man_review.forum_posts fp
        WHERE fp.author_id = u.id
          AND (fp.thread_id, fp.id) NOT IN (
              SELECT thread_id, MIN(id)
              FROM man_review.forum_posts
              GROUP BY thread_id
          )
    ), 0)

    +

    -- Series rated × 1 (distinct series only)
    COALESCE((
        SELECT COUNT(DISTINCT uv.series_id)
        FROM man_review.user_votes uv
        WHERE uv.user_id = u.id
    ), 0)

);
