"""translation stage tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_translation_stage"
down_revision = "0003_glossary_stage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ltw_segment_translations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("segment_id", sa.Integer(), nullable=False),
        sa.Column("active_version_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["ltw_translation_projects.id"],
            name="fk_st_project",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id"],
            ["ltw_chapter_segments.id"],
            name="fk_st_segment",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ltw_segment_translations"),
        sa.UniqueConstraint("project_id", "segment_id", name="uq_st_project_segment"),
    )
    op.create_index("ix_ltw_segment_translations_project_id", "ltw_segment_translations", ["project_id"], unique=False)
    op.create_index("ix_ltw_segment_translations_segment_id", "ltw_segment_translations", ["segment_id"], unique=False)
    op.create_index(
        "ix_ltw_segment_translations_active_version_id",
        "ltw_segment_translations",
        ["active_version_id"],
        unique=False,
    )

    op.create_table(
        "ltw_segment_translation_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("segment_translation_id", sa.Integer(), nullable=False),
        sa.Column("version_index", sa.Integer(), nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("model_profile_id", sa.String(length=64), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("translated_text", sa.Text(), nullable=False),
        sa.Column("translated_text_path", sa.String(length=512), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["ltw_translation_projects.id"],
            name="fk_stv_project",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["segment_translation_id"],
            ["ltw_segment_translations.id"],
            name="fk_stv_translation",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ltw_segment_translation_versions"),
        sa.UniqueConstraint(
            "segment_translation_id",
            "version_index",
            name="uq_stv_translation_version",
        ),
    )
    op.create_index(
        "ix_ltw_segment_translation_versions_project_id",
        "ltw_segment_translation_versions",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_ltw_segment_translation_versions_segment_translation_id",
        "ltw_segment_translation_versions",
        ["segment_translation_id"],
        unique=False,
    )

    op.create_foreign_key(
        "fk_st_active_version",
        "ltw_segment_translations",
        "ltw_segment_translation_versions",
        ["active_version_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_st_active_version",
        "ltw_segment_translations",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_ltw_segment_translation_versions_segment_translation_id",
        table_name="ltw_segment_translation_versions",
    )
    op.drop_index(
        "ix_ltw_segment_translation_versions_project_id",
        table_name="ltw_segment_translation_versions",
    )
    op.drop_table("ltw_segment_translation_versions")
    op.drop_index("ix_ltw_segment_translations_active_version_id", table_name="ltw_segment_translations")
    op.drop_index("ix_ltw_segment_translations_segment_id", table_name="ltw_segment_translations")
    op.drop_index("ix_ltw_segment_translations_project_id", table_name="ltw_segment_translations")
    op.drop_table("ltw_segment_translations")
