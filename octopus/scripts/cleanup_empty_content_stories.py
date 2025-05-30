"""Script to cleanup processed items where related email story has empty target content."""

import logging
from sqlalchemy import select, delete
from sqlalchemy.exc import SQLAlchemyError

from octopus.db.models.emails import EmailStory
from octopus.db.models.summaries import ProcessedItem, ItemTagRelation, ItemEntityRelation
from octopus.db.session import session_scope

logger = logging.getLogger(__name__)


def cleanup_empty_content_stories() -> None:
    """Remove processed items where related email story has empty target content."""
    with session_scope() as db:
        try:
            # Find processed items where related email story has null content
            stmt = (
                select(ProcessedItem.id)
                .join(
                    EmailStory,
                    (ProcessedItem.related_item_type == "email_story") &
                    (ProcessedItem.related_item_id == EmailStory.id)
                )
                .where(EmailStory.target_content.is_(None))
            )
            items_to_delete = db.execute(stmt).scalars().all()

            if not items_to_delete:
                logger.info("No items to cleanup")
                return

            # Delete tag relations
            db.execute(
                delete(ItemTagRelation)
                .where(ItemTagRelation.item_id.in_(items_to_delete))
            )

            # Delete entity relations
            db.execute(
                delete(ItemEntityRelation)
                .where(ItemEntityRelation.item_id.in_(items_to_delete))
            )

            # Delete processed items
            db.execute(
                delete(ProcessedItem)
                .where(ProcessedItem.id.in_(items_to_delete))
            )

            db.commit()
            logger.info(f"Cleaned up {len(items_to_delete)} processed items")

        except SQLAlchemyError as e:
            logger.error(f"Database error during cleanup: {str(e)}")
            raise


def main() -> None:
    """Main entry point for the script."""
    cleanup_empty_content_stories()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
