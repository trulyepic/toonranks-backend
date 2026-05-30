import math

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, or_
from typing import Literal, Optional, List

from app.database import get_async_session
from app.models.forum_model import ForumThread, ForumPost, ForumSeriesRef, ForumReaction, ForumReport, ForumFollower, ForumBookmark, ForumCategory
from app.models.series_model import Series
from app.models.user_model import User

from app.schemas.forum_schemas import (
    ForumThreadOut, ForumPostOut, CreateThreadIn, CreatePostIn, SeriesRefOut, ThreadSettingsIn, UpdatePostIn,
    UpdateThreadIn, PageOut, PostsPageOut, ThreadPostsPageOut,
    ForumReportIn, ForumReportReviewIn, ForumReportOut, ForumReportsPageOut,
    FollowToggleOut, BookmarkToggleOut,
    ForumCategoryOut, CreateCategoryIn, UpdateCategoryIn,
)
from app.utils.forum_content import reject_disallowed_images

# ✅ Use your existing token utils (no changes there)
from app.utils.token_utils import get_current_user, SECRET_KEY, ALGORITHM
from jose import jwt, JWTError
from app.limiter import limiter
from app.moderation.profanity import ensure_clean

router = APIRouter(prefix="/forum", tags=["forum"])
DEFAULT_AVATAR_PRESET = "blue"
UPVOTE = "UPVOTE"
DOWNVOTE = "DOWNVOTE"
LEGACY_HEART = "HEART"
POSITIVE_REACTION_KINDS = (UPVOTE, LEGACY_HEART)
MAX_THREADS_PER_USER = 50  # Raised from 10; limits thread spam without blocking active contributors


class LockToggleIn(BaseModel):
    locked: bool

class PinToggleIn(BaseModel):
    pinned: bool

class ForumVoteIn(BaseModel):
    vote: Optional[Literal["UPVOTE", "DOWNVOTE"]] = None


class ForumVoteOut(BaseModel):
    viewer_vote: Optional[Literal["UPVOTE", "DOWNVOTE"]] = None
    upvote_count: int
    downvote_count: int


class HeartToggleOut(BaseModel):
    hearted: bool
    count: int


def _normalize_vote_kind(kind: Optional[str]) -> Optional[str]:
    if kind == LEGACY_HEART:
        return UPVOTE
    if kind in {UPVOTE, DOWNVOTE}:
        return kind
    return None


async def _post_vote_bits(
    db: AsyncSession, post_id: int, viewer_id: Optional[int]
) -> tuple[int, int, Optional[str]]:
    upvote_stmt = select(func.count(ForumReaction.id)).where(
        ForumReaction.post_id == post_id, ForumReaction.kind.in_(POSITIVE_REACTION_KINDS)
    )
    upvote_count = int((await db.execute(upvote_stmt)).scalar_one() or 0)

    downvote_stmt = select(func.count(ForumReaction.id)).where(
        ForumReaction.post_id == post_id, ForumReaction.kind == DOWNVOTE
    )
    downvote_count = int((await db.execute(downvote_stmt)).scalar_one() or 0)

    viewer_vote = None
    if viewer_id:
        viewer_stmt = (
            select(ForumReaction)
            .where(
                ForumReaction.post_id == post_id,
                ForumReaction.user_id == viewer_id,
            )
            .limit(1)
        )
        reaction = (await db.execute(viewer_stmt)).scalars().first()
        viewer_vote = _normalize_vote_kind(getattr(reaction, "kind", None))

    return upvote_count, downvote_count, viewer_vote


async def _post_heart_bits(db: AsyncSession, post_id: int, viewer_id: Optional[int]) -> tuple[int, bool]:
    upvote_count, _downvote_count, viewer_vote = await _post_vote_bits(db, post_id, viewer_id)
    return upvote_count, viewer_vote == UPVOTE


# ------------------------------
# helpers
# ------------------------------
def _is_admin(user: "User") -> bool:
    return (getattr(user, "role", "") or "").upper() == "ADMIN"


def _author_profile(user: Optional[User]) -> dict:
    return {
        "author_username": getattr(user, "username", None) if user else None,
        "author_role": getattr(user, "role", None) if user else None,
        "author_avatar_url": getattr(user, "avatar_url", None) if user else None,
        "author_avatar_preset": (
            getattr(user, "avatar_preset", None) if user else None
        ) or DEFAULT_AVATAR_PRESET,
    }


async def _post_to_plain_dict(p: ForumPost, db: AsyncSession, viewer: Optional["User"]=None) -> dict:
    refs = await db.execute(
        select(ForumSeriesRef, Series)
        .join(Series, Series.id == ForumSeriesRef.series_id)
        .where(ForumSeriesRef.post_id == p.id)
    )
    srefs = []
    for (_ref, s) in refs.all():
        srefs.append({
            "series_id": s.id,
            "title": s.title,
            "cover_url": s.cover_url,
            "type": s.type,
            "status": s.status,
        })

    author = None
    if p.author_id:
        author = await db.get(User, p.author_id)

    upvote_count, downvote_count, viewer_vote = await _post_vote_bits(
        db, p.id, getattr(viewer, "id", None)
    )
    author_profile = _author_profile(author)

    # Always include parent_id; use 0 for top-level
    resolved_upvotes = int(getattr(p, "upvote_count", upvote_count) or upvote_count)
    return {
        "id": p.id,
        **author_profile,
        "content_markdown": p.content_markdown,
        "created_at": str(p.created_at),
        "updated_at": str(p.updated_at),
        "series_refs": srefs,
        "parent_id": int(p.parent_id) if p.parent_id is not None else 0,
        "upvote_count": resolved_upvotes,
        "downvote_count": int(getattr(p, "downvote_count", downvote_count) or downvote_count),
        "viewer_vote": viewer_vote,
        "heart_count": resolved_upvotes,
        "viewer_has_hearted": viewer_vote == UPVOTE,
    }

def dump_model(m):
    return m.model_dump(exclude_none=False) if hasattr(m, "model_dump") else m.dict(exclude_none=False)

# ------------------------------
# Local optional-user helper ONLY in this file
# ------------------------------
async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
) -> Optional[User]:
    auth = request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return None
    token = auth.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("id")
        if user_id is None:
            return None
    except JWTError:
        return None

    user = await db.get(User, user_id)
    return user

