"""sharing roles

Revision ID: c4e9a1f7b3d6
Revises: b1c7f3d4a9e2
Create Date: 2026-10-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e9a1f7b3d6'
down_revision: Union[str, Sequence[str], None] = 'b1c7f3d4a9e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dataset_collaborators',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dataset_id', 'user_id', name='uq_dataset_collaborator'),
    )
    op.create_index(op.f('ix_dataset_collaborators_dataset_id'), 'dataset_collaborators', ['dataset_id'], unique=False)
    op.create_index(op.f('ix_dataset_collaborators_user_id'), 'dataset_collaborators', ['user_id'], unique=False)

    op.create_table(
        'dataset_invite_links',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_dataset_invite_links_dataset_id'), 'dataset_invite_links', ['dataset_id'], unique=False)
    op.create_index(op.f('ix_dataset_invite_links_token'), 'dataset_invite_links', ['token'], unique=True)

    op.create_table(
        'dataset_share_links',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('column_name', sa.String(length=255), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_dataset_share_links_dataset_id'), 'dataset_share_links', ['dataset_id'], unique=False)
    op.create_index(op.f('ix_dataset_share_links_token'), 'dataset_share_links', ['token'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_dataset_share_links_token'), table_name='dataset_share_links')
    op.drop_index(op.f('ix_dataset_share_links_dataset_id'), table_name='dataset_share_links')
    op.drop_table('dataset_share_links')

    op.drop_index(op.f('ix_dataset_invite_links_token'), table_name='dataset_invite_links')
    op.drop_index(op.f('ix_dataset_invite_links_dataset_id'), table_name='dataset_invite_links')
    op.drop_table('dataset_invite_links')

    op.drop_index(op.f('ix_dataset_collaborators_user_id'), table_name='dataset_collaborators')
    op.drop_index(op.f('ix_dataset_collaborators_dataset_id'), table_name='dataset_collaborators')
    op.drop_table('dataset_collaborators')
