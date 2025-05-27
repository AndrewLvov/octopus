"""Database models for digest emails and their extracted links."""

from datetime import datetime
from typing import List
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index, Boolean, UniqueConstraint
from sqlalchemy.orm import relationship

from .base import Base


class DigestEmail(Base):
    """
    Represents a digest email from AI newsletters/subscriptions.

    Attributes:
        id (int): The primary key
        message_id (str): Gmail message ID
        sender (str): Email address of the sender
        subject (str): Subject of the email
        received_at (datetime): When the email was received
        content_text (str): Plain text content
        content_html (str): HTML content if available
        extracted_links (List[DigestLink]): Links extracted from the email
    """
    __tablename__ = "digest_emails"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(String(100), unique=True, nullable=False)
    sender = Column(String(255), nullable=False)
    subject = Column(String(500), nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=False)
    content_text = Column(String, nullable=True)
    content_html = Column(String, nullable=True)

    # Relationships
    extracted_links = relationship(
        "DigestLink",
        back_populates="email",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index('idx_digest_emails_received_at', 'received_at'),
        Index('idx_digest_emails_sender', 'sender'),
    )


class EmailStory(Base):
    """
    Represents a story extracted from an email digest.

    Attributes:
        id (int): The primary key
        url (str): The URL of the story
        title (str): Title extracted from email context
        discovered_at (datetime): When the story was found in email
        source_email_id (int): ID of the email this came from
        target_content (str, optional): Content extracted from URL
    """
    __tablename__ = "email_stories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(2048), nullable=False)
    title = Column(String(500), nullable=False)
    discovered_at = Column(DateTime(timezone=True), nullable=False)
    source_email_id = Column(
        Integer,
        ForeignKey("digest_emails.id", ondelete="SET NULL"),
        nullable=True
    )
    target_content = Column(String, nullable=True)

    # Relationships
    source_email = relationship("DigestEmail")
    digest_links = relationship("DigestLink", back_populates="story")

    __table_args__ = (
        Index('idx_email_stories_discovered_at', 'discovered_at'),
        Index('idx_email_stories_url', 'url'),
    )


class DigestLink(Base):
    """
    Represents a link extracted from a digest email.

    Attributes:
        id (int): The primary key
        email_id (int): ID of the parent email
        url (str): The extracted URL
        title (str): Title or description of the link from email context
        context (str): Text surrounding the link
        processed (bool): Whether this link has been processed
        story_id (int): ID of the email story created from this link
    """
    __tablename__ = "digest_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email_id = Column(
        Integer,
        ForeignKey("digest_emails.id", ondelete="CASCADE"),
        nullable=False
    )
    url = Column(String(2048), nullable=False)
    title = Column(String(500), nullable=True)
    context = Column(String, nullable=True)
    processed = Column(Boolean, default=False, nullable=False)
    story_id = Column(
        Integer,
        ForeignKey("email_stories.id", ondelete="SET NULL"),
        nullable=True
    )

    # Relationships
    email = relationship("DigestEmail", back_populates="extracted_links")
    story = relationship("EmailStory", back_populates="digest_links")

    __table_args__ = (
        Index('idx_digest_links_processed', 'processed'),
        Index('idx_digest_links_url', 'url'),
        UniqueConstraint('email_id', 'url', name='uq_digest_links_email_url')
    )
