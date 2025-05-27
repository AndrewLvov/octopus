"""Telegram data provider for fetching stories from channels."""

import logging
import pytz
from datetime import datetime as dtime
from typing import List, Optional

from telethon import TelegramClient
from telethon.tl.types import Message

from octopus.db.models.telegram import TelegramStory
from octopus.db.session import get_session

logger = logging.getLogger(__name__)


class TelegramProvider:
    """Provider for fetching stories from Telegram channels."""

    def __init__(self, api_id: str, api_hash: str, session_name: str = "octopus"):
        """
        Initialize Telegram provider.

        Args:
            api_id: Telegram API ID
            api_hash: Telegram API hash
            session_name: Name for the Telegram session file
        """
        self.client = TelegramClient(session_name, api_id, api_hash)

    async def start(self):
        """Start the Telegram client."""
        await self.client.start()

    async def stop(self):
        """Stop the Telegram client."""
        await self.client.disconnect()

    async def get_channel_messages(
        self,
        channel: str,
        limit: Optional[int] = None,
        min_id: Optional[int] = None
    ) -> List[Message]:
        """
        Get messages from a Telegram channel.

        Args:
            channel: Channel username or ID
            limit: Maximum number of messages to fetch
            min_id: Only fetch messages newer than this ID

        Returns:
            List[Message]: List of Telegram messages
        """
        try:
            messages = []
            async for message in self.client.iter_messages(
                channel,
                limit=limit,
                min_id=min_id,
                reverse=True  # Get oldest messages first
            ):
                if message.text:  # Only get messages with text
                    messages.append(message)
            return messages
        except Exception as e:
            logger.error(f"Error fetching messages from {channel}: {str(e)}")
            return []

    async def save_messages(self, channel: str, messages: List[Message]) -> None:
        """
        Save Telegram messages to database if they don't already exist.

        Args:
            channel: Channel username or ID
            messages: List of messages to save
        """
        with get_session() as db:
            for message in messages:
                # Check if message already exists
                existing = db.query(TelegramStory).filter(
                    TelegramStory.channel_id == str(channel),
                    TelegramStory.message_id == str(message.id)
                ).first()

                if not existing:
                    # Create new story
                    story = TelegramStory(
                        channel_id=str(channel),
                        message_id=str(message.id),
                        content=message.text,
                        posted_at=message.date,
                        discovered_at=pytz.utc.localize(dtime.now())
                    )
                    db.add(story)
                    logger.info(f"Added new message {message.id} from channel {channel}")
                else:
                    logger.debug(f"Message {message.id} from channel {channel} already exists")

            db.commit()
