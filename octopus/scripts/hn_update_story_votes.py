import logging
import asyncio
import ssl
import certifi
import pytz
from datetime import datetime as dtime
from typing import Set, Dict, Any

import aiohttp
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError, DBAPIError
from octopus.db.models.hacker_news import Story, StoryVotes
from octopus.data_providers.hacker_news import API_URL
from octopus.db.session import get_session

logger = logging.getLogger(__name__)

async def fetch_story_ids() -> Set[int]:
    """
    Fetch list of new story IDs from Hacker News API.
    
    Returns:
        Set[int]: Set of story IDs
        
    Raises:
        aiohttp.ClientError: If there's a network or HTTP error
        json.JSONDecodeError: If the response is not valid JSON
    """
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://hacker-news.firebaseio.com/v0/newstories.json?print=pretty",
            ssl=ssl_context
        ) as response:
            if response.status != 200:
                raise aiohttp.ClientError(f"Hacker News returned HTTP {response.status}")
            return set(await response.json())

async def fetch_story_info(session: aiohttp.ClientSession, story_id: int, ssl_context: ssl.SSLContext) -> Dict[str, Any]:
    """
    Fetch story details from Hacker News API.
    
    Args:
        session: aiohttp client session
        story_id: ID of the story to fetch
        ssl_context: SSL context for HTTPS requests
        
    Returns:
        Dict[str, Any]: Story information
        
    Raises:
        aiohttp.ClientError: If there's a network or HTTP error
        json.JSONDecodeError: If the response is not valid JSON
    """
    async with session.get(
        f"{API_URL}/v0/item/{story_id}.json?print=pretty",
        ssl=ssl_context
    ) as response:
        if response.status != 200:
            raise aiohttp.ClientError(f"Hacker News returned HTTP {response.status}")
        return await response.json()


async def update_story_votes() -> None:
    """
    Update vote counts for existing stories.
    
    Raises:
        aiohttp.ClientError: If there's a network or HTTP error
        SQLAlchemyError: If there's a database error
    """
    logger.info("Updating story votes")
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    
    with get_session() as db:
        try:
            async with aiohttp.ClientSession() as session:
                # Load all stories with their IDs
                result = db.execute(select(Story.id))
                story_ids = result.scalars().all()
                
                batch_size = 10
                
                for i, story_id in enumerate(story_ids, 1):
                    try:
                        # Fetch latest vote for this story
                        vote_result = db.execute(
                            select(StoryVotes.vote_count)
                            .where(StoryVotes.story_id == story_id)
                            .order_by(StoryVotes.tstamp.desc())
                            .limit(1)
                        )
                        last_vote_count = vote_result.scalar_one_or_none()

                        story_info = await fetch_story_info(session, story_id, ssl_context)
                        story_score = story_info.get('score')
                        
                        if story_score is None or (last_vote_count and last_vote_count == story_score):
                            continue

                        story_vote = StoryVotes(
                            story_id=story_id,
                            vote_count=story_score,
                            tstamp=pytz.utc.localize(dtime.now())
                        )
                        db.add(story_vote)
                        
                        # Commit every batch_size records
                        if i % batch_size == 0:
                            db.commit()
                            logger.info("Committed batch of %d vote updates", batch_size)
                        
                    except aiohttp.ClientError as e:
                        logger.error("Failed to fetch votes for story %d: %s", story_id, str(e))
                        continue
                
                # Commit any remaining records
                if i % batch_size != 0:
                    db.commit()
                    logger.info("Committed final batch of %d vote updates", i % batch_size)
                
        except (SQLAlchemyError, DBAPIError) as e:
            db.rollback()
            logger.error("Database error while updating votes: %s", str(e))
            raise


async def main() -> None:
    """Main entry point for the script"""
    try:
        await update_story_votes()
    except (aiohttp.ClientError, SQLAlchemyError) as e:
        logger.error("Script failed: %s", str(e))
        raise

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
