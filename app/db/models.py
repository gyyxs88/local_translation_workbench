from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class TranslationProject(Base):
    __tablename__ = "ltw_translation_projects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    project_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_language: Mapped[str] = mapped_column(String(16), nullable=False)
    target_language: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created", server_default="created")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=FetchedValue(),
    )

    operation_requests: Mapped[list["OperationRequest"]] = relationship(back_populates="project")
    leases: Mapped[list["ProjectLease"]] = relationship(back_populates="project")


class ProjectSynopsis(Base):
    __tablename__ = "ltw_project_synopsis"
    __table_args__ = (UniqueConstraint("project_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_translation_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_synopsis_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_synopsis_status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_synopsis_origin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_synopsis_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_synopsis_model_profile_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_synopsis_provider_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_synopsis_model_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_synopsis_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_synopsis_status: Mapped[str] = mapped_column(String(32), nullable=False)
    target_synopsis_origin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_synopsis_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_synopsis_model_profile_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_synopsis_provider_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_synopsis_model_name: Mapped[str | None] = mapped_column(String(64), nullable=True)


class OperationRequest(Base):
    __tablename__ = "ltw_operation_requests"
    __table_args__ = (UniqueConstraint("request_id", "operation_name"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    operation_name: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_translation_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    project: Mapped[TranslationProject] = relationship(back_populates="operation_requests")


class ProjectLease(Base):
    __tablename__ = "ltw_project_leases"
    __table_args__ = (UniqueConstraint("project_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_translation_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lease_owner: Mapped[str] = mapped_column(String(128), nullable=False)
    lease_token: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    project: Mapped[TranslationProject] = relationship(back_populates="leases")


class ProviderConfig(Base):
    __tablename__ = "ltw_provider_configs"
    __table_args__ = (UniqueConstraint("provider_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    api_key_env_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=FetchedValue(),
    )


class ModelProfile(Base):
    __tablename__ = "ltw_model_profiles"
    __table_args__ = (UniqueConstraint("profile_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    profile_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_provider_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temperature: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fallback_profile_keys_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    is_default: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=FetchedValue(),
    )


class Chapter(Base):
    __tablename__ = "ltw_chapters"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_translation_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chapter_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_path: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_path: Mapped[str] = mapped_column(String(512), nullable=False)
    stage_status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready", server_default="ready")


class ChapterSegment(Base):
    __tablename__ = "ltw_chapter_segments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_translation_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_text_path: Mapped[str] = mapped_column(String(512), nullable=False)
    translation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", server_default="pending")


class SegmentTranslation(Base):
    __tablename__ = "ltw_segment_translations"
    __table_args__ = (UniqueConstraint("project_id", "segment_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_translation_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    segment_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_chapter_segments.id", name="fk_st_segment", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    active_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("ltw_segment_translation_versions.id", name="fk_st_active_version", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


class SegmentTranslationVersion(Base):
    __tablename__ = "ltw_segment_translation_versions"
    __table_args__ = (UniqueConstraint("segment_translation_id", "version_index"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_translation_projects.id", name="fk_stv_project", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    segment_translation_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_segment_translations.id", name="fk_stv_translation", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    origin_workflow_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ltw_workflow_runs.id", name="fk_stv_origin_workflow_run", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    origin_step_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ltw_workflow_step_runs.id", name="fk_stv_origin_step_run", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    origin_draft_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("ltw_translation_draft_versions.id", name="fk_stv_origin_draft_version", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    version_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    glossary_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    translated_text: Mapped[str] = mapped_column(Text, nullable=False)
    translated_text_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed", server_default="completed")


class TranslationDraftVersion(Base):
    __tablename__ = "ltw_translation_draft_versions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_run_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_translation_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    segment_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_chapter_segments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_run_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_workflow_step_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_draft_id: Mapped[int | None] = mapped_column(
        ForeignKey("ltw_translation_draft_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    draft_role: Mapped[str] = mapped_column(String(32), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    glossary_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    translated_text: Mapped[str] = mapped_column(Text, nullable=False)
    translated_text_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed", server_default="completed")
    evidence_payload: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)


class TranslationDraftReview(Base):
    __tablename__ = "ltw_translation_draft_reviews"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    draft_version_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_translation_draft_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_run_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_workflow_step_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    review_type: Mapped[str] = mapped_column(String(32), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason_codes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    structured_payload: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)


class StageRun(Base):
    __tablename__ = "ltw_stage_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_translation_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_value: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running", server_default="running")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class WorkflowProfile(Base):
    __tablename__ = "ltw_workflow_profiles"
    __table_args__ = (UniqueConstraint("workflow_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    is_default: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    definition_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class WorkflowRun(Base):
    __tablename__ = "ltw_workflow_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_translation_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_value: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running", server_default="running")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    step_runs: Mapped[list["WorkflowStepRun"]] = relationship(back_populates="run")


class WorkflowStepRun(Base):
    __tablename__ = "ltw_workflow_step_runs"
    __table_args__ = (UniqueConstraint("workflow_run_id", "step_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_run_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    llm_role: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_profile_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running", server_default="running")
    input_ref: Mapped[str] = mapped_column(Text, nullable=False)
    output_payload: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[WorkflowRun] = relationship(back_populates="step_runs")


class GlossaryEntry(Base):
    __tablename__ = "ltw_glossary_entries"
    __table_args__ = (UniqueConstraint("project_id", "source_term", "scope_anchor"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_translation_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_term: Mapped[str] = mapped_column(String(255), nullable=False)
    target_term: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="entity", server_default="entity")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", server_default="active")
    locked: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    term_group_key: Mapped[str] = mapped_column(String(255), nullable=False)
    relation_role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="independent",
        server_default="independent",
    )
    scope_level: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="project_term",
        server_default="project_term",
    )
    scope_chapter_id: Mapped[int | None] = mapped_column(
        ForeignKey("ltw_chapters.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    scope_anchor: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="project",
        server_default="project",
    )


class GlossaryCandidate(Base):
    __tablename__ = "ltw_glossary_candidates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_translation_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_term: Mapped[str] = mapped_column(String(255), nullable=False)
    suggested_term: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", server_default="pending")
    term_group_key: Mapped[str] = mapped_column(String(255), nullable=False)
    relation_role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="independent",
        server_default="independent",
    )
    scope_level: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="chapter_term",
        server_default="chapter_term",
    )
    scope_chapter_id: Mapped[int | None] = mapped_column(
        ForeignKey("ltw_chapters.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    workflow_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ltw_workflow_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


class GlossaryDraftCandidate(Base):
    __tablename__ = "ltw_glossary_draft_candidates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_run_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_translation_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_term: Mapped[str] = mapped_column(String(255), nullable=False)
    suggested_term: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    term_group_key: Mapped[str] = mapped_column(String(255), nullable=False)
    relation_role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="independent",
        server_default="independent",
    )
    scope_level: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="chapter_term",
        server_default="chapter_term",
    )
    scope_chapter_id: Mapped[int | None] = mapped_column(
        ForeignKey("ltw_chapters.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    evidence_payload: Mapped[dict[str, object] | list[object] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", server_default="pending")


class GlossaryCandidateReview(Base):
    __tablename__ = "ltw_glossary_candidate_reviews"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    draft_candidate_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_glossary_draft_candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_run_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_workflow_step_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    review_type: Mapped[str] = mapped_column(String(32), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason_codes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    structured_payload: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)


class ReviewRun(Base):
    __tablename__ = "ltw_review_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_translation_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_value: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed", server_default="completed")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReviewIssue(Base):
    __tablename__ = "ltw_review_issues"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_translation_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    review_run_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_review_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    issue_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium", server_default="medium")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open", server_default="open")


class ExportRun(Base):
    __tablename__ = "ltw_export_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_translation_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_value: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed", server_default="completed")
    manifest_path: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class ExportArtifact(Base):
    __tablename__ = "ltw_export_artifacts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    export_run_id: Mapped[int] = mapped_column(
        ForeignKey("ltw_export_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
