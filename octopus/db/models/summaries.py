"""Database models for processed items and their relations."""
from datetime import datetime
from decimal import Decimal
from typing import List

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, DECIMAL, Index
from sqlalchemy.orm import relationship

from .base import Base


class ProcessedItem(Base):
    """
    Represents a processed item with summary, tags, and entities.

    Attributes:
        id (int): The primary key, a unique identifier for the processed item
        created_at (datetime): When the item was processed
        summary (str): Generated summary of the item
        related_item_type (str): Type of the related item (e.g., "story", "document")
        related_item_id (int): ID of the related item
        tags (list[ItemTagRelation]): Related tags and their scores
    """
    __tablename__ = "processed_stories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    summary = Column(String, nullable=False)
    related_item_type = Column(String, nullable=False)
    related_item_id = Column(Integer, nullable=False)

    # Relationships
    tags = relationship("ItemTagRelation", back_populates="item")
    entities = relationship("ItemEntityRelation", back_populates="item")


class ItemTag(Base):
    """
    Represents a tag that items can be related to.

    Attributes:
        id (int): The primary key, a unique identifier for the tag
        name (str): The name of the tag, must be unique
        items (list[ItemTagRelation]): Items related to this tag
    """
    __tablename__ = "item_tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)

    # Relationships
    items = relationship("ItemTagRelation", back_populates="tag")


class ItemTagRelation(Base):
    """
    Represents a many-to-many relationship between items and tags.

    Attributes:
        item_id (int): ID of the processed item
        tag_id (int): ID of the tag
        relation_value (Decimal): Strength of the relationship (0.0 to 1.0)
        item (ProcessedItem): The related processed item
        tag (ItemTag): The related tag
    """
    __tablename__ = "item_tag_relations"

    item_id = Column(Integer, ForeignKey("processed_stories.id", ondelete="CASCADE"), primary_key=True)
    tag_id = Column(Integer, ForeignKey("item_tags.id", ondelete="CASCADE"), primary_key=True)
    relation_value = Column(DECIMAL(precision=3, scale=2), nullable=False)

    # Relationships
    item = relationship("ProcessedItem", back_populates="tags")
    tag = relationship("ItemTag", back_populates="items")

    __table_args__ = (
        Index('idx_item_tag_relation_scores', 'relation_value'),
    )


class ItemEntity(Base):
    """
    Represents an entity that can be related to items.

    Attributes:
        id (int): The primary key, a unique identifier for the entity
        name (str): The name of the entity
        type (str): The type of entity (company, product, person, framework)
        items (list[ItemEntityRelation]): Items related to this entity
    """
    __tablename__ = "item_entities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)

    # Relationships
    items = relationship("ItemEntityRelation", back_populates="entity")

    __table_args__ = (
        Index('idx_item_entities_name_type', 'name', 'type'),
    )


class ItemEntityRelation(Base):
    """
    Represents a many-to-many relationship between items and entities.

    Attributes:
        item_id (int): ID of the processed item
        entity_id (int): ID of the entity
        relation_value (Decimal): Strength of the relationship (0.0 to 1.0)
        context (str): Description of how the entity is mentioned
        item (ProcessedItem): The related processed item
        entity (ItemEntity): The related entity
    """
    __tablename__ = "item_entity_relations"

    item_id = Column(Integer, ForeignKey("processed_stories.id", ondelete="CASCADE"), primary_key=True)
    entity_id = Column(Integer, ForeignKey("item_entities.id", ondelete="CASCADE"), primary_key=True)
    relation_value = Column(DECIMAL(precision=3, scale=2), nullable=False)
    context = Column(String, nullable=False)

    # Relationships
    item = relationship("ProcessedItem", back_populates="entities")
    entity = relationship("ItemEntity", back_populates="items")

    __table_args__ = (
        Index('idx_item_entity_relation_scores', 'relation_value'),
    )
