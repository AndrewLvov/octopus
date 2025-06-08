"""Script to generate a comprehensive digest of AI/ML/cybersecurity stories using LLM analysis."""

import logging
import os
from datetime import datetime as dtime, timedelta, UTC
from decimal import Decimal
from typing import List, Tuple, Optional

from sqlalchemy import select, and_, desc
from sqlalchemy.orm import Session, joinedload

from octopus.db.session import session_scope
from octopus.db.models.summaries import (
    ProcessedItem,
    ItemTagRelation,
    ItemTag,
    ItemEntityRelation,
    ItemEntity
)
from octopus.db.models.digests import Digest, DigestStory
from octopus.db.models.hacker_news import Story
from octopus.db.models.emails import EmailStory
from octopus.db.models.telegram import TelegramStory
from octopus.genai.processor import GenAIProcessor, ResponseFormat

logger = logging.getLogger(__name__)

# Tags we're interested in
RELEVANT_TAGS = [
    "artificial intelligence",
    "machine learning",
    "generative ai",
    "large language models",
    "cybersecurity",
    "computer vision",
    "natural language processing"
]

MIN_TAG_SCORE = Decimal("0.3")  # Lower the threshold to catch more potential insights
DEFAULT_DAYS = 7

# Approximate token limits (4 chars per token)
MAX_CONTEXT_TOKENS = 100_000  # Leave room for prompt and response
CHARS_PER_TOKEN = 4


