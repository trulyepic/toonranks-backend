
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    func,
    UniqueConstraint, Boolean,
text
)
from sqlalchemy.orm import relationship
from app.database import Base

SCHEMA = "man_review"


class ForumCategory(Base):
    """Top-level board that threads are organised into (e.g. General Discussion, Series Talk)."""
    __tablename__ = "forum_categories"
    __table_args__ = ({"schema": SCHEMA},)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    slug = Column(String(100), nullable=False, unique=True, index=True)
    description = Column(String(500), nullable=True)
    position = Column(Integer, nullable=False, server_default="0", default=0)
    is_visible = Column(Boolean, nullable=False, server_default=text("true"), default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    threads = relationship("ForumThread", back_populates="category")


class ForumThread(Base):
    __tablename__ = "forum_threads"
    __table_args__ = (
        # add any extra constraints here if needed
        {"schema": SCHEMA},
    )

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False, index=True)

    # user is in man_review.users
    author_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    category_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # denormalized counters for faster thread list
    post_count = Column(Integer, nullable=False, server_default="0")
    last_post_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    locked = Column(Boolean, nullable=False, server_default=text("false"))
    latest_first = Column(Boolean, nullable=False, server_default="false")
    view_count = Column(Integer, nullable=False, server_default="0", default=0)
    is_pinned = Column(Boolean, nullable=False, server_default=text("false"), default=False)

    # relationships
    category = relationship("ForumCategory", back_populates="threads")
    posts = relationship(
        "ForumPost",
        back_populates="thread",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    series_refs = relationship(
        "ForumSeriesRef",
        back_populates="thread",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ForumPost(Base):
    __tablename__ = "forum_posts"
    __table_args__ = ({"schema": SCHEMA},)

    id = Column(Integer, primary_key=True, index=True)

    thread_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    parent_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_posts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    content_markdown = Column(Text, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    # Legacy heart_count is kept during the web/mobile transition. New clients
    # should use upvote_count/downvote_count and ForumReaction.kind.
    heart_count = Column(Integer, nullable=False, server_default="0")
    upvote_count = Column(Integer, nullable=False, server_default="0")
    downvote_count = Column(Integer, nullable=False, server_default="0")

    # relationships
    thread = relationship("ForumThread", back_populates="posts")
    series_refs = relationship(
        "ForumSeriesRef",
        back_populates="post",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    parent = relationship("ForumPost", remote_side=[id], backref="replies")


class ForumSeriesRef(Base):
    __tablename__ = "forum_series_refs"
    __table_args__ = (
        # Optional: prevent duplicate (thread_id, post_id, series_id) triples
        # UniqueConstraint("thread_id", "post_id", "series_id", name="uq_forum_series_ref"),
        {"schema": SCHEMA},
    )

    id = Column(Integer, primary_key=True, index=True)

    thread_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Can be null when the reference is attached to the thread header (not a specific post)
    post_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_posts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Points to your Series table
    series_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.series.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # relationships
    thread = relationship("ForumThread", back_populates="series_refs")
    post = relationship("ForumPost", back_populates="series_refs")


class ForumReaction(Base):
    __tablename__ = "forum_reactions"
    __table_args__ = (
        UniqueConstraint("post_id", "user_id", name="uq_forum_reaction_post_user"),
        {"schema": SCHEMA},
    )

    id = Column(Integer, primary_key=True)
    post_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Valid values: UPVOTE, DOWNVOTE. Legacy HEART rows should be migrated to UPVOTE.
    kind = Column(String(20), nullable=False, server_default="UPVOTE")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ForumReport(Base):
    __tablename__ = "forum_reports"
    __table_args__ = (
        UniqueConstraint("post_id", "reporter_id", name="uq_forum_report_post_reporter"),
        {"schema": SCHEMA},
    )

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    thread_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reporter_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reason = Column(String(500), nullable=True)
    # OPEN → admin has not reviewed; REVIEWED → action taken; DISMISSED → no action needed
    status = Column(String(20), nullable=False, server_default="OPEN")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"),
        nullable=True,
    )


class ForumFollower(Base):
    """Tracks which users are following which threads (for thread-reply notifications)."""
    __tablename__ = "forum_followers"
    __table_args__ = (
        UniqueConstraint("thread_id", "user_id", name="uq_forum_follower_thread_user"),
        {"schema": SCHEMA},
    )

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ForumBookmark(Base):
    """Tracks individual posts a user has bookmarked to revisit later."""
    __tablename__ = "forum_bookmarks"
    __table_args__ = (
        UniqueConstraint("post_id", "user_id", name="uq_forum_bookmark_post_user"),
        {"schema": SCHEMA},
    )

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    thread_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ForumReadState(Base):
    """Tracks the last post a user has seen in each thread for unread-badge support."""
    __tablename__ = "forum_read_states"
    __table_args__ = (
        UniqueConstraint("thread_id", "user_id", name="uq_forum_read_state"),
        {"schema": SCHEMA},
    )

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    last_seen_post_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_posts.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
