"""Shared database operations."""

from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from octopus.db.models.summaries import ItemTag, ItemEntity


def get_or_create_tag(db: Session, tag_name: str) -> ItemTag:
    """
    Get existing tag or create new one.
    
    Args:
        db: Database session
        tag_name: Name of the tag to get or create
        
    Returns:
        ItemTag: The retrieved or created tag
    """
    stmt = select(ItemTag).where(ItemTag.name == tag_name)
    tag = db.execute(stmt).scalar_one_or_none()

    if not tag:
        tag = ItemTag(name=tag_name)
        db.add(tag)
        db.commit()

    return tag


def get_or_create_entity(db: Session, name: str, entity_type: str) -> ItemEntity:
    """
    Get existing entity or create new one.
    
    Args:
        db: Database session
        name: Name of the entity
        entity_type: Type of the entity (company, product, person, framework)
        
    Returns:
        ItemEntity: The retrieved or created entity
    """
    stmt = select(ItemEntity).where(
        ItemEntity.name == name,
        ItemEntity.type == entity_type
    )
    entity = db.execute(stmt).scalar_one_or_none()

    if not entity:
        entity = ItemEntity(
            name=name,
            type=entity_type
        )
        db.add(entity)
        db.commit()

    return entity


def ensure_required_tags(db: Session, required_tags: list[str]) -> None:
    """
    Ensure required tags exist in the database.
    
    Args:
        db: Database session
        required_tags: List of required tag names
    """
    for tag_name in required_tags:
        stmt = select(ItemTag).where(ItemTag.name == tag_name)
        tag = db.execute(stmt).scalar_one_or_none()

        if not tag:
            tag = ItemTag(name=tag_name)
            db.add(tag)

    db.commit()
