from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..errors import ToolError
from .constants import ACCEPTANCE_WRITER, RAW_WRITER, REVIEW_WRITER, REVISION_WRITER, TERMS_WRITER
from .io import compute_sha256, ensure_within_root, normalize_project_key, read_yaml, write_text, write_yaml


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class EditorialRuntimeService:
    def __init__(self, projects_root: Path) -> None:
        self.projects_root = Path(projects_root)

    def project_root(self, project_key: str) -> Path:
        safe_key = normalize_project_key(project_key)
        return ensure_within_root(self.projects_root, self.projects_root / safe_key)

    def init_project(
        self,
        *,
        project_key: str,
        title: str,
        source_language: str,
        target_language: str,
    ) -> dict[str, Any]:
        safe_key = normalize_project_key(project_key)
        root = self.project_root(safe_key)
        manifest_path = root / "manifest.yaml"
        if manifest_path.exists():
            manifest = read_yaml(manifest_path)
            return {"project_key": safe_key, "project_root": str(root), "manifest": manifest}

        for relative_dir in (
            "source/chapters",
            "source/segments",
            "rules",
            "memory",
            "chapters",
            "exports",
            ".ltw-cache",
        ):
            (root / relative_dir).mkdir(parents=True, exist_ok=True)

        created_at = _utc_now()
        manifest = {
            "runtime": "editorial",
            "compatibility": "not_backward_compatible",
            "project_key": safe_key,
            "title": title,
            "source_language": source_language,
            "target_language": target_language,
            "created_at": created_at,
            "updated_at": created_at,
        }
        write_yaml(manifest_path, manifest)
        write_yaml(
            root / "editorial-ledger.yaml",
            {
                "project_key": safe_key,
                "runs": [],
                "decisions": [],
            },
        )
        write_yaml(root / "source" / "manifest.yaml", {"project_key": safe_key, "chapters": [], "synopsis": None})
        write_text(root / "rules" / "style-guide.md", "# Style Guide\n\n")
        write_yaml(root / "rules" / "glossary.yaml", {"terms": []})
        write_yaml(root / "rules" / "glossary-candidates.yaml", {"candidates": []})
        write_text(root / "memory" / "tm.accepted.jsonl", "")
        return {"project_key": safe_key, "project_root": str(root), "manifest": manifest}

    def _require_project(self, project_key: str) -> Path:
        root = self.project_root(project_key)
        if not (root / "manifest.yaml").exists():
            raise ToolError(code="not_found", message=f"找不到 Editorial Runtime 项目: {project_key}", status=404)
        return root

    def _chapter_root(self, project_root: Path, chapter_key: str) -> Path:
        safe_chapter_key = str(chapter_key).strip().lower()
        if not safe_chapter_key.startswith("ch") or "/" in safe_chapter_key or "\\" in safe_chapter_key:
            raise ToolError(code="invalid_arguments", message=f"chapter_key 不合法: {chapter_key}", status=400)
        return ensure_within_root(project_root, project_root / "chapters" / safe_chapter_key)

    def prepare_source(
        self,
        *,
        project_key: str,
        synopsis: str,
        chapters: list[dict[str, Any]],
    ) -> dict[str, Any]:
        root = self._require_project(project_key)
        if not chapters:
            raise ToolError(code="invalid_arguments", message="chapters 不能为空。", status=400)

        synopsis_path = root / "source" / "synopsis.md"
        write_text(synopsis_path, (synopsis or "").rstrip() + "\n")
        manifest_chapters: list[dict[str, Any]] = []
        for index, chapter in enumerate(chapters, start=1):
            chapter_key = str(chapter.get("chapter_key") or f"ch{index:03d}").strip().lower()
            title = str(chapter.get("title") or f"Chapter {index}")
            source_text = str(chapter.get("source_text") or "").rstrip()
            if not source_text:
                raise ToolError(code="invalid_arguments", message=f"{chapter_key} source_text 不能为空。", status=400)
            source_path = root / "source" / "chapters" / f"{chapter_key}.md"
            write_text(source_path, source_text + "\n")
            manifest_chapters.append(
                {
                    "chapter_key": chapter_key,
                    "chapter_index": index,
                    "title": title,
                    "source_path": f"source/chapters/{chapter_key}.md",
                    "source_sha256": compute_sha256(source_path),
                }
            )

        manifest = {
            "project_key": normalize_project_key(project_key),
            "synopsis": {
                "path": "source/synopsis.md",
                "sha256": compute_sha256(synopsis_path),
            },
            "chapters": manifest_chapters,
            "updated_at": _utc_now(),
        }
        write_yaml(root / "source" / "manifest.yaml", manifest)
        return {"project_key": normalize_project_key(project_key), "chapter_count": len(manifest_chapters)}

    def _source_chapter(self, root: Path, chapter_key: str) -> dict[str, Any]:
        source_manifest = read_yaml(root / "source" / "manifest.yaml")
        for chapter in source_manifest.get("chapters", []):
            if chapter.get("chapter_key") == chapter_key:
                return chapter
        raise ToolError(code="not_found", message=f"找不到源章节: {chapter_key}", status=404)

    def assign_chapter(self, *, project_key: str, chapter_key: str, brief: str) -> dict[str, Any]:
        root = self._require_project(project_key)
        source_chapter = self._source_chapter(root, chapter_key)
        chapter_root = self._chapter_root(root, chapter_key)
        for relative_dir in ("raw", "review", "revised", "accepted"):
            (chapter_root / relative_dir).mkdir(parents=True, exist_ok=True)
        write_text(
            chapter_root / "task.md",
            f"# {chapter_key} Task\n\n"
            f"- title: {source_chapter['title']}\n"
            f"- source_path: {source_chapter['source_path']}\n"
            f"- source_sha256: {source_chapter['source_sha256']}\n\n"
            f"{brief.rstrip()}\n",
        )
        record = {
            "chapter_key": chapter_key,
            "status": "planned",
            "source_sha256": source_chapter["source_sha256"],
            "runs": [],
            "updated_at": _utc_now(),
        }
        write_yaml(chapter_root / "record.yaml", record)
        write_text(chapter_root / "annotations.md", "# Annotations\n\n")
        return {"project_key": normalize_project_key(project_key), "chapter_key": chapter_key, "status": "planned"}

    def prepare_term_pack(
        self,
        *,
        project_key: str,
        chapter_key: str,
        terms: list[dict[str, Any]],
    ) -> dict[str, Any]:
        root = self._require_project(project_key)
        chapter_root = self._chapter_root(root, chapter_key)
        record_path = chapter_root / "record.yaml"
        record = read_yaml(record_path)
        if record.get("status") not in {"planned", "term_ready"}:
            raise ToolError(code="conflict_error", message="只有 planned 章节可以准备术语包。", status=409)
        lines = ["# Term Pack", ""]
        for term in terms:
            lines.append(
                f"- {term.get('source_term', '')} => {term.get('target_term', '')} "
                f"({term.get('status', 'candidate')})"
            )
        write_text(chapter_root / "term-pack.md", "\n".join(lines).rstrip() + "\n")
        record["status"] = "term_ready"
        record["term_pack_sha256"] = compute_sha256(chapter_root / "term-pack.md")
        record["updated_at"] = _utc_now()
        record.setdefault("runs", []).append(
            {
                "desk": TERMS_WRITER,
                "status": "completed",
                "outputs": [{"path": "term-pack.md", "sha256": record["term_pack_sha256"]}],
                "finished_at": _utc_now(),
            }
        )
        write_yaml(record_path, record)
        return {"project_key": normalize_project_key(project_key), "chapter_key": chapter_key, "status": "term_ready"}

    def _record_path(self, root: Path, chapter_key: str) -> Path:
        return self._chapter_root(root, chapter_key) / "record.yaml"

    def _require_status(self, record: dict[str, Any], allowed: set[str], message: str) -> None:
        if record.get("status") not in allowed:
            raise ToolError(code="conflict_error", message=message, status=409)

    def _record_run(
        self,
        *,
        record: dict[str, Any],
        desk: str,
        inputs: list[dict[str, str]],
        outputs: list[dict[str, str]],
        note: str,
    ) -> None:
        record.setdefault("runs", []).append(
            {
                "desk": desk,
                "status": "completed",
                "inputs": inputs,
                "outputs": outputs,
                "note": note,
                "finished_at": _utc_now(),
            }
        )
        record["updated_at"] = _utc_now()

    def write_raw(self, *, project_key: str, chapter_key: str, content: str, note: str) -> dict[str, Any]:
        root = self._require_project(project_key)
        chapter_root = self._chapter_root(root, chapter_key)
        record_path = self._record_path(root, chapter_key)
        record = read_yaml(record_path)
        self._require_status(record, {"term_ready", "raw_ready"}, "只有 term_ready 章节可以写 raw。")
        output_path = chapter_root / "raw" / "main-translator.md"
        write_text(output_path, content.rstrip() + "\n")
        record["status"] = "raw_ready"
        self._record_run(
            record=record,
            desk=RAW_WRITER,
            inputs=[
                {"path": "task.md", "sha256": compute_sha256(chapter_root / "task.md")},
                {"path": "term-pack.md", "sha256": compute_sha256(chapter_root / "term-pack.md")},
            ],
            outputs=[{"path": "raw/main-translator.md", "sha256": compute_sha256(output_path)}],
            note=note,
        )
        write_yaml(record_path, record)
        return {"project_key": normalize_project_key(project_key), "chapter_key": chapter_key, "status": "raw_ready"}

    def write_bilingual_review(
        self,
        *,
        project_key: str,
        chapter_key: str,
        content: str,
        needs_annotation: bool,
    ) -> dict[str, Any]:
        root = self._require_project(project_key)
        chapter_root = self._chapter_root(root, chapter_key)
        record_path = self._record_path(root, chapter_key)
        record = read_yaml(record_path)
        self._require_status(record, {"raw_ready", "review_ready"}, "只有 raw_ready 章节可以写双语审校。")
        output_path = chapter_root / "review" / "bilingual-review.md"
        header = "# Bilingual Review\n\n"
        annotation_line = f"needs_annotation: {str(needs_annotation).lower()}\n\n"
        write_text(output_path, header + annotation_line + content.rstrip() + "\n")
        record["status"] = "review_ready"
        record["needs_annotation"] = bool(needs_annotation)
        self._record_run(
            record=record,
            desk=REVIEW_WRITER,
            inputs=[{"path": "raw/main-translator.md", "sha256": compute_sha256(chapter_root / "raw" / "main-translator.md")}],
            outputs=[{"path": "review/bilingual-review.md", "sha256": compute_sha256(output_path)}],
            note="bilingual review",
        )
        write_yaml(record_path, record)
        return {"project_key": normalize_project_key(project_key), "chapter_key": chapter_key, "status": "review_ready"}

    def adjudicate_review(
        self,
        *,
        project_key: str,
        chapter_key: str,
        decision: str,
        content: str,
    ) -> dict[str, Any]:
        root = self._require_project(project_key)
        chapter_root = self._chapter_root(root, chapter_key)
        record_path = self._record_path(root, chapter_key)
        record = read_yaml(record_path)
        self._require_status(record, {"review_ready"}, "只有 review_ready 章节可以裁决审校范围。")
        output_path = chapter_root / "review" / "adjudication.md"
        write_text(output_path, f"# Adjudication\n\n- decision: {decision}\n\n{content.rstrip()}\n")
        record["adjudication"] = {"decision": decision, "path": "review/adjudication.md", "sha256": compute_sha256(output_path)}
        self._record_run(
            record=record,
            desk=ACCEPTANCE_WRITER,
            inputs=[{"path": "review/bilingual-review.md", "sha256": compute_sha256(chapter_root / "review" / "bilingual-review.md")}],
            outputs=[{"path": "review/adjudication.md", "sha256": compute_sha256(output_path)}],
            note=decision,
        )
        write_yaml(record_path, record)
        return {"project_key": normalize_project_key(project_key), "chapter_key": chapter_key, "status": "review_ready"}

    def write_revision(
        self,
        *,
        project_key: str,
        chapter_key: str,
        content: str,
        annotations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        root = self._require_project(project_key)
        chapter_root = self._chapter_root(root, chapter_key)
        record_path = self._record_path(root, chapter_key)
        record = read_yaml(record_path)
        self._require_status(record, {"review_ready", "revision_ready"}, "只有 review_ready 章节可以写责编修订。")
        if "adjudication" not in record:
            raise ToolError(code="conflict_error", message="缺少总译审裁决，责编不能写 revised。", status=409)
        output_path = chapter_root / "revised" / "line-editor.md"
        write_text(output_path, content.rstrip() + "\n")
        annotation_lines = ["# Annotations", ""]
        for annotation in annotations:
            annotation_lines.append(f"- status: {annotation.get('status', 'candidate')}")
            annotation_lines.append(f"  text: {annotation.get('text', '')}")
        write_text(chapter_root / "annotations.md", "\n".join(annotation_lines).rstrip() + "\n")
        record["status"] = "revision_ready"
        self._record_run(
            record=record,
            desk=REVISION_WRITER,
            inputs=[
                {"path": "review/bilingual-review.md", "sha256": compute_sha256(chapter_root / "review" / "bilingual-review.md")},
                {"path": "review/adjudication.md", "sha256": compute_sha256(chapter_root / "review" / "adjudication.md")},
            ],
            outputs=[
                {"path": "revised/line-editor.md", "sha256": compute_sha256(output_path)},
                {"path": "annotations.md", "sha256": compute_sha256(chapter_root / "annotations.md")},
            ],
            note="line edit revision",
        )
        write_yaml(record_path, record)
        return {"project_key": normalize_project_key(project_key), "chapter_key": chapter_key, "status": "revision_ready"}
