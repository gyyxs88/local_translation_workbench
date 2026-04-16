"""add glossary gender modeling"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0018_glossary_gender_modeling"
down_revision = "0017_translation_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ltw_glossary_draft_candidates",
        sa.Column("gender", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "ltw_glossary_candidates",
        sa.Column("category", sa.String(length=64), nullable=False, server_default="entity"),
    )
    op.add_column(
        "ltw_glossary_candidates",
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.add_column(
        "ltw_glossary_candidates",
        sa.Column("gender", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "ltw_glossary_entries",
        sa.Column("gender", sa.String(length=32), nullable=True),
    )
    op.alter_column("ltw_glossary_candidates", "category", server_default=None)


def downgrade() -> None:
    op.drop_column("ltw_glossary_entries", "gender")
    op.drop_column("ltw_glossary_candidates", "gender")
    op.drop_column("ltw_glossary_candidates", "note")
    op.drop_column("ltw_glossary_candidates", "category")
    op.drop_column("ltw_glossary_draft_candidates", "gender")
