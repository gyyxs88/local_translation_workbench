"""add glossary term relationship fields"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0012_glossary_term_relationships"
down_revision = "0011_provider_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ltw_glossary_entries",
        sa.Column("term_group_key", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "ltw_glossary_entries",
        sa.Column("relation_role", sa.String(length=32), nullable=False, server_default="independent"),
    )
    op.add_column(
        "ltw_glossary_candidates",
        sa.Column("term_group_key", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "ltw_glossary_candidates",
        sa.Column("relation_role", sa.String(length=32), nullable=False, server_default="independent"),
    )

    op.execute(
        sa.text(
            """
            UPDATE ltw_glossary_entries
            SET term_group_key = source_term
            WHERE term_group_key = ''
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE ltw_glossary_candidates
            SET term_group_key = source_term
            WHERE term_group_key = ''
            """
        )
    )

    op.alter_column("ltw_glossary_entries", "term_group_key", server_default=None)
    op.alter_column("ltw_glossary_candidates", "term_group_key", server_default=None)


def downgrade() -> None:
    op.drop_column("ltw_glossary_candidates", "relation_role")
    op.drop_column("ltw_glossary_candidates", "term_group_key")
    op.drop_column("ltw_glossary_entries", "relation_role")
    op.drop_column("ltw_glossary_entries", "term_group_key")