# ------------------------------
# Mappers
# ------------------------------
async def _thread_to_out(t: ForumThread, db: AsyncSession, viewer_id: Optional[int] = None) -> ForumThreadOut:
    author = None
    if t.author_id:
        author = await db.get(User, t.author_id)

    refs = await db.execute(
        select(ForumSeriesRef, Series)
        .join(Series, Series.id == ForumSeriesRef.series_id)
        .where(ForumSeriesRef.thread_id == t.id, ForumSeriesRef.post_id == None)
    )
    srefs = [
        SeriesRefOut(
            series_id=s.id,
            title=s.title,
            cover_url=s.cover_url,
            type=s.type,
            status=s.status,
        )
        for (_ref, s) in refs.all()
    ]

    viewer_is_following = False
    if viewer_id:
        follow_row = (await db.execute(
            select(ForumFollower).where(
                ForumFollower.thread_id == t.id,
                ForumFollower.user_id == viewer_id,
            ).limit(1)
        )).scalars().first()
        viewer_is_following = follow_row is not None

    category_id = getattr(t, "category_id", None)
    category_name: Optional[str] = None
    if category_id:
        cat = await db.get(ForumCategory, category_id)
        category_name = cat.name if cat else None

    return ForumThreadOut(
        id=t.id,
        title=t.title,
        **_author_profile(author),
        created_at=str(t.created_at),
        updated_at=str(t.updated_at),
        post_count=t.post_count or 0,
        last_post_at=str(t.last_post_at),
        series_refs=srefs,
        locked=bool(getattr(t, "locked", False)),
        latest_first=bool(getattr(t, "latest_first", False)),
        is_pinned=bool(getattr(t, "is_pinned", False)),
        view_count=int(getattr(t, "view_count", 0) or 0),
        viewer_is_following=viewer_is_following,
        category_id=category_id,
        category_name=category_name,
    )

async def _post_to_out(p: ForumPost, db: AsyncSession, viewer: Optional["User"]=None) -> ForumPostOut:
    refs = await db.execute(
        select(ForumSeriesRef, Series)
        .join(Series, Series.id == ForumSeriesRef.series_id)
        .where(ForumSeriesRef.post_id == p.id)
    )
    srefs = [
        SeriesRefOut(
            series_id=s.id,
            title=s.title,
            cover_url=s.cover_url,
            type=s.type,
            status=s.status,
        )
        for (_ref, s) in refs.all()
    ]

    author = None
    if p.author_id:
        author = await db.get(User, p.author_id)

    upvote_count, downvote_count, viewer_vote = await _post_vote_bits(
        db, p.id, getattr(viewer, "id", None)
    )
    resolved_upvotes = int(getattr(p, "upvote_count", upvote_count) or upvote_count)

    viewer_has_bookmarked = False
    viewer_id = getattr(viewer, "id", None)
    if viewer_id:
        bookmark_row = (await db.execute(
            select(ForumBookmark).where(
                ForumBookmark.post_id == p.id,
                ForumBookmark.user_id == viewer_id,
            ).limit(1)
        )).scalars().first()
        viewer_has_bookmarked = bookmark_row is not None

    return ForumPostOut(
        id=p.id,
        thread_id=p.thread_id,
        **_author_profile(author),
        content_markdown=p.content_markdown,
        created_at=str(p.created_at),
        updated_at=str(p.updated_at),
        series_refs=srefs,
        parent_id=p.parent_id if p.parent_id is not None else 0,
        upvote_count=resolved_upvotes,
        downvote_count=int(getattr(p, "downvote_count", downvote_count) or downvote_count),
        viewer_vote=viewer_vote,
        heart_count=resolved_upvotes,
        viewer_has_hearted=viewer_vote == UPVOTE,
        viewer_has_bookmarked=viewer_has_bookmarked,
    )

# ------------------------------
# Routes
# ------------------------------
@router.get("/threads", response_model=List[ForumThreadOut])
async def list_threads(
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_async_session),
    _viewer: Optional[User] = Depends(get_current_user_optional),
):
    stmt = select(ForumThread).order_by(ForumThread.is_pinned.desc(), ForumThread.updated_at.desc())
    if q:
        stmt = select(ForumThread).where(ForumThread.title.ilike(f"%{q}%")).order_by(
            ForumThread.is_pinned.desc(), ForumThread.updated_at.desc()
        )

    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(stmt)).scalars().all()
    return [await _thread_to_out(t, db) for t in rows]

@router.post("/threads", response_model=ForumThreadOut)
@limiter.limit("3/minute;20/hour;60/day")
async def create_thread(
request: Request,
    payload: CreateThreadIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    # ✅ Profanity check (title + first post)
    try:
        ensure_clean(payload.title)
        ensure_clean(payload.first_post_markdown)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"code": "PROFANITY", "message": "Reply contains inappropriate language."}
        )

    # 🔒 limit: max 10 threads per user
    existing_count = (
        await db.execute(
            select(func.count(ForumThread.id)).where(ForumThread.author_id == user.id)
        )
    ).scalar_one()
    if existing_count >= MAX_THREADS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Thread limit reached ({MAX_THREADS_PER_USER}). Delete an existing thread to create a new one.",
        )

    # Validate category if provided
    if payload.category_id:
        cat = await db.get(ForumCategory, payload.category_id)
        if not cat:
            raise HTTPException(status_code=404, detail="Category not found")

    thread = ForumThread(title=payload.title, author_id=user.id, category_id=payload.category_id)
    db.add(thread)
    await db.flush()  # get thread.id

    post = ForumPost(
        thread_id=thread.id,
        author_id=user.id,
        content_markdown=payload.first_post_markdown,
    )
    db.add(post)

    for sid in payload.series_ids or []:
        db.add(ForumSeriesRef(thread_id=thread.id, post_id=None, series_id=sid))

    thread.post_count = 1
    thread.last_post_at = func.now()

    # +2 CP for starting a thread
    thread_author = await db.get(User, user.id)
    if thread_author is not None:
        thread_author.cred_score = max(0, (thread_author.cred_score or 0) + 2)

    await db.commit()
    await db.refresh(thread)

    return await _thread_to_out(thread, db)

