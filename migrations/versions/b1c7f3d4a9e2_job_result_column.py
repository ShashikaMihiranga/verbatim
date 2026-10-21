"""job result column

Revision ID: b1c7f3d4a9e2
Revises: a3f8c1d9e254
Create Date: 2026-10-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c7f3d4a9e2'
down_revision: Union[str, Sequence[str], None] = 'a3f8c1d9e254'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('result', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs', 'result')
