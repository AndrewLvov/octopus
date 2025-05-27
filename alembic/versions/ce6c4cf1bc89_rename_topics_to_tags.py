"""rename_topics_to_tags

Revision ID: ce6c4cf1bc89
Revises: 9d2211dd37ad
Create Date: 2025-03-30 13:45:58.192285

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ce6c4cf1bc89'
down_revision: Union[str, None] = '9d2211dd37ad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Rename tables
    op.rename_table('item_topics', 'item_tags')
    op.rename_table('item_topic_relations', 'item_tag_relations')
    
    # Rename foreign key constraints
    op.execute('ALTER TABLE item_tag_relations RENAME CONSTRAINT fk_item_topic_relations_item_id_processed_stories TO fk_item_tag_relations_item_id_processed_stories')
    op.execute('ALTER TABLE item_tag_relations RENAME CONSTRAINT fk_item_topic_relations_topic_id_item_topics TO fk_item_tag_relations_tag_id_item_tags')
    
    # Rename primary key constraints
    op.execute('ALTER TABLE item_tags RENAME CONSTRAINT pk_item_topics TO pk_item_tags')
    op.execute('ALTER TABLE item_tag_relations RENAME CONSTRAINT pk_item_topic_relations TO pk_item_tag_relations')
    
    # Rename unique constraints
    op.execute('ALTER TABLE item_tags RENAME CONSTRAINT uq_item_topics_name TO uq_item_tags_name')
    
    # Rename indices
    op.execute('ALTER INDEX idx_item_topic_relation_scores RENAME TO idx_item_tag_relation_scores')
    
    # Rename columns
    op.alter_column('item_tag_relations', 'topic_id', new_column_name='tag_id')


def downgrade() -> None:
    """Downgrade schema."""
    # Rename columns back
    op.alter_column('item_tag_relations', 'tag_id', new_column_name='topic_id')
    
    # Rename indices back
    op.execute('ALTER INDEX idx_item_tag_relation_scores RENAME TO idx_item_topic_relation_scores')
    
    # Rename unique constraints back
    op.execute('ALTER TABLE item_tags RENAME CONSTRAINT uq_item_tags_name TO uq_item_topics_name')
    
    # Rename primary key constraints back
    op.execute('ALTER TABLE item_tags RENAME CONSTRAINT pk_item_tags TO pk_item_topics')
    op.execute('ALTER TABLE item_tag_relations RENAME CONSTRAINT pk_item_tag_relations TO pk_item_topic_relations')
    
    # Rename foreign key constraints back
    op.execute('ALTER TABLE item_tag_relations RENAME CONSTRAINT fk_item_tag_relations_item_id_processed_stories TO fk_item_topic_relations_item_id_processed_stories')
    op.execute('ALTER TABLE item_tag_relations RENAME CONSTRAINT fk_item_tag_relations_tag_id_item_tags TO fk_item_topic_relations_topic_id_item_topics')
    
    # Rename tables back
    op.rename_table('item_tag_relations', 'item_topic_relations')
    op.rename_table('item_tags', 'item_topics')
