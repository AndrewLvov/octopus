"""Add url_contents table."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20250406180400'
down_revision = '20250405203500'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        'url_contents',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('url', sa.String(length=2048), nullable=False),
        sa.Column('target_content', postgresql.TEXT(), nullable=True),
        sa.Column('extracted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('url')
    )
    op.create_index('idx_url_contents_url', 'url_contents', ['url'])
    op.create_index('idx_url_contents_extracted_at', 'url_contents', ['extracted_at'])
    op.create_index('idx_url_contents_last_checked_at', 'url_contents', ['last_checked_at'])

def downgrade() -> None:
    op.drop_index('idx_url_contents_last_checked_at', table_name='url_contents')
    op.drop_index('idx_url_contents_extracted_at', table_name='url_contents')
    op.drop_index('idx_url_contents_url', table_name='url_contents')
    op.drop_table('url_contents')
