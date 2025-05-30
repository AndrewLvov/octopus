"""Script to clean up old digest emails that have been processed."""

from datetime import datetime, timedelta, timezone
from sqlalchemy import select, and_

from ..db.session import session_scope
from ..db.models.emails import DigestEmail, DigestLink


def cleanup_old_digests(days_to_keep: int = 30) -> None:
    """
    Clean up digest emails older than specified days.
    Only removes emails where all links have been processed.

    Args:
        days_to_keep: Number of days of emails to keep
    """
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)

    with session_scope() as session:
        # Find old emails where all links are processed
        old_emails = select(DigestEmail).where(
            and_(
                DigestEmail.received_at < cutoff_date,
                ~DigestEmail.extracted_links.any(DigestLink.processed == False)
            )
        )

        # Delete the emails (cascade will handle links)
        result = session.execute(
            old_emails.execution_options(synchronize_session="fetch")
        )
        emails = result.scalars().all()

        if emails:
            for email in emails:
                session.delete(email)
            session.commit()
            print(f"Deleted {len(emails)} old digest emails")
        else:
            print("No old digest emails to clean up")


if __name__ == '__main__':
    cleanup_old_digests()
