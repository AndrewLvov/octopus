"""Add digests table

Revision ID: 5b1e18992b39
Revises: 20250417153300
Create Date: 2025-06-02 20:29:50.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5b1e18992b39'
down_revision: Union[str, None] = '20250417153300'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create digests table
    op.create_table(
        'digests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('content', sa.String(), nullable=False),
        sa.Column('start_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('file_path', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Create digest_stories table
    op.create_table(
        'digest_stories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('digest_id', sa.Integer(), nullable=False),
        sa.Column('processed_item_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['digest_id'], ['digests.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['processed_item_id'], ['processed_stories.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('digest_stories')
    op.drop_table('digests')
