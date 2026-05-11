"""add translation annotations"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0023_translation_annotations"
down_revision = "0022_model_routes_db_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ltw_annotations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("source_anchor", sa.String(length=255), nullable=False),
        sa.Column("target_anchor", sa.String(length=255), nullable=False),
        sa.Column("annotation_type", sa.String(length=64), nullable=False),
        sa.Column("canonical_key", sa.String(length=320), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="candidate"),
        sa.Column("locked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="llm_annotation"),
        sa.Column("conflict_with_annotation_id", sa.Integer(), nullable=True),
        sa.Column("evidence_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["conflict_with_annotation_id"], ["ltw_annotations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["ltw_translation_projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "canonical_key"),
    )
    op.create_index(op.f("ix_ltw_annotations_project_id"), "ltw_annotations", ["project_id"], unique=False)
    op.create_index(
        op.f("ix_ltw_annotations_conflict_with_annotation_id"),
        "ltw_annotations",
        ["conflict_with_annotation_id"],
        unique=False,
    )

    op.create_table(
        "ltw_annotation_occurrences",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("annotation_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("chapter_id", sa.Integer(), nullable=False),
        sa.Column("segment_id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("source_anchor", sa.String(length=255), nullable=False),
        sa.Column("target_anchor", sa.String(length=255), nullable=False),
        sa.Column("source_start", sa.Integer(), nullable=True),
        sa.Column("source_end", sa.Integer(), nullable=True),
        sa.Column("target_start", sa.Integer(), nullable=True),
        sa.Column("target_end", sa.Integer(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["annotation_id"], ["ltw_annotations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chapter_id"], ["ltw_chapters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["ltw_translation_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["segment_id"], ["ltw_chapter_segments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["ltw_segment_translation_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("annotation_id", "version_id", "source_anchor", "target_anchor"),
    )
    op.create_index(
        op.f("ix_ltw_annotation_occurrences_annotation_id"),
        "ltw_annotation_occurrences",
        ["annotation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ltw_annotation_occurrences_project_id"),
        "ltw_annotation_occurrences",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ltw_annotation_occurrences_chapter_id"),
        "ltw_annotation_occurrences",
        ["chapter_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ltw_annotation_occurrences_segment_id"),
        "ltw_annotation_occurrences",
        ["segment_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ltw_annotation_occurrences_version_id"),
        "ltw_annotation_occurrences",
        ["version_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ltw_annotation_occurrences_version_id"), table_name="ltw_annotation_occurrences")
    op.drop_index(op.f("ix_ltw_annotation_occurrences_segment_id"), table_name="ltw_annotation_occurrences")
    op.drop_index(op.f("ix_ltw_annotation_occurrences_chapter_id"), table_name="ltw_annotation_occurrences")
    op.drop_index(op.f("ix_ltw_annotation_occurrences_project_id"), table_name="ltw_annotation_occurrences")
    op.drop_index(op.f("ix_ltw_annotation_occurrences_annotation_id"), table_name="ltw_annotation_occurrences")
    op.drop_table("ltw_annotation_occurrences")
    op.drop_index(op.f("ix_ltw_annotations_conflict_with_annotation_id"), table_name="ltw_annotations")
    op.drop_index(op.f("ix_ltw_annotations_project_id"), table_name="ltw_annotations")
    op.drop_table("ltw_annotations")
