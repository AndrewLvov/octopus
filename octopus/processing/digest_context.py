"""Common functionality for generating digest contexts."""

from datetime import datetime, timedelta, UTC
from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy import select, and_, desc
from sqlalchemy.orm import Session, joinedload

from octopus.db.models.summaries import (
    ProcessedItem,
    ItemTagRelation,
    ItemTag,
    ItemEntityRelation,
    ItemEntity
)
from octopus.db.models.hacker_news import Story
from octopus.db.models.emails import EmailStory
from octopus.db.models.telegram import TelegramStory

# Approximate token limits (4 chars per token)
MAX_CONTEXT_TOKENS = 100_000  # Leave room for prompt and response
CHARS_PER_TOKEN = 4

def estimate_tokens(text: str) -> int:
    """Estimate number of tokens in text using character count."""
    return len(text) // CHARS_PER_TOKEN

def format_story_context(
    story: ProcessedItem,
    db: Session,
    use_summary: bool = False,
    relevant_entity_types: Optional[List[str]] = None
) -> tuple[str, int]:
    """
    Format a story for context using full content or summary based on use_summary flag.
    
    Args:
        story: The ProcessedItem to format
        db: Database session
        use_summary: Whether to use summary instead of full content
        relevant_entity_types: Optional list of entity types to filter by
    
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
            content = related_story.target_content or related_story.content or ""
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
        relevant_entities = story.entities
        if relevant_entity_types:
            relevant_entities = [
                relation for relation in story.entities 
                if relation.entity.entity_type in relevant_entity_types
            ]
        if relevant_entities:
            entities_section = "Entities:\n"
            for relation in relevant_entities:
                entity = relation.entity
                entities_section += f"- {entity.name} ({entity.entity_type}): {entity.description or 'No description available'}\n"
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
    relevant_tags: List[str],
    days: int,
    min_score: Decimal
) -> List[ProcessedItem]:
    """Get relevant stories from the last N days."""
    cutoff_date = datetime.now(UTC) - timedelta(days=days)
    
    # Query for relevant stories
    stmt = (
        select(ProcessedItem)
        .join(ItemTagRelation)
        .join(ItemTag)
        .where(
            and_(
                ProcessedItem.created_at >= cutoff_date,
                ItemTag.name.in_(relevant_tags),
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

def prepare_context(
    stories: List[ProcessedItem],
    prompt_tokens: int,
    db: Session,
    relevant_entity_types: Optional[List[str]] = None
) -> str:
    """
    Prepare context for the LLM by fitting stories within token limit.
    Falls back to summaries for largest stories if content exceeds token limit.
    """
    available_tokens = MAX_CONTEXT_TOKENS - prompt_tokens
    context_parts = []
    story_sizes = []  # List of (index, content_length) tuples
    total_tokens = 0
    
    # First pass: Try to include full content for all stories
    for i, story in enumerate(stories):
        story_context, content_length = format_story_context(
            story,
            db,
            use_summary=False,
            relevant_entity_types=relevant_entity_types
        )
        tokens = estimate_tokens(story_context)
        story_sizes.append((i, content_length))
        total_tokens += tokens
        context_parts.append(story_context)
    
    # If total tokens exceed limit, replace largest stories with summaries
    if total_tokens > available_tokens:
        # Sort stories by content length, largest first
        story_sizes.sort(key=lambda x: x[1], reverse=True)
        
        # Replace largest stories with summaries until we're under the token limit
        for idx, _ in story_sizes:
            if total_tokens <= available_tokens:
                break
                
            # Replace full content with summary for this story
            old_context = context_parts[idx]
            new_context, _ = format_story_context(
                stories[idx],
                db,
                use_summary=True,
                relevant_entity_types=relevant_entity_types
            )
            
            # Update total tokens
            total_tokens -= estimate_tokens(old_context)
            total_tokens += estimate_tokens(new_context)
            
            # Replace the context
            context_parts[idx] = new_context
    
    return "\n".join(context_parts)