# @router.get("/threads/{thread_id}")
# async def get_thread(
#     thread_id: int,
#     db: AsyncSession = Depends(get_async_session),
#     _viewer: Optional[User] = Depends(get_current_user_optional),  # optional
# ):
#     t = await db.get(ForumThread, thread_id)
#     if not t:
#         raise HTTPException(status_code=404, detail="Thread not found")
#
#     header_refs = await db.execute(
#         select(ForumSeriesRef, Series)
#         .join(Series, Series.id == ForumSeriesRef.series_id)
#         .where(ForumSeriesRef.thread_id == thread_id, ForumSeriesRef.post_id == None)
#     )
#     header = [
#         {
#             "series_id": s.id,
#             "title": s.title,
#             "cover_url": s.cover_url,
#             "type": s.type,
#             "status": s.status,
#         }
#         for (_ref, s) in header_refs.all()
#     ]
#
#     posts = (
#         await db.execute(
#             select(ForumPost)
#             .where(ForumPost.thread_id == thread_id)
#             .order_by(ForumPost.created_at.asc())
#         )
#     ).scalars().all()
#
#     posts_out = [await _post_to_plain_dict(p, db) for p in posts]
#
#     return {
#         "thread": {
#             "id": t.id,
#             "title": t.title,
#             "author_username": None,
#             "created_at": str(t.created_at),
#             "updated_at": str(t.updated_at),
#             "post_count": t.post_count or 0,
#             "last_post_at": str(t.last_post_at),
#             "series_refs": header,
#             "locked": bool(getattr(t, "locked", False)),
#         },
#         "posts": posts_out,
#     }


@router.get("/threads-paged", response_model=PageOut)
async def list_threads_paged(
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    author_id: Optional[int] = None,  # allows "my threads" count without fetching 1000 rows
    sort: Optional[Literal["activity", "newest", "replies"]] = Query("activity"),
    category_id: Optional[int] = None,
    category_slug: Optional[str] = None,
    db: AsyncSession = Depends(get_async_session),
    _viewer: Optional[User] = Depends(get_current_user_optional),
):
    filters = []
    if q:
        filters.append(ForumThread.title.ilike(f"%{q}%"))
    if author_id is not None:
        filters.append(ForumThread.author_id == author_id)

    # Category filtering — slug takes priority over id for clean URLs
    if category_slug:
        cat_row = (await db.execute(
            select(ForumCategory).where(ForumCategory.slug == category_slug).limit(1)
        )).scalars().first()
        if cat_row:
            filters.append(ForumThread.category_id == cat_row.id)
        else:
            # Unknown slug → return empty page (not a 404; keeps UI simple)
            filters.append(ForumThread.category_id == -1)
    elif category_id is not None:
        filters.append(ForumThread.category_id == category_id)

    # total
    total_stmt = select(func.count(ForumThread.id))
    if filters:
        total_stmt = total_stmt.where(*filters)
    total = int((await db.execute(total_stmt)).scalar_one() or 0)

    # Pinned threads always surface first regardless of sort selection
    if sort == "newest":
        order_clause = [ForumThread.is_pinned.desc(), ForumThread.created_at.desc(), ForumThread.id.desc()]
    elif sort == "replies":
        order_clause = [ForumThread.is_pinned.desc(), ForumThread.post_count.desc(), ForumThread.id.desc()]
    else:  # "activity" (default)
        order_clause = [ForumThread.is_pinned.desc(), ForumThread.last_post_at.desc(), ForumThread.id.desc()]

    stmt = select(ForumThread).order_by(*order_clause)
    if filters:
        stmt = stmt.where(*filters)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    rows = (await db.execute(stmt)).scalars().all()
    items = [await _thread_to_out(t, db) for t in rows]

    total_pages = max(1, math.ceil(total / page_size))
    return PageOut(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        has_prev=page > 1,
        has_next=page < total_pages,
        sort=sort,
    )

@router.get("/threads/{thread_id}")
async def get_thread(
    thread_id: int,
    db: AsyncSession = Depends(get_async_session),
    viewer: Optional[User] = Depends(get_current_user_optional),  # optional
):
    t = await db.get(ForumThread, thread_id)
    if not t:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Increment view count; skip if the viewer is the thread author to avoid self-inflation
    if not (viewer and viewer.id == t.author_id):
        t.view_count = (t.view_count or 0) + 1
        await db.commit()
        await db.refresh(t)

    # Posts (unchanged)
    posts = (
        await db.execute(
            select(ForumPost)
            .where(ForumPost.thread_id == thread_id)
            .order_by(ForumPost.created_at.asc())
        )
    ).scalars().all()
    posts_out = [await _post_to_plain_dict(p, db, viewer) for p in posts]

    # ✅ Reuse the shared mapper so locked + latest_first + series_refs are all included
    thread_out = await _thread_to_out(t, db)

    # If you want to be explicit, dump the Pydantic model into a dict
    return {
        "thread": dump_model(thread_out),
        "posts": posts_out,
    }


