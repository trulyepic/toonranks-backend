import math
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.routes.auth import get_db
from app.limiter import limiter
from app.models.user_model import User
from app.models.user_favourite import UserFavourite
from app.models.series_model import Series
from app.models.reading_list import ReadingList, ReadingListItem
from app.models.forum_model import ForumPost
from app.models.user_vote import UserVote

router = APIRouter(prefix="/users", tags=["users"])


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
    Only users with cred_score > 0 appear.
    """
    # Total ranked users (admins excluded)
    total_stmt = select(func.count(User.id)).where(
        User.cred_score > 0,
        User.role != "ADMIN",
    )
    total = int((await db.execute(total_stmt)).scalar_one() or 0)
    total_pages = max(1, math.ceil(total / page_size))

    # Page of ranked users with post counts and distinct series rated
    offset = (page - 1) * page_size
    stmt = (
        select(
            User,
            func.count(ForumPost.id).label("post_count"),
            func.count(func.distinct(UserVote.series_id)).label("series_rated"),
        )
        .outerjoin(ForumPost, ForumPost.author_id == User.id)
        .outerjoin(UserVote, UserVote.user_id == User.id)
        .where(User.cred_score > 0, User.role != "ADMIN")
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

    # ── Cred rank (None for admins and users with score 0) ───────────────
    cred_score = user.cred_score or 0
    rank: Optional[int] = None
    if cred_score > 0 and user.role != "ADMIN":
        rank_stmt = select(func.count(User.id)).where(
            User.cred_score > cred_score,
            User.role != "ADMIN",
        )
        users_above = int((await db.execute(rank_stmt)).scalar_one() or 0)
        rank = users_above + 1

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
    )
