"""SQLAlchemy models for tech digests."""

from datetime import datetime
from typing import List

from sqlalchemy import String, DateTime, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from octopus.db.models.base import Base
from octopus.db.models.summaries import ProcessedItem


class Digest(Base):
    """Tech digest model storing generated content and metadata."""
    __tablename__ = "digests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content: Mapped[str] = mapped_column(String, nullable=False)
    start_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False
    )
    end_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow
    )
    file_path: Mapped[str] = mapped_column(String, nullable=False)

    # Relationships
    stories: Mapped[List["DigestStory"]] = relationship(
        "DigestStory",
        back_populates="digest",
        cascade="all, delete-orphan"
    )


class DigestStory(Base):
    """Association table linking digests to their stories."""
    __tablename__ = "digest_stories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    digest_id: Mapped[int] = mapped_column(
        ForeignKey("digests.id", ondelete="CASCADE"),
        nullable=False
    )
    processed_item_id: Mapped[int] = mapped_column(
        ForeignKey("processed_stories.id", ondelete="CASCADE"),
        nullable=False
    )

    # Relationships
    digest: Mapped[Digest] = relationship(
        "Digest",
        back_populates="stories"
    )
    processed_item: Mapped[ProcessedItem] = relationship(
        "ProcessedItem"
    )
