"""Add unique constraint to telegram stories

Revision ID: 20250405203500
Revises: 20250405143800
Create Date: 2025-04-05 20:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20250405203500'
down_revision: Union[str, None] = '20250405143800'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add unique constraint for channel_id and message_id
    op.create_unique_constraint(
        op.f('uq_telegram_stories_channel_message'),
        'telegram_stories',
        ['channel_id', 'message_id']
    )


def downgrade() -> None:
    # Remove unique constraint
    op.drop_constraint(
        op.f('uq_telegram_stories_channel_message'),
        'telegram_stories',
        type_='unique'
    )
