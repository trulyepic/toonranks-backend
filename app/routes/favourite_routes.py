from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.routes.auth import get_db
from app.models.user_favourite import UserFavourite
from app.models.series_model import Series
from app.utils.token_utils import get_current_user
from app.models.user_model import User

router = APIRouter(prefix="/me/favourites", tags=["favourites"])

MAX_FAVOURITES = 6


# ── Schemas ──────────────────────────────────────────────────────────────────

class FavouriteSeriesOut(BaseModel):
    series_id: int
    position: int
    title: str
    cover_url: Optional[str]
    type: Optional[str]

    model_config = {"from_attributes": True}


class ReplaceFavouritesRequest(BaseModel):
    series_ids: List[int]

    @field_validator("series_ids")
    @classmethod
    def validate_length(cls, v: List[int]) -> List[int]:
        if len(v) > MAX_FAVOURITES:
            raise ValueError(f"You can pin at most {MAX_FAVOURITES} series.")
        if len(v) != len(set(v)):
            raise ValueError("Duplicate series IDs are not allowed.")
        return v


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("", response_model=List[FavouriteSeriesOut])
async def get_my_favourites(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(UserFavourite, Series)
        .join(Series, Series.id == UserFavourite.series_id)
        .where(UserFavourite.user_id == current_user.id)
        .order_by(UserFavourite.position.asc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        FavouriteSeriesOut(
            series_id=fav.series_id,
            position=fav.position,
            title=series.title,
            cover_url=series.cover_url,
            type=series.type.value if series.type else None,
        )
        for fav, series in rows
    ]


@router.put("", response_model=List[FavouriteSeriesOut])
async def replace_my_favourites(
    payload: ReplaceFavouritesRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    series_ids = payload.series_ids

    # Verify all requested series exist
    if series_ids:
        stmt = select(Series).where(Series.id.in_(series_ids))
        found = (await db.execute(stmt)).scalars().all()
        found_ids = {s.id for s in found}
        missing = set(series_ids) - found_ids
        if missing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Series not found: {sorted(missing)}",
            )

    # Replace all existing favourites atomically
    await db.execute(
        delete(UserFavourite).where(UserFavourite.user_id == current_user.id)
    )
    for position, series_id in enumerate(series_ids):
        db.add(
            UserFavourite(
                user_id=current_user.id,
                series_id=series_id,
                position=position,
            )
        )
    await db.commit()

    # Return the updated list with series info
    stmt = (
        select(UserFavourite, Series)
        .join(Series, Series.id == UserFavourite.series_id)
        .where(UserFavourite.user_id == current_user.id)
        .order_by(UserFavourite.position.asc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        FavouriteSeriesOut(
            series_id=fav.series_id,
            position=fav.position,
            title=series.title,
            cover_url=series.cover_url,
            type=series.type.value if series.type else None,
        )
        for fav, series in rows
    ]


@router.delete("/{series_id}", response_model=List[FavouriteSeriesOut])
async def remove_my_favourite(
    series_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        delete(UserFavourite).where(
            UserFavourite.user_id == current_user.id,
            UserFavourite.series_id == series_id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Favourite not found.")

    # Re-compact positions (0, 1, 2, …) after removal
    stmt = (
        select(UserFavourite)
        .where(UserFavourite.user_id == current_user.id)
        .order_by(UserFavourite.position.asc())
    )
    remaining = (await db.execute(stmt)).scalars().all()
    for new_pos, fav in enumerate(remaining):
        fav.position = new_pos

    await db.commit()

    # Return updated list with series info
    stmt = (
        select(UserFavourite, Series)
        .join(Series, Series.id == UserFavourite.series_id)
        .where(UserFavourite.user_id == current_user.id)
        .order_by(UserFavourite.position.asc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        FavouriteSeriesOut(
            series_id=fav.series_id,
            position=fav.position,
            title=series.title,
            cover_url=series.cover_url,
            type=series.type.value if series.type else None,
        )
        for fav, series in rows
    ]
