"""add provider secret references"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0026_provider_secret_refs"
down_revision = "0025_terminal_fallback_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ltw_provider_configs", sa.Column("api_key_secret_ref", sa.Text(), nullable=True))
    op.alter_column(
        "ltw_provider_configs",
        "api_key_value",
        existing_type=sa.Text(),
        nullable=True,
    )


def downgrade() -> None:
    _ensure_no_ref_only_providers_before_downgrade()
    op.drop_column("ltw_provider_configs", "api_key_secret_ref")
    op.alter_column(
        "ltw_provider_configs",
        "api_key_value",
        existing_type=sa.Text(),
        nullable=False,
    )


def _ensure_no_ref_only_providers_before_downgrade() -> None:
    bind = op.get_bind()
    ref_only_count = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM ltw_provider_configs
            WHERE api_key_value IS NULL
            """
        )
    ).scalar_one()
    if int(ref_only_count) > 0:
        raise RuntimeError(
            "Cannot downgrade 0026_provider_secret_refs while provider rows have "
            "api_key_secret_ref-backed keys and NULL api_key_value. Restore database "
            "api_key_value values or use a manual rollback plan before downgrading."
        )
