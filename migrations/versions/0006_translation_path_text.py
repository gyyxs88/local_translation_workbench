"""align translation output path column with model"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0006_path_text"
down_revision = "0005_translation_meta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {
        column["name"]: column for column in inspector.get_columns("ltw_segment_translation_versions")
    }
    translated_text_path = columns.get("translated_text_path")
    current_length = getattr((translated_text_path or {}).get("type"), "length", None)
    if current_length is not None:
        op.alter_column(
            "ltw_segment_translation_versions",
            "translated_text_path",
            existing_type=sa.String(length=current_length),
            type_=sa.Text(),
            existing_nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {
        column["name"]: column for column in inspector.get_columns("ltw_segment_translation_versions")
    }
    translated_text_path = columns.get("translated_text_path")
    current_length = getattr((translated_text_path or {}).get("type"), "length", None)
    if current_length is None:
        op.alter_column(
            "ltw_segment_translation_versions",
            "translated_text_path",
            existing_type=sa.Text(),
            type_=sa.String(length=512),
            existing_nullable=False,
        )
