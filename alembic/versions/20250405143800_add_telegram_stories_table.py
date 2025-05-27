"""Add telegram stories table

Revision ID: 20250405143800
Revises: 20250401145000
Create Date: 2025-04-05 14:38:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20250405143800'
down_revision: Union[str, None] = '20250402203000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create telegram_stories table
    op.create_table(
        'telegram_stories',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('channel_id', sa.String(length=100), nullable=False),
        sa.Column('message_id', sa.String(length=100), nullable=False),
        sa.Column('content', sa.String(), nullable=False),
        sa.Column('urls', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('discovered_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_telegram_stories'))
    )
    
    # Create indexes
    op.create_index(
        op.f('idx_telegram_stories_posted_at'),
        'telegram_stories',
        ['posted_at'],
        unique=False
    )
    op.create_index(
        op.f('idx_telegram_stories_channel'),
        'telegram_stories',
        ['channel_id'],
        unique=False
    )
    op.create_index(
        op.f('idx_telegram_stories_message'),
        'telegram_stories',
        ['message_id'],
        unique=False
    )


def downgrade() -> None:
    op.drop_table('telegram_stories')
