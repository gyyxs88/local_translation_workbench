"""add translation workflow storage"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0015_translation_workflow"
down_revision = "0014_glossary_workflow_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ltw_translation_draft_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workflow_run_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("segment_id", sa.Integer(), nullable=False),
        sa.Column("step_run_id", sa.Integer(), nullable=False),
        sa.Column("parent_draft_id", sa.Integer(), nullable=True),
        sa.Column("draft_role", sa.String(length=32), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("glossary_snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("model_profile_id", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column("translated_text", sa.Text(), nullable=False),
        sa.Column("translated_text_path", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("evidence_payload", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["ltw_workflow_runs.id"],
            name=op.f("fk_ltw_translation_draft_versions_workflow_run_id_ltw_workflow_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["ltw_translation_projects.id"],
            name=op.f("fk_ltw_translation_draft_versions_project_id_ltw_translation_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id"],
            ["ltw_chapter_segments.id"],
            name=op.f("fk_ltw_translation_draft_versions_segment_id_ltw_chapter_segments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_run_id"],
            ["ltw_workflow_step_runs.id"],
            name=op.f("fk_ltw_translation_draft_versions_step_run_id_ltw_workflow_step_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_draft_id"],
            ["ltw_translation_draft_versions.id"],
            name=op.f("fk_ltw_translation_draft_versions_parent_draft_id_ltw_translation_draft_versions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ltw_translation_draft_versions"),
    )
    op.create_index(
        "ix_ltw_translation_draft_versions_workflow_run_id",
        "ltw_translation_draft_versions",
        ["workflow_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_ltw_translation_draft_versions_project_id",
        "ltw_translation_draft_versions",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_ltw_translation_draft_versions_segment_id",
        "ltw_translation_draft_versions",
        ["segment_id"],
        unique=False,
    )
    op.create_index(
        "ix_ltw_translation_draft_versions_step_run_id",
        "ltw_translation_draft_versions",
        ["step_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_ltw_translation_draft_versions_parent_draft_id",
        "ltw_translation_draft_versions",
        ["parent_draft_id"],
        unique=False,
    )

    op.create_table(
        "ltw_translation_draft_reviews",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("draft_version_id", sa.Integer(), nullable=False),
        sa.Column("step_run_id", sa.Integer(), nullable=False),
        sa.Column("review_type", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("reason_codes", sa.JSON(), nullable=True),
        sa.Column("structured_payload", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["draft_version_id"],
            ["ltw_translation_draft_versions.id"],
            name=op.f("fk_ltw_translation_draft_reviews_draft_version_id_ltw_translation_draft_versions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_run_id"],
            ["ltw_workflow_step_runs.id"],
            name=op.f("fk_ltw_translation_draft_reviews_step_run_id_ltw_workflow_step_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ltw_translation_draft_reviews"),
    )
    op.create_index(
        "ix_ltw_translation_draft_reviews_draft_version_id",
        "ltw_translation_draft_reviews",
        ["draft_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_ltw_translation_draft_reviews_step_run_id",
        "ltw_translation_draft_reviews",
        ["step_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ltw_translation_draft_reviews_step_run_id", table_name="ltw_translation_draft_reviews")
    op.drop_index("ix_ltw_translation_draft_reviews_draft_version_id", table_name="ltw_translation_draft_reviews")
    op.drop_table("ltw_translation_draft_reviews")

    op.drop_index("ix_ltw_translation_draft_versions_parent_draft_id", table_name="ltw_translation_draft_versions")
    op.drop_index("ix_ltw_translation_draft_versions_step_run_id", table_name="ltw_translation_draft_versions")
    op.drop_index("ix_ltw_translation_draft_versions_segment_id", table_name="ltw_translation_draft_versions")
    op.drop_index("ix_ltw_translation_draft_versions_project_id", table_name="ltw_translation_draft_versions")
    op.drop_index("ix_ltw_translation_draft_versions_workflow_run_id", table_name="ltw_translation_draft_versions")
    op.drop_table("ltw_translation_draft_versions")
