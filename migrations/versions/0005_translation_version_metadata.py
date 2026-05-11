"""translation version metadata alignment"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0005_translation_meta"
down_revision = "0004_translation_stage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {
        column["name"] for column in inspector.get_columns("ltw_segment_translation_versions")
    }

    if "source_hash" not in existing_columns:
        op.add_column(
            "ltw_segment_translation_versions",
            sa.Column("source_hash", sa.String(length=64), nullable=False, server_default=""),
        )
    if "glossary_snapshot_id" not in existing_columns:
        op.add_column(
            "ltw_segment_translation_versions",
            sa.Column(
                "glossary_snapshot_id",
                sa.String(length=64),
                nullable=False,
                server_default="glossary-current",
            ),
        )
    if "model_name" not in existing_columns:
        op.add_column(
            "ltw_segment_translation_versions",
            sa.Column("model_name", sa.String(length=64), nullable=False, server_default=""),
        )
    if "status" not in existing_columns:
        op.add_column(
            "ltw_segment_translation_versions",
            sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        )

    op.execute(
        sa.text(
            """
            UPDATE ltw_segment_translation_versions
            SET
              source_hash = SHA2(source_text, 256),
              model_name = model_profile_id,
              status = COALESCE(status, 'completed')
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {
        column["name"] for column in inspector.get_columns("ltw_segment_translation_versions")
    }
    if "status" in existing_columns:
        op.drop_column("ltw_segment_translation_versions", "status")
    if "model_name" in existing_columns:
        op.drop_column("ltw_segment_translation_versions", "model_name")
    if "glossary_snapshot_id" in existing_columns:
        op.drop_column("ltw_segment_translation_versions", "glossary_snapshot_id")
    if "source_hash" in existing_columns:
        op.drop_column("ltw_segment_translation_versions", "source_hash")
