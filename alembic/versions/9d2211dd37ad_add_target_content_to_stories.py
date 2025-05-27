"""add_target_content_to_stories

Revision ID: 9d2211dd37ad
Revises: b11a71e19547
Create Date: 2025-03-27 13:08:06.112487

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9d2211dd37ad'
down_revision: Union[str, None] = 'b11a71e19547'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('stories', sa.Column('target_content', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('stories', 'target_content')
