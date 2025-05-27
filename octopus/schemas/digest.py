"""Pydantic models for tech digest data."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel


class TagScore(BaseModel):
    """Tag with its relevance score."""
    name: str
    score: Decimal


class EntityMention(BaseModel):
    """Entity mention with context and score."""
    name: str
    type: str
    context: str
    score: Decimal


class DigestStory(BaseModel):
    """Story with its metadata, tags, and entities."""
    processed_item_id: int
    created_at: datetime
    summary: str
    url: Optional[str] = None
    title: Optional[str] = None
    tags: List[TagScore]
    entities: List[EntityMention]
