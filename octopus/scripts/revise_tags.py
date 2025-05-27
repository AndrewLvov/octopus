"""Script to revise and improve tag organization."""
import os
import logging
import argparse
from typing import Dict, List, Union

from sqlalchemy import select
from sqlalchemy.orm import Session

from octopus.db.session import SessionLocal
from octopus.genai.processor import GenAIProcessor, ResponseFormat
from octopus.db.models.summaries import ItemTag, ItemTagRelation, ProcessedItem
from octopus.db.models.hacker_news import Story

logger = logging.getLogger(__name__)


def get_prompt() -> str:
    """Read the tag analysis prompt from file."""
    prompt_path = os.path.join(os.path.dirname(__file__), "..", "genai", "prompts", "revise_tags.txt")
    with open(prompt_path, "r") as f:
        return f.read()


def get_all_tags(session: Session) -> List[ItemTag]:
    """Get all tags from the database."""
    return session.query(ItemTag).all()


async def get_tag_mapping(
    processor: GenAIProcessor,
    tags: Union[List[ItemTag], List[str]]
) -> Dict[str, List[str]]:
    """Use LLM to analyze tags and get mapping suggestions."""
    # Handle both ItemTag objects and string tags
    tags_list = "\n".join(
        f"- {tag.name if isinstance(tag, ItemTag) else tag}"
        for tag in tags
    )
    prompt = get_prompt().format(tags=tags_list)

    try:
        # Use YAML response format with automatic validation, parsing and retries
        result = await processor.process(
            prompt,
            response_format=ResponseFormat.YAML
        )
        
        if not isinstance(result, dict) or "tag_mapping" not in result:
            raise ValueError("Response must contain 'tag_mapping' key")
        
        tag_mapping = result["tag_mapping"]
        if not isinstance(tag_mapping, dict):
            raise ValueError("tag_mapping must be a dictionary")
            
        # Validate and normalize the mapping
        normalized_mapping = {}
        for old_tag, new_tags in tag_mapping.items():
            if not isinstance(new_tags, list):
                raise ValueError(f"Mapping for '{old_tag}' must be a list")
                
            # Empty list means keep the tag unchanged
            if not new_tags:
                normalized_mapping[old_tag] = [old_tag]
            else:
                # Ensure all new tags are lowercase strings
                normalized_mapping[old_tag] = [
                    str(tag).lower() for tag in new_tags
                ]
                
        return normalized_mapping
    except ValueError as e:
        logger.error(f"Invalid response structure: {e}")
        raise


def update_tag_relations(
    session: Session,
    old_to_new_tags: Dict[str, List[str]],
    tag_name_to_id: Dict[str, int],
    new_tag_ids: Dict[str, int],
    dry_run: bool = False
) -> None:
    """Update all tag relations based on the mapping."""
    # Log tag conversions
    for old_tag, new_tags in old_to_new_tags.items():
        if len(new_tags) == 1 and old_tag == new_tags[0]:
            continue  # Skip if tag remains the same
        logger.info(f"Converting tag '{old_tag}' to {new_tags}")

    # Process each item's tags
    items = session.query(ProcessedItem).all()
    processed_relations = set()

    for item in items:
        # Get all tag relations for this item
        item_relations = (
            session.query(ItemTagRelation)
            .join(ItemTag)
            .filter(
                ItemTagRelation.item_id == item.id,
                ItemTag.name.in_(old_to_new_tags.keys())
            )
        )

        for relation in item_relations:
            old_tag = session.get(ItemTag, relation.tag_id)
            if not old_tag or relation in processed_relations:
                continue
            processed_relations.add(relation)

            new_tag_names = old_to_new_tags[old_tag.name]

            # Handle tag splitting and merging
            if len(new_tag_names) > 1:
                # Tag is being split into multiple tags
                msg = (
                    f"Item {item.id}: Splitting tag '{old_tag.name}' into {new_tag_names} "
                    f"with score {relation.relation_value}"
                )
                logger.info(f"{'Would ' if dry_run else ''}split tag: {msg}")

                if not dry_run:
                    # Create new relations for each split tag
                    for new_tag_name in new_tag_names:
                        new_tag_name = new_tag_name.lower()

                        # Skip if this would create a self-reference
                        if new_tag_name == old_tag.name:
                            continue

                        existing_relation = (
                            session.query(ItemTagRelation)
                            .filter(
                                ItemTagRelation.item_id == item.id,
                                ItemTagRelation.tag_id == new_tag_ids[new_tag_name]
                            )
                        ).first()

                        if not existing_relation and relation.relation_value > 0.0:
                            # Only create new relation if score is not zero
                            new_relation = ItemTagRelation(
                                item_id=item.id,
                                tag_id=new_tag_ids[new_tag_name],
                                relation_value=relation.relation_value
                            )
                            session.add(new_relation)

            else:
                # Single tag mapping
                new_tag_name = new_tag_names[0].lower()

                if new_tag_name == old_tag.name:
                    # Tag remains the same
                    continue

                msg = f"Item {item.id}: Converting tag '{old_tag.name}' to '{new_tag_name}'"
                logger.info(f"{'Would ' if dry_run else ''}convert tag: {msg}")

                if not dry_run:
                    # Check if relation already exists for the new tag
                    existing_relation = (
                        session.query(ItemTagRelation)
                        .filter(
                            ItemTagRelation.item_id == item.id,
                            ItemTagRelation.tag_id == new_tag_ids[new_tag_name]
                        )
                    ).first()

                    if existing_relation:
                        # Keep highest non-zero score if merging
                        new_score = max(
                            existing_relation.relation_value,
                            relation.relation_value
                        )
                        if new_score > 0.0:
                            existing_relation.relation_value = new_score
                        else:
                            # If both scores are zero, remove the relation
                            session.delete(existing_relation)
                        session.delete(relation)
                    elif relation.relation_value > 0.0:
                        # Only update if score is not zero
                        relation.tag_id = new_tag_ids[new_tag_name]
                    else:
                        # Remove zero-score relation
                        session.delete(relation)


