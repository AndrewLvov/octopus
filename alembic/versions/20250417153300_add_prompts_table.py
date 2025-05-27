"""Add prompts table."""

from alembic import op
import sqlalchemy as sa

revision = '20250417153300'
down_revision = '20250406180400'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'prompts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('prompt_text', sa.Text(), nullable=False),
        sa.Column('response_text', sa.Text(), nullable=False),
        sa.Column('response_format', sa.String(length=10), nullable=False),
        sa.Column('temperature', sa.String(length=10), nullable=True),
        sa.Column('max_tokens', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_prompts_created_at', 'prompts', ['created_at'])


def downgrade() -> None:
    op.drop_index('idx_prompts_created_at', table_name='prompts')
    op.drop_table('prompts')
