"""initial schema"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ltw_translation_projects",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("project_key", sa.String(length=64), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("source_language", sa.String(length=16), nullable=False),
        sa.Column("target_language", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="created"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ltw_translation_projects"),
    )
    op.create_index("ix_ltw_translation_projects_project_key", "ltw_translation_projects", ["project_key"], unique=True)
    op.create_index("ix_ltw_translation_projects_request_id", "ltw_translation_projects", ["request_id"], unique=True)

    op.create_table(
        "ltw_operation_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("operation_name", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["ltw_translation_projects.id"],
            name="fk_ltw_operation_requests_project_id_ltw_translation_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ltw_operation_requests"),
        sa.UniqueConstraint("request_id", "operation_name", name="uq_ltw_operation_requests_request_id"),
    )
    op.create_index("ix_ltw_operation_requests_project_id", "ltw_operation_requests", ["project_id"], unique=False)
    op.create_index("ix_ltw_operation_requests_request_id", "ltw_operation_requests", ["request_id"], unique=False)

    op.create_table(
        "ltw_project_leases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["ltw_translation_projects.id"],
            name="fk_ltw_project_leases_project_id_ltw_translation_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ltw_project_leases"),
        sa.UniqueConstraint("project_id", "lease_owner", name="uq_ltw_project_leases_project_id"),
    )
    op.create_index("ix_ltw_project_leases_project_id", "ltw_project_leases", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ltw_project_leases_project_id", table_name="ltw_project_leases")
    op.drop_table("ltw_project_leases")
    op.drop_index("ix_ltw_operation_requests_request_id", table_name="ltw_operation_requests")
    op.drop_index("ix_ltw_operation_requests_project_id", table_name="ltw_operation_requests")
    op.drop_table("ltw_operation_requests")
    op.drop_index("ix_ltw_translation_projects_request_id", table_name="ltw_translation_projects")
    op.drop_index("ix_ltw_translation_projects_project_key", table_name="ltw_translation_projects")
    op.drop_table("ltw_translation_projects")
