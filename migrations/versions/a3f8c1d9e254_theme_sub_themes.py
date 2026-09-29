"""theme sub_themes

Revision ID: a3f8c1d9e254
Revises: e15812ca2ddb
Create Date: 2026-09-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f8c1d9e254'
down_revision: Union[str, Sequence[str], None] = 'e15812ca2ddb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('themes', sa.Column('sub_themes', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('themes', 'sub_themes')
