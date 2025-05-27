"""Database model for storing LLM prompts and their metadata."""

from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String, Text

from octopus.db.models.base import Base


class Prompt(Base):
    """Model for storing LLM prompts and their metadata."""

    __tablename__ = "prompts"

    id = Column(Integer, primary_key=True)
    prompt_text = Column(Text, nullable=False)
    response_text = Column(Text, nullable=False)
    response_format = Column(String(10), nullable=False)  # RAW, YAML, or JSON
    temperature = Column(String(10), nullable=True)
    max_tokens = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        """String representation of the Prompt."""
        return f"<Prompt(id={self.id}, created_at={self.created_at})>"
