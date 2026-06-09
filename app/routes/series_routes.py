from decimal import Decimal
from typing import List, Optional
from sqlalchemy import select, and_, or_, delete

from fastapi import APIRouter, UploadFile, File, Depends, Request, Form
from sqlalchemy import cast, String
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import AsyncSessionLocal, get_async_session
from app.models.series_detail import SeriesDetail
from app.models.series_model import Series, SeriesType, SeriesStatus, SeriesApprovalStatus
from app.models.user_model import User
from app.models.user_vote import UserVote
from app.schemas.series_schemas import SeriesCreate, SeriesOut, RankedSeriesOut, PendingSeriesOut
from app.s3 import upload_to_s3, delete_from_s3
from urllib.parse import urlparse
from fastapi import Query, HTTPException
from app.deps.admin import require_admin, require_series_submitter, can_submit_series, is_admin
from app.utils.token_utils import get_current_user
from datetime import datetime, timezone



def extract_s3_key(cover_url: str) -> str:
    parsed = urlparse(cover_url)
    return parsed.path.lstrip("/")
router = APIRouter()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

@router.delete("/series/{series_id}", status_code=204)
async def delete_series(
    series_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    # Fetch the series record
    result = await db.execute(select(Series).where(Series.id == series_id))
    series = result.scalar_one_or_none()

    if not series:
        raise HTTPException(status_code=404, detail="Series not found")

    # Extract S3 object key from URL and delete it
    if series.cover_url:
        try:
            key = extract_s3_key(series.cover_url)
            delete_from_s3(key)
        except Exception as e:
            print(f"Warning: Failed to delete image from S3: {e}")

    detail_result = await db.execute(select(SeriesDetail).where(SeriesDetail.series_id == series_id))
    detail = detail_result.scalar_one_or_none()
    if detail and detail.series_cover_url:
        try:
            detail_key = extract_s3_key(detail.series_cover_url)
            delete_from_s3(detail_key)
        except Exception as e:
            print(f"Warning: Failed to delete detail image from S3: {e}")

    await db.execute(delete(UserVote).where(UserVote.series_id == series_id))

    await db.delete(series)
    await db.commit()

@router.post("/series/", response_model=SeriesOut)
async def create_series(
    series: SeriesCreate = Depends(SeriesCreate.as_form),
    cover: UploadFile = File(...),
    current_user: User = Depends(require_series_submitter),
    db: AsyncSession = Depends(get_db)
):
    image_url = upload_to_s3(cover.file, cover.filename, cover.content_type, folder=series.title)

    new_series = Series(
        title=series.title,
        genre=series.genre,
        type=series.type.name,  # Convert Enum to string
        cover_url=image_url,
        author=series.author,
        artist=series.artist,
        status=SeriesStatus(series.status.value) if series.status else None,
        approval_status=SeriesApprovalStatus.DRAFT.value,
        submitted_by_id=current_user.id,
        approved_by_id=None,
        approved_at=None,
    )

    db.add(new_series)
    await db.commit()
    await db.refresh(new_series)
    return new_series


@router.get("/series/", response_model=list[SeriesOut])
async def list_series(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Series).where(Series.approval_status == SeriesApprovalStatus.APPROVED.value)
    )
    return result.scalars().all()


@router.put("/series/{series_id}", response_model=SeriesOut)
async def update_series(
    series_id: int,
    title: Optional[str] = Form(None),
    genre: Optional[str] = Form(None),
    type: Optional[SeriesType] = Form(None),
    author: Optional[str] = Form(None),
    artist: Optional[str] = Form(None),
    status: Optional[SeriesStatus] = Form(None),
    cover: Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session)
):
    # 1) Load row
    result = await session.execute(select(Series).where(Series.id == series_id))
    series = result.scalars().first()
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")

    is_owner_of_pending = (
        can_submit_series(current_user)
        and series.submitted_by_id == current_user.id
        and series.approval_status != SeriesApprovalStatus.APPROVED.value
    )
    if not (is_admin(current_user) or is_owner_of_pending):
        raise HTTPException(
            status_code=403,
            detail="You cannot edit this title"
        )

    payload = {
        "title": title,
        "genre": genre,
        "type": type,
        "author": author,
        "artist": artist,
        "status": status,
    }

    for field, value in payload.items():
        if value is not None:
            setattr(series, field, value)

    if cover is not None and cover.filename:
        if series.cover_url:
            try:
                delete_from_s3(extract_s3_key(series.cover_url))
            except Exception as exc:
                print(f"Warning: Failed to delete old series cover from S3: {exc}")
        series.cover_url = upload_to_s3(
            cover.file,
            cover.filename,
            cover.content_type,
            folder=series.title or str(series.id),
        )

    await session.commit()
    await session.refresh(series)
    return series


