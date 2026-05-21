-- Toon Ranks forum vote migration.
-- Run this once before deploying the backend that exposes upvote/downvote fields.

ALTER TABLE man_review.forum_posts
  ADD COLUMN IF NOT EXISTS upvote_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS downvote_count integer NOT NULL DEFAULT 0;

UPDATE man_review.forum_reactions
SET kind = 'UPVOTE'
WHERE kind = 'HEART';

UPDATE man_review.forum_posts post
SET
  upvote_count = counts.upvotes,
  downvote_count = counts.downvotes,
  heart_count = counts.upvotes
FROM (
  SELECT
    post.id AS post_id,
    COUNT(reaction.id) FILTER (WHERE reaction.kind = 'UPVOTE') AS upvotes,
    COUNT(reaction.id) FILTER (WHERE reaction.kind = 'DOWNVOTE') AS downvotes
  FROM man_review.forum_posts post
  LEFT JOIN man_review.forum_reactions reaction
    ON reaction.post_id = post.id
  GROUP BY post.id
) counts
WHERE post.id = counts.post_id;

ALTER TABLE man_review.forum_reactions
  ALTER COLUMN kind SET DEFAULT 'UPVOTE';