@router.get("/threads/{thread_id}/posts-paged", response_model=ThreadPostsPageOut)
async def get_thread_posts_paged(
    thread_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_async_session),
    viewer: Optional[User] = Depends(get_current_user_optional),
):
    # 1) Thread + OP
    t = await db.get(ForumThread, thread_id)
    if not t:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Increment view count on page 1 only (so paginating deeper doesn't keep inflating the count)
    if page == 1 and not (viewer and viewer.id == t.author_id):
        t.view_count = (t.view_count or 0) + 1
        await db.commit()
        await db.refresh(t)

    # Oldest post is the OP
    first_post = (
        await db.execute(
            select(ForumPost)
            .where(ForumPost.thread_id == thread_id)
            .order_by(ForumPost.created_at.asc(), ForumPost.id.asc())
            .limit(1)
        )
    ).scalars().first()
    if not first_post:
        # shouldn't happen, but be safe
        out = ThreadPostsPageOut(
            thread=await _thread_to_out(t, db),
            posts=[],
            page=page,
            page_size=page_size,
            total_top_level=0,
            total_pages=1,
            has_prev=False,
            has_next=False,
        )
        return out

    # 2) Count top-level replies (parent IS NULL or direct reply to OP) excluding OP
    total_top_level = int(
        (
            await db.execute(
                select(func.count(ForumPost.id)).where(
                    ForumPost.thread_id == thread_id,
                    or_(
                        ForumPost.parent_id.is_(None),
                        ForumPost.parent_id == first_post.id,
                    ),
                    ForumPost.id != first_post.id,
                )
            )
        ).scalar_one()
        or 0
    )
    total_pages = max(1, math.ceil(total_top_level / page_size))
    page = min(page, total_pages)

    # 3) Page of top-level roots (stable order: oldest→newest)
    #    Includes both null-parent posts and direct replies to the OP so the
    #    frontend's "originalReplies" section is populated on reload.
    roots = (
        await db.execute(
            select(ForumPost)
            .where(
                ForumPost.thread_id == thread_id,
                or_(
                    ForumPost.parent_id.is_(None),
                    ForumPost.parent_id == first_post.id,
                ),
                ForumPost.id != first_post.id,
            )
            .order_by(ForumPost.created_at.asc(), ForumPost.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    root_ids = [p.id for p in roots]

    # 4) Fetch descendants for those roots (iterative, avoids recursive CTE complexity)
    descendants: list[ForumPost] = []
    frontier = set(root_ids)
    while frontier:
        children = (
            await db.execute(
                select(ForumPost)
                .where(
                    ForumPost.thread_id == thread_id,
                    ForumPost.parent_id.in_(frontier),
                )
            )
        ).scalars().all()
        if not children:
            break
        descendants.extend(children)
        frontier = set(c.id for c in children)

    # 5) Build a flat list: OP first, then roots, each followed by their subtree
    #    The frontend sorts children per parent; order here just needs to be consistent.
    by_parent: dict[int, list[ForumPost]] = {}
    subset = roots + descendants
    for p in subset:
        pid = int(p.parent_id) if p.parent_id is not None else 0
        by_parent.setdefault(pid, []).append(p)

    # sort roots by time asc (children are sorted by the client)
    roots_sorted = sorted(roots, key=lambda p: (p.created_at, p.id))

    ordered_models: list[ForumPost] = [first_post]
    def walk(parent: ForumPost):
        kids = by_parent.get(parent.id, [])
        # children order not critical; client sorts by created_at asc
        for k in kids:
            ordered_models.append(k)
            walk(k)

    for r in roots_sorted:
        ordered_models.append(r)
        walk(r)

    # 6) Map to output
    thread_out = await _thread_to_out(t, db)
    posts_out: list[ForumPostOut] = []
    for m in ordered_models:
        posts_out.append(await _post_to_out(m, db, viewer))

    return ThreadPostsPageOut(
        thread=thread_out,
        posts=posts_out,
        page=page,
        page_size=page_size,
        total_top_level=total_top_level,
        total_pages=total_pages,
        has_prev=page > 1,
        has_next=page < total_pages,
    )


@router.patch("/threads/{thread_id}/lock")
async def set_thread_lock(
    thread_id: int,
    body: LockToggleIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Admin only")
    t = await db.get(ForumThread, thread_id)
    if not t:
        raise HTTPException(status_code=404, detail="Thread not found")
    t.locked = bool(body.locked)
    await db.commit()
    await db.refresh(t)
    return {"id": t.id, "locked": t.locked}


@router.patch("/threads/{thread_id}/pin")
async def set_thread_pin(
    thread_id: int,
    body: PinToggleIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Admin-only: pin or unpin a thread so it always appears at the top of the thread list."""
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Admin only")
    t = await db.get(ForumThread, thread_id)
    if not t:
        raise HTTPException(status_code=404, detail="Thread not found")
    t.is_pinned = bool(body.pinned)
    await db.commit()
    await db.refresh(t)
    return {"id": t.id, "is_pinned": t.is_pinned}


@router.post("/threads/{thread_id}/posts")
@limiter.limit("6/minute;40/hour;150/day")
async def create_post(
request: Request,
    thread_id: int,
    payload: CreatePostIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    thread = await db.get(ForumThread, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    # ✅ Fail fast if thread is locked (non-admins)
    if bool(getattr(thread, "locked", False)) and not _is_admin(user):
        raise HTTPException(status_code=423, detail="Thread is locked")

    # ✅ Profanity check (reply content)
    try:
        ensure_clean(payload.content_markdown)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"code": "PROFANITY", "message": "Reply contains inappropriate language."}
        )

    reject_disallowed_images(payload.content_markdown)


    parent_id = payload.parent_id
    if parent_id is not None:
        parent = await db.get(ForumPost, parent_id)
        if not parent:
            raise HTTPException(status_code=404, detail="Parent post not found")

        if bool(getattr(thread, "locked", False)) and not _is_admin(user):
            raise HTTPException(status_code=423, detail="Thread is locked")

        if parent.thread_id != thread_id:
            raise HTTPException(status_code=400, detail="Parent post is from another thread")

    post = ForumPost(
        thread_id=thread_id,
        author_id=user.id,
        content_markdown=payload.content_markdown,
        parent_id=parent_id,
    )
    db.add(post)
    await db.flush()

    for sid in (payload.series_ids or []):
        db.add(ForumSeriesRef(thread_id=thread_id, post_id=post.id, series_id=sid))

    thread.post_count = (thread.post_count or 0) + 1
    thread.last_post_at = func.now()

    # +1 CP for posting a reply
    reply_author = await db.get(User, user.id)
    if reply_author is not None:
        reply_author.cred_score = max(0, (reply_author.cred_score or 0) + 1)

    await db.commit()
    await db.refresh(post)

    return await _post_to_plain_dict(post, db)

@router.get("/series-search", response_model=List[SeriesRefOut])
@limiter.limit("30/minute;1000/day")
async def forum_series_search(
request: Request,
    q: str = Query(..., min_length=1),
    limit: int = 10,
    db: AsyncSession = Depends(get_async_session),
):
    rows = (
        await db.execute(
            select(Series).where(Series.title.ilike(f"%{q}%")).limit(limit)
        )
    ).scalars().all()
    return [
        SeriesRefOut(
            series_id=s.id,
            title=s.title,
            cover_url=s.cover_url,
            type=s.type,
            status=s.status,
        )
        for s in rows
    ]

# ------------------------------
# Deletes (owner-or-admin)
# ------------------------------
@router.delete("/threads/{thread_id}/posts/{post_id}", status_code=204)
async def delete_post(
    thread_id: int,
    post_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    post = await db.get(ForumPost, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.thread_id != thread_id:
        raise HTTPException(status_code=400, detail="Post is not in this thread")

    # Only admins or the author of the post
    if not (_is_admin(user) or post.author_id == user.id):
        raise HTTPException(status_code=403, detail="Admins or the post owner may delete this post.")

    # Prevent deleting the original post via this endpoint
    first_post_id = (
        await db.execute(
            select(ForumPost.id)
            .where(ForumPost.thread_id == thread_id)
            .order_by(ForumPost.created_at.asc())
            .limit(1)
        )
    ).scalar_one()
    if post.id == first_post_id:
        raise HTTPException(status_code=400, detail="Delete the thread to remove the original post.")

    thread = await db.get(ForumThread, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Reverse CP for this reply before deleting
    if post.author_id:
        post_author = await db.get(User, post.author_id)
        if post_author is not None:
            post_upvotes = int(getattr(post, "upvote_count", 0) or 0)
            post_downvotes = int(getattr(post, "downvote_count", 0) or 0)
            delta = -1 - (post_upvotes * 2) + post_downvotes
            post_author.cred_score = max(0, (post_author.cred_score or 0) + delta)

    await db.delete(post)   # cascades to children via ON DELETE CASCADE
    await db.flush()

    # refresh thread counters
    total_posts = (
        await db.execute(
            select(func.count()).select_from(ForumPost).where(ForumPost.thread_id == thread_id)
        )
    ).scalar_one()
    last_post_at = (
        await db.execute(
            select(func.max(ForumPost.created_at)).where(ForumPost.thread_id == thread_id)
        )
    ).scalar_one()

    thread.post_count = int(total_posts or 0)
    thread.last_post_at = last_post_at or thread.created_at

    await db.commit()
    return Response(status_code=204)

@router.delete("/threads/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    thread = await db.get(ForumThread, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Admins OR owner of the thread
    if not (_is_admin(user) or thread.author_id == user.id):
        raise HTTPException(status_code=403, detail="Admins or the thread owner may delete this thread.")

    # Reverse CP for every post in the thread before the cascade delete
    all_posts = (
        await db.execute(
            select(ForumPost).where(ForumPost.thread_id == thread_id)
        )
    ).scalars().all()

    if all_posts:
        # The OP is the earliest post — thread creation gave the author +2 (not +1)
        op_id = min(all_posts, key=lambda p: (p.created_at, p.id)).id
        user_cache: dict[int, User] = {}

        for p in all_posts:
            if not p.author_id:
                continue
            if p.author_id not in user_cache:
                fetched = await db.get(User, p.author_id)
                if fetched is None:
                    continue
                user_cache[p.author_id] = fetched
            p_author = user_cache[p.author_id]
            post_upvotes = int(getattr(p, "upvote_count", 0) or 0)
            post_downvotes = int(getattr(p, "downvote_count", 0) or 0)
            # OP author loses thread-creation credit (2); reply authors lose reply credit (1)
            post_credit = 2 if p.id == op_id else 1
            delta = -post_credit - (post_upvotes * 2) + post_downvotes
            p_author.cred_score = max(0, (p_author.cred_score or 0) + delta)

    await db.delete(thread)  # cascades to posts + series refs
    await db.commit()
    return Response(status_code=204)

@router.delete("/threads/{thread_id}/posts/{post_id}/mine", status_code=204)
async def delete_my_post(
    thread_id: int,
    post_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    post = await db.get(ForumPost, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.thread_id != thread_id:
        raise HTTPException(status_code=400, detail="Post is not in this thread")
    # must be author or admin
    if (user.role or "").upper() != "ADMIN" and post.author_id != user.id:
        raise HTTPException(status_code=403, detail="Not allowed")

    # Reverse CP for this reply before deleting
    if post.author_id:
        post_author = await db.get(User, post.author_id)
        if post_author is not None:
            post_upvotes = int(getattr(post, "upvote_count", 0) or 0)
            post_downvotes = int(getattr(post, "downvote_count", 0) or 0)
            delta = -1 - (post_upvotes * 2) + post_downvotes
            post_author.cred_score = max(0, (post_author.cred_score or 0) + delta)

    await db.delete(post)
    await db.flush()

    thread = await db.get(ForumThread, thread_id)
    if thread:
        total_posts = (
            await db.execute(
                select(func.count()).select_from(ForumPost).where(ForumPost.thread_id == thread_id)
            )
        ).scalar_one()
        last_post_at = (
            await db.execute(
                select(func.max(ForumPost.created_at)).where(ForumPost.thread_id == thread_id)
            )
        ).scalar_one()

        thread.post_count = int(total_posts or 0)
        thread.last_post_at = last_post_at or thread.created_at

    await db.commit()
    return Response(status_code=204)

@router.patch("/threads/{thread_id}/settings", response_model=dict)
async def update_thread_settings(
    thread_id: int,
    body: ThreadSettingsIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Admin only")
    t = await db.get(ForumThread, thread_id)
    if not t:
        raise HTTPException(status_code=404, detail="Thread not found")

    if body.latest_first is not None:
        t.latest_first = bool(body.latest_first)

    await db.commit()
    await db.refresh(t)
    return {"id": t.id, "latest_first": t.latest_first}


@router.patch("/threads/{thread_id}/posts/{post_id}", response_model=ForumPostOut)
@limiter.limit("12/minute;80/hour;300/day")
async def update_post(
    request: Request,
    thread_id: int,
    post_id: int,
    payload: UpdatePostIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    thread = await db.get(ForumThread, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    post = await db.get(ForumPost, post_id)
    if not post or post.thread_id != thread_id:
        raise HTTPException(status_code=404, detail="Post not found")

    # If thread is locked, only admins may edit
    if bool(getattr(thread, "locked", False)) and not _is_admin(user):
        raise HTTPException(status_code=423, detail="Thread is locked")

    # Only admins or the author may edit
    if not (_is_admin(user) or post.author_id == user.id):
        raise HTTPException(status_code=403, detail="Admins or the post owner may edit this post.")

    # Profanity check
    try:
        ensure_clean(payload.content_markdown)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"code": "PROFANITY", "message": "Reply contains inappropriate language."}
        )

    reject_disallowed_images(payload.content_markdown)

    # Update the content
    post.content_markdown = payload.content_markdown

    # Replace series refs for this post (if series_ids provided)
    await db.execute(
        delete(ForumSeriesRef).where(
            ForumSeriesRef.thread_id == thread_id,
            ForumSeriesRef.post_id == post_id,
        )
    )
    for sid in (payload.series_ids or []):
        db.add(ForumSeriesRef(thread_id=thread_id, post_id=post_id, series_id=sid))

    await db.commit()
    await db.refresh(post)

    # Return normalized shape
    return await _post_to_out(post, db)


from sqlalchemy import select, func, delete
from fastapi import HTTPException, status

@router.patch("/threads/{thread_id}", response_model=ForumThreadOut)
@limiter.limit("6/minute;40/hour;150/day")
async def update_thread(
    request: Request,
    thread_id: int,
    payload: UpdateThreadIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    thread = await db.get(ForumThread, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    is_admin = _is_admin(user)
    is_owner = thread.author_id == user.id
    if not (is_admin or is_owner):
        raise HTTPException(status_code=403, detail="Admins or the thread owner may edit this thread.")

    # If locked, only admins may edit anything
    if bool(getattr(thread, "locked", False)) and not is_admin:
        raise HTTPException(status_code=423, detail="Thread is locked")

    # Validate + update title
    if payload.title is not None:
        try:
            ensure_clean(payload.title)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"code": "PROFANITY", "message": "Title contains inappropriate language."}
            )
        thread.title = payload.title

    # Update the first post if body provided
    if payload.first_post_markdown is not None:
        try:
            ensure_clean(payload.first_post_markdown)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"code": "PROFANITY", "message": "Reply contains inappropriate language."}
            )

        first_post = (
            await db.execute(
                select(ForumPost)
                .where(ForumPost.thread_id == thread_id)
                .order_by(ForumPost.created_at.asc())
                .limit(1)
            )
        ).scalars().first()

        if not first_post:
            raise HTTPException(status_code=404, detail="Original post not found")

        first_post.content_markdown = payload.first_post_markdown

    # Replace header-level series refs IF provided
    if payload.series_ids is not None:
        await db.execute(
            delete(ForumSeriesRef).where(
                ForumSeriesRef.thread_id == thread_id,
                ForumSeriesRef.post_id == None,  # header refs only
            )
        )
        for sid in map(int, payload.series_ids):
            db.add(ForumSeriesRef(thread_id=thread_id, series_id=sid))

    # Re-categorize if category_id provided (pass 0 to clear)
    if payload.category_id is not None:
        if payload.category_id == 0:
            thread.category_id = None
        else:
            cat = await db.get(ForumCategory, payload.category_id)
            if not cat:
                raise HTTPException(status_code=404, detail="Category not found")
            thread.category_id = payload.category_id

    await db.commit()
    await db.refresh(thread)
    return await _thread_to_out(thread, db)


@router.post("/threads/{thread_id}/posts/{post_id}/heart", response_model=HeartToggleOut)
@limiter.limit("30/minute;1000/day")
async def toggle_heart(
    request: Request,
    thread_id: int,
    post_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    vote_result = await set_post_vote(
        request=request,
        thread_id=thread_id,
        post_id=post_id,
        payload=ForumVoteIn(vote=UPVOTE),
        user=user,
        db=db,
    )
    return HeartToggleOut(
        hearted=vote_result.viewer_vote == UPVOTE,
        count=vote_result.upvote_count,
    )


@router.post("/threads/{thread_id}/posts/{post_id}/vote", response_model=ForumVoteOut)
@limiter.limit("30/minute;1000/day")
async def set_post_vote(
    request: Request,
    thread_id: int,
    post_id: int,
    payload: ForumVoteIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    post = await db.get(ForumPost, post_id)
    if not post or post.thread_id != thread_id:
        raise HTTPException(status_code=404, detail="Post not found")

    # Block self-voting — can't vote on your own posts
    if post.author_id and post.author_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot vote on your own posts.",
        )

    # Reactions are allowed on locked threads per product note.

    existing = (
        await db.execute(
            select(ForumReaction)
            .where(
                ForumReaction.post_id == post_id,
                ForumReaction.user_id == user.id,
            )
            .limit(1)
        )
    ).scalars().first()

    requested_vote = payload.vote
    existing_vote = _normalize_vote_kind(getattr(existing, "kind", None))

    if requested_vote is None or existing_vote == requested_vote:
        viewer_vote = None
        if existing:
            await db.delete(existing)
    elif existing:
        existing.kind = requested_vote
        viewer_vote = requested_vote
    else:
        db.add(ForumReaction(post_id=post_id, user_id=user.id, kind=requested_vote))
        viewer_vote = requested_vote

    upvote_count = int(getattr(post, "upvote_count", 0) or 0)
    downvote_count = int(getattr(post, "downvote_count", 0) or 0)

    if existing_vote == UPVOTE:
        upvote_count = max(0, upvote_count - 1)
    elif existing_vote == DOWNVOTE:
        downvote_count = max(0, downvote_count - 1)

    if viewer_vote == UPVOTE:
        upvote_count += 1
    elif viewer_vote == DOWNVOTE:
        downvote_count += 1

    post.upvote_count = upvote_count
    post.downvote_count = downvote_count
    post.heart_count = upvote_count

    # ── Adjust author's cred_score in real time ────────────────────────────
    # Formula: upvotes are worth +2, downvotes are worth -1
    if post.author_id:
        delta = 0
        if existing_vote == UPVOTE:
            delta -= 2   # removing a previously counted upvote
        elif existing_vote == DOWNVOTE:
            delta += 1   # removing a previously counted downvote
        if viewer_vote == UPVOTE:
            delta += 2   # new upvote added
        elif viewer_vote == DOWNVOTE:
            delta -= 1   # new downvote added

        if delta != 0:
            author = await db.get(User, post.author_id)
            if author is not None:
                author.cred_score = max(0, (author.cred_score or 0) + delta)

    await db.commit()

    return ForumVoteOut(
        viewer_vote=viewer_vote,
        upvote_count=upvote_count,
        downvote_count=downvote_count,
    )


# ------------------------------
# Me endpoints (auth required)
# ------------------------------

@router.get("/me/threads", response_model=PageOut)
async def get_my_threads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Paginated list of threads the signed-in user created."""
    total_stmt = select(func.count(ForumThread.id)).where(
        ForumThread.author_id == user.id
    )
    total = int((await db.execute(total_stmt)).scalar_one() or 0)

    stmt = (
        select(ForumThread)
        .where(ForumThread.author_id == user.id)
        .order_by(ForumThread.last_post_at.desc(), ForumThread.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).scalars().all()
    items = [await _thread_to_out(t, db) for t in rows]

    total_pages = max(1, math.ceil(total / page_size))
    return PageOut(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        has_prev=page > 1,
        has_next=page < total_pages,
    )


@router.get("/me/posts", response_model=PostsPageOut)
async def get_my_posts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Paginated list of posts (replies) the signed-in user has written."""
    total_stmt = select(func.count(ForumPost.id)).where(
        ForumPost.author_id == user.id
    )
    total = int((await db.execute(total_stmt)).scalar_one() or 0)

    stmt = (
        select(ForumPost)
        .where(ForumPost.author_id == user.id)
        .order_by(ForumPost.created_at.desc(), ForumPost.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).scalars().all()
    items = [await _post_to_out(p, db, user) for p in rows]

    total_pages = max(1, math.ceil(total / page_size))
    return PostsPageOut(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        has_prev=page > 1,
        has_next=page < total_pages,
    )


@router.get("/me/votes", response_model=PostsPageOut)
async def get_my_votes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Paginated list of posts the signed-in user has voted on (upvote or downvote)."""
    total_stmt = select(func.count(ForumReaction.id)).where(
        ForumReaction.user_id == user.id,
        ForumReaction.kind.in_([UPVOTE, DOWNVOTE]),
    )
    total = int((await db.execute(total_stmt)).scalar_one() or 0)

    reactions_stmt = (
        select(ForumReaction)
        .where(
            ForumReaction.user_id == user.id,
            ForumReaction.kind.in_([UPVOTE, DOWNVOTE]),
        )
        .order_by(ForumReaction.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    reactions = (await db.execute(reactions_stmt)).scalars().all()

    items: list[ForumPostOut] = []
    for reaction in reactions:
        post = await db.get(ForumPost, reaction.post_id)
        if post:
            items.append(await _post_to_out(post, db, user))

    total_pages = max(1, math.ceil(total / page_size))
    return PostsPageOut(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        has_prev=page > 1,
        has_next=page < total_pages,
    )



# ------------------------------
# Post reporting
# ------------------------------

async def _report_to_out(report: "ForumReport", db: AsyncSession) -> ForumReportOut:
    """Map a ForumReport row to the output schema, pulling in usernames and post/thread context."""
    reporter = await db.get(User, report.reporter_id) if report.reporter_id else None
    reviewed_by = await db.get(User, report.reviewed_by_id) if report.reviewed_by_id else None
    post = await db.get(ForumPost, report.post_id) if report.post_id else None
    thread = await db.get(ForumThread, report.thread_id) if report.thread_id else None

    excerpt = None
    if post and post.content_markdown:
        excerpt = post.content_markdown[:200] + ("…" if len(post.content_markdown) > 200 else "")

    return ForumReportOut(
        id=report.id,
        post_id=report.post_id,
        thread_id=report.thread_id,
        reporter_username=getattr(reporter, "username", None),
        reason=report.reason,
        status=report.status,
        created_at=str(report.created_at),
        reviewed_at=str(report.reviewed_at) if report.reviewed_at else None,
        reviewed_by_username=getattr(reviewed_by, "username", None),
        post_excerpt=excerpt,
        thread_title=getattr(thread, "title", None),
    )


@router.post("/threads/{thread_id}/posts/{post_id}/report", status_code=201)
@limiter.limit("5/hour")
async def report_post(
    request: Request,
    thread_id: int,
    post_id: int,
    payload: ForumReportIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Submit a report on a forum post. One report per user per post."""
    post = await db.get(ForumPost, post_id)
    if not post or post.thread_id != thread_id:
        raise HTTPException(status_code=404, detail="Post not found")

    if post.author_id == user.id:
        raise HTTPException(status_code=403, detail="You cannot report your own post.")

    existing = (
        await db.execute(
            select(ForumReport).where(
                ForumReport.post_id == post_id,
                ForumReport.reporter_id == user.id,
            ).limit(1)
        )
    ).scalars().first()
    if existing:
        raise HTTPException(status_code=409, detail="You have already reported this post.")

    reason = (payload.reason or "").strip()[:500] or None

    db.add(ForumReport(
        post_id=post_id,
        thread_id=thread_id,
        reporter_id=user.id,
        reason=reason,
        status="OPEN",
    ))
    await db.commit()
    return {"message": "Report submitted. Our team will review it shortly."}


@router.get("/reports", response_model=ForumReportsPageOut)
async def list_reports(
    status: Optional[str] = Query("OPEN"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Admin-only: paginated list of post reports for moderation review."""
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Admin only")

    filters = []
    if status:
        filters.append(ForumReport.status == status.upper())

    total_stmt = select(func.count(ForumReport.id))
    if filters:
        total_stmt = total_stmt.where(*filters)
    total = int((await db.execute(total_stmt)).scalar_one() or 0)

    stmt = select(ForumReport).order_by(ForumReport.created_at.desc())
    if filters:
        stmt = stmt.where(*filters)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    rows = (await db.execute(stmt)).scalars().all()
    items = [await _report_to_out(r, db) for r in rows]

    total_pages = max(1, math.ceil(total / page_size))
    return ForumReportsPageOut(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        has_prev=page > 1,
        has_next=page < total_pages,
    )


@router.patch("/reports/{report_id}", response_model=ForumReportOut)
async def review_report(
    report_id: int,
    payload: ForumReportReviewIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Admin-only: mark a report as REVIEWED or DISMISSED."""
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Admin only")

    report = await db.get(ForumReport, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    report.status = payload.status
    report.reviewed_at = func.now()
    report.reviewed_by_id = user.id
    await db.commit()
    await db.refresh(report)
    return await _report_to_out(report, db)


# ------------------------------
# Thread following
# ------------------------------

@router.post("/threads/{thread_id}/follow", response_model=FollowToggleOut)
@limiter.limit("30/minute")
async def toggle_thread_follow(
    request: Request,
    thread_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Toggle follow on a thread. Follow if not following; unfollow if already following."""
    thread = await db.get(ForumThread, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    existing = (await db.execute(
        select(ForumFollower).where(
            ForumFollower.thread_id == thread_id,
            ForumFollower.user_id == user.id,
        ).limit(1)
    )).scalars().first()

    if existing:
        await db.delete(existing)
        following = False
    else:
        db.add(ForumFollower(thread_id=thread_id, user_id=user.id))
        following = True

    await db.commit()

    follower_count = int((await db.execute(
        select(func.count(ForumFollower.id)).where(ForumFollower.thread_id == thread_id)
    )).scalar_one() or 0)

    return FollowToggleOut(following=following, follower_count=follower_count)


@router.get("/me/following", response_model=PageOut)
async def get_my_following(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Paginated list of threads the signed-in user is following."""
    total_stmt = select(func.count(ForumFollower.id)).where(ForumFollower.user_id == user.id)
    total = int((await db.execute(total_stmt)).scalar_one() or 0)

    rows = (await db.execute(
        select(ForumThread)
        .join(ForumFollower, ForumFollower.thread_id == ForumThread.id)
        .where(ForumFollower.user_id == user.id)
        .order_by(ForumFollower.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).scalars().all()

    items = [await _thread_to_out(t, db, viewer_id=user.id) for t in rows]
    total_pages = max(1, math.ceil(total / page_size))
    return PageOut(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        has_prev=page > 1,
        has_next=page < total_pages,
    )


# ------------------------------
# Post bookmarking
# ------------------------------

@router.post("/threads/{thread_id}/posts/{post_id}/bookmark", response_model=BookmarkToggleOut)
@limiter.limit("60/minute")
async def toggle_post_bookmark(
    request: Request,
    thread_id: int,
    post_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Toggle bookmark on a post. Bookmark if not bookmarked; remove if already bookmarked."""
    post = await db.get(ForumPost, post_id)
    if not post or post.thread_id != thread_id:
        raise HTTPException(status_code=404, detail="Post not found")

    existing = (await db.execute(
        select(ForumBookmark).where(
            ForumBookmark.post_id == post_id,
            ForumBookmark.user_id == user.id,
        ).limit(1)
    )).scalars().first()

    if existing:
        await db.delete(existing)
        bookmarked = False
    else:
        db.add(ForumBookmark(post_id=post_id, thread_id=thread_id, user_id=user.id))
        bookmarked = True

    await db.commit()
    return BookmarkToggleOut(bookmarked=bookmarked)


@router.get("/me/bookmarks", response_model=PostsPageOut)
async def get_my_bookmarks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Paginated list of posts the signed-in user has bookmarked, newest bookmark first."""
    total_stmt = select(func.count(ForumBookmark.id)).where(ForumBookmark.user_id == user.id)
    total = int((await db.execute(total_stmt)).scalar_one() or 0)

    bookmarks = (await db.execute(
        select(ForumBookmark)
        .where(ForumBookmark.user_id == user.id)
        .order_by(ForumBookmark.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).scalars().all()

    items: list[ForumPostOut] = []
    for bm in bookmarks:
        post = await db.get(ForumPost, bm.post_id)
        if post:
            items.append(await _post_to_out(post, db, user))

    total_pages = max(1, math.ceil(total / page_size))
    return PostsPageOut(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        has_prev=page > 1,
        has_next=page < total_pages,
    )


# ==============================
# Forum Categories
# ==============================

@router.get("/categories", response_model=List[ForumCategoryOut])
async def list_categories(
    db: AsyncSession = Depends(get_async_session),
):
    """Public. Returns all visible categories ordered by position, each with a thread count."""
    rows = (await db.execute(
        select(ForumCategory)
        .where(ForumCategory.is_visible == True)
        .order_by(ForumCategory.position.asc(), ForumCategory.id.asc())
    )).scalars().all()

    out = []
    for cat in rows:
        count = int((await db.execute(
            select(func.count(ForumThread.id)).where(ForumThread.category_id == cat.id)
        )).scalar_one() or 0)
        out.append(ForumCategoryOut(
            id=cat.id,
            name=cat.name,
            slug=cat.slug,
            description=cat.description,
            position=cat.position,
            thread_count=count,
        ))
    return out


@router.post("/categories", response_model=ForumCategoryOut, status_code=201)
async def create_category(
    payload: CreateCategoryIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Admin only. Create a new forum category."""
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required")

    # Unique name + slug enforced by DB constraint, but give a nice error
    existing = (await db.execute(
        select(ForumCategory).where(
            (ForumCategory.name == payload.name) | (ForumCategory.slug == payload.slug)
        ).limit(1)
    )).scalars().first()
    if existing:
        raise HTTPException(status_code=409, detail="A category with that name or slug already exists")

    cat = ForumCategory(
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
        position=payload.position or 0,
    )
    db.add(cat)
    await db.commit()
    await db.refresh(cat)

    return ForumCategoryOut(
        id=cat.id,
        name=cat.name,
        slug=cat.slug,
        description=cat.description,
        position=cat.position,
        thread_count=0,
    )


@router.patch("/categories/{category_id}", response_model=ForumCategoryOut)
async def update_category(
    category_id: int,
    payload: UpdateCategoryIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Admin only. Update name, slug, description, position, or visibility."""
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required")

    cat = await db.get(ForumCategory, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    if payload.name is not None:
        cat.name = payload.name
    if payload.slug is not None:
        cat.slug = payload.slug
    if payload.description is not None:
        cat.description = payload.description
    if payload.position is not None:
        cat.position = payload.position
    if payload.is_visible is not None:
        cat.is_visible = payload.is_visible

    await db.commit()
    await db.refresh(cat)

    thread_count = int((await db.execute(
        select(func.count(ForumThread.id)).where(ForumThread.category_id == cat.id)
    )).scalar_one() or 0)

    return ForumCategoryOut(
        id=cat.id,
        name=cat.name,
        slug=cat.slug,
        description=cat.description,
        position=cat.position,
        thread_count=thread_count,
    )


@router.delete("/categories/{category_id}", status_code=204)
async def delete_category(
    category_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Admin only. Delete a category only if it has no threads; returns 409 otherwise."""
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required")

    cat = await db.get(ForumCategory, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    thread_count = int((await db.execute(
        select(func.count(ForumThread.id)).where(ForumThread.category_id == category_id)
    )).scalar_one() or 0)
    if thread_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete: {thread_count} thread(s) still belong to this category. Re-assign them first.",
        )

    await db.delete(cat)
    await db.commit()
