"""add translation version provenance"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0017_translation_provenance"
down_revision = "0016_provider_health_fallback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ltw_segment_translation_versions",
        sa.Column("origin_workflow_run_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "ltw_segment_translation_versions",
        sa.Column("origin_step_run_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "ltw_segment_translation_versions",
        sa.Column("origin_draft_version_id", sa.Integer(), nullable=True),
    )

    op.create_index(
        "ix_ltw_segment_translation_versions_origin_workflow_run_id",
        "ltw_segment_translation_versions",
        ["origin_workflow_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_ltw_segment_translation_versions_origin_step_run_id",
        "ltw_segment_translation_versions",
        ["origin_step_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_ltw_segment_translation_versions_origin_draft_version_id",
        "ltw_segment_translation_versions",
        ["origin_draft_version_id"],
        unique=False,
    )

    op.create_foreign_key(
        "fk_stv_origin_workflow_run",
        "ltw_segment_translation_versions",
        "ltw_workflow_runs",
        ["origin_workflow_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_stv_origin_step_run",
        "ltw_segment_translation_versions",
        "ltw_workflow_step_runs",
        ["origin_step_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_stv_origin_draft_version",
        "ltw_segment_translation_versions",
        "ltw_translation_draft_versions",
        ["origin_draft_version_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_stv_origin_draft_version", "ltw_segment_translation_versions", type_="foreignkey")
    op.drop_constraint("fk_stv_origin_step_run", "ltw_segment_translation_versions", type_="foreignkey")
    op.drop_constraint("fk_stv_origin_workflow_run", "ltw_segment_translation_versions", type_="foreignkey")

    op.drop_index(
        "ix_ltw_segment_translation_versions_origin_draft_version_id",
        table_name="ltw_segment_translation_versions",
    )
    op.drop_index(
        "ix_ltw_segment_translation_versions_origin_step_run_id",
        table_name="ltw_segment_translation_versions",
    )
    op.drop_index(
        "ix_ltw_segment_translation_versions_origin_workflow_run_id",
        table_name="ltw_segment_translation_versions",
    )

    op.drop_column("ltw_segment_translation_versions", "origin_draft_version_id")
    op.drop_column("ltw_segment_translation_versions", "origin_step_run_id")
    op.drop_column("ltw_segment_translation_versions", "origin_workflow_run_id")
