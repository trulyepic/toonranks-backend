import math
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.routes.auth import get_db
from app.limiter import limiter
from app.models.user_model import User
from app.models.user_favourite import UserFavourite
from app.models.series_model import Series
from app.models.reading_list import ReadingList, ReadingListItem
from app.models.forum_model import ForumPost, ForumThread
from app.models.user_vote import UserVote

router = APIRouter(prefix="/users", tags=["users"])

# Caps for the public profile lists so the payload stays small. The owner's own
# Account page (paginated endpoints) remains the place to browse everything.
PUBLIC_RATINGS_LIMIT = 30
PUBLIC_POSTS_LIMIT = 20
POST_EXCERPT_CHARS = 200


def _excerpt(markdown: str) -> str:
    """A short, plain-ish preview of a forum post for the public profile."""
    text = " ".join((markdown or "").split())
    if len(text) <= POST_EXCERPT_CHARS:
        return text
    return text[:POST_EXCERPT_CHARS].rstrip() + "…"


# ── Schemas ───────────────────────────────────────────────────────────────────

class PublicFavouriteOut(BaseModel):
    series_id: int
    position: int
    title: str
    cover_url: Optional[str]
    type: Optional[str]

    model_config = {"from_attributes": True}


class PublicReadingListOut(BaseModel):
    name: str
    item_count: int
    share_token: str

    model_config = {"from_attributes": True}


class PublicSeriesRatingOut(BaseModel):
    series_id: int
    title: Optional[str]
    cover_url: Optional[str]
    type: Optional[str]
    score: float  # the user's own average across the categories they scored

    model_config = {"from_attributes": True}


class PublicForumPostOut(BaseModel):
    post_id: int
    thread_id: int
    thread_title: Optional[str]
    excerpt: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PublicProfileOut(BaseModel):
    username: str
    role: str
    avatar_url: Optional[str]
    avatar_preset: Optional[str]
    registered_at: Optional[datetime]
    cred_score: int
    rank: Optional[int]
    post_count: int
    favourites: List[PublicFavouriteOut]
    reading_lists: List[PublicReadingListOut]
    # None when the user has hidden that section (vs [] meaning "public but empty").
    ratings: Optional[List[PublicSeriesRatingOut]] = None
    posts: Optional[List[PublicForumPostOut]] = None

    model_config = {"from_attributes": True}


class LeaderboardUserOut(BaseModel):
    rank: int
    username: str
    role: str
    avatar_url: Optional[str]
    avatar_preset: Optional[str]
    cred_score: int
    post_count: int
    series_rated: int

    model_config = {"from_attributes": True}


class LeaderboardPageOut(BaseModel):
    items: List[LeaderboardUserOut]
    total: int
    page: int
    page_size: int
    total_pages: int


# ── Routes ────────────────────────────────────────────────────────────────────

class UserSearchResult(BaseModel):
    username: str
    avatar_url: Optional[str] = None
    avatar_preset: Optional[str] = None


