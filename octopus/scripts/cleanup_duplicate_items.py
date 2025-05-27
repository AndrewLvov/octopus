import logging
from sqlalchemy import select, func, text
from octopus.db.session import get_session
from octopus.db.models.summaries import ProcessedItem
from octopus.db.models.hacker_news import Story

logger = logging.getLogger(__name__)

def cleanup_duplicate_items():
    """
    Clean up duplicate ProcessedItems for hacker_news_stories, keeping only the latest one.
    Deletes all older duplicates.
    """
    with get_session() as db:
        try:
            # First, get all story IDs that have duplicates
            duplicate_stories = (
                db.query(ProcessedItem.related_item_id)
                .filter(ProcessedItem.related_item_type == 'hacker_news_story')
                .group_by(ProcessedItem.related_item_id)
                .having(func.count(ProcessedItem.id) > 1)
                .all()
            )
            
            duplicate_count = 0
            kept_count = 0
            
            # For each story with duplicates
            for (story_id,) in duplicate_stories:
                # Get all items for this story, ordered by creation date
                items = (
                    db.query(ProcessedItem)
                    .filter(
                        ProcessedItem.related_item_type == 'hacker_news_story',
                        ProcessedItem.related_item_id == story_id
                    )
                    .order_by(ProcessedItem.created_at.desc())
                    .all()
                )
                
                # Keep the first (latest) one, delete the rest
                kept_count += 1
                items_to_delete = items[1:]  # Skip the first item (latest)
                duplicate_count += len(items_to_delete)
                
                if items_to_delete:
                    # Delete duplicates with CASCADE
                    db.execute(
                        text("DELETE FROM processed_stories WHERE id = ANY(:ids)"),
                        {"ids": [item.id for item in items_to_delete]}
                    )
            
            db.commit()
            logger.info(f"Cleanup complete. Kept {kept_count} items, deleted {duplicate_count} duplicates")

        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
            db.rollback()
            raise

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    cleanup_duplicate_items()
