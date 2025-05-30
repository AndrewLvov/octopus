"""Script to process Telegram stories and generate summaries."""

import logging
import re
import pytz
from datetime import datetime as dtime
from typing import List, Tuple
import asyncio

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError, DBAPIError

from octopus.processing.story_processor import StoryProcessor, EmptySummaryResult
from octopus.db.models.telegram import TelegramStory
from octopus.db.models.summaries import (
    ProcessedItem, ItemTagRelation, ItemEntityRelation
)
from octopus.db.models.url_content import URLContent
from octopus.db.session import session_scope
from octopus.processing.content_extractor import DiffBotExtractor
from octopus.db.operations import get_or_create_tag, get_or_create_entity, ensure_required_tags

logger = logging.getLogger(__name__)

REQUIRED_TAGS = ["machine learning", "generative ai", "cybersecurity"]

# Initialize processors
story_processor = StoryProcessor(required_tags=REQUIRED_TAGS)
content_extractor = DiffBotExtractor()


def extract_urls(content: str) -> List[str]:
    """
    Extract URLs from message content.
    
    Args:
        content: The message content to extract URLs from
        
    Returns:
        List[str]: List of extracted URLs
    """
    # URL regex pattern
    url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+'
    return re.findall(url_pattern, content)


async def process_story_content(
        story_content: str, urls_content: List[str] = None
) -> Tuple[str, List[Tuple[str, float]], List[Tuple[str, str, float, str]]]:
    """
    Process story content using story processor.
    
    Args:
        story_content: The content to process
        urls_content: Optional list of content extracted from URLs
        
    Returns:
        Tuple[str, List[Tuple[str, float]], List[Tuple[str, str, float, str]]]: 
            A tuple containing the summary, list of (tag, score) tuples, and list of (name, type, score, context) tuples
    """
    # Combine URL content if available
    target_content = "\n\n".join(urls_content) if urls_content else None
    return await story_processor.process_content(story_content, target_content, None)


async def process_telegram_stories(force_regenerate: bool = False) -> None:
    """
    Process Telegram stories to generate summaries, tags, and entities.
    
    Args:
        force_regenerate: If True, regenerate summaries for all stories, even if they already exist
    """
    with session_scope() as db:
        try:
            # Ensure required tags exist
            ensure_required_tags(db, REQUIRED_TAGS)
            
            # Process stories in batches
            batch_size = 100
            offset = 0
            
            while True:
                # Get batch of stories
                stmt = (
                    select(TelegramStory)
                    .outerjoin(
                        ProcessedItem,
                        (ProcessedItem.related_item_type == "telegram_story") &
                        (ProcessedItem.related_item_id == TelegramStory.id)
                    )
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
                            ProcessedItem.related_item_type == "telegram_story",
                            ProcessedItem.related_item_id == story.id
                        )
                    ).scalar_one_or_none()

                    if processed_item and not force_regenerate:
                        continue

                    # Extract URLs if not already present
                    if not story.urls:
                        urls = extract_urls(story.content)
                        story.urls = urls
                        db.commit()

                    # Get or extract content from URLs
                    url_contents = []
                    if story.urls:
                        now = pytz.utc.localize(dtime.now())
                        for url in story.urls:
                            # Check if we have cached content
                            url_content = db.execute(
                                select(URLContent).where(URLContent.url == url)
                            ).scalar_one_or_none()

                            if url_content:
                                if url_content.target_content:
                                    url_contents.append(url_content.target_content)
                                continue

                            # Extract content if not cached
                            content = content_extractor.extract_content(url)
                            if content:
                                url_contents.append(content)
                                # Cache the content
                                url_content = URLContent(
                                    url=url,
                                    target_content=content,
                                    extracted_at=now,
                                    last_checked_at=now
                                )
                                db.add(url_content)
                                db.flush()

                    # Process story content
                    try:
                        summary, tags, entities = await process_story_content(
                            story.content, url_contents)
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
                            related_item_type="telegram_story",
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

                    logger.info(f"Processed Telegram story {story.id}")
                    db.commit()
                
                # Move to next batch
                offset += batch_size
                
        except (SQLAlchemyError, DBAPIError) as e:
            logger.error(f"Database error in main processing loop: {str(e)}")
            raise


async def main() -> None:
    """Main entry point for the script"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Process Telegram stories')
    parser.add_argument(
        '--force-regenerate',
        action='store_true',
        help='Regenerate summaries for all stories, even if they already exist'
    )
    
    args = parser.parse_args()
    await process_telegram_stories(force_regenerate=args.force_regenerate)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
