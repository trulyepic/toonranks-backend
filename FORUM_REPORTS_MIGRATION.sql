-- Toon Ranks forum reports migration.
-- Creates the forum_reports table for post-level moderation reporting.
-- Run this once against the production database before deploying the
-- backend-forum-post-reporting branch.

CREATE TABLE IF NOT EXISTS man_review.forum_reports (
    id              SERIAL PRIMARY KEY,
    post_id         INTEGER NOT NULL REFERENCES man_review.forum_posts(id)    ON DELETE CASCADE,
    thread_id       INTEGER NOT NULL REFERENCES man_review.forum_threads(id)  ON DELETE CASCADE,
    reporter_id     INTEGER NOT NULL REFERENCES man_review.users(id)          ON DELETE CASCADE,
    reason          VARCHAR(500),
    status          VARCHAR(20) NOT NULL DEFAULT 'OPEN',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at     TIMESTAMPTZ,
    reviewed_by_id  INTEGER REFERENCES man_review.users(id) ON DELETE SET NULL,
    CONSTRAINT uq_forum_report_post_reporter UNIQUE (post_id, reporter_id)
);

CREATE INDEX IF NOT EXISTS idx_forum_reports_post_id     ON man_review.forum_reports (post_id);
CREATE INDEX IF NOT EXISTS idx_forum_reports_reporter_id ON man_review.forum_reports (reporter_id);
CREATE INDEX IF NOT EXISTS idx_forum_reports_status      ON man_review.forum_reports (status);
