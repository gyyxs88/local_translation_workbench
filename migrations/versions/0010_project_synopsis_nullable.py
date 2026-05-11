"""allow nullable synopsis fields"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0010_project_synopsis_nullable"
down_revision = "0009_project_synopsis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "ltw_project_synopsis",
        "source_synopsis_text",
        existing_type=sa.Text(),
        nullable=True,
        existing_nullable=False,
    )
    op.alter_column(
        "ltw_project_synopsis",
        "source_synopsis_origin",
        existing_type=sa.String(length=32),
        nullable=True,
        existing_nullable=False,
    )
    op.alter_column(
        "ltw_project_synopsis",
        "source_synopsis_hash",
        existing_type=sa.String(length=64),
        nullable=True,
        existing_nullable=False,
    )
    op.alter_column(
        "ltw_project_synopsis",
        "source_synopsis_model_profile_id",
        existing_type=sa.String(length=64),
        nullable=True,
        existing_nullable=False,
    )
    op.alter_column(
        "ltw_project_synopsis",
        "source_synopsis_provider_name",
        existing_type=sa.String(length=64),
        nullable=True,
        existing_nullable=False,
    )
    op.alter_column(
        "ltw_project_synopsis",
        "source_synopsis_model_name",
        existing_type=sa.String(length=64),
        nullable=True,
        existing_nullable=False,
    )
    op.alter_column(
        "ltw_project_synopsis",
        "target_synopsis_text",
        existing_type=sa.Text(),
        nullable=True,
        existing_nullable=False,
    )
    op.alter_column(
        "ltw_project_synopsis",
        "target_synopsis_origin",
        existing_type=sa.String(length=32),
        nullable=True,
        existing_nullable=False,
    )
    op.alter_column(
        "ltw_project_synopsis",
        "target_synopsis_hash",
        existing_type=sa.String(length=64),
        nullable=True,
        existing_nullable=False,
    )
    op.alter_column(
        "ltw_project_synopsis",
        "target_synopsis_model_profile_id",
        existing_type=sa.String(length=64),
        nullable=True,
        existing_nullable=False,
    )
    op.alter_column(
        "ltw_project_synopsis",
        "target_synopsis_provider_name",
        existing_type=sa.String(length=64),
        nullable=True,
        existing_nullable=False,
    )
    op.alter_column(
        "ltw_project_synopsis",
        "target_synopsis_model_name",
        existing_type=sa.String(length=64),
        nullable=True,
        existing_nullable=False,
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE ltw_project_synopsis
        SET
            source_synopsis_text = COALESCE(source_synopsis_text, ''),
            source_synopsis_origin = COALESCE(source_synopsis_origin, ''),
            source_synopsis_hash = COALESCE(source_synopsis_hash, ''),
            source_synopsis_model_profile_id = COALESCE(source_synopsis_model_profile_id, ''),
            source_synopsis_provider_name = COALESCE(source_synopsis_provider_name, ''),
            source_synopsis_model_name = COALESCE(source_synopsis_model_name, ''),
            target_synopsis_text = COALESCE(target_synopsis_text, ''),
            target_synopsis_origin = COALESCE(target_synopsis_origin, ''),
            target_synopsis_hash = COALESCE(target_synopsis_hash, ''),
            target_synopsis_model_profile_id = COALESCE(target_synopsis_model_profile_id, ''),
            target_synopsis_provider_name = COALESCE(target_synopsis_provider_name, ''),
            target_synopsis_model_name = COALESCE(target_synopsis_model_name, '')
        """
    )
    op.alter_column(
        "ltw_project_synopsis",
        "target_synopsis_model_name",
        existing_type=sa.String(length=64),
        nullable=False,
        existing_nullable=True,
    )
    op.alter_column(
        "ltw_project_synopsis",
        "target_synopsis_provider_name",
        existing_type=sa.String(length=64),
        nullable=False,
        existing_nullable=True,
    )
    op.alter_column(
        "ltw_project_synopsis",
        "target_synopsis_model_profile_id",
        existing_type=sa.String(length=64),
        nullable=False,
        existing_nullable=True,
    )
    op.alter_column(
        "ltw_project_synopsis",
        "target_synopsis_hash",
        existing_type=sa.String(length=64),
        nullable=False,
        existing_nullable=True,
    )
    op.alter_column(
        "ltw_project_synopsis",
        "target_synopsis_origin",
        existing_type=sa.String(length=32),
        nullable=False,
        existing_nullable=True,
    )
    op.alter_column(
        "ltw_project_synopsis",
        "target_synopsis_text",
        existing_type=sa.Text(),
        nullable=False,
        existing_nullable=True,
    )
    op.alter_column(
        "ltw_project_synopsis",
        "source_synopsis_model_name",
        existing_type=sa.String(length=64),
        nullable=False,
        existing_nullable=True,
    )
    op.alter_column(
        "ltw_project_synopsis",
        "source_synopsis_provider_name",
        existing_type=sa.String(length=64),
        nullable=False,
        existing_nullable=True,
    )
    op.alter_column(
        "ltw_project_synopsis",
        "source_synopsis_model_profile_id",
        existing_type=sa.String(length=64),
        nullable=False,
        existing_nullable=True,
    )
    op.alter_column(
        "ltw_project_synopsis",
        "source_synopsis_hash",
        existing_type=sa.String(length=64),
        nullable=False,
        existing_nullable=True,
    )
    op.alter_column(
        "ltw_project_synopsis",
        "source_synopsis_origin",
        existing_type=sa.String(length=32),
        nullable=False,
        existing_nullable=True,
    )
    op.alter_column(
        "ltw_project_synopsis",
        "source_synopsis_text",
        existing_type=sa.Text(),
        nullable=False,
        existing_nullable=True,
    )
