"""add review llm quality loop fields"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0020_review_llm_quality_loop"
down_revision = "0019_glossary_age_group_modeling"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ltw_review_issues", sa.Column("segment_id", sa.Integer(), nullable=True))
    op.add_column("ltw_review_issues", sa.Column("version_id", sa.Integer(), nullable=True))
    op.add_column(
        "ltw_review_issues",
        sa.Column("issue_source", sa.String(length=16), nullable=False, server_default="hard"),
    )
    op.add_column(
        "ltw_review_issues",
        sa.Column("round_index", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "ltw_review_issues",
        sa.Column("requires_rewrite", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("ltw_review_issues", sa.Column("structured_payload", sa.JSON(), nullable=True))
    op.create_index("ix_ltw_review_issues_segment_id", "ltw_review_issues", ["segment_id"])
    op.create_index("ix_ltw_review_issues_version_id", "ltw_review_issues", ["version_id"])
    op.create_foreign_key(
        "fk_review_issue_segment",
        "ltw_review_issues",
        "ltw_chapter_segments",
        ["segment_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_review_issue_version",
        "ltw_review_issues",
        "ltw_segment_translation_versions",
        ["version_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_review_issue_version", "ltw_review_issues", type_="foreignkey")
    op.drop_constraint("fk_review_issue_segment", "ltw_review_issues", type_="foreignkey")
    op.drop_index("ix_ltw_review_issues_version_id", table_name="ltw_review_issues")
    op.drop_index("ix_ltw_review_issues_segment_id", table_name="ltw_review_issues")
    op.drop_column("ltw_review_issues", "structured_payload")
    op.drop_column("ltw_review_issues", "requires_rewrite")
    op.drop_column("ltw_review_issues", "round_index")
    op.drop_column("ltw_review_issues", "issue_source")
    op.drop_column("ltw_review_issues", "version_id")
    op.drop_column("ltw_review_issues", "segment_id")
