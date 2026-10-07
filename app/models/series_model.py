
from sqlalchemy import JSON, Column, Integer, String, Enum as SqlEnum
from sqlalchemy.orm import relationship
from app.database import Base
import enum

class SeriesType(enum.Enum):
    MANGA = "MANGA"
    MANHWA = "MANHWA"
    MANHUA = "MANHUA"

class SeriesStatus(enum.Enum):
    ONGOING = "ONGOING"
    COMPLETE = "COMPLETE"
    HIATUS = "HIATUS"
    UNKNOWN = "UNKNOWN"
    SEASON_END = "SEASON_END"

class SeriesApprovalStatus(enum.Enum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    APPROVED = "APPROVED"

class Series(Base):
    __tablename__ = 'series'
    __table_args__ = {"schema": "man_review"}

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    genre = Column(String)
    vote_count = Column(Integer, default=0)
    cover_url = Column(String)
    type = Column(SqlEnum(SeriesType), nullable=False)
    author = Column(String)
    artist = Column(String)
    external_source = Column(String, nullable=True)
    external_id = Column(String, nullable=True)
    external_url = Column(String, nullable=True)
    external_score = Column(Integer, nullable=True)
    external_popularity = Column(Integer, nullable=True)
    external_synced_at = Column(String, nullable=True)
    # [{"site": "Tapas", "url": "https://..."}] — official reading platforms
    where_to_read = Column(JSON, nullable=True)
    approval_status = Column(String, nullable=False, default=SeriesApprovalStatus.APPROVED.value)
    submitted_by_id = Column(Integer, nullable=True)
    approved_by_id = Column(Integer, nullable=True)
    approved_at = Column(String, nullable=True)

    status = Column(
        SqlEnum(
            SeriesStatus,
            name="series_status",
            schema="man_review",
            create_type=False,  # don't try to create; we already created via SQL
        ),
        nullable=True,
    )

    # Relationship to SeriesDetail
    detail = relationship(
        "SeriesDetail",
        back_populates="series",
        uselist=False,
        cascade="all, delete-orphan"
    )
