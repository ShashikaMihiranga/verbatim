"""job kind fits "look_inside_other" (17 characters)

Revision ID: 5d2b8e7c1f03
Revises: 3c7e1f2a9b40
Create Date: 2026-10-25 17:00:00

`jobs.kind` was VARCHAR(16). Postgres refused every "look_inside_other" job (BUG-057); SQLite, used locally
and in tests, does not enforce the length, so nothing caught it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5d2b8e7c1f03'
down_revision: Union[str, Sequence[str], None] = '3c7e1f2a9b40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('jobs') as batch:
        batch.alter_column('kind', existing_type=sa.String(length=16), type_=sa.String(length=32),
                           existing_nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('jobs') as batch:
        batch.alter_column('kind', existing_type=sa.String(length=32), type_=sa.String(length=16),
                           existing_nullable=False)
