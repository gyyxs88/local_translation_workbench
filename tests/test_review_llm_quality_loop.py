from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import inspect, select

from tools.local_translation_workbench.app.db.models import (
    Chapter,
    ChapterSegment,
    ReviewIssue,
    SegmentTranslation,
    SegmentTranslationVersion,
    TranslationProject,
)
from tools.local_translation_workbench.app.errors import ToolError
from tools.local_translation_workbench.app.providers.base import TextGenerationResult
from tools.local_translation_workbench.app.repositories.projects import ProjectService
from tools.local_translation_workbench.app.repositories.review import ReviewRepository
from tools.local_translation_workbench.app.services.chaptering_service import ChapteringService
from tools.local_translation_workbench.app.services.review_service import ReviewService
from tools.local_translation_workbench.app.services.review_quality_loop_service import ReviewQualityLoopService
from tools.local_translation_workbench.app.services.review_prompt_service import ReviewPromptService
from tools.local_translation_workbench.app.services.translation_service import TranslationService


def _create_review_issue_context(db_session):
    project = TranslationProject(
        request_id="review-loop-schema-project",
        project_key="review_loop_schema_project",
        source_path="source.txt",
        source_language="zh",
        target_language="en",
        status="created",
    )
    db_session.add(project)
    db_session.flush()

    chapter = Chapter(
        project_id=project.id,
        chapter_index=1,
        chapter_title="开始",
        source_path="chapter.txt",
        normalized_path="chapter.normalized.txt",
        stage_status="ready",
    )
    db_session.add(chapter)
    db_session.flush()

    segment = ChapterSegment(
        project_id=project.id,
        chapter_id=chapter.id,
        segment_index=1,
        source_text_path="segment.txt",
        translation_status="translated",
        review_status="pending",
    )
    db_session.add(segment)
    db_session.flush()

    translation = SegmentTranslation(
        project_id=project.id,
        segment_id=segment.id,
        active_version_id=None,
    )
    db_session.add(translation)
    db_session.flush()

    version = SegmentTranslationVersion(
        project_id=project.id,
        segment_translation_id=translation.id,
        version_index=1,
        source_hash="a" * 64,
        glossary_snapshot_id="b" * 64,
        provider_name="fake_provider",
        model_profile_id="profile-review-loop",
        model_name="review-model",
        source_text="她推开门。",
        translated_text="She closed the door.",
        translated_text_path="v0001.txt",
        status="completed",
    )
    db_session.add(version)
    db_session.flush()
    translation.active_version_id = version.id
    db_session.flush()
    return project, chapter, segment, version


def test_review_issue_schema_and_repository_store_segment_loop_payload(db_session) -> None:
    columns = {column["name"] for column in inspect(db_session.bind).get_columns("ltw_review_issues")}

    assert {
        "segment_id",
        "version_id",
        "issue_source",
        "round_index",
        "requires_rewrite",
        "structured_payload",
    } <= columns

    project, chapter, segment, version = _create_review_issue_context(db_session)
    repository = ReviewRepository(db_session)
    review_run = repository.create_run(
        project_id=project.id,
        scope_type="all",
        scope_value=json.dumps({"type": "all"}),
        status="completed",
        summary=json.dumps({"request_id": "schema-test"}),
    )
    issue = repository.create_issue(
        project_id=project.id,
        review_run_id=review_run.id,
        chapter_id=chapter.id,
        segment_id=segment.id,
        version_id=version.id,
        issue_type="mistranslation",
        severity="high",
        message="译文误解了动作。",
        status="open",
        issue_source="llm",
        round_index=1,
        requires_rewrite=True,
        structured_payload={"rewrite_instruction": "修正动作含义。"},
    )
    db_session.commit()

    stored = db_session.execute(select(ReviewIssue).where(ReviewIssue.id == issue.id)).scalar_one()
    assert stored.segment_id == segment.id
    assert stored.version_id == version.id
    assert stored.issue_source == "llm"
    assert stored.round_index == 1
    assert stored.requires_rewrite is True
    assert stored.structured_payload == {"rewrite_instruction": "修正动作含义。"}


