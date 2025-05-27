"""rename email story content column

Revision ID: 20250402203000
Revises: 20250401145000
Create Date: 2025-04-02 20:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20250402203000'
down_revision: Union[str, None] = '20250401145000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename content column to target_content
    op.alter_column('email_stories', 'content',
                    new_column_name='target_content',
                    existing_type=sa.String)


def downgrade() -> None:
    # Rename target_content column back to content
    op.alter_column('email_stories', 'target_content',
                    new_column_name='content',
                    existing_type=sa.String)
