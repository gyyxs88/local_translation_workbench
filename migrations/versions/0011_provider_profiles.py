"""add provider and model profile tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0011_provider_profiles"
down_revision = "0010_project_synopsis_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ltw_provider_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider_key", sa.String(length=64), nullable=False),
        sa.Column("provider_type", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("api_key_env_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_key"),
    )
    op.create_index(op.f("ix_ltw_provider_configs_provider_key"), "ltw_provider_configs", ["provider_key"], unique=False)

    op.create_table(
        "ltw_model_profiles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("profile_key", sa.String(length=64), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=True),
        sa.Column("temperature", sa.Integer(), nullable=True),
        sa.Column("is_default", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["provider_id"], ["ltw_provider_configs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_key"),
    )
    op.create_index(op.f("ix_ltw_model_profiles_profile_key"), "ltw_model_profiles", ["profile_key"], unique=False)
    op.create_index(op.f("ix_ltw_model_profiles_provider_id"), "ltw_model_profiles", ["provider_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ltw_model_profiles_provider_id"), table_name="ltw_model_profiles")
    op.drop_index(op.f("ix_ltw_model_profiles_profile_key"), table_name="ltw_model_profiles")
    op.drop_table("ltw_model_profiles")
    op.drop_index(op.f("ix_ltw_provider_configs_provider_key"), table_name="ltw_provider_configs")
    op.drop_table("ltw_provider_configs")