def _load_prompt() -> str:
    """Load the tech digest prompt."""
    prompt_path = "octopus/genai/prompts/tech_digest.txt"
    try:
        with open(prompt_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        logger.error(f"Prompt file not found: {prompt_path}")
        raise


def _estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in text using character count."""
    return len(text) // CHARS_PER_TOKEN


def _format_story_context(story: ProcessedItem, db: Session, use_summary: bool = False) -> tuple[str, int]:
    """
    Format a story for context using full content or summary based on use_summary flag.
    
    Returns:
        tuple: (formatted context string, content length in characters)
    """
    title = "Untitled"
    url = ""
    content = ""

    # Get the related story based on type
    if story.related_item_type == "hacker_news_story":
        stmt = select(Story).where(Story.id == story.related_item_id)
        related_story = db.execute(stmt).scalar_one_or_none()
        if related_story:
            title = related_story.title if related_story.title else "Untitled"
            url = f" ({related_story.url})" if related_story.url else ""
            content = related_story.target_content or related_story.content or ""
    elif story.related_item_type == "email_story":
        stmt = select(EmailStory).where(EmailStory.id == story.related_item_id)
        related_story = db.execute(stmt).scalar_one_or_none()
        if related_story:
            title = related_story.title if related_story.title else "Untitled"
            url = f" ({related_story.url})" if related_story.url else ""
            content = related_story.target_content or ""
    elif story.related_item_type == "telegram_story":
        stmt = select(TelegramStory).where(TelegramStory.id == story.related_item_id)
        related_story = db.execute(stmt).scalar_one_or_none()
        if related_story:
            title = f"Telegram: {related_story.channel_id}"
            url = f" (Message ID: {related_story.message_id})"
            content = related_story.content
    
    # Use summary if flag is set or no content available
    if use_summary or not content.strip():
        content_section = f"Summary:\n{story.summary}"
    else:
        content_section = f"Content:\n{content}"
    
    # Format entities information
    entities_section = ""
    if story.entities:
        entities_section = "Entities:\n"
        for relation in story.entities:
            entity = relation.entity
            entities_section += f"- {entity.name} ({entity.type})"
        entities_section += "\n"

    formatted_context = f"""Story: {title}{url}
Type: {story.related_item_type}
ID: {story.related_item_id}
{entities_section}{content_section}
---
"""
    return formatted_context, len(content)


def get_relevant_stories(
    db: Session,
    start_date: dtime,
    end_date: dtime,
    min_score: Decimal = MIN_TAG_SCORE
) -> List[ProcessedItem]:
    """Get relevant stories within the specified date range."""
    # Query for relevant stories
    stmt = (
        select(ProcessedItem)
        .join(ItemTagRelation)
        .join(ItemTag)
        .where(
            and_(
                ProcessedItem.created_at >= start_date,
                ProcessedItem.created_at <= end_date,
                ItemTag.name.in_(RELEVANT_TAGS),
                ItemTagRelation.relation_value >= min_score
            )
        )
        .order_by(desc(ProcessedItem.created_at))
        .distinct()
        .options(
            joinedload(ProcessedItem.tags).joinedload(ItemTagRelation.tag),
            joinedload(ProcessedItem.entities).joinedload(ItemEntityRelation.entity)
        )
    )
    
    return db.execute(stmt).unique().scalars().all()


def prepare_context(stories: List[ProcessedItem], prompt_tokens: int, db: Session) -> str:
    """
    Prepare context for the LLM by fitting stories within token limit.
    Falls back to summaries for largest stories if content exceeds the token limit.
    """
    available_tokens = MAX_CONTEXT_TOKENS - prompt_tokens
    context_parts = []
    story_sizes = []  # List of (index, content_length) tuples
    total_tokens = 0
    
    # First pass: Try to include full content for all stories
    for i, story in enumerate(stories):
        story_context, content_length = _format_story_context(story, db, use_summary=False)
        tokens = _estimate_tokens(story_context)
        story_sizes.append((i, content_length))
        total_tokens += tokens
        context_parts.append(story_context)
    
    # If total tokens exceed the limit, replace the largest stories with summaries
    if total_tokens > available_tokens:
        logger.info(f"Total tokens ({total_tokens}) exceed limit ({available_tokens}), "
                    f"replacing largest stories with summaries")
        
        # Sort stories by content length, the largest first
        story_sizes.sort(key=lambda x: x[1], reverse=True)
        
        # Replace largest stories with summaries until we're under the token limit
        for idx, _ in story_sizes:
            if total_tokens <= available_tokens:
                break
                
            # Replace full content with summary for this story
            old_context = context_parts[idx]
            new_context, _ = _format_story_context(stories[idx], db, use_summary=True)
            
            # Update total tokens
            total_tokens -= _estimate_tokens(old_context)
            total_tokens += _estimate_tokens(new_context)
            
            # Replace the context
            context_parts[idx] = new_context
            logger.info(f"Replaced content with summary for story {stories[idx].related_item_id}")
    
    return "\n".join(context_parts)


async def main(start_date: Optional[dtime] = None, end_date: Optional[dtime] = None):
    """Generate and print tech digest for the specified time period.
    
    Args:
        start_date: Start date for the digest. If None, defaults to DEFAULT_DAYS ago
        end_date: End date for the digest. If None, defaults to current time
    """
    processor = GenAIProcessor()
    
    try:
        prompt_template = _load_prompt()
        prompt_tokens = _estimate_tokens(prompt_template)
        
        with session_scope() as db:
            # Set default date range if not provided
            if end_date is None:
                end_date = dtime.now(UTC)
            if start_date is None:
                start_date = end_date - timedelta(days=DEFAULT_DAYS)

            stories = get_relevant_stories(db, start_date=start_date, end_date=end_date)
            logger.info(f"Found {len(stories)} relevant stories between {start_date} and {end_date}")
            
            if not stories:
                print("No relevant stories found in the specified time period.")
                return
            
            # Prepare context that fits within token limits
            context = prepare_context(stories, prompt_tokens, db)
            logger.info(f"Prepared context with {_estimate_tokens(context)} tokens")
            
            # Format prompt with context
            prompt = prompt_template.format(context=context)
            
            # Generate digest using LLM
            logger.info("Generating digest with LLM...")
            digest = await processor.process(
                prompt,
                response_format=ResponseFormat.RAW,
                temperature=0.3  # Lower temperature for more focused analysis
            )
            
            # Create a digests directory if it doesn't exist
            os.makedirs("data/digests", exist_ok=True)
            
            # Generate filename with the current datetime
            current_time = dtime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"data/digests/tech_digest_{current_time}.txt"
            
            # Write digest to file
            with open(filename, "w") as f:
                f.write(f"Tech Digest - {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}\n")
                f.write("=" * 40 + "\n")
                f.write(digest)
            
            logger.info(f"Digest saved to {filename}")
            
            # Save digest to a database
            db_digest = Digest(
                content=digest,
                start_date=start_date,
                end_date=end_date,
                file_path=filename
            )
            db.add(db_digest)
            
            # Link stories to digest
            for story in stories:
                db_digest_story = DigestStory(
                    digest=db_digest,
                    processed_item_id=story.id
                )
                db.add(db_digest_story)
            
            db.commit()
            logger.info(f"Digest saved to database with ID {db_digest.id}")
            
    except Exception as e:
        logger.error(f"Error generating digest: {str(e)}")
        raise

if __name__ == "__main__":
    import asyncio
    import sys
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler()  # Output to console
        ]
    )
    
    # Parse command line arguments for date range
    start_date = None
    end_date = None
    
    if len(sys.argv) > 2:
        # If both dates provided: start_date end_date
        start_date = dtime.fromisoformat(sys.argv[1]).replace(tzinfo=UTC)
        end_date = dtime.fromisoformat(sys.argv[2]).replace(tzinfo=UTC)
    elif len(sys.argv) > 1:
        # If only days provided (backward compatibility)
        days = int(sys.argv[1])
        end_date = dtime.now(UTC)
        start_date = end_date - timedelta(days=days)
    
    asyncio.run(main(start_date, end_date))
