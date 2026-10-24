"""job progress (live counts for Look inside Other)

Revision ID: 3c7e1f2a9b40
Revises: 1ab09b2dd97c
Create Date: 2026-10-24 21:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3c7e1f2a9b40'
down_revision: Union[str, Sequence[str], None] = '1ab09b2dd97c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('jobs', sa.Column('progress', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('jobs', 'progress')
