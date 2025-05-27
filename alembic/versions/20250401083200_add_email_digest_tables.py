"""Add email digest tables

Revision ID: 20250401083200
Revises: ce6c4cf1bc89
Create Date: 2025-04-01 08:32:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20250401083200'
down_revision: Union[str, None] = 'ce6c4cf1bc89'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create digest_emails table
    op.create_table(
        'digest_emails',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('message_id', sa.String(length=100), nullable=False),
        sa.Column('sender', sa.String(length=255), nullable=False),
        sa.Column('subject', sa.String(length=500), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('content_text', sa.String(), nullable=True),
        sa.Column('content_html', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_digest_emails')),
        sa.UniqueConstraint('message_id', name=op.f('uq_digest_emails_message_id'))
    )
    op.create_index(
        op.f('idx_digest_emails_received_at'),
        'digest_emails',
        ['received_at'],
        unique=False
    )
    op.create_index(
        op.f('idx_digest_emails_sender'),
        'digest_emails',
        ['sender'],
        unique=False
    )

    # Create email_stories table
    op.create_table(
        'email_stories',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('url', sa.String(length=2048), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('discovered_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('source_email_id', sa.Integer(), nullable=True),
        sa.Column('content', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ['source_email_id'],
            ['digest_emails.id'],
            name=op.f('fk_email_stories_source_email_id_digest_emails'),
            ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_email_stories'))
    )
    op.create_index(
        op.f('idx_email_stories_discovered_at'),
        'email_stories',
        ['discovered_at'],
        unique=False
    )
    op.create_index(
        op.f('idx_email_stories_url'),
        'email_stories',
        ['url'],
        unique=False
    )

    # Create digest_links table
    op.create_table(
        'digest_links',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('email_id', sa.Integer(), nullable=False),
        sa.Column('url', sa.String(length=2048), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=True),
        sa.Column('context', sa.String(), nullable=True),
        sa.Column('processed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('story_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ['email_id'],
            ['digest_emails.id'],
            name=op.f('fk_digest_links_email_id_digest_emails'),
            ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['story_id'],
            ['email_stories.id'],
            name=op.f('fk_digest_links_story_id_stories'),
            ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_digest_links'))
    )
    op.create_index(
        op.f('idx_digest_links_processed'),
        'digest_links',
        ['processed'],
        unique=False
    )
    op.create_index(
        op.f('idx_digest_links_url'),
        'digest_links',
        ['url'],
        unique=False
    )


def downgrade() -> None:
    op.drop_table('digest_links')
    op.drop_table('email_stories')
    op.drop_table('digest_emails')