def cleanup_unused_tags(session: Session, dry_run: bool = False) -> None:
    """Remove tags that have no relations."""
    # Find tags with no relations
    unused_tags = (
        session.query(ItemTag)
        .outerjoin(ItemTagRelation)
        .filter(ItemTagRelation.tag_id.is_(None))
        .all()
    )

    # Delete unused tags
    for tag in unused_tags:
        msg = f"Removing unused tag: {tag.name}"
        logger.info(f"{'Would ' if dry_run else ''}{msg}")
        if not dry_run:
            session.delete(tag)


async def analyze_story_tags(processor: GenAIProcessor, session: Session, dry_run: bool = False) -> None:
    """Analyze tags generated by story summaries and suggest improvements."""
    from octopus.scripts.generate_story_summaries import process_story_content

    # Get all processed items with their tags
    items = (
        session.query(ProcessedItem)
        .join(ItemTagRelation)
        .join(ItemTag)
        .filter(ProcessedItem.related_item_type == "hacker_news_story")
        .all()
    )

    logger.info(f"Analyzing tags for {len(items)} processed items...")

    # Track all unique tags suggested by LLM
    suggested_tags = set()

    for item in items:
        story = session.query(Story).filter(Story.id == item.related_item_id).first()
        if not story:
            continue

        # Process story content to get suggested tags
        _, tags, _ = await process_story_content(
            story.content,
            story.target_content,
            [comment.content for comment in story.comments if not comment.deleted]
        )

        # Add suggested tags to set
        suggested_tags.update(tag_name.lower() for tag_name, _ in tags)

    logger.info(f"Found {len(suggested_tags)} unique suggested tags")

    # Get all existing tags
    existing_tags = get_all_tags(session)
    existing_tag_names = {tag.name for tag in existing_tags}

    # Combine existing and suggested tags for analysis
    all_tags = list(existing_tag_names | suggested_tags)

    # Get tag mapping from LLM
    tag_mapping = await get_tag_mapping(processor, [ItemTag(name=name) for name in all_tags])
    logger.info(f"Tag mapping: {tag_mapping}")

    # Create new tags if needed
    tag_name_to_id = {tag.name: tag.id for tag in existing_tags}
    new_tag_ids = {}

    # Collect all unique new tag names
    all_new_tags = set()
    for new_tags in tag_mapping.values():
        all_new_tags.update(new_tag.lower() for new_tag in new_tags)

    if dry_run:
        # In dry-run mode, just show what would be created/updated
        for new_name in all_new_tags:
            if new_name not in tag_name_to_id:
                logger.info(f"Would create new tag: {new_name}")
            new_tag_ids[new_name] = -1  # Dummy ID for dry run
    else:
        # Actually create new tags
        for new_name in all_new_tags:
            if new_name not in tag_name_to_id:
                new_tag = ItemTag(name=new_name)
                session.add(new_tag)
                session.flush()
                new_tag_ids[new_name] = new_tag.id
                logger.info(f"Created new tag: {new_name}")
            else:
                new_tag_ids[new_name] = tag_name_to_id[new_name]

    # Update relations
    update_tag_relations(session, tag_mapping, tag_name_to_id, new_tag_ids, dry_run)

    if not dry_run:
        # Cleanup unused tags and commit changes
        cleanup_unused_tags(session, dry_run=args.dry_run)
        session.commit()

    logger.info("Tag analysis and revision completed successfully")


async def main() -> None:
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(description='Revise tags and analyze story tags')
    parser.add_argument(
        '--analyze-stories',
        action='store_true',
        help='Analyze tags from story summaries to improve tag organization'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )

    args = parser.parse_args()
    processor = GenAIProcessor()

    with SessionLocal() as session:
        if args.analyze_stories:
            await analyze_story_tags(processor, session, dry_run=args.dry_run)
            return

        # Get all current tags
        tags = get_all_tags(session)
        if not tags:
            logger.info("No tags found in the database")
            return

        # Get tag mapping from LLM
        tag_mapping = await get_tag_mapping(processor, tags)
        logger.info(f"Tag mapping: {tag_mapping}")

        # Create new tags if needed
        tag_name_to_id = {tag.name: tag.id for tag in tags}
        new_tag_ids = {}

        # Collect all unique new tag names
        all_new_tags = set()
        for new_tags in tag_mapping.values():
            all_new_tags.update(new_tag.lower() for new_tag in new_tags)

        if args.dry_run:
            # In dry-run mode, just show what would be created/updated
            for new_name in all_new_tags:
                if new_name not in tag_name_to_id:
                    logger.info(f"Would create new tag: {new_name}")
                new_tag_ids[new_name] = -1  # Dummy ID for dry run
        else:
            # Actually create new tags
            for new_name in all_new_tags:
                if new_name not in tag_name_to_id:
                    new_tag = ItemTag(name=new_name)
                    session.add(new_tag)
                    session.flush()
                    new_tag_ids[new_name] = new_tag.id
                    logger.info(f"Created new tag: {new_name}")
                else:
                    new_tag_ids[new_name] = tag_name_to_id[new_name]

        # Update relations
        update_tag_relations(session, tag_mapping, tag_name_to_id, new_tag_ids, dry_run=args.dry_run)

        if not args.dry_run:
            # Cleanup unused tags and commit changes
            cleanup_unused_tags(session, dry_run=args.dry_run)
            session.commit()

        logger.info("Tag revision completed successfully")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import asyncio
    asyncio.run(main())
