#!/usr/bin/env python3
"""
Script to update stories' target_content using DiffBot API.
"""
import logging
from sqlalchemy import select

from octopus.db.session import session_scope
from octopus.db.models.hacker_news import Story
from octopus.processing.content_extractor import update_story_content

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    """Update target content for stories that don't have it yet."""
    with session_scope() as db:
        # Get stories that have URLs but no target content
        stmt = select(Story).where(
            Story.url.isnot(None),
            Story.target_content.is_(None)
        )
        stories = db.execute(stmt).scalars().all()
        
        logger.info(f"Found {len(stories)} stories to process")
        
        success_count = 0
        for story in stories:
            if not story.target_content:
                if update_story_content(db, story):
                    success_count += 1
                
        logger.info(f"Successfully updated {success_count} out of {len(stories)} stories")

if __name__ == "__main__":
    main()
