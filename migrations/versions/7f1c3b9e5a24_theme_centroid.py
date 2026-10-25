"""theme centroid, for theme grouping's similarity check

Revision ID: 7f1c3b9e5a24
Revises: 6e4a9c2d7b18
Create Date: 2026-10-25 20:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7f1c3b9e5a24'
down_revision: Union[str, Sequence[str], None] = '6e4a9c2d7b18'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('themes', sa.Column('centroid', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('themes') as batch:
        batch.drop_column('centroid')
