from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .io import ensure_within_root, normalize_project_key, read_yaml, write_text, write_yaml


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