@router.get("/search", response_model=List[UserSearchResult])
@limiter.limit("30/minute")
async def search_users(
    request: Request,
    q: str = Query(..., min_length=1, max_length=30),
    limit: int = Query(8, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    """
    Lightweight username prefix search for @-mention autocomplete.
    Returns matching users ordered by username.
    """
    rows = (await db.execute(
        select(User.username, User.avatar_url, User.avatar_preset)
        .where(User.username.ilike(f"{q}%"))
        .order_by(User.username.asc())
        .limit(limit)
    )).all()

    return [
        UserSearchResult(
            username=row.username,
            avatar_url=row.avatar_url,
            avatar_preset=row.avatar_preset,
        )
        for row in rows
    ]


@router.get("/leaderboard", response_model=LeaderboardPageOut)
async def get_leaderboard(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    Ranked list of Rankers ordered by cred_score descending.
    All non-admin users appear; new users with no activity (cred_score 0) sort to
    the bottom and climb as they participate. Admins are excluded from ranking.
    """
    # Total ranked users (admins excluded)
    total_stmt = select(func.count(User.id)).where(
        User.role != "ADMIN",
    )
    total = int((await db.execute(total_stmt)).scalar_one() or 0)
    total_pages = max(1, math.ceil(total / page_size))

    # Page of users with post counts and distinct series rated. Ties (e.g. all the
    # 0-cred newcomers) break by id ascending, so order is stable across pages.
    offset = (page - 1) * page_size
    stmt = (
        select(
            User,
            func.count(ForumPost.id).label("post_count"),
            func.count(func.distinct(UserVote.series_id)).label("series_rated"),
        )
        .outerjoin(ForumPost, ForumPost.author_id == User.id)
        .outerjoin(UserVote, UserVote.user_id == User.id)
        .where(User.role != "ADMIN")
        .group_by(User.id)
        .order_by(User.cred_score.desc(), User.id.asc())
        .offset(offset)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).all()

    items = [
        LeaderboardUserOut(
            rank=offset + i + 1,
            username=user.username,
            role=user.role or "GENERAL",
            avatar_url=user.avatar_url,
            avatar_preset=user.avatar_preset,
            cred_score=user.cred_score or 0,
            post_count=int(post_count or 0),
            series_rated=int(series_rated or 0),
        )
        for i, (user, post_count, series_rated) in enumerate(rows)
    ]

    return LeaderboardPageOut(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{username}", response_model=PublicProfileOut)
async def get_public_profile(
    username: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Public profile for any user — no auth required.
    Returns username, role, avatar, join date, Cred Points, rank,
    post count, pinned favourites, and public reading lists.
    """
    stmt = select(User).where(User.username == username)
    user = (await db.execute(stmt)).scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{username}' not found.",
        )

    # ── Cred rank (None only for admins, who are excluded from ranking) ──────
    # Every non-admin user is ranked, including newcomers with cred_score 0 (they
    # sit at the bottom and climb as they participate). Uses the same tie-break as
    # the leaderboard: higher cred first, then smaller id.
    cred_score = user.cred_score or 0
    rank: Optional[int] = None
    if user.role != "ADMIN":
        rank_stmt = select(func.count(User.id)).where(
            User.role != "ADMIN",
            or_(
                User.cred_score > cred_score,
                and_(User.cred_score == cred_score, User.id < user.id),
            ),
        )
        users_before = int((await db.execute(rank_stmt)).scalar_one() or 0)
        rank = users_before + 1

    # ── Post count ────────────────────────────────────────────────────────
    post_count_stmt = select(func.count(ForumPost.id)).where(
        ForumPost.author_id == user.id
    )
    post_count = int((await db.execute(post_count_stmt)).scalar_one() or 0)

    # ── Pinned favourites ─────────────────────────────────────────────────
    fav_stmt = (
        select(UserFavourite, Series)
        .join(Series, Series.id == UserFavourite.series_id)
        .where(UserFavourite.user_id == user.id)
        .order_by(UserFavourite.position.asc())
    )
    fav_rows = (await db.execute(fav_stmt)).all()
    favourites = [
        PublicFavouriteOut(
            series_id=fav.series_id,
            position=fav.position,
            title=series.title,
            cover_url=series.cover_url,
            type=series.type.value if series.type else None,
        )
        for fav, series in fav_rows
    ]

    # ── Public reading lists (only is_public=True) ─────────────────────────
    rl_stmt = (
        select(
            ReadingList,
            func.count(ReadingListItem.id).label("item_count"),
        )
        .outerjoin(ReadingListItem, ReadingListItem.list_id == ReadingList.id)
        .where(
            ReadingList.user_id == user.id,
            ReadingList.is_public.is_(True),
        )
        .group_by(ReadingList.id)
        .order_by(ReadingList.name.asc())
    )
    rl_rows = (await db.execute(rl_stmt)).all()
    reading_lists = [
        PublicReadingListOut(
            name=rl.name,
            item_count=item_count,
            share_token=str(rl.share_token),
        )
        for rl, item_count in rl_rows
    ]

    # ── Rated series (only if the user keeps ratings public) ───────────────
    # One row per series the user has voted on, with their own average score
    # across the categories they scored. Capped to the most recent set.
    ratings: Optional[List[PublicSeriesRatingOut]] = None
    if user.public_ratings:
        rating_stmt = (
            select(
                UserVote.series_id,
                func.avg(UserVote.score).label("avg_score"),
                Series.title,
                Series.cover_url,
                Series.type,
            )
            .join(Series, Series.id == UserVote.series_id)
            .where(UserVote.user_id == user.id)
            .group_by(UserVote.series_id, Series.title, Series.cover_url, Series.type)
            .order_by(UserVote.series_id.desc())
            .limit(PUBLIC_RATINGS_LIMIT)
        )
        rating_rows = (await db.execute(rating_stmt)).all()
        ratings = [
            PublicSeriesRatingOut(
                series_id=series_id,
                title=title,
                cover_url=cover_url,
                type=stype.value if stype else None,
                score=round(float(avg_score), 1),
            )
            for series_id, avg_score, title, cover_url, stype in rating_rows
        ]

    # ── Forum posts (only if the user keeps posts public) ──────────────────
    posts: Optional[List[PublicForumPostOut]] = None
    if user.public_posts:
        post_stmt = (
            select(ForumPost, ForumThread.title)
            .join(ForumThread, ForumThread.id == ForumPost.thread_id)
            .where(ForumPost.author_id == user.id)
            .order_by(ForumPost.created_at.desc())
            .limit(PUBLIC_POSTS_LIMIT)
        )
        post_rows = (await db.execute(post_stmt)).all()
        posts = [
            PublicForumPostOut(
                post_id=post.id,
                thread_id=post.thread_id,
                thread_title=thread_title,
                excerpt=_excerpt(post.content_markdown),
                created_at=post.created_at,
            )
            for post, thread_title in post_rows
        ]

    return PublicProfileOut(
        username=user.username,
        role=user.role or "GENERAL",
        avatar_url=user.avatar_url,
        avatar_preset=user.avatar_preset,
        registered_at=user.registered_at,
        cred_score=cred_score,
        rank=rank,
        post_count=post_count,
        favourites=favourites,
        reading_lists=reading_lists,
        ratings=ratings,
        posts=posts,
    )