@router.get("/series/pending", response_model=list[PendingSeriesOut])
async def list_pending_series(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Series).where(Series.approval_status == SeriesApprovalStatus.PENDING.value).order_by(Series.id.desc())
    )
    rows = result.scalars().all()
    detail_map = {}
    if rows:
        detail_result = await db.execute(
            select(SeriesDetail.series_id, SeriesDetail.synopsis, SeriesDetail.series_cover_url).where(
                SeriesDetail.series_id.in_([row.id for row in rows])
            )
        )
        detail_map = {
            series_id: bool((synopsis or "").strip() and (series_cover_url or "").strip())
            for series_id, synopsis, series_cover_url in detail_result.all()
        }

    submitter_ids = {row.submitted_by_id for row in rows if row.submitted_by_id}
    username_by_id = {}
    if submitter_ids:
        users_result = await db.execute(
            select(User.id, User.username).where(User.id.in_(submitter_ids))
        )
        username_by_id = {uid: username for uid, username in users_result.all()}

    payload = []
    for row in rows:
        payload.append({
            "id": row.id,
            "title": row.title,
            "genre": row.genre,
            "type": row.type,
            "author": row.author,
            "artist": row.artist,
            "status": row.status,
            "vote_count": row.vote_count or 0,
            "cover_url": row.cover_url,
            "approval_status": row.approval_status,
            "submitted_by_id": row.submitted_by_id,
            "submitted_by_username": username_by_id.get(row.submitted_by_id),
            "approved_by_id": row.approved_by_id,
            "approved_at": row.approved_at,
            "detail_ready": detail_map.get(row.id, False),
        })
    return payload


@router.get("/series/submissions/mine", response_model=list[PendingSeriesOut])
async def list_my_submissions(
    current_user: User = Depends(require_series_submitter),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Series)
        .where(Series.submitted_by_id == current_user.id)
        .order_by(Series.id.desc())
    )
    rows = result.scalars().all()
    detail_map = {}
    if rows:
        detail_result = await db.execute(
            select(SeriesDetail.series_id, SeriesDetail.synopsis, SeriesDetail.series_cover_url).where(
                SeriesDetail.series_id.in_([row.id for row in rows])
            )
        )
        detail_map = {
            series_id: bool((synopsis or "").strip() and (series_cover_url or "").strip())
            for series_id, synopsis, series_cover_url in detail_result.all()
        }

    payload = []
    for row in rows:
        payload.append({
            "id": row.id,
            "title": row.title,
            "genre": row.genre,
            "type": row.type,
            "author": row.author,
            "artist": row.artist,
            "status": row.status,
            "vote_count": row.vote_count or 0,
            "cover_url": row.cover_url,
            "approval_status": row.approval_status,
            "submitted_by_id": row.submitted_by_id,
            "submitted_by_username": current_user.username,
            "approved_by_id": row.approved_by_id,
            "approved_at": row.approved_at,
            "detail_ready": detail_map.get(row.id, False),
        })
    return payload


@router.post("/series/{series_id}/approve", response_model=SeriesOut)
async def approve_series(
    series_id: int,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Series).where(Series.id == series_id))
    series = result.scalar_one_or_none()
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    if series.approval_status == SeriesApprovalStatus.APPROVED.value:
        return series

    detail_result = await db.execute(
        select(SeriesDetail).where(SeriesDetail.series_id == series_id)
    )
    detail = detail_result.scalar_one_or_none()
    if not detail or not (detail.synopsis or "").strip() or not (detail.series_cover_url or "").strip():
        raise HTTPException(
            status_code=400,
            detail="Title details must be completed before approval"
        )

    series.approval_status = SeriesApprovalStatus.APPROVED.value
    series.approved_by_id = admin_user.id
    series.approved_at = datetime.now(timezone.utc).isoformat()

    await db.commit()
    await db.refresh(series)
    return series


