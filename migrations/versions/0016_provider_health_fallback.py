"""add provider profile fallback config"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0016_provider_health_fallback"
down_revision = "0015_translation_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ltw_model_profiles",
        sa.Column("fallback_profile_keys_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ltw_model_profiles", "fallback_profile_keys_json")
