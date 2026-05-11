"""glossary stage tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_glossary_stage"
down_revision = "0002_chaptering_stage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ltw_glossary_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("source_term", sa.String(length=255), nullable=False),
        sa.Column("target_term", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False, server_default=sa.text("'entity'")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'active'")),
        sa.Column("locked", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["ltw_translation_projects.id"],
            name="fk_ltw_glossary_entries_project_id_ltw_translation_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ltw_glossary_entries"),
        sa.UniqueConstraint("project_id", "source_term", name="uq_ltw_glossary_entries_project_source_term"),
    )
    op.create_index("ix_ltw_glossary_entries_project_id", "ltw_glossary_entries", ["project_id"], unique=False)

    op.create_table(
        "ltw_glossary_candidates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("chapter_id", sa.Integer(), nullable=False),
        sa.Column("source_term", sa.String(length=255), nullable=False),
        sa.Column("suggested_term", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'pending'")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["ltw_translation_projects.id"],
            name="fk_ltw_glossary_candidates_project_id_ltw_translation_projects",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["ltw_chapters.id"],
            name="fk_ltw_glossary_candidates_chapter_id_ltw_chapters",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ltw_glossary_candidates"),
    )
    op.create_index("ix_ltw_glossary_candidates_project_id", "ltw_glossary_candidates", ["project_id"], unique=False)
    op.create_index("ix_ltw_glossary_candidates_chapter_id", "ltw_glossary_candidates", ["chapter_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ltw_glossary_candidates_chapter_id", table_name="ltw_glossary_candidates")
    op.drop_index("ix_ltw_glossary_candidates_project_id", table_name="ltw_glossary_candidates")
    op.drop_table("ltw_glossary_candidates")
    op.drop_index("ix_ltw_glossary_entries_project_id", table_name="ltw_glossary_entries")
    op.drop_table("ltw_glossary_entries")
