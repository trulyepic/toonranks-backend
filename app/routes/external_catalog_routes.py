from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.deps.admin import require_admin
from app.models.series_detail import SeriesDetail
from app.models.series_model import Series, SeriesApprovalStatus, SeriesStatus
from app.models.user_model import User
from app.schemas.series_schemas import PendingSeriesOut, SeriesStatusEnum, SeriesTypeEnum
from app.utils.external_catalog import (
    AniListSort,
    ExternalTitleCandidate,
    candidate_title_values,
    discover_anilist_titles,
    search_anilist_titles,
    titles_match,
)

router = APIRouter(prefix="/external-catalog", tags=["external-catalog"])


class ExternalImportRequest(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    source: str = Field(pattern="^ANILIST$")
    external_id: str = Field(min_length=1, max_length=80)
    external_url: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=300)
    type: SeriesTypeEnum
    genre: str = Field(default="", max_length=500)
    synopsis: str = ""
    cover_url: str = Field(default="", max_length=1000)
    detail_cover_url: str = Field(default="", max_length=1000)
    author: str = Field(default="", max_length=300)
    artist: str = Field(default="", max_length=300)
    status: Optional[SeriesStatusEnum] = None
    title_aliases: list[str] = Field(default_factory=list)
    popularity: Optional[int] = None
    average_score: Optional[int] = None


class ExternalImportResponse(BaseModel):
    imported: bool
    duplicate: bool
    series: PendingSeriesOut


