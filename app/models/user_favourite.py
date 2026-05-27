from sqlalchemy import Column, Integer, ForeignKey, UniqueConstraint
from app.database import Base


class UserFavourite(Base):
    __tablename__ = "user_favourites"
    __table_args__ = (
        UniqueConstraint("user_id", "series_id", name="uq_user_favourite_series"),
        {"schema": "man_review"},
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("man_review.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    series_id = Column(
        Integer,
        ForeignKey("man_review.series.id", ondelete="CASCADE"),
        nullable=False,
    )
    position = Column(Integer, nullable=False)  # 0–5
