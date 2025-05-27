"""
Database models for Hacker News stories, comments, and vote history.
"""

from typing import Optional
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index, CheckConstraint, Boolean
from sqlalchemy.orm import relationship, validates
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql import text

from .base import Base


class Story(Base):
    """
    Represents a Hacker News story in the database.

    Attributes:
        id (int): The primary key, a unique identifier for the story
        title (str): The title of the story (max 500 chars)
        url (str, optional): The URL of the story (max 2048 chars)
        content (str, optional): The text content of the story
        target_content (str, optional): The extracted article content from the URL using DiffBot
        posted_at (datetime): The time the story was posted
        user (str): The username of the poster (max 100 chars)
        votes (List[StoryVotes]): Vote history for this story
    """

    __tablename__ = "stories"

    id = Column(Integer, primary_key=True)
    url = Column(String(2048))  # Max URL length
    title = Column(String(500), nullable=False)
    content = Column(String)
    target_content = Column(String)
    posted_at = Column(DateTime(timezone=True), nullable=False)
    user = Column(String(100), nullable=False)

    # Relationships
    votes = relationship(
        "StoryVotes",
        back_populates="story",
        cascade="all, delete-orphan",
        order_by="desc(StoryVotes.tstamp)",
    )

    # Indexes
    __table_args__ = (
        Index('idx_stories_posted_at', 'posted_at'),
        Index('idx_stories_user', 'user'),
    )

    @hybrid_property
    def latest_votes(self) -> Optional[int]:
        """
        Get the most recent vote count for this story.
        
        Returns:
            Optional[int]: The latest vote count, or None if no votes exist
        """
        latest = next(iter(self.votes), None)
        return latest.vote_count if latest else None

    @validates('title')
    def validate_title(self, key: str, title: str) -> str:
        """Validate story title."""
        if not title or not title.strip():
            raise ValueError("Story title cannot be empty")
        return title.strip()

    @validates('url')
    def validate_url(self, key: str, url: Optional[str]) -> Optional[str]:
        """Validate story URL."""
        if url:
            url = url.strip()
            if len(url) > 2048:
                raise ValueError("URL is too long (max 2048 characters)")
        return url


class StoryComment(Base):
    """
    Represents a Hacker News story comment.

    Attributes:
        id (int): The primary key, a unique identifier for the comment
        story_id (int): The ID of the associated story
        parent_id (int, optional): The ID of the parent comment if this is a reply
        content (str): The text content of the comment
        posted_at (datetime): The time the comment was posted
        user (str): The username of the commenter
        deleted (bool): Whether the comment has been deleted
    """

    __tablename__ = "story_comments"

    id = Column(Integer, primary_key=True)
    story_id = Column(
        Integer,
        ForeignKey("stories.id", ondelete="CASCADE"),
        nullable=False
    )
    parent_id = Column(
        Integer,
        ForeignKey("story_comments.id", ondelete="CASCADE"),
        nullable=True
    )
    content = Column(String, nullable=False)
    posted_at = Column(DateTime(timezone=True), nullable=False)
    user = Column(String(100), nullable=False)
    deleted = Column(Boolean, default=False, nullable=False)

    # Relationships
    story = relationship("Story", back_populates="comments")
    parent = relationship("StoryComment", remote_side=[id], backref="replies")

    # Indexes
    __table_args__ = (
        Index('idx_story_comments_story_id', 'story_id'),
        Index('idx_story_comments_parent_id', 'parent_id'),
        Index('idx_story_comments_posted_at', 'posted_at'),
        Index('idx_story_comments_user', 'user'),
    )

    @validates('content')
    def validate_content(self, key: str, content: str) -> str:
        """Validate comment content."""
        if not content or not content.strip():
            raise ValueError("Comment content cannot be empty")
        return content.strip()


class StoryVotes(Base):
    """
    Represents the vote history for a Hacker News story.

    Attributes:
        id (int): The primary key, a unique identifier for the vote record
        story_id (int): The ID of the associated story
        story (Story): The associated story object
        vote_count (int): The number of votes at this point in time
        tstamp (datetime): The timestamp when this vote count was recorded
    """

    __tablename__ = "story_votes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    story_id = Column(
        Integer,
        ForeignKey("stories.id", ondelete="CASCADE"),
        nullable=False
    )
    vote_count = Column(Integer, nullable=False)
    tstamp = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text('now()')
    )

    # Relationships
    story = relationship("Story", back_populates="votes")

    # Constraints
    __table_args__ = (
        CheckConstraint('vote_count >= 0', name='positive_vote_count'),
        Index('idx_story_votes_story_time', 'story_id', 'tstamp'),
    )

    @validates('vote_count')
    def validate_vote_count(self, key: str, count: int) -> int:
        """Validate vote count is non-negative."""
        if count < 0:
            raise ValueError("Vote count cannot be negative")
        return count


# Update Story model to include comments relationship
Story.comments = relationship(
    "StoryComment",
    back_populates="story",
    cascade="all, delete-orphan",
    order_by="desc(StoryComment.posted_at)",
)
