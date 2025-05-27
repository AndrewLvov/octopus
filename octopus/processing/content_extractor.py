"""
Content extraction using DiffBot API.
"""
import logging
import time
from typing import Optional
import requests
from requests.exceptions import HTTPError
from sqlalchemy.orm import Session

from octopus.settings import settings
from octopus.db.models.hacker_news import Story

logger = logging.getLogger(__name__)

class DiffBotExtractor:
    """Handles content extraction using DiffBot API."""

    def __init__(self):
        self.api_key = settings.diffbot_api_key
        self.api_url = "https://api.diffbot.com/v3/article"

    def extract_content(self, url: str, max_retries: int = 3, initial_delay: float = 1.0) -> Optional[str]:
        """
        Extract article content from a URL using DiffBot API.
        
        Args:
            url: The URL to extract content from
            max_retries: Maximum number of retry attempts for rate limit errors
            initial_delay: Initial delay in seconds between retries (doubles with each retry)
            
        Returns:
            Optional[str]: The extracted article content, or None if extraction failed
        """
        # Skip mailto: URLs as they're not valid for content extraction
        if url.startswith('mailto:'):
            logger.info(f"Skipping mailto URL: {url}")
            return None

        delay = initial_delay
        attempt = 0

        while attempt < max_retries:
            try:
                params = {
                    "token": self.api_key,
                    "url": url
                }
                response = requests.get(self.api_url, params=params)
                response.raise_for_status()

                data = response.json()
                if "objects" in data and len(data["objects"]) > 0:
                    article = data["objects"][0]
                    return article.get("text")

                return None

            except HTTPError as e:
                if e.response.status_code == 429:  # Too Many Requests
                    if attempt < max_retries - 1:
                        logger.warning(f"Rate limit hit, retrying in {delay} seconds...")
                        time.sleep(delay)
                        delay *= 2  # Exponential backoff
                        attempt += 1
                        continue
                logger.error(f"Error extracting content from {url}: {str(e)}")
                return None

        return None
            

def update_story_content(db: Session, story: Story) -> bool:
    """
    Update a story's target_content by extracting content from its URL.
    
    Args:
        db: Database session
        story: Story to update
        
    Returns:
        bool: True if content was successfully extracted and updated
    """
    if not story.url:
        logger.info(f"Story {story.id} has no URL to extract content from")
        return False
        
    extractor = DiffBotExtractor()
    content = extractor.extract_content(story.url)
    
    if content:
        story.target_content = content
        db.commit()
        logger.info(f"Updated target content for story {story.id}")
        return True
        
    logger.warning(f"Failed to extract content for story {story.id}")
    return False