@router.get("/series/rankings", response_model=List[RankedSeriesOut])
async def get_ranked_series(
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=50),
    type: Optional[str] = Query(None),
    genre: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    sort: Optional[str] = Query(
        "score",
        description="Display order: score (default) | votes | newest | title",
    ),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Series, SeriesDetail).join(
        SeriesDetail, Series.id == SeriesDetail.series_id, isouter=True
    ).where(Series.approval_status == SeriesApprovalStatus.APPROVED.value)

    if type:
        stmt = stmt.where(Series.type == type.upper())

    if genre:
        stmt = stmt.where(Series.genre.ilike(f"%{genre}%"))

    if status:
        stmt = stmt.where(Series.status == status.upper())

    query = await db.execute(stmt)
    results = query.all()
    print(f"🔍 Total results from DB (joined): {len(results)}")

    ranked_series = []
    for series, detail in results:
        def safe_avg(total, count):
            return total / count if count else 0

        if detail:
            story = safe_avg(detail.story_total, detail.story_count)
            chars = safe_avg(detail.characters_total, detail.characters_count)
            world = safe_avg(detail.worldbuilding_total, detail.worldbuilding_count)
            art = safe_avg(detail.art_total, detail.art_count)
            drama = safe_avg(detail.drama_or_fight_total, detail.drama_or_fight_count)
            # final_score = round((story + chars + world + art + drama) / 5, 2)
            final_score = Decimal((story + chars + world + art + drama) / 5)
            # print(f"final_socre: {final_score}")
        else:
            final_score = 0.0

        ranked_series.append({
            "id": series.id,
            "title": series.title,
            "genre": series.genre,
            "type": series.type,
            "author": series.author,
            "artist": series.artist,
            "cover_url": series.cover_url,
            "vote_count": series.vote_count or 0,
            "final_score": final_score,
            "status": series.status.name if series.status else None,
        })

    # Rank is ALWAYS score-based — the "ranking" is by final_score. Compute it
    # first so every item carries its true rank regardless of display order.
    ranked = [s for s in ranked_series if s["final_score"] > 0]
    unranked = [s for s in ranked_series if s["final_score"] == 0]

    ranked.sort(key=lambda x: x["final_score"], reverse=True)
    for idx, s in enumerate(ranked):
        s["rank"] = idx + 1
    for s in unranked:
        s["rank"] = None

    # `sort` controls the DISPLAY order only; each item keeps its score-based rank.
    sort_key = (sort or "score").lower()
    if sort_key == "votes":
        ordered = sorted(ranked_series, key=lambda x: x["vote_count"], reverse=True)
    elif sort_key == "newest":
        ordered = sorted(ranked_series, key=lambda x: x["id"], reverse=True)
    elif sort_key == "title":
        ordered = sorted(ranked_series, key=lambda x: (x["title"] or "").casefold())
    else:  # "score" (default): ranked by score desc, unranked last
        ordered = ranked + unranked

    start = (page - 1) * page_size
    end = start + page_size
    return ordered[start:end]




