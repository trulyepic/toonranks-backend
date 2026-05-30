from __future__ import annotations

from pydantic import BaseModel, Field
from typing import List, Literal, Optional


class ForumCategoryOut(BaseModel):
    id: int
    name: str
    slug: str
    description: Optional[str] = None
    position: int = 0
    thread_count: int = 0


class CreateCategoryIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    description: Optional[str] = Field(default=None, max_length=500)
    position: Optional[int] = 0


class UpdateCategoryIn(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    slug: Optional[str] = Field(default=None, min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    description: Optional[str] = Field(default=None, max_length=500)
    position: Optional[int] = None
    is_visible: Optional[bool] = None


class SeriesRefOut(BaseModel):
    series_id: int
    title: Optional[str] = None
    cover_url: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None


class ForumPostOut(BaseModel):
    id: int
    thread_id: int = 0
    author_username: Optional[str] = None
    author_role: Optional[str] = None
    author_avatar_url: Optional[str] = None
    author_avatar_preset: Optional[str] = "blue"
    content_markdown: str
    created_at: str
    updated_at: str
    series_refs: List[SeriesRefOut] = []
    parent_id: Optional[int] = None
    upvote_count: int = 0
    downvote_count: int = 0
    viewer_vote: Optional[str] = None
    heart_count: int = 0
    viewer_has_hearted: bool = False
    viewer_has_bookmarked: bool = False  # True when the authenticated viewer has bookmarked this post


class ForumThreadOut(BaseModel):
    id: int
    title: str
    author_username: Optional[str] = None
    author_role: Optional[str] = None
    author_avatar_url: Optional[str] = None
    author_avatar_preset: Optional[str] = "blue"
    created_at: str
    updated_at: str
    post_count: int
    last_post_at: str
    series_refs: List[SeriesRefOut] = []
    locked: bool = False
    latest_first: bool = False
    is_pinned: bool = False
    view_count: int = 0
    viewer_is_following: bool = False  # True when the authenticated viewer follows this thread
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    has_unread: bool = False        # True when viewer has unread posts since last mark-read
    unread_count: int = 0           # Number of posts since last mark-read (0 if no read state)


class CreateThreadIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    first_post_markdown: str = Field(min_length=1)
    series_ids: List[int] = []
    category_id: Optional[int] = None



class CreatePostIn(BaseModel):
    content_markdown: str = Field(min_length=1)
    series_ids: List[int] = Field(default_factory=list)   # <— safer default
    parent_id: Optional[int] = None

class ThreadSettingsIn(BaseModel):
    latest_first: Optional[bool] = None


class UpdatePostIn(BaseModel):
    content_markdown: str
    series_ids: List[int] = []

class UpdateThreadIn(BaseModel):
    # All optional so the client can send only what changed
    title: Optional[str] = Field(default=None, min_length=3, max_length=200)
    first_post_markdown: Optional[str] = Field(default=None, min_length=1)
    # Optional: only replace header refs when provided
    series_ids: Optional[List[int]] = None
    category_id: Optional[int] = None  # pass 0 or null to unset


class ForumReportIn(BaseModel):
    reason: Optional[str] = None  # optional free-text, max 500 chars

class ForumReportReviewIn(BaseModel):
    status: Literal["REVIEWED", "DISMISSED"]

class ForumReportOut(BaseModel):
    id: int
    post_id: int
    thread_id: int
    reporter_username: Optional[str] = None
    reason: Optional[str] = None
    status: str
    created_at: str
    reviewed_at: Optional[str] = None
    reviewed_by_username: Optional[str] = None
    # Snapshot of the reported post so admins have context without a separate fetch
    post_excerpt: Optional[str] = None
    thread_title: Optional[str] = None

class ForumReportsPageOut(BaseModel):
    items: List[ForumReportOut]
    page: int
    page_size: int
    total: int
    total_pages: int
    has_prev: bool
    has_next: bool


class PageOut(BaseModel):
    items: List[ForumThreadOut]
    page: int
    page_size: int
    total: int
    total_pages: int
    has_prev: bool
    has_next: bool
    sort: Optional[str] = "activity"


class PostsPageOut(BaseModel):
    items: List[ForumPostOut]
    page: int
    page_size: int
    total: int
    total_pages: int
    has_prev: bool
    has_next: bool


class ThreadPostsPageOut(BaseModel):
    thread: ForumThreadOut
    posts: List[ForumPostOut]         # OP first, then this page's roots + their descendants
    page: int
    page_size: int
    total_top_level: int              # number of top-level replies (excludes OP)
    total_pages: int
    has_prev: bool
    has_next: bool


class MarkReadIn(BaseModel):
    last_seen_post_id: int


class MarkReadOut(BaseModel):
    thread_id: int
    last_seen_post_id: int
    last_seen_at: str


class FollowToggleOut(BaseModel):
    following: bool
    follower_count: int


class BookmarkToggleOut(BaseModel):
    bookmarked: bool
