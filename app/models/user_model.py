from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import relationship

from app.database import Base

class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "man_review"}

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    role = Column(String, default="GENERAL")  # GENERAL, CONTRIBUTOR, or ADMIN
    email = Column(String, unique=True, index=True, nullable=True)
    is_verified = Column(Boolean, default=False, nullable=False, server_default="false")
    avatar_url = Column(String, nullable=True)
    avatar_preset = Column(String, nullable=True, default="blue")
    signup_platform = Column(String, nullable=False, default="web", server_default="web")
    auth_provider = Column(String, nullable=False, default="email", server_default="email")

    registered_at = Column(DateTime(timezone=True), nullable=True)
    cred_score = Column(Integer, nullable=False, server_default="0", default=0)

    reading_lists = relationship("ReadingList", cascade="all, delete-orphan", backref="owner")

