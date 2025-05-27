import logging
import asyncio
import ssl
import certifi
import pytz
from datetime import datetime as dtime, timedelta, UTC
from typing import List, Dict, Any

import aiohttp
from sqlalchemy import select, or_
from sqlalchemy.exc import SQLAlchemyError, DBAPIError
from sqlalchemy.orm import Session

from octopus.db.models.hacker_news import Story, StoryComment
from octopus.db.session import get_session

logger = logging.getLogger(__name__)

async def fetch_story_comments(session: aiohttp.ClientSession, story_id: int, ssl_context: ssl.SSLContext) -> List[int]:
    """
    Fetch comment IDs for a story from the Hacker News API.

    Args:
        session: The aiohttp client session
        story_id: The ID of the story to fetch comments for
        ssl_context: SSL context for HTTPS requests

    Returns:
        List of comment IDs

    Raises:
        aiohttp.ClientError: If there's a network or HTTP error
    """
    url = f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
    async with session.get(url, ssl=ssl_context) as response:
        response.raise_for_status()
        story_data = await response.json()
        return story_data.get('kids', [])

async def fetch_comment_info(session: aiohttp.ClientSession, comment_id: int, ssl_context: ssl.SSLContext) -> Dict[str, Any]:
    """
    Fetch comment information from the Hacker News API.

    Args:
        session: The aiohttp client session
        comment_id: The ID of the comment to fetch
        ssl_context: SSL context for HTTPS requests

    Returns:
        Comment data dictionary

    Raises:
        aiohttp.ClientError: If there's a network or HTTP error
    """
    url = f"https://hacker-news.firebaseio.com/v0/item/{comment_id}.json"
    async with session.get(url, ssl=ssl_context) as response:
        response.raise_for_status()
        return await response.json()

async def process_comment(
    db: Session,
    session: aiohttp.ClientSession,
    comment_id: int,
    story_id: int,
    parent_id: int | None,
    ssl_context: ssl.SSLContext
) -> None:
    """
    Process a single comment, storing it in the database and recursively processing its replies.

    Args:
        db: Database session
        session: The aiohttp client session
        comment_id: The ID of the comment to process
        story_id: The ID of the story this comment belongs to
        parent_id: The ID of the parent comment, if any
        ssl_context: SSL context for HTTPS requests
    """
    try:
        # Check if comment already exists
        comment = db.get(StoryComment, comment_id)
        if comment:
            if comment.deleted:
                # Re-check if comment is still deleted
                comment_info = await fetch_comment_info(session, comment_id, ssl_context)
                if not comment_info.get('deleted', True):
                    comment.deleted = False
                    comment.content = comment_info.get('text', '')
                    db.commit()
            return

        comment_info = await fetch_comment_info(session, comment_id, ssl_context)
        
        # Skip deleted or dead comments
        if comment_info.get('deleted') or comment_info.get('dead'):
            return

        # Create new comment
        comment = StoryComment(
            id=comment_id,
            story_id=story_id,
            parent_id=parent_id,
            content=comment_info.get('text', ''),
            posted_at=pytz.utc.localize(
                dtime.fromtimestamp(comment_info['time'])
            ),
            user=comment_info['by'],
            deleted=False
        )
        db.add(comment)
        db.commit()

        # Process replies recursively
        if 'kids' in comment_info:
            for reply_id in comment_info['kids']:
                await process_comment(db, session, reply_id, story_id, comment_id, ssl_context)

    except aiohttp.ClientError as e:
        logger.error(f"Failed to fetch comment {comment_id}: {str(e)}")
    except KeyError as e:
        logger.error(f"Invalid comment data for {comment_id}: {str(e)}")

async def update_story_comments() -> None:
    """
    Update comments for all stories in the database.

    Raises:
        aiohttp.ClientError: If there's a network or HTTP error
        SQLAlchemyError: If there's a database error
    """
    logger.info("Starting comment update process")
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    try:
        async with aiohttp.ClientSession() as session:
            with get_session() as db:
                # Get current time in UTC
                now = dtime.now(tz=UTC)

                # Get stories that:
                # - are less than 2 days old AND
                # - either have no comments OR their last comment is older than 6 hours
                query = (
                    select(Story)
                    .where(
                        Story.posted_at >= (now - timedelta(days=2)),
                        or_(
                            ~Story.comments.any(),  # No comments
                            Story.comments.any(StoryComment.posted_at <= (now - timedelta(hours=6)))  # Old last comment
                        )
                    )
                )
                
                result = db.execute(query)
                stories = result.scalars().all()

                for story in stories:
                    # Skip if story has comments and the most recent one is newer than 6 hours
                    if story.comments:
                        latest_comment = story.comments[0]  # Comments are ordered by posted_at desc
                        if latest_comment.posted_at > (now - timedelta(hours=6)):
                            continue
                    try:
                        logger.info(f"Fetching comments for story {story.id}")
                        comment_ids = await fetch_story_comments(session, story.id, ssl_context)
                        
                        for comment_id in comment_ids:
                            await process_comment(db, session, comment_id, story.id, None, ssl_context)

                    except aiohttp.ClientError as e:
                        logger.error(f"Failed to fetch comments for story {story.id}: {str(e)}")
                        continue

    except (SQLAlchemyError, DBAPIError) as e:
        logger.error(f"Database error: {str(e)}")
        raise


async def main() -> None:
    """Main entry point for the script"""
    try:
        await update_story_comments()
    except (aiohttp.ClientError, SQLAlchemyError) as e:
        logger.error(f"Script failed: {str(e)}")
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
