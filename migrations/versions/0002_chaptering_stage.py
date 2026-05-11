"""chaptering stage tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_chaptering_stage"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ltw_chapters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("chapter_index", sa.Integer(), nullable=False),
        sa.Column("chapter_title", sa.String(length=255), nullable=False),
        sa.Column("source_path", sa.String(length=512), nullable=False),
        sa.Column("normalized_path", sa.String(length=512), nullable=False),
        sa.Column("stage_status", sa.String(length=32), nullable=False, server_default=sa.text("'ready'")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["ltw_translation_projects.id"],
            name="fk_ltw_chapters_project_id_ltw_translation_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ltw_chapters"),
    )
    op.create_index("ix_ltw_chapters_project_id", "ltw_chapters", ["project_id"], unique=False)

    op.create_table(
        "ltw_chapter_segments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("chapter_id", sa.Integer(), nullable=False),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("source_text_path", sa.String(length=512), nullable=False),
        sa.Column("translation_status", sa.String(length=32), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("review_status", sa.String(length=32), nullable=False, server_default=sa.text("'pending'")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["ltw_translation_projects.id"],
            name="fk_ltw_chapter_segments_project_id_ltw_translation_projects",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["ltw_chapters.id"],
            name="fk_ltw_chapter_segments_chapter_id_ltw_chapters",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ltw_chapter_segments"),
    )
    op.create_index("ix_ltw_chapter_segments_project_id", "ltw_chapter_segments", ["project_id"], unique=False)
    op.create_index("ix_ltw_chapter_segments_chapter_id", "ltw_chapter_segments", ["chapter_id"], unique=False)

    op.create_table(
        "ltw_stage_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_value", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'running'")),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["ltw_translation_projects.id"],
            name="fk_ltw_stage_runs_project_id_ltw_translation_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ltw_stage_runs"),
    )
    op.create_index("ix_ltw_stage_runs_project_id", "ltw_stage_runs", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ltw_stage_runs_project_id", table_name="ltw_stage_runs")
    op.drop_table("ltw_stage_runs")
    op.drop_index("ix_ltw_chapter_segments_chapter_id", table_name="ltw_chapter_segments")
    op.drop_index("ix_ltw_chapter_segments_project_id", table_name="ltw_chapter_segments")
    op.drop_table("ltw_chapter_segments")
    op.drop_index("ix_ltw_chapters_project_id", table_name="ltw_chapters")
    op.drop_table("ltw_chapters")