def test_review_prompt_service_parses_llm_review_json() -> None:
    service = ReviewPromptService()
    result = service.parse_quality_review_response(
        json.dumps(
            {
                "passed": False,
                "score": 0.4,
                "issues": [
                    {
                        "issue_type": "mistranslation",
                        "severity": "high",
                        "requires_rewrite": True,
                        "message": "动作误译。",
                        "source_evidence": "她推开门。",
                        "translation_evidence": "She closed the door.",
                        "rewrite_instruction": "把动作改为推开门。",
                    }
                ],
            },
            ensure_ascii=False,
        )
    )

    assert result["passed"] is False
    assert result["score"] == 0.4
    assert result["issues"][0]["issue_type"] == "mistranslation"
    assert result["issues"][0]["requires_rewrite"] is True


def test_review_prompt_service_rejects_non_json_review_response() -> None:
    service = ReviewPromptService()

    try:
        service.parse_quality_review_response("not json")
    except ToolError as exc:
        assert exc.code == "provider_error"
        assert "LLM 质检必须返回 JSON" in exc.message
    else:
        raise AssertionError("expected ToolError")


def test_review_prompt_service_accepts_json_or_plain_rewrite_response() -> None:
    service = ReviewPromptService()

    assert service.parse_rewrite_response('{"translated_text":"Fixed text."}') == "Fixed text."
    assert service.parse_rewrite_response("Plain fixed text.") == "Plain fixed text."


class SequencedReviewProvider:
    def __init__(self, outputs: list[str], usage_sequence: list[dict[str, int]] | None = None) -> None:
        self.outputs = list(outputs)
        self.usage_sequence = list(usage_sequence or [])
        self.calls: list[dict[str, object]] = []

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        self.calls.append({"prompt": prompt, "model_name": model_name, "timeout_seconds": timeout_seconds})
        content = self.outputs.pop(0)
        usage = self.usage_sequence.pop(0) if self.usage_sequence else None
        return TextGenerationResult(
            content=content,
            provider_name="sequenced_review_provider",
            model_name=model_name,
            model_profile_id="profile-review-loop",
            usage=usage,
        )


def _prepare_one_segment_project(database_url: str, project_workspace: Path, db_session, request_id_factory) -> int:
    source_file = project_workspace / "review-loop-source.txt"
    source_file.write_text("第1章 开始\n她推开门。", encoding="utf-8")
    project = ProjectService(database_url).create_project(
        request_id=request_id_factory("review-loop-project"),
        source_path=str(source_file),
        source_language="zh",
        target_language="en",
    )
    ChapteringService(db_session, base_data_dir=project_workspace).run(
        request_id=request_id_factory("review-loop-chaptering"),
        project_id=project.id,
        source_file_path=source_file,
        scope={"type": "all"},
    )
    TranslationService(
        db_session,
        base_data_dir=project_workspace,
        provider=SequencedReviewProvider(["Source synopsis", "Target synopsis", "She closed the door."]),
    ).run(
        request_id=request_id_factory("review-loop-translation"),
        project_id=project.id,
        scope={"type": "all"},
        model_profile_id="profile-review-loop",
    )
    return project.id


