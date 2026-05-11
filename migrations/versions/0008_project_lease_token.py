"""project lease token and single-project uniqueness"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_project_lease_token"
down_revision = "0007_review_export_stage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DELETE older
        FROM ltw_project_leases AS older
        INNER JOIN ltw_project_leases AS newer
            ON older.project_id = newer.project_id
           AND older.id < newer.id
        """
    )

    op.add_column(
        "ltw_project_leases",
        sa.Column("lease_token", sa.String(length=64), nullable=True),
    )
    op.execute(
        """
        UPDATE ltw_project_leases
        SET lease_token = SHA2(CONCAT(project_id, '-', lease_owner, '-', id), 256)
        WHERE lease_token IS NULL
        """
    )
    op.alter_column(
        "ltw_project_leases",
        "lease_token",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.alter_column(
        "ltw_project_leases",
        "expires_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        new_column_name="lease_expires_at",
    )
    op.drop_constraint("uq_ltw_project_leases_project_id", "ltw_project_leases", type_="unique")
    op.create_unique_constraint("uq_ltw_project_leases_project_id", "ltw_project_leases", ["project_id"])


def downgrade() -> None:
    op.drop_constraint("uq_ltw_project_leases_project_id", "ltw_project_leases", type_="unique")
    op.create_unique_constraint(
        "uq_ltw_project_leases_project_id",
        "ltw_project_leases",
        ["project_id", "lease_owner"],
    )
    op.alter_column(
        "ltw_project_leases",
        "lease_expires_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        new_column_name="expires_at",
    )
    op.drop_column("ltw_project_leases", "lease_token")
