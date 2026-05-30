from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database import Base

SCHEMA = "man_review"


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = ({"schema": SCHEMA},)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # THREAD_REPLY  — someone replied to a thread the user authored
    # THREAD_FOLLOW_REPLY — someone replied to a thread the user follows
    # POST_MENTION  — someone @-mentioned the user in a post
    kind = Column(String(30), nullable=False)
    is_read = Column(Boolean, nullable=False, server_default="false", default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    read_at = Column(DateTime(timezone=True), nullable=True)

    # Contextual FKs — only the fields relevant to the notification kind are set
    thread_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_threads.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    post_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.forum_posts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    actor_id = Column(
        Integer,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Human-readable summary so the notification can render without joining every table
    summary = Column(String(300), nullable=True)
