"""Script to fetch new stories from Telegram channels."""

import logging
import asyncio
from typing import List
from sqlalchemy import select, func

from octopus.data_providers.telegram import TelegramProvider
from octopus.db.models.telegram import TelegramStory
from octopus.db.session import session_scope
from octopus.settings import settings

logger = logging.getLogger(__name__)


async def get_latest_message_id(channel: str) -> int:
    """
    Get the latest message ID we have for a channel.
    
    Args:
        channel: Channel username or ID
        
    Returns:
        int: Latest message ID or 0 if no messages exist
    """
    with session_scope() as db:
        result = db.execute(
            select(func.max(TelegramStory.message_id))
            .where(TelegramStory.channel_id == str(channel))
        ).scalar()
        return int(result) if result else 0


async def fetch_new_stories() -> None:
    """Fetch new stories from configured Telegram channels."""
    provider = TelegramProvider(
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash
    )

    try:
        # Start Telegram client
        await provider.start()

        # Process each channel
        for channel in settings.telegram_channels:
            # Get latest message ID we have for this channel
            latest_id = await get_latest_message_id(channel)

            # Fetch new messages
            messages = await provider.get_channel_messages(
                channel=channel,
                limit=100,
                min_id=latest_id
            )

            if messages:
                # Save new messages
                await provider.save_messages(channel, messages)
                logger.info(
                    f"Saved {len(messages)} new messages from channel {channel}"
                )
            else:
                logger.info(f"No new messages from channel {channel}")

    finally:
        # Always disconnect client
        await provider.stop()


async def main() -> None:
    """Main entry point for the script."""
    await fetch_new_stories()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
