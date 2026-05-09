"""add agent translation primitives"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0024_agent_primitives"
down_revision = "0023_translation_annotations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ltw_provider_call_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("workflow_run_id", sa.Integer(), nullable=True),
        sa.Column("workflow_step_run_id", sa.Integer(), nullable=True),
        sa.Column("stage", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=True),
        sa.Column("step_key", sa.String(length=64), nullable=True),
        sa.Column("llm_role", sa.String(length=64), nullable=True),
        sa.Column("requested_model_profile_id", sa.String(length=64), nullable=True),
        sa.Column("actual_model_profile_id", sa.String(length=64), nullable=True),
        sa.Column("provider_name", sa.String(length=64), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("fallback_depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ok"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_type", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_creation_input_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_read_input_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["ltw_translation_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["ltw_workflow_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workflow_step_run_id"], ["ltw_workflow_step_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ltw_provider_call_logs_project_id"), "ltw_provider_call_logs", ["project_id"])
    op.create_index(op.f("ix_ltw_provider_call_logs_workflow_run_id"), "ltw_provider_call_logs", ["workflow_run_id"])
    op.create_index(
        op.f("ix_ltw_provider_call_logs_workflow_step_run_id"),
        "ltw_provider_call_logs",
        ["workflow_step_run_id"],
    )
    op.create_index(op.f("ix_ltw_provider_call_logs_stage"), "ltw_provider_call_logs", ["stage"])
    op.create_index(op.f("ix_ltw_provider_call_logs_action"), "ltw_provider_call_logs", ["action"])
    op.create_index(op.f("ix_ltw_provider_call_logs_status"), "ltw_provider_call_logs", ["status"])
    op.create_index(op.f("ix_ltw_provider_call_logs_error_type"), "ltw_provider_call_logs", ["error_type"])

    op.create_table(
        "ltw_glossary_denylist_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("source_term", sa.String(length=255), nullable=True),
        sa.Column("pattern", sa.String(length=512), nullable=True),
        sa.Column("match_type", sa.String(length=32), nullable=False, server_default="exact"),
        sa.Column("reason_code", sa.String(length=64), nullable=False, server_default="manual_reject"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["project_id"], ["ltw_translation_projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ltw_glossary_denylist_rules_project_id"),
        "ltw_glossary_denylist_rules",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ltw_glossary_denylist_rules_project_id"), table_name="ltw_glossary_denylist_rules")
    op.drop_table("ltw_glossary_denylist_rules")
    op.drop_index(op.f("ix_ltw_provider_call_logs_error_type"), table_name="ltw_provider_call_logs")
    op.drop_index(op.f("ix_ltw_provider_call_logs_status"), table_name="ltw_provider_call_logs")
    op.drop_index(op.f("ix_ltw_provider_call_logs_action"), table_name="ltw_provider_call_logs")
    op.drop_index(op.f("ix_ltw_provider_call_logs_stage"), table_name="ltw_provider_call_logs")
    op.drop_index(op.f("ix_ltw_provider_call_logs_workflow_step_run_id"), table_name="ltw_provider_call_logs")
    op.drop_index(op.f("ix_ltw_provider_call_logs_workflow_run_id"), table_name="ltw_provider_call_logs")
    op.drop_index(op.f("ix_ltw_provider_call_logs_project_id"), table_name="ltw_provider_call_logs")
    op.drop_table("ltw_provider_call_logs")
