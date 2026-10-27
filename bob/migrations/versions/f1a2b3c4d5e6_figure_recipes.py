"""figure recipes

Revision ID: f1a2b3c4d5e6
Revises: d713c4564af0
Create Date: 2026-10-20 02:38:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'd713c4564af0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "figure_recipes",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("study_id", sa.String(length=32), nullable=False),
        sa.Column("assay_id", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("preset", sa.String(length=40), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("source", sa.JSON(), nullable=False),
        sa.Column("layout_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("preview", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assay_id"], ["assays.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("study_id", "name"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("figure_recipes")
