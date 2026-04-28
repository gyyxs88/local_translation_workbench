"""add glossary chapter statuses"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0021_glossary_chapter_statuses"
down_revision = "0020_review_llm_quality_loop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ltw_glossary_chapter_statuses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("chapter_id", sa.Integer(), nullable=False),
        sa.Column("workflow_run_id", sa.Integer(), nullable=True),
        sa.Column("workflow_step_run_id", sa.Integer(), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("extraction_status", sa.String(length=32), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("finalized_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quality_issue_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model_profile_id", sa.String(length=64), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["ltw_chapters.id"],
            name="fk_gcs_chapter",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["ltw_translation_projects.id"],
            name="fk_gcs_project",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["ltw_workflow_runs.id"],
            name="fk_gcs_workflow_run",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_step_run_id"],
            ["ltw_workflow_step_runs.id"],
            name="fk_gcs_workflow_step",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_gcs"),
        sa.UniqueConstraint("project_id", "chapter_id", name="uq_gcs_project_chapter"),
    )
    op.create_index(
        "ix_gcs_project",
        "ltw_glossary_chapter_statuses",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_gcs_chapter",
        "ltw_glossary_chapter_statuses",
        ["chapter_id"],
        unique=False,
    )
    op.create_index(
        "ix_gcs_workflow_run",
        "ltw_glossary_chapter_statuses",
        ["workflow_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_gcs_workflow_step",
        "ltw_glossary_chapter_statuses",
        ["workflow_step_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_gcs_workflow_step", table_name="ltw_glossary_chapter_statuses")
    op.drop_index("ix_gcs_workflow_run", table_name="ltw_glossary_chapter_statuses")
    op.drop_index("ix_gcs_chapter", table_name="ltw_glossary_chapter_statuses")
    op.drop_index("ix_gcs_project", table_name="ltw_glossary_chapter_statuses")
    op.drop_table("ltw_glossary_chapter_statuses")