@router.get("/series/summary/{series_id}", response_model=RankedSeriesOut)
async def get_series_summary(
    series_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    target_stmt = select(Series, SeriesDetail).join(
        SeriesDetail, Series.id == SeriesDetail.series_id, isouter=True
    ).where(Series.id == series_id)
    target_result = await db.execute(target_stmt)
    target_row = target_result.first()

    if not target_row:
        raise HTTPException(status_code=404, detail="Series not found")

    series_row, target_detail = target_row
    current_user = None
    token = request.headers.get("authorization", "").replace("Bearer ", "")
    if token:
        try:
            current_user = await get_current_user(token=token, session=db)
        except Exception:
            current_user = None

    can_view_pending = bool(
        current_user and (
            current_user.id == series_row.submitted_by_id
            or (current_user.role or "").upper() == "ADMIN"
        )
    )
    if (
        series_row.approval_status != SeriesApprovalStatus.APPROVED.value
        and not can_view_pending
    ):
        raise HTTPException(status_code=404, detail="Series not found")

    def safe_avg(total, count):
        return total / count if count else 0

    approved_stmt = select(Series, SeriesDetail).join(
        SeriesDetail, Series.id == SeriesDetail.series_id, isouter=True
    ).where(Series.approval_status == SeriesApprovalStatus.APPROVED.value)
    approved_result = await db.execute(approved_stmt)
    approved_rows = approved_result.all()

    ranked_series = []
    for s, d in approved_rows:
        if d:
            story = safe_avg(d.story_total, d.story_count)
            chars = safe_avg(d.characters_total, d.characters_count)
            world = safe_avg(d.worldbuilding_total, d.worldbuilding_count)
            art = safe_avg(d.art_total, d.art_count)
            drama = safe_avg(d.drama_or_fight_total, d.drama_or_fight_count)
            final_score = Decimal((story + chars + world + art + drama) / 5)
        else:
            final_score = 0.0

        ranked_series.append({
            "id": s.id,
            "title": s.title,
            "genre": s.genre,
            "type": s.type,
            "author": s.author,
            "artist": s.artist,
            "cover_url": s.cover_url,
            "vote_count": s.vote_count or 0,
            "final_score": final_score,
            "status": s.status.name if s.status else None,
        })

    ranked = [x for x in ranked_series if x["final_score"] > 0]
    unranked = [x for x in ranked_series if x["final_score"] == 0]

    ranked.sort(key=lambda x: x["final_score"], reverse=True)
    for idx, x in enumerate(ranked):
        x["rank"] = idx + 1
    for x in unranked:
        x["rank"] = None

    combined = ranked + unranked
    item = next((x for x in combined if x["id"] == series_id), None)
    if item:
        return item

    if series_row.approval_status == SeriesApprovalStatus.APPROVED.value:
        raise HTTPException(status_code=404, detail="Series not found")

    if target_detail:
        story = safe_avg(target_detail.story_total, target_detail.story_count)
        chars = safe_avg(target_detail.characters_total, target_detail.characters_count)
        world = safe_avg(target_detail.worldbuilding_total, target_detail.worldbuilding_count)
        art = safe_avg(target_detail.art_total, target_detail.art_count)
        drama = safe_avg(target_detail.drama_or_fight_total, target_detail.drama_or_fight_count)
        final_score = Decimal((story + chars + world + art + drama) / 5)
    else:
        final_score = 0.0

    return {
        "id": series_row.id,
        "title": series_row.title,
        "genre": series_row.genre,
        "type": series_row.type,
        "author": series_row.author,
        "artist": series_row.artist,
        "cover_url": series_row.cover_url,
        "vote_count": series_row.vote_count or 0,
        "final_score": final_score,
        "status": series_row.status.name if series_row.status else None,
        "rank": None,
    }

@router.get("/series/search", response_model=List[RankedSeriesOut])
async def search_series(
    query: str = Query(..., description="Search keyword"),
    type: Optional[str] = Query(
        None,
        description=(
            "Optional series type (MANGA/MANHWA/MANHUA). When provided, both the "
            "results and the rank are scoped to that category, so each result keeps "
            "its true rank within the type. When omitted, ranks reflect the full "
            "'All' ranking."
        ),
    ),
    db: AsyncSession = Depends(get_db)
):
    def safe_avg(total, count):
        return total / count if count else 0

    def compute_final_score(detail) -> Decimal:
        if not detail:
            return Decimal(0)
        story = safe_avg(detail.story_total, detail.story_count)
        chars = safe_avg(detail.characters_total, detail.characters_count)
        world = safe_avg(detail.worldbuilding_total, detail.worldbuilding_count)
        art = safe_avg(detail.art_total, detail.art_count)
        drama = safe_avg(detail.drama_or_fight_total, detail.drama_or_fight_count)
        return Decimal((story + chars + world + art + drama) / 5)

    # 1) Build the FULL approved ranking (optionally scoped to a type) so that each
    #    search result can keep its TRUE rank — its position in the overall ranking —
    #    instead of being re-ranked among only the search matches.
    full_stmt = select(Series, SeriesDetail).join(
        SeriesDetail, Series.id == SeriesDetail.series_id, isouter=True
    ).where(Series.approval_status == SeriesApprovalStatus.APPROVED.value)
    if type:
        full_stmt = full_stmt.where(Series.type == type.upper())

    full_rows = (await db.execute(full_stmt)).all()

    scored = [(series.id, compute_final_score(detail)) for series, detail in full_rows]
    score_by_id = {sid: score for sid, score in scored}

    # Only series with a positive score are ranked; rank by score descending.
    ranked_ids = sorted(
        (entry for entry in scored if entry[1] > 0),
        key=lambda entry: entry[1],
        reverse=True,
    )
    rank_by_id = {sid: idx + 1 for idx, (sid, _) in enumerate(ranked_ids)}

    # 2) Run the search query (scoped to the same type, when provided).
    stmt = select(Series).where(
        and_(
            Series.approval_status == SeriesApprovalStatus.APPROVED.value,
            or_(
                Series.title.ilike(f"%{query}%"),
                Series.genre.ilike(f"%{query}%"),
                cast(Series.type, String).ilike(f"%{query}%"),
                Series.author.ilike(f"%{query}%"),
                Series.artist.ilike(f"%{query}%"),
                cast(Series.status, String).ilike(f"%{query}%"),
            ),
        )
    )
    if type:
        stmt = stmt.where(Series.type == type.upper())

    matches = (await db.execute(stmt)).scalars().all()

    payload = []
    for series in matches:
        payload.append({
            "id": series.id,
            "title": series.title,
            "genre": series.genre,
            "type": series.type,
            "author": series.author,
            "artist": series.artist,
            "cover_url": series.cover_url,
            "vote_count": series.vote_count or 0,
            # Reuse the score computed for the full ranking (every match is part of
            # the approved set, so it is always present in score_by_id).
            "final_score": score_by_id.get(series.id, Decimal(0)),
            "status": series.status.name if series.status else None,
            "rank": rank_by_id.get(series.id),  # None for unranked (score 0)
        })

    # Present results in true-rank order, with unranked (rank None) last.
    payload.sort(key=lambda item: (item["rank"] is None, item["rank"] or 0))
    return payload
