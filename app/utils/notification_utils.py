from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.notification_model import Notification
from app.models.user_model import User
from app.models.forum_model import ForumThread, ForumFollower
from app.utils.mention_utils import extract_mentions


async def notify_mentions(
    content: str,
    thread_id: int,
    post_id: int,
    actor_id: int,
    db: AsyncSession,
) -> None:
    """Parse @mentions in post content and create POST_MENTION notifications."""
    usernames = extract_mentions(content)
    for username in usernames:
        target = (await db.execute(
            select(User).where(User.username.ilike(username)).limit(1)
        )).scalars().first()
        if target and target.id != actor_id:
            db.add(Notification(
                user_id=target.id,
                kind="POST_MENTION",
                thread_id=thread_id,
                post_id=post_id,
                actor_id=actor_id,
                summary="mentioned you in a post",
            ))


async def notify_thread_reply(
    thread_id: int,
    post_id: int,
    actor_id: int,
    db: AsyncSession,
) -> None:
    """Notify the thread author (THREAD_REPLY) and all followers (THREAD_FOLLOW_REPLY)."""
    thread = await db.get(ForumThread, thread_id)
    if not thread:
        return

    notified: set[int] = {actor_id}  # never notify the replier about their own reply

    # Notify thread author
    if thread.author_id and thread.author_id not in notified:
        db.add(Notification(
            user_id=thread.author_id,
            kind="THREAD_REPLY",
            thread_id=thread_id,
            post_id=post_id,
            actor_id=actor_id,
            summary="replied to your thread",
        ))
        notified.add(thread.author_id)

    # Notify all followers who haven't already been notified
    followers = (await db.execute(
        select(ForumFollower).where(ForumFollower.thread_id == thread_id)
    )).scalars().all()

    for f in followers:
        if f.user_id not in notified:
            db.add(Notification(
                user_id=f.user_id,
                kind="THREAD_FOLLOW_REPLY",
                thread_id=thread_id,
                post_id=post_id,
                actor_id=actor_id,
                summary="posted in a thread you follow",
            ))
            notified.add(f.user_id)
