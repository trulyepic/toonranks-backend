from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.routes.auth import get_db
from app.models.user_model import User
from app.models.user_favourite import UserFavourite
from app.models.series_model import Series
from app.models.reading_list import ReadingList, ReadingListItem

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
    favourites: List[PublicFavouriteOut]
    reading_lists: List[PublicReadingListOut]

    model_config = {"from_attributes": True}


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/{username}", response_model=PublicProfileOut)
async def get_public_profile(
    username: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Public profile for any user — no auth required.
    Returns username, role, avatar, join date, pinned favourites,
    and public reading lists.
    """
    stmt = select(User).where(User.username == username)
    user = (await db.execute(stmt)).scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{username}' not found.",
        )

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
        role=user.role,
        avatar_url=user.avatar_url,
        avatar_preset=user.avatar_preset,
        registered_at=user.registered_at,
        favourites=favourites,
        reading_lists=reading_lists,
    )
