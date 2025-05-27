#!/usr/bin/env python3
"""Script to normalize existing URLs in the database."""

import asyncio
import logging
from collections import defaultdict
from sqlalchemy import select, update, delete
from sqlalchemy.orm import Session

from octopus.db.models.emails import DigestLink, EmailStory
from octopus.db.models.hacker_news import Story
from octopus.db.session import get_session
from octopus.processing.url_normalizer import normalize_url

logger = logging.getLogger(__name__)


async def get_url_mapping(urls):
    """Create mapping of original URLs to their normalized versions."""
    mapping = {}
    for url in urls:
        try:
            normalized = await normalize_url(url)
            mapping[url] = normalized
        except Exception as e:
            logger.error(f"Error normalizing URL {url}: {e}")
            mapping[url] = url  # Keep original if normalization fails
    return mapping


async def find_conflicts(mapping):
    """Find URLs that would normalize to the same target."""
    conflicts = defaultdict(list)
    for original, normalized in mapping.items():
        if original != normalized:  # Only track URLs that would change
            conflicts[normalized].append(original)
    return {k: v for k, v in conflicts.items() if len(v) > 1}


async def normalize_digest_links(session: Session) -> int:
    """Normalize URLs in digest_links table."""
    # Get all unique URLs
    stmt = select(DigestLink.url).distinct()
    urls = session.execute(stmt).scalars().all()
    
    # Create URL mapping and find conflicts
    mapping = await get_url_mapping(urls)
    conflicts = await find_conflicts(mapping)
    
    updated = 0
    for normalized, originals in conflicts.items():
        # For each set of conflicting URLs, keep one and update others to point to it
        keep_url = originals[0]
        other_urls = originals[1:]
        
        # Get all links that use the URLs we want to update
        for url in other_urls:
            # Find links using this URL
            links = session.execute(
                select(DigestLink).where(DigestLink.url == url)
            ).scalars().all()
            
            # Update each link to use the URL we're keeping
            for link in links:
                link.url = normalized
            updated += len(links)
        
        session.commit()
    
    # Now handle non-conflicting URLs
    for url, normalized in mapping.items():
        if url != normalized and url not in {u for urls in conflicts.values() for u in urls}:
            stmt = update(DigestLink).where(DigestLink.url == url).values(url=normalized)
            result = session.execute(stmt)
            updated += result.rowcount
            session.commit()
    
    return updated


async def normalize_email_stories(session: Session) -> int:
    """Normalize URLs in email_stories table."""
    stmt = select(EmailStory.url).distinct()
    urls = session.execute(stmt).scalars().all()
    
    mapping = await get_url_mapping(urls)
    updated = 0
    
    for url, normalized in mapping.items():
        if url != normalized:
            # Check if normalized URL already exists
            existing = session.scalar(
                select(EmailStory).where(EmailStory.url == normalized)
            )
            if not existing:
                stmt = update(EmailStory).where(EmailStory.url == url).values(url=normalized)
                result = session.execute(stmt)
                updated += result.rowcount
                session.commit()
    
    return updated


async def normalize_hn_stories(session: Session) -> int:
    """Normalize URLs in stories table."""
    stmt = select(Story.url).distinct().where(Story.url.isnot(None))
    urls = session.execute(stmt).scalars().all()
    
    mapping = await get_url_mapping(urls)
    updated = 0
    
    for url, normalized in mapping.items():
        if url != normalized:
            # Check if normalized URL already exists
            existing = session.scalar(
                select(Story).where(Story.url == normalized)
            )
            if not existing:
                stmt = update(Story).where(Story.url == url).values(url=normalized)
                result = session.execute(stmt)
                updated += result.rowcount
                session.commit()
    
    return updated


async def main():
    """Main entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    with get_session() as session:
        try:
            # Update URLs in each table
            digest_links = await normalize_digest_links(session)
            email_stories = await normalize_email_stories(session)
            hn_stories = await normalize_hn_stories(session)
            
            print(f"\nUpdated URLs:")
            print(f"- Digest Links: {digest_links}")
            print(f"- Email Stories: {email_stories}")
            print(f"- HN Stories: {hn_stories}")
            print(f"Total: {digest_links + email_stories + hn_stories}")
            
        except Exception as e:
            logger.error(f"Error: {e}")
            session.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(main())
