"""add glossary workflow storage and scope fields"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0014_glossary_workflow_storage"
down_revision = "0013_workflow_runtime_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    glossary_entries = sa.table(
        "ltw_glossary_entries",
        sa.column("scope_level", sa.String(length=32)),
        sa.column("scope_chapter_id", sa.Integer()),
        sa.column("scope_anchor", sa.String(length=64)),
    )
    chapter_scope_anchor = sa.literal("chapter:") + sa.cast(glossary_entries.c.scope_chapter_id, sa.String())

    op.add_column(
        "ltw_glossary_entries",
        sa.Column("scope_level", sa.String(length=32), nullable=False, server_default="project_term"),
    )
    op.add_column("ltw_glossary_entries", sa.Column("scope_chapter_id", sa.Integer(), nullable=True))
    op.add_column(
        "ltw_glossary_entries",
        sa.Column("scope_anchor", sa.String(length=64), nullable=False, server_default="project"),
    )
    op.create_foreign_key(
        op.f("fk_ltw_glossary_entries_scope_chapter_id_ltw_chapters"),
        "ltw_glossary_entries",
        "ltw_chapters",
        ["scope_chapter_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.execute(
        sa.update(glossary_entries).values(
            scope_anchor=sa.case(
                (
                    sa.and_(
                        glossary_entries.c.scope_level == "chapter_term",
                        glossary_entries.c.scope_chapter_id.is_not(None),
                    ),
                    chapter_scope_anchor,
                ),
                else_=sa.literal("project"),
            )
        )
    )
    op.drop_constraint("uq_ltw_glossary_entries_project_source_term", "ltw_glossary_entries", type_="unique")
    op.create_unique_constraint(
        op.f("uq_ltw_glossary_entries_project_id"),
        "ltw_glossary_entries",
        ["project_id", "source_term", "scope_anchor"],
    )
    op.create_index(
        "ix_ltw_glossary_entries_scope_chapter_id",
        "ltw_glossary_entries",
        ["scope_chapter_id"],
        unique=False,
    )

    op.add_column(
        "ltw_glossary_candidates",
        sa.Column("scope_level", sa.String(length=32), nullable=False, server_default="chapter_term"),
    )
    op.add_column("ltw_glossary_candidates", sa.Column("scope_chapter_id", sa.Integer(), nullable=True))
    op.add_column("ltw_glossary_candidates", sa.Column("workflow_run_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_ltw_glossary_candidates_scope_chapter_id_ltw_chapters"),
        "ltw_glossary_candidates",
        "ltw_chapters",
        ["scope_chapter_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_ltw_glossary_candidates_workflow_run_id_ltw_workflow_runs"),
        "ltw_glossary_candidates",
        "ltw_workflow_runs",
        ["workflow_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        sa.text(
            """
            UPDATE ltw_glossary_candidates
            SET scope_chapter_id = chapter_id
            WHERE scope_chapter_id IS NULL
            """
        )
    )
    op.create_index(
        "ix_ltw_glossary_candidates_scope_chapter_id",
        "ltw_glossary_candidates",
        ["scope_chapter_id"],
        unique=False,
    )
    op.create_index(
        "ix_ltw_glossary_candidates_workflow_run_id",
        "ltw_glossary_candidates",
        ["workflow_run_id"],
        unique=False,
    )

    op.create_table(
        "ltw_glossary_draft_candidates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workflow_run_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("chapter_id", sa.Integer(), nullable=False),
        sa.Column("source_term", sa.String(length=255), nullable=False),
        sa.Column("suggested_term", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("term_group_key", sa.String(length=255), nullable=False),
        sa.Column("relation_role", sa.String(length=32), nullable=False, server_default="independent"),
        sa.Column("scope_level", sa.String(length=32), nullable=False, server_default="chapter_term"),
        sa.Column("scope_chapter_id", sa.Integer(), nullable=True),
        sa.Column("evidence_payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["ltw_workflow_runs.id"],
            name=op.f("fk_ltw_glossary_draft_candidates_workflow_run_id_ltw_workflow_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["ltw_translation_projects.id"],
            name=op.f("fk_ltw_glossary_draft_candidates_project_id_ltw_translation_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["ltw_chapters.id"],
            name=op.f("fk_ltw_glossary_draft_candidates_chapter_id_ltw_chapters"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scope_chapter_id"],
            ["ltw_chapters.id"],
            name=op.f("fk_ltw_glossary_draft_candidates_scope_chapter_id_ltw_chapters"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ltw_glossary_draft_candidates"),
    )
    op.create_index(
        "ix_ltw_glossary_draft_candidates_workflow_run_id",
        "ltw_glossary_draft_candidates",
        ["workflow_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_ltw_glossary_draft_candidates_project_id",
        "ltw_glossary_draft_candidates",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_ltw_glossary_draft_candidates_chapter_id",
        "ltw_glossary_draft_candidates",
        ["chapter_id"],
        unique=False,
    )
    op.create_index(
        "ix_ltw_glossary_draft_candidates_scope_chapter_id",
        "ltw_glossary_draft_candidates",
        ["scope_chapter_id"],
        unique=False,
    )

    op.create_table(
        "ltw_glossary_candidate_reviews",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("draft_candidate_id", sa.Integer(), nullable=False),
        sa.Column("step_run_id", sa.Integer(), nullable=False),
        sa.Column("review_type", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("reason_codes", sa.JSON(), nullable=True),
        sa.Column("structured_payload", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["draft_candidate_id"],
            ["ltw_glossary_draft_candidates.id"],
            name=op.f("fk_ltw_glossary_candidate_reviews_draft_candidate_id_ltw_glossary_draft_candidates"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_run_id"],
            ["ltw_workflow_step_runs.id"],
            name=op.f("fk_ltw_glossary_candidate_reviews_step_run_id_ltw_workflow_step_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ltw_glossary_candidate_reviews"),
    )
    op.create_index(
        "ix_ltw_glossary_candidate_reviews_step_run_id",
        "ltw_glossary_candidate_reviews",
        ["step_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_ltw_glossary_candidate_reviews_draft_candidate_id",
        "ltw_glossary_candidate_reviews",
        ["draft_candidate_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ltw_glossary_candidate_reviews_draft_candidate_id", table_name="ltw_glossary_candidate_reviews")
    op.drop_index("ix_ltw_glossary_candidate_reviews_step_run_id", table_name="ltw_glossary_candidate_reviews")
    op.drop_table("ltw_glossary_candidate_reviews")

    op.drop_index("ix_ltw_glossary_draft_candidates_scope_chapter_id", table_name="ltw_glossary_draft_candidates")
    op.drop_index("ix_ltw_glossary_draft_candidates_chapter_id", table_name="ltw_glossary_draft_candidates")
    op.drop_index("ix_ltw_glossary_draft_candidates_project_id", table_name="ltw_glossary_draft_candidates")
    op.drop_index("ix_ltw_glossary_draft_candidates_workflow_run_id", table_name="ltw_glossary_draft_candidates")
    op.drop_table("ltw_glossary_draft_candidates")

    op.drop_index("ix_ltw_glossary_candidates_workflow_run_id", table_name="ltw_glossary_candidates")
    op.drop_index("ix_ltw_glossary_candidates_scope_chapter_id", table_name="ltw_glossary_candidates")
    op.drop_constraint(
        op.f("fk_ltw_glossary_candidates_workflow_run_id_ltw_workflow_runs"),
        "ltw_glossary_candidates",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_ltw_glossary_candidates_scope_chapter_id_ltw_chapters"),
        "ltw_glossary_candidates",
        type_="foreignkey",
    )
    op.drop_column("ltw_glossary_candidates", "workflow_run_id")
    op.drop_column("ltw_glossary_candidates", "scope_chapter_id")
    op.drop_column("ltw_glossary_candidates", "scope_level")

    op.drop_index("ix_ltw_glossary_entries_scope_chapter_id", table_name="ltw_glossary_entries")
    op.drop_constraint(op.f("uq_ltw_glossary_entries_project_id"), "ltw_glossary_entries", type_="unique")
    op.drop_constraint(
        op.f("fk_ltw_glossary_entries_scope_chapter_id_ltw_chapters"),
        "ltw_glossary_entries",
        type_="foreignkey",
    )
    op.drop_column("ltw_glossary_entries", "scope_anchor")
    op.drop_column("ltw_glossary_entries", "scope_chapter_id")
    op.drop_column("ltw_glossary_entries", "scope_level")
    op.create_unique_constraint(
        "uq_ltw_glossary_entries_project_source_term",
        "ltw_glossary_entries",
        ["project_id", "source_term"],
    )
