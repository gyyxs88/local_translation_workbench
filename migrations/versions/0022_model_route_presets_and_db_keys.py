"""add model route presets"""

from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa


revision = "0022_model_routes_db_keys"
down_revision = "0021_glossary_chapter_statuses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _migrate_provider_keys_to_database()
    op.create_table(
        "ltw_model_route_presets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("preset_key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("preset_key"),
    )
    op.create_index(
        op.f("ix_ltw_model_route_presets_preset_key"),
        "ltw_model_route_presets",
        ["preset_key"],
        unique=False,
    )

    op.create_table(
        "ltw_model_route_bindings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("preset_id", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("step_key", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=True),
        sa.Column("llm_role", sa.String(length=64), nullable=True),
        sa.Column("draft_role", sa.String(length=32), nullable=True),
        sa.Column("model_profile_id", sa.String(length=64), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["preset_id"], ["ltw_model_route_presets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("preset_id", "stage", "step_key", "action", "llm_role", "draft_role"),
    )
    op.create_index(
        op.f("ix_ltw_model_route_bindings_preset_id"),
        "ltw_model_route_bindings",
        ["preset_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ltw_model_route_bindings_stage"),
        "ltw_model_route_bindings",
        ["stage"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ltw_model_route_bindings_stage"), table_name="ltw_model_route_bindings")
    op.drop_index(op.f("ix_ltw_model_route_bindings_preset_id"), table_name="ltw_model_route_bindings")
    op.drop_table("ltw_model_route_bindings")
    op.drop_index(op.f("ix_ltw_model_route_presets_preset_key"), table_name="ltw_model_route_presets")
    op.drop_table("ltw_model_route_presets")


def _migrate_provider_keys_to_database() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    provider_columns = {
        column["name"]
        for column in inspector.get_columns("ltw_provider_configs")
    }
    has_env_column = "api_key_env_name" in provider_columns
    has_value_column = "api_key_value" in provider_columns

    if not has_value_column:
        op.add_column("ltw_provider_configs", sa.Column("api_key_value", sa.Text(), nullable=True))
        has_value_column = True

    if has_env_column:
        rows = bind.execute(
            sa.text(
                """
                SELECT id, provider_key, api_key_env_name, api_key_value
                FROM ltw_provider_configs
                ORDER BY id ASC
                """
            )
        ).mappings().all()
        missing: list[str] = []
        for row in rows:
            existing_key = row.get("api_key_value")
            if existing_key:
                continue
            env_name = row.get("api_key_env_name")
            env_value = os.getenv(str(env_name or ""))
            if not env_value:
                missing.append(f"{row['provider_key']}({env_name})")
                continue
            bind.execute(
                sa.text(
                    """
                    UPDATE ltw_provider_configs
                    SET api_key_value = :api_key_value
                    WHERE id = :id
                    """
                ),
                {"api_key_value": env_value, "id": row["id"]},
            )
        if missing:
            raise RuntimeError(
                "无法把旧 provider key 自动迁入数据库，以下环境变量缺失: "
                + ", ".join(missing)
            )
        op.drop_column("ltw_provider_configs", "api_key_env_name")

    if has_value_column:
        op.alter_column(
            "ltw_provider_configs",
            "api_key_value",
            existing_type=sa.Text(),
            nullable=False,
        )