def test_quality_loop_rewrites_until_llm_review_passes(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_one_segment_project(database_url, project_workspace, db_session, request_id_factory)
    provider = SequencedReviewProvider(
        [
            json.dumps(
                {
                    "passed": False,
                    "issues": [
                        {
                            "issue_type": "mistranslation",
                            "severity": "high",
                            "requires_rewrite": True,
                            "message": "动作误译。",
                            "rewrite_instruction": "把 closed 改为 opened。",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            json.dumps({"translated_text": "She opened the door."}, ensure_ascii=False),
            json.dumps({"passed": True, "issues": []}, ensure_ascii=False),
        ],
        usage_sequence=[
            {"input_tokens": 10, "output_tokens": 5},
            {"input_tokens": 11, "output_tokens": 6},
            {"input_tokens": 12, "output_tokens": 7},
        ],
    )
    service = ReviewQualityLoopService(db_session, base_data_dir=project_workspace, provider=provider)

    result = service.run(
        project_id=project_id,
        rows=service.resolve_review_rows_for_tests(project_id=project_id),
        hard_issues_by_segment={},
        model_profile_id="profile-review-loop",
        provider_model_name="review-model",
        max_rewrite_rounds=2,
    )

    assert result["passed_segment_count"] == 1
    assert result["needs_revision_segment_count"] == 0
    assert result["rewrite_segment_count"] == 1
    assert result["token_usage"]["call_count"] == 3
    assert len(result["rewrite_version_ids"]) == 1


def test_review_service_hybrid_loop_writes_llm_issues_and_new_active_version(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_one_segment_project(database_url, project_workspace, db_session, request_id_factory)
    provider = SequencedReviewProvider(
        [
            json.dumps(
                {
                    "passed": False,
                    "issues": [
                        {
                            "issue_type": "mistranslation",
                            "severity": "high",
                            "requires_rewrite": True,
                            "message": "动作误译。",
                            "rewrite_instruction": "把 closed 改为 opened。",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            "She opened the door.",
            json.dumps({"passed": True, "issues": []}, ensure_ascii=False),
        ]
    )

    result = ReviewService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("review-hybrid"),
        project_id=project_id,
        scope={"type": "all"},
        model_profile_id="profile-review-loop",
        provider_model_name="review-model",
        review_mode="hybrid",
        max_rewrite_rounds=2,
    )

    issues = db_session.execute(select(ReviewIssue).where(ReviewIssue.review_run_id == result.run_id)).scalars().all()
    active_version = db_session.execute(
        select(SegmentTranslationVersion).order_by(SegmentTranslationVersion.id.desc())
    ).scalars().first()

    assert result.issue_count == 1
    assert result.rewrite_segment_count == 1
    assert issues[0].issue_source == "llm"
    assert issues[0].segment_id is not None
    assert active_version.translated_text == "She opened the door."


def test_inspect_review_exposes_llm_loop_fields(
    database_url: str,
    project_workspace: Path,
    db_session,
    request_id_factory,
) -> None:
    project_id = _prepare_one_segment_project(database_url, project_workspace, db_session, request_id_factory)
    provider = SequencedReviewProvider(
        [
            json.dumps(
                {
                    "passed": False,
                    "issues": [
                        {
                            "issue_type": "mistranslation",
                            "severity": "high",
                            "requires_rewrite": True,
                            "message": "动作误译。",
                            "rewrite_instruction": "修正动作。",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            "She opened the door.",
            json.dumps({"passed": True, "issues": []}, ensure_ascii=False),
        ]
    )
    ReviewService(db_session, base_data_dir=project_workspace, provider=provider).run(
        request_id=request_id_factory("review-inspect-loop"),
        project_id=project_id,
        scope={"type": "all"},
        model_profile_id="profile-review-loop",
        provider_model_name="review-model",
        review_mode="hybrid",
        max_rewrite_rounds=2,
    )

    payload = ReviewService(db_session).inspect(project_id=project_id)

    assert payload["runs"][0]["summary"]["mode"] == "hybrid"
    assert payload["runs"][0]["summary"]["rewrite_segment_count"] == 1
    assert payload["issues"][0]["issue_source"] == "llm"
    assert payload["issues"][0]["segment_id"] is not None
    assert payload["issues"][0]["version_id"] is not None
    assert payload["issues"][0]["round_index"] == 0
    assert payload["issues"][0]["requires_rewrite"] is True
    assert payload["issues"][0]["structured_payload"]["rewrite_instruction"] == "修正动作。"
