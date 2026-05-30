-- Phase 7: Forum Read State Tracking
-- Run this in pgAdmin on your AWS DB BEFORE merging/deploying the branch.

CREATE TABLE IF NOT EXISTS man_review.forum_read_states (
    id                  SERIAL PRIMARY KEY,
    thread_id           INT NOT NULL REFERENCES man_review.forum_threads(id) ON DELETE CASCADE,
    user_id             INT NOT NULL REFERENCES man_review.users(id)         ON DELETE CASCADE,
    last_seen_post_id   INT          REFERENCES man_review.forum_posts(id)   ON DELETE SET NULL,
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_forum_read_state UNIQUE (thread_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_forum_read_states_thread_id ON man_review.forum_read_states (thread_id);
CREATE INDEX IF NOT EXISTS ix_forum_read_states_user_id   ON man_review.forum_read_states (user_id);
