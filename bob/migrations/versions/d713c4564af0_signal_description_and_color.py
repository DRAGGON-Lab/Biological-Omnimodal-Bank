"""signal description and color

Revision ID: d713c4564af0
Revises: dc9642fa0f49
Create Date: 2026-10-06 20:30:13.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd713c4564af0'
down_revision: Union[str, Sequence[str], None] = 'dc9642fa0f49'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('signals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('description', sa.String(length=200), server_default='', nullable=False))
        batch_op.add_column(sa.Column('color', sa.String(length=32), server_default='', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('signals', schema=None) as batch_op:
        batch_op.drop_column('color')
        batch_op.drop_column('description')
