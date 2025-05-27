"""Add unique constraint to digest links

Revision ID: 20250401145000
Revises: 20250401083200
Create Date: 2025-04-01 14:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20250401145000'
down_revision: Union[str, None] = '20250401083200'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add unique constraint to prevent duplicate URLs within same email
    op.create_unique_constraint(
        'uq_digest_links_email_url',
        'digest_links',
        ['email_id', 'url']
    )


def downgrade() -> None:
    op.drop_constraint(
        'uq_digest_links_email_url',
        'digest_links',
        type_='unique'
    )
