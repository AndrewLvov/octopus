import logging
import json
import pytz
from datetime import datetime as dtime
from typing import List, Tuple
import asyncio

from sqlalchemy import select, desc
from sqlalchemy.exc import SQLAlchemyError, DBAPIError
from octopus.processing.story_processor import StoryProcessor, EmptySummaryResult
from octopus.db.models.hacker_news import Story, StoryVotes
from octopus.db.models.summaries import (
    ProcessedItem, ItemTag, ItemTagRelation, ItemEntity, ItemEntityRelation
)
from octopus.db.session import get_session

logger = logging.getLogger(__name__)

REQUIRED_TAGS = ["machine learning", "generative ai", "cybersecurity"]


def ensure_required_tags(db) -> None:
    """
    Ensure required tags exist in the database.
    
    Args:
        db: Database session
    """
    for tag_name in REQUIRED_TAGS:
        stmt = select(ItemTag).where(ItemTag.name == tag_name)
        tag = db.execute(stmt).scalar_one_or_none()

        if not tag:
            tag = ItemTag(name=tag_name)
            db.add(tag)

    db.commit()


def get_or_create_tag(db, tag_name: str) -> ItemTag:
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


def get_or_create_entity(db, name: str, entity_type: str) -> ItemEntity:
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

# Initialize story processor
processor = StoryProcessor(required_tags=REQUIRED_TAGS)

async def process_story_content(story_content: str, target_content: str = None, comments: List[str] = None) -> Tuple[str, List[Tuple[str, float]], List[Tuple[str, str, float, str]]]:
    """
    Process story content and comments using story processor.
    
    Args:
        story_content: The content to process
        target_content: Optional extracted article content
        comments: Optional list of comment texts to include in analysis
        
    Returns:
        Tuple[str, List[Tuple[str, float]], List[Tuple[str, str, float, str]]]: 
            A tuple containing the summary, list of (tag, score) tuples, and list of (name, type, score, context) tuples
    """
    return await processor.process_content(story_content, target_content, comments)


async def process_stories(force_regenerate: bool = False) -> None:
    """
    Process stories to generate summaries, tags, and entities.
    
    Args:
        force_regenerate: If True, regenerate summaries for all stories, even if they already exist
    """
    with get_session() as db:
        try:
            # Ensure required tags exist
            ensure_required_tags(db)
            
            # Process stories in batches
            batch_size = 100
            offset = 0
            
            while True:
                # Get batch of stories
                # Subquery to get latest vote count for each story
                latest_votes = (
                    select(StoryVotes.story_id, StoryVotes.vote_count)
                    .distinct(StoryVotes.story_id)
                    .order_by(StoryVotes.story_id, desc(StoryVotes.tstamp))
                    .subquery()
                )

                stmt = (
                    select(Story)
                    .outerjoin(
                        ProcessedItem,
                        (ProcessedItem.related_item_type == "hacker_news_story") &
                        (ProcessedItem.related_item_id == Story.id)
                    )
                    .join(
                        latest_votes,
                        Story.id == latest_votes.c.story_id
                    )
                    .where(latest_votes.c.vote_count > 100)  # Only process stories with >100 votes
                )
                
                if not force_regenerate:
                    stmt = stmt.where(ProcessedItem.id.is_(None))
                    
                stmt = stmt.limit(batch_size).offset(offset)
                stories = db.execute(stmt).unique().scalars().all()
                
                if not stories:
                    break
                
                # Process current batch
                for story in stories:
                    processed_item = db.execute(
                        select(ProcessedItem).where(
                            ProcessedItem.related_item_type == "hacker_news_story",
                            ProcessedItem.related_item_id == story.id
                        )
                    ).scalar_one_or_none()
                    if processed_item and not force_regenerate:
                        continue
                    # Get story comments
                    comments = [comment.content for comment in story.comments if not comment.deleted]
                    
                    # Process story content with comments
                    try:
                        summary, tags, entities = await process_story_content(
                            story.content, story.target_content, comments)
                    except EmptySummaryResult:
                        logger.warning(f"Failed to process story {story.id}")
                        continue
                    
                        # Get existing or create new processed item
                    if force_regenerate:
                        if processed_item:
                            # Delete existing relations
                            db.execute(
                                ItemTagRelation.__table__.delete().where(
                                    ItemTagRelation.item_id == processed_item.id
                                )
                            )
                            db.execute(
                                ItemEntityRelation.__table__.delete().where(
                                    ItemEntityRelation.item_id == processed_item.id
                                )
                            )
                            
                            # Update existing item
                            processed_item.created_at = pytz.utc.localize(dtime.now())
                            processed_item.summary = summary
                            db.flush()

                    if not processed_item:
                        processed_item = ProcessedItem(
                            created_at=pytz.utc.localize(dtime.now()),
                            summary=summary,
                            related_item_type="hacker_news_story",
                            related_item_id=story.id
                        )
                        db.add(processed_item)
                        db.flush()  # To get processed_item.id

                    # Create tag relations
                    tag_dict = dict(tags)

                    # Ensure required tags are included with at least 0.5 score
                    for required_tag in REQUIRED_TAGS:
                        if required_tag not in tag_dict:
                            tag_dict[required_tag] = 0.0

                    # Create tag relations
                    for tag_name, score in tag_dict.items():
                        tag = get_or_create_tag(db, tag_name)
                        relation = ItemTagRelation(
                            item_id=processed_item.id,
                            tag_id=tag.id,
                            relation_value=score
                        )
                        db.add(relation)

                    # Create entity relations
                    for name, entity_type, score, context in entities:
                        entity = get_or_create_entity(db, name, entity_type)
                        relation = ItemEntityRelation(
                            item_id=processed_item.id,
                            entity_id=entity.id,
                            relation_value=score,
                            context=context
                        )
                        db.add(relation)

                    logger.info(f"Processed story {story.id}")
                    db.commit()
                
                # Move to next batch
                offset += batch_size
                
        except (SQLAlchemyError, DBAPIError) as e:
            logger.error(f"Database error in main processing loop: {str(e)}")
            raise

async def main() -> None:
    """Main entry point for the script"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate story summaries')
    parser.add_argument(
        '--force-regenerate',
        action='store_true',
        help='Regenerate summaries for all stories, even if they already exist'
    )
    
    args = parser.parse_args()
    await process_stories(force_regenerate=args.force_regenerate)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
