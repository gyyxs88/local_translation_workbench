"""add terminal fallback profile config"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0025_terminal_fallback_profiles"
down_revision = "0024_agent_primitives"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ltw_terminal_fallback_profiles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("profile_key", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["profile_key"], ["ltw_model_profiles.profile_key"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_key"),
    )
    op.create_index(
        op.f("ix_ltw_terminal_fallback_profiles_profile_key"),
        "ltw_terminal_fallback_profiles",
        ["profile_key"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_ltw_terminal_fallback_profiles_profile_key"),
        table_name="ltw_terminal_fallback_profiles",
    )
    op.drop_table("ltw_terminal_fallback_profiles")
