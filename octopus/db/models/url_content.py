"""Database models for URL content storage."""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import TEXT

from .base import Base


class URLContent(Base):
    """
    Stores extracted content for URLs.
    
    This model caches content extracted from URLs to avoid making repeated
    API calls to content extraction services like Diffbot.
    
    Attributes:
        id (int): The primary key
        url (str): The normalized URL
        target_content (str): The extracted content from the URL
        extracted_at (datetime): When the content was extracted
        last_checked_at (datetime): When the URL was last checked for updates
    """
    __tablename__ = "url_contents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(2048), nullable=False, unique=True)
    target_content = Column(TEXT, nullable=True)
    extracted_at = Column(DateTime(timezone=True), nullable=False)
    last_checked_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index('idx_url_contents_url', 'url'),
        Index('idx_url_contents_extracted_at', 'extracted_at'),
        Index('idx_url_contents_last_checked_at', 'last_checked_at'),
    )

    def __repr__(self) -> str:
        return f"<URLContent(id={self.id}, url={self.url})>"
