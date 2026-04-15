"""project synopsis table"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_project_synopsis"
down_revision = "0008_project_lease_token"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ltw_project_synopsis",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("source_synopsis_text", sa.Text(), nullable=False),
        sa.Column("source_synopsis_status", sa.String(length=32), nullable=False),
        sa.Column("source_synopsis_origin", sa.String(length=32), nullable=False),
        sa.Column("source_synopsis_hash", sa.String(length=64), nullable=False),
        sa.Column("source_synopsis_model_profile_id", sa.String(length=64), nullable=False),
        sa.Column("source_synopsis_provider_name", sa.String(length=64), nullable=False),
        sa.Column("source_synopsis_model_name", sa.String(length=64), nullable=False),
        sa.Column("target_synopsis_text", sa.Text(), nullable=False),
        sa.Column("target_synopsis_status", sa.String(length=32), nullable=False),
        sa.Column("target_synopsis_origin", sa.String(length=32), nullable=False),
        sa.Column("target_synopsis_hash", sa.String(length=64), nullable=False),
        sa.Column("target_synopsis_model_profile_id", sa.String(length=64), nullable=False),
        sa.Column("target_synopsis_provider_name", sa.String(length=64), nullable=False),
        sa.Column("target_synopsis_model_name", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["ltw_translation_projects.id"],
            name="fk_ltw_project_synopsis_project_id_ltw_translation_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ltw_project_synopsis"),
        sa.UniqueConstraint("project_id", name="uq_ltw_project_synopsis_project_id"),
    )
    op.create_index(
        "ix_ltw_project_synopsis_project_id",
        "ltw_project_synopsis",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ltw_project_synopsis_project_id", table_name="ltw_project_synopsis")
    op.drop_table("ltw_project_synopsis")
