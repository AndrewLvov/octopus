"""Script to cleanup tag relations with zero scores."""
import logging
import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from octopus.db.session import SessionLocal
from octopus.db.models.summaries import ItemTagRelation

logger = logging.getLogger(__name__)


def cleanup_zero_score_relations(session: Session, dry_run: bool = False) -> None:
    """Remove all tag relations with a score of 0.0."""
    # Find all relations with zero score
    zero_score_relations = (
        session.query(ItemTagRelation)
        .filter(ItemTagRelation.relation_value == 0.0)
        .all()
    )

    if not zero_score_relations:
        logger.info("No zero-score relations found")
        return

    logger.info(f"Found {len(zero_score_relations)} zero-score relations")

    # Delete zero-score relations
    for relation in zero_score_relations:
        msg = f"Removing zero-score relation: item_id={relation.item_id}, tag_id={relation.tag_id}"
        logger.info(f"{'Would ' if dry_run else ''}{msg}")
        if not dry_run:
            session.delete(relation)

    if not dry_run:
        session.commit()
        logger.info("Zero-score relations cleanup completed")


async def main() -> None:
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(description='Cleanup tag relations with zero scores')
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )

    args = parser.parse_args()

    with SessionLocal() as session:
        cleanup_zero_score_relations(session, dry_run=args.dry_run)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import asyncio
    asyncio.run(main())
