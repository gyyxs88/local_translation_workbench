"""add glossary age group modeling"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0019_glossary_age_group_modeling"
down_revision = "0018_glossary_gender_modeling"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ltw_glossary_draft_candidates",
        sa.Column("age_group", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "ltw_glossary_candidates",
        sa.Column("age_group", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "ltw_glossary_entries",
        sa.Column("age_group", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ltw_glossary_entries", "age_group")
    op.drop_column("ltw_glossary_candidates", "age_group")
    op.drop_column("ltw_glossary_draft_candidates", "age_group")
