"""Pydantic models for tech digest data."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel


class TagScore(BaseModel):
    """Tag with its relevance score."""
    name: str
    score: Decimal

    model_config = {
        "from_attributes": True
    }


class EntityMention(BaseModel):
    """Entity mention with context and score."""
    name: str
    type: str
    context: str
    score: Decimal

    model_config = {
        "from_attributes": True
    }


class DigestStoryBase(BaseModel):
    """Story with its metadata, tags, and entities."""
    processed_item_id: int
    created_at: datetime
    summary: str
    url: Optional[str] = None
    title: Optional[str] = None
    tags: List[TagScore] = []
    entities: List[EntityMention] = []

    model_config = {
        "from_attributes": True
    }

    @classmethod
    def model_validate(cls, obj):
        return cls(
            processed_item_id=obj.processed_item_id,
            created_at=obj.processed_item.created_at,
            summary=obj.processed_item.summary,
            url=None,  # Set if needed
            title=None,  # Set if needed
            tags=[
                TagScore(
                    name=rel.tag.name,
                    score=rel.relation_value
                ) for rel in obj.processed_item.tags
            ],
            entities=[
                EntityMention(
                    name=rel.entity.name,
                    type=rel.entity.type,
                    context=rel.context,
                    score=rel.relation_value
                ) for rel in obj.processed_item.entities
            ]
        )


class DigestBase(BaseModel):
    """Base digest model."""
    content: str
    start_date: datetime
    end_date: datetime
    file_path: str


class DigestCreate(DigestBase):
    """Digest creation model."""
    pass


class DigestResponse(DigestBase):
    """Digest response model."""
    id: int
    created_at: datetime
    stories: List[DigestStoryBase]

    model_config = {
        "from_attributes": True
    }
