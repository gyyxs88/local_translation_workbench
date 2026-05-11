"""add workflow runtime foundation tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0013_workflow_runtime_foundation"
down_revision = "0012_glossary_term_relationships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ltw_workflow_profiles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workflow_key", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("is_default", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("definition_json", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ltw_workflow_profiles"),
        sa.UniqueConstraint("workflow_key"),
    )
    op.create_index("ix_ltw_workflow_profiles_workflow_key", "ltw_workflow_profiles", ["workflow_key"], unique=False)
    op.create_index("ix_ltw_workflow_profiles_stage", "ltw_workflow_profiles", ["stage"], unique=False)

    op.create_table(
        "ltw_workflow_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workflow_key", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_value", sa.Text(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["ltw_translation_projects.id"],
            name="fk_ltw_workflow_runs_project_id_ltw_translation_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ltw_workflow_runs"),
    )
    op.create_index("ix_ltw_workflow_runs_workflow_key", "ltw_workflow_runs", ["workflow_key"], unique=False)
    op.create_index("ix_ltw_workflow_runs_project_id", "ltw_workflow_runs", ["project_id"], unique=False)
    op.create_index("ix_ltw_workflow_runs_stage", "ltw_workflow_runs", ["stage"], unique=False)
    op.create_index("ix_ltw_workflow_runs_request_id", "ltw_workflow_runs", ["request_id"], unique=False)

    op.create_table(
        "ltw_workflow_step_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workflow_run_id", sa.Integer(), nullable=False),
        sa.Column("step_key", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("llm_role", sa.String(length=64), nullable=False),
        sa.Column("model_profile_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column("input_ref", sa.Text(), nullable=False),
        sa.Column("output_payload", sa.JSON(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["ltw_workflow_runs.id"],
            name="fk_ltw_workflow_step_runs_workflow_run_id_ltw_workflow_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ltw_workflow_step_runs"),
        sa.UniqueConstraint("workflow_run_id", "step_key"),
    )
    op.create_index(
        "ix_ltw_workflow_step_runs_workflow_run_id",
        "ltw_workflow_step_runs",
        ["workflow_run_id"],
        unique=False,
    )
    op.create_index("ix_ltw_workflow_step_runs_step_key", "ltw_workflow_step_runs", ["step_key"], unique=False)
    op.create_index("ix_ltw_workflow_step_runs_action", "ltw_workflow_step_runs", ["action"], unique=False)
    op.create_index("ix_ltw_workflow_step_runs_llm_role", "ltw_workflow_step_runs", ["llm_role"], unique=False)
    op.create_index(
        "ix_ltw_workflow_step_runs_model_profile_id",
        "ltw_workflow_step_runs",
        ["model_profile_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ltw_workflow_step_runs_model_profile_id", table_name="ltw_workflow_step_runs")
    op.drop_index("ix_ltw_workflow_step_runs_llm_role", table_name="ltw_workflow_step_runs")
    op.drop_index("ix_ltw_workflow_step_runs_action", table_name="ltw_workflow_step_runs")
    op.drop_index("ix_ltw_workflow_step_runs_step_key", table_name="ltw_workflow_step_runs")
    op.drop_index("ix_ltw_workflow_step_runs_workflow_run_id", table_name="ltw_workflow_step_runs")
    op.drop_table("ltw_workflow_step_runs")

    op.drop_index("ix_ltw_workflow_runs_request_id", table_name="ltw_workflow_runs")
    op.drop_index("ix_ltw_workflow_runs_stage", table_name="ltw_workflow_runs")
    op.drop_index("ix_ltw_workflow_runs_project_id", table_name="ltw_workflow_runs")
    op.drop_index("ix_ltw_workflow_runs_workflow_key", table_name="ltw_workflow_runs")
    op.drop_table("ltw_workflow_runs")

    op.drop_index("ix_ltw_workflow_profiles_stage", table_name="ltw_workflow_profiles")
    op.drop_index("ix_ltw_workflow_profiles_workflow_key", table_name="ltw_workflow_profiles")
    op.drop_table("ltw_workflow_profiles")
