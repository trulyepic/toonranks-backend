-- Phase 6: Notifications Table
-- Run this in pgAdmin on your AWS DB BEFORE merging/deploying the branch.

CREATE TABLE IF NOT EXISTS man_review.notifications (
    id          SERIAL PRIMARY KEY,
    user_id     INT NOT NULL REFERENCES man_review.users(id) ON DELETE CASCADE,
    kind        VARCHAR(30) NOT NULL,
    is_read     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at     TIMESTAMPTZ,
    thread_id   INT REFERENCES man_review.forum_threads(id) ON DELETE CASCADE,
    post_id     INT REFERENCES man_review.forum_posts(id)   ON DELETE CASCADE,
    actor_id    INT REFERENCES man_review.users(id)         ON DELETE SET NULL,
    summary     VARCHAR(300)
);

-- Fast lookup of a user's unread notifications (used by badge count endpoint)
CREATE INDEX IF NOT EXISTS ix_notifications_user_is_read
    ON man_review.notifications (user_id, is_read);

CREATE INDEX IF NOT EXISTS ix_notifications_created_at
    ON man_review.notifications (created_at DESC);

CREATE INDEX IF NOT EXISTS ix_notifications_thread_id
    ON man_review.notifications (thread_id);

CREATE INDEX IF NOT EXISTS ix_notifications_post_id
    ON man_review.notifications (post_id);
