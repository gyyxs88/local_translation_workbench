"""review and export stage tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_review_export_stage"
down_revision = "0006_path_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ltw_review_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_value", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["ltw_translation_projects.id"],
            name="fk_ltw_review_runs_project_id_ltw_translation_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ltw_review_runs"),
    )
    op.create_index("ix_ltw_review_runs_project_id", "ltw_review_runs", ["project_id"], unique=False)

    op.create_table(
        "ltw_export_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_value", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("manifest_path", sa.String(length=512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["ltw_translation_projects.id"],
            name="fk_ltw_export_runs_project_id_ltw_translation_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ltw_export_runs"),
    )
    op.create_index("ix_ltw_export_runs_project_id", "ltw_export_runs", ["project_id"], unique=False)

    op.create_table(
        "ltw_review_issues",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("review_run_id", sa.Integer(), nullable=False),
        sa.Column("chapter_id", sa.Integer(), nullable=False),
        sa.Column("issue_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["ltw_chapters.id"],
            name="fk_ltw_review_issues_chapter_id_ltw_chapters",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["ltw_translation_projects.id"],
            name="fk_ltw_review_issues_project_id_ltw_translation_projects",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["review_run_id"],
            ["ltw_review_runs.id"],
            name="fk_ltw_review_issues_review_run_id_ltw_review_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ltw_review_issues"),
    )
    op.create_index("ix_ltw_review_issues_project_id", "ltw_review_issues", ["project_id"], unique=False)
    op.create_index("ix_ltw_review_issues_review_run_id", "ltw_review_issues", ["review_run_id"], unique=False)
    op.create_index("ix_ltw_review_issues_chapter_id", "ltw_review_issues", ["chapter_id"], unique=False)

    op.create_table(
        "ltw_export_artifacts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("export_run_id", sa.Integer(), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.ForeignKeyConstraint(
            ["export_run_id"],
            ["ltw_export_runs.id"],
            name="fk_ltw_export_artifacts_export_run_id_ltw_export_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ltw_export_artifacts"),
    )
    op.create_index("ix_ltw_export_artifacts_export_run_id", "ltw_export_artifacts", ["export_run_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ltw_export_artifacts_export_run_id", table_name="ltw_export_artifacts")
    op.drop_table("ltw_export_artifacts")
    op.drop_index("ix_ltw_review_issues_chapter_id", table_name="ltw_review_issues")
    op.drop_index("ix_ltw_review_issues_review_run_id", table_name="ltw_review_issues")
    op.drop_index("ix_ltw_review_issues_project_id", table_name="ltw_review_issues")
    op.drop_table("ltw_review_issues")
    op.drop_index("ix_ltw_export_runs_project_id", table_name="ltw_export_runs")
    op.drop_table("ltw_export_runs")
    op.drop_index("ix_ltw_review_runs_project_id", table_name="ltw_review_runs")
    op.drop_table("ltw_review_runs")