class ExternalBatchImportRequest(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    type: SeriesTypeEnum
    sort: AniListSort = "POPULARITY_DESC"
    page: int = Field(default=1, ge=1, le=20)
    page_size: int = Field(default=25, ge=1, le=50)
    genre: Optional[str] = Field(default=None, max_length=80)


class ExternalBatchImportResponse(BaseModel):
    imported: int
    duplicates: int
    skipped: int
    items: list[ExternalImportResponse]


def _pending_series_payload(series: Series, *, username: str, detail_ready: bool) -> dict:
    return {
        "id": series.id,
        "title": series.title,
        "genre": series.genre,
        "type": series.type,
        "author": series.author,
        "artist": series.artist,
        "status": series.status,
        "vote_count": series.vote_count or 0,
        "cover_url": series.cover_url,
        "approval_status": series.approval_status,
        "submitted_by_id": series.submitted_by_id,
        "submitted_by_username": username,
        "approved_by_id": series.approved_by_id,
        "approved_at": series.approved_at,
        "detail_ready": detail_ready,
        "external_source": series.external_source,
        "external_id": series.external_id,
        "external_url": series.external_url,
    }


def _candidate_titles(payload: "ExternalImportRequest") -> list[str]:
    return candidate_title_values(
        ExternalTitleCandidate(
            source=payload.source,
            external_id=payload.external_id,
            external_url=payload.external_url,
            title=payload.title,
            type=payload.type,
            genre=payload.genre,
            title_aliases=payload.title_aliases,
        )
    )


async def _find_existing(
    session: AsyncSession,
    *,
    source: str,
    external_id: str,
    payload: "ExternalImportRequest",
    series_type: str,
) -> Optional[Series]:
    existing_by_source = await session.scalar(
        select(Series).where(
            Series.external_source == source,
            Series.external_id == external_id,
        )
    )
    if existing_by_source:
        return existing_by_source

    existing_rows = (
        await session.execute(select(Series).where(Series.type == series_type))
    ).scalars().all()
    candidate_titles = _candidate_titles(payload)
    for existing in existing_rows:
        if any(titles_match(candidate_title, existing.title) for candidate_title in candidate_titles):
            return existing

    return None


async def _detail_ready(session: AsyncSession, series_id: int) -> bool:
    detail = await session.scalar(select(SeriesDetail).where(SeriesDetail.series_id == series_id))
    return bool(
        detail
        and (detail.synopsis or "").strip()
        and (detail.series_cover_url or "").strip()
    )


async def _create_pending_import(
    session: AsyncSession,
    payload: ExternalImportRequest,
    admin_user: User,
) -> Series:
    status_value = None
    if payload.status:
        status_value = SeriesStatus(payload.status)

    series = Series(
        title=payload.title.strip(),
        genre=payload.genre.strip(),
        type=payload.type,
        cover_url=payload.cover_url.strip(),
        author=payload.author.strip(),
        artist=payload.artist.strip(),
        status=status_value,
        external_source=payload.source.upper(),
        external_id=payload.external_id.strip(),
        external_url=payload.external_url.strip(),
        external_score=payload.average_score,
        external_popularity=payload.popularity,
        approval_status=SeriesApprovalStatus.PENDING.value,
        submitted_by_id=admin_user.id,
    )
    session.add(series)
    await session.flush()

    detail = SeriesDetail(
        series_id=series.id,
        synopsis=payload.synopsis.strip(),
        series_cover_url=(payload.detail_cover_url or payload.cover_url).strip(),
    )
    session.add(detail)
    return series


def _candidate_to_import_request(candidate: ExternalTitleCandidate) -> ExternalImportRequest:
    return ExternalImportRequest(**candidate.model_dump())


@router.get("/search", response_model=list[ExternalTitleCandidate])
async def search_external_catalog(
    query: str = Query(..., min_length=2, max_length=100),
    type: Optional[SeriesTypeEnum] = Query(None),
    page: int = Query(1, ge=1, le=10),
    page_size: int = Query(12, ge=1, le=25),
    _admin: User = Depends(require_admin),
):
    try:
        return await search_anilist_titles(
            query.strip(),
            page=page,
            per_page=page_size,
            series_type=type,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"External catalog search failed: {exc}",
        ) from exc


@router.get("/discover", response_model=list[ExternalTitleCandidate])
async def discover_external_catalog(
    type: SeriesTypeEnum = Query(...),
    sort: AniListSort = Query("POPULARITY_DESC"),
    page: int = Query(1, ge=1, le=20),
    page_size: int = Query(25, ge=1, le=50),
    genre: Optional[str] = Query(None, max_length=80),
    _admin: User = Depends(require_admin),
):
    try:
        return await discover_anilist_titles(
            series_type=type,
            sort=sort,
            page=page,
            per_page=page_size,
            genre=genre,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"External catalog discovery failed: {exc}",
        ) from exc


@router.post("/import", response_model=ExternalImportResponse, status_code=201)
async def import_external_title(
    payload: ExternalImportRequest,
    admin_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    source = payload.source.upper()
    external_id = payload.external_id.strip()

    existing = await _find_existing(
        session,
        source=source,
        external_id=external_id,
        payload=payload,
        series_type=payload.type,
    )
    if existing:
        return ExternalImportResponse(
            imported=False,
            duplicate=True,
            series=_pending_series_payload(
                existing,
                username=admin_user.username,
                detail_ready=await _detail_ready(session, existing.id),
            ),
        )

    series = await _create_pending_import(session, payload, admin_user)
    await session.commit()
    await session.refresh(series)

    return ExternalImportResponse(
        imported=True,
        duplicate=False,
        series=_pending_series_payload(
            series,
            username=admin_user.username,
            detail_ready=bool(
                payload.synopsis.strip()
                and (payload.detail_cover_url or payload.cover_url).strip()
            ),
        ),
    )


@router.post("/import-batch", response_model=ExternalBatchImportResponse)
async def import_external_batch(
    payload: ExternalBatchImportRequest,
    admin_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        candidates = await discover_anilist_titles(
            series_type=payload.type,
            sort=payload.sort,
            page=payload.page,
            per_page=payload.page_size,
            genre=payload.genre,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"External catalog batch import failed: {exc}",
        ) from exc

    imported = 0
    duplicates = 0
    skipped = 0
    items: list[ExternalImportResponse] = []

    for candidate in candidates:
        if not candidate.title.strip() or not candidate.external_id.strip():
            skipped += 1
            continue

        import_payload = _candidate_to_import_request(candidate)
        existing = await _find_existing(
            session,
            source=import_payload.source.upper(),
            external_id=import_payload.external_id.strip(),
            payload=import_payload,
            series_type=import_payload.type,
        )
        if existing:
            duplicates += 1
            items.append(
                ExternalImportResponse(
                    imported=False,
                    duplicate=True,
                    series=_pending_series_payload(
                        existing,
                        username=admin_user.username,
                        detail_ready=await _detail_ready(session, existing.id),
                    ),
                )
            )
            continue

        series = await _create_pending_import(session, import_payload, admin_user)
        imported += 1
        items.append(
            ExternalImportResponse(
                imported=True,
                duplicate=False,
                series=_pending_series_payload(
                    series,
                    username=admin_user.username,
                    detail_ready=bool(
                        import_payload.synopsis.strip()
                        and (import_payload.detail_cover_url or import_payload.cover_url).strip()
                    ),
                ),
            )
        )

    if imported:
        await session.commit()
    else:
        await session.rollback()

    return ExternalBatchImportResponse(
        imported=imported,
        duplicates=duplicates,
        skipped=skipped,
        items=items,
    )
