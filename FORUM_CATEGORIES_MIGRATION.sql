-- Phase 5: Forum Categories
-- Run this in pgAdmin on your AWS DB BEFORE merging/deploying the branch.

-- ────────────────────────────────────────────────────────────
-- 1. Categories table
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS man_review.forum_categories (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL UNIQUE,
    slug        VARCHAR(100) NOT NULL UNIQUE,
    description VARCHAR(500),
    position    INTEGER NOT NULL DEFAULT 0,
    is_visible  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_forum_categories_slug ON man_review.forum_categories(slug);

-- ────────────────────────────────────────────────────────────
-- 2. Add category_id FK to forum_threads
-- ────────────────────────────────────────────────────────────
ALTER TABLE man_review.forum_threads
    ADD COLUMN IF NOT EXISTS category_id INTEGER
        REFERENCES man_review.forum_categories(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_forum_threads_category_id ON man_review.forum_threads(category_id);

-- ────────────────────────────────────────────────────────────
-- 3. Seed default categories
-- ────────────────────────────────────────────────────────────
INSERT INTO man_review.forum_categories (name, slug, description, position) VALUES
    ('General Discussion', 'general',       'Talk about anything Toon Ranks related',          0),
    ('Series Talk',        'series',        'Discuss specific series, share recommendations',  1),
    ('Site Feedback',      'feedback',      'Bug reports, feature requests, and suggestions',  2),
    ('Introductions',      'introductions', 'Introduce yourself to the community',             3)
ON CONFLICT (slug) DO NOTHING;
