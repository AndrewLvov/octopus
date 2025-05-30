import logging
import asyncio
import ssl
import certifi
import pytz
from datetime import datetime as dtime

import aiohttp
from sqlalchemy.exc import SQLAlchemyError, DBAPIError

from octopus.db.models.hacker_news import Story
from octopus.db.session import session_scope
from octopus.scripts.hn_update_story_votes import fetch_story_ids, fetch_story_info, update_story_votes
from octopus.processing.url_normalizer import normalize_url

logger = logging.getLogger(__name__)

async def get_new_stories() -> None:
    """
    Fetch and store new stories from Hacker News.

    Raises:
        aiohttp.ClientError: If there's a network or HTTP error
        SQLAlchemyError: If there's a database error
    """
    logger.info("Fetching new stories")
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    try:
        new_story_ids = await fetch_story_ids()
        logger.info("Found %d new stories", len(new_story_ids))

        async with aiohttp.ClientSession() as session:
            with session_scope() as db:
                try:
                    for new_story_id in new_story_ids:
                        try:
                            story = db.get(Story, new_story_id)
                            if story:
                                continue

                            story_info = await fetch_story_info(session, new_story_id, ssl_context)

                            if story_info.get('dead'):
                                continue

                            url = story_info.get('url')
                            if url:
                                # url = await normalize_url(url)
                                url = url[:1024] if url else None

                            story = Story(
                                id=new_story_id,
                                title=story_info['title'],
                                url=url,
                                content=story_info.get('text'),
                                posted_at=pytz.utc.localize(
                                    dtime.fromtimestamp(story_info['time'])
                                ),
                                user=story_info['by']
                            )
                            db.add(story)

                        except aiohttp.ClientError as e:
                            logger.error("Failed to fetch story %d: %s", new_story_id, str(e))
                            continue
                        except KeyError as e:
                            logger.error("Invalid story data for %d: %s", new_story_id, str(e))
                            continue

                        db.commit()

                except (SQLAlchemyError, DBAPIError) as e:
                    db.rollback()
                    logger.error("Database error while storing stories: %s", str(e))
                    raise

    except aiohttp.ClientError as e:
        logger.error("Failed to fetch story IDs: %s", str(e))
        raise


async def main() -> None:
    """Main entry point for the script"""
    try:
        await get_new_stories()
    except (aiohttp.ClientError, SQLAlchemyError) as e:
        logger.error("Script failed: %s", str(e))
        raise

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
