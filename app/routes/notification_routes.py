import math
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models.notification_model import Notification
from app.models.user_model import User
from app.utils.token_utils import get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


# ──────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────

class NotificationOut(BaseModel):
    id: int
    kind: str
    is_read: bool
    created_at: str
    read_at: Optional[str] = None
    thread_id: Optional[int] = None
    post_id: Optional[int] = None
    actor_username: Optional[str] = None
    summary: Optional[str] = None


class NotificationsPageOut(BaseModel):
    items: List[NotificationOut]
    page: int
    page_size: int
    total: int
    total_pages: int
    has_prev: bool
    has_next: bool
    unread_count: int


class UnreadCountOut(BaseModel):
    count: int


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

async def _notif_to_out(n: Notification, db: AsyncSession) -> NotificationOut:
    actor_username: Optional[str] = None
    if n.actor_id:
        actor = await db.get(User, n.actor_id)
        actor_username = getattr(actor, "username", None) if actor else None

    return NotificationOut(
        id=n.id,
        kind=n.kind,
        is_read=n.is_read,
        created_at=str(n.created_at),
        read_at=str(n.read_at) if n.read_at else None,
        thread_id=n.thread_id,
        post_id=n.post_id,
        actor_username=actor_username,
        summary=n.summary,
    )


# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────

@router.get("", response_model=NotificationsPageOut)
async def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    unread_only: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Paginated list of notifications for the signed-in user, newest first."""
    base_filter = [Notification.user_id == user.id]
    if unread_only:
        base_filter.append(Notification.is_read == False)

    total = int((await db.execute(
        select(func.count(Notification.id)).where(*base_filter)
    )).scalar_one() or 0)

    unread_count = int((await db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id,
            Notification.is_read == False,
        )
    )).scalar_one() or 0)

    rows = (await db.execute(
        select(Notification)
        .where(*base_filter)
        .order_by(Notification.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).scalars().all()

    items = [await _notif_to_out(n, db) for n in rows]
    total_pages = max(1, math.ceil(total / page_size))

    return NotificationsPageOut(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        has_prev=page > 1,
        has_next=page < total_pages,
        unread_count=unread_count,
    )


@router.get("/unread-count", response_model=UnreadCountOut)
async def get_unread_count(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Lightweight endpoint for polling the notification badge count."""
    count = int((await db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id,
            Notification.is_read == False,
        )
    )).scalar_one() or 0)
    return UnreadCountOut(count=count)


@router.patch("/{notification_id}/read", response_model=NotificationOut)
async def mark_notification_read(
    notification_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Mark a single notification as read."""
    notif = await db.get(Notification, notification_id)
    if not notif or notif.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found")

    if not notif.is_read:
        from sqlalchemy import func as sqlfunc
        notif.is_read = True
        notif.read_at = sqlfunc.now()
        await db.commit()
        await db.refresh(notif)

    return await _notif_to_out(notif, db)


@router.post("/read-all", status_code=204)
async def mark_all_read(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Mark all of the signed-in user's unread notifications as read."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    await db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.is_read == False)
        .values(is_read=True, read_at=now)
    )
    await db.commit()
