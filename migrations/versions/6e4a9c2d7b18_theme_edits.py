"""theme edits, for undo in the theme editor

Revision ID: 6e4a9c2d7b18
Revises: 5d2b8e7c1f03
Create Date: 2026-10-25 19:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6e4a9c2d7b18'
down_revision: Union[str, Sequence[str], None] = '5d2b8e7c1f03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'theme_edits',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=False),
        sa.Column('column_name', sa.String(length=255), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('before', sa.JSON(), nullable=False),
        sa.Column('created_ids', sa.JSON(), nullable=False),
        sa.Column('touched_ids', sa.JSON(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('undone_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_theme_edits_dataset_id'), 'theme_edits', ['dataset_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_theme_edits_dataset_id'), table_name='theme_edits')
    op.drop_table('theme_edits')
