"""Database models for Telegram channel stories."""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY

from .base import Base
from sqlalchemy.orm import relationship, foreign
from octopus.db.models.summaries import ProcessedItem

class TelegramStory(Base):
    """
    Represents a story from a Telegram channel.

    Attributes:
        id (int): The primary key
        channel_id (str): ID of the Telegram channel
        message_id (str): ID of the message in the channel
        content (str): The message content
        urls (List[str]): List of URLs found in the message
        posted_at (datetime): When the message was posted
        discovered_at (datetime): When we discovered the message
    """
    __tablename__ = "telegram_stories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(String(100), nullable=False)
    message_id = Column(String(100), nullable=False)
    content = Column(String, nullable=False)
    urls = Column(ARRAY(String), nullable=True)
    posted_at = Column(DateTime(timezone=True), nullable=False)
    discovered_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index('idx_telegram_stories_posted_at', 'posted_at'),
        Index('idx_telegram_stories_channel', 'channel_id'),
        Index('idx_telegram_stories_message', 'message_id'),
        UniqueConstraint('channel_id', 'message_id', name='uq_telegram_stories_channel_message'),
    )

    # Relationship to ProcessedItem for summary/tags/entities
    processed_item = relationship(
        "ProcessedItem",
        primaryjoin="and_(foreign(ProcessedItem.related_item_id)==TelegramStory.id, ProcessedItem.related_item_type=='telegram_story')",
        uselist=False,
        viewonly=True
    )

    def __repr__(self) -> str:
        return f"<TelegramStory(id={self.id}, channel={self.channel_id}, message={self.message_id})>"
