"""Script to process AI digest emails and extract links for analysis."""

import asyncio
import os
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from octopus.data_providers.gmail import GmailDigestProvider
from octopus.db.models.emails import DigestEmail, DigestLink, EmailStory
from octopus.db.session import session_scope
from octopus.settings import settings
from octopus.processing.url_normalizer import normalize_url_async


async def process_links(
    session: Session,
    email: DigestEmail,
    links: List[dict],
    metadata: dict
) -> None:
    """Process and store links from an email."""
    for link_data in links:
        # Normalize URL
        normalized_url = await normalize_url_async(link_data['url'])
        
        # Check if link already exists for this email
        existing_link = session.scalar(
            select(DigestLink).where(
                DigestLink.email_id == email.id,
                DigestLink.url == normalized_url
            )
        )
        if existing_link:
            continue

        # Check if story with this URL already exists
        existing_story = session.scalar(
            select(EmailStory).where(EmailStory.url == normalized_url)
        )

        link = DigestLink(
            email=email,
            url=normalized_url,
            title=link_data['title'],
            context=link_data['context']
        )

        if existing_story:
            link.story = existing_story
            link.processed = True
        else:
            # Create new story
            story = EmailStory(
                url=normalized_url,
                title=link_data['title'],
                discovered_at=metadata['received_at'],
                source_email_id=email.id
            )
            session.add(story)
            link.story = story
            link.processed = True

        session.add(link)


async def process_message(
    session: Session,
    message_data: dict,
    provider: GmailDigestProvider
) -> Optional[DigestEmail]:
    """Process a single digest email message."""
    # Check if message exists
    existing = session.scalar(
        select(DigestEmail).where(DigestEmail.message_id == message_data['id'])
    )
    if existing:
        return existing

    # Get message details
    message_details = provider.get_message_details(message_data['id'])
    if not message_details:
        return None

    # Extract metadata
    metadata = provider.parse_message_metadata(message_details)
    
    # Extract content
    content = provider.get_message_content(message_details)

    # Create email
    email = DigestEmail(
        message_id=message_data['id'],
        sender=metadata['sender'],
        subject=metadata['subject'],
        received_at=metadata['received_at'],
        content_text=content['text'],
        content_html=content['html']
    )
    session.add(email)

    # Extract and store links
    links = provider.extract_links_from_content(content)
    await process_links(session, email, links, metadata)

    return email


async def main():
    """Main function to process digest emails."""
    if not settings.gmail_credentials_path or not settings.gmail_token_path:
        raise ValueError("Gmail credentials and token paths must be configured in settings")
    
    provider = GmailDigestProvider(settings.gmail_credentials_path, settings.gmail_token_path)
    provider.authenticate()

    # Get recent digest emails
    messages = provider.get_digest_emails(
        days=30,  # Emails from last 30 days
        max_results=200
    )

    with session_scope() as session:
        for message_data in messages:
            email = await process_message(session, message_data, provider)
            if email:
                session.commit()


if __name__ == '__main__':
    asyncio.run(main())
