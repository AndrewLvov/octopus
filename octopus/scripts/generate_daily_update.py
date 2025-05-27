"""Script to get new stories, update HN comments, and generate digests."""

import asyncio
import logging

from octopus.scripts.telegram_get_new_stories import main as get_telegram_stories
from octopus.scripts.hn_get_new_stories import main as get_hn_stories
from octopus.scripts.email_process_stories import main as get_email_stories
from octopus.scripts.hn_update_story_comments import main as update_hn_comments
from octopus.scripts.generate_tech_digest import main as generate_tech_digest

logger = logging.getLogger(__name__)

async def main():
    """Run the daily update process."""
    try:
        # Get new stories from all sources
        logger.info("Getting new stories from Telegram...")
        await get_telegram_stories()
        
        logger.info("Getting new stories from Hacker News...")
        await get_hn_stories()
        
        logger.info("Getting new stories from Email...")
        await get_email_stories()
        
        # Update HN comments
        logger.info("Updating Hacker News comments...")
        await update_hn_comments()
        
        # Generate digests
        logger.info("Generating tech digest...")
        await generate_tech_digest()

        logger.info("Daily update completed successfully")
        
    except Exception as e:
        logger.error(f"Error during daily update: {str(e)}")
        raise

if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler()  # Output to console
        ]
    )
    
    asyncio.run(main())
