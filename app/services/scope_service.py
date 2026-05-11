from __future__ import annotations

from dataclasses import dataclass

from ..errors import ToolError

BASE_SCOPE_TYPES = {"all", "chapter_range", "chapter_list"}
TRANSLATION_SCOPE_TYPES = BASE_SCOPE_TYPES | {"stale_only", "failed_only", "missing_only"}
REVIEW_SCOPE_TYPES = BASE_SCOPE_TYPES | {"missing_only"}
STAGE_SCOPE_TYPES = {
    "chaptering": BASE_SCOPE_TYPES,
    "glossary": BASE_SCOPE_TYPES,
    "translation": TRANSLATION_SCOPE_TYPES,
    "review": REVIEW_SCOPE_TYPES,
    "export": BASE_SCOPE_TYPES,
}
DYNAMIC_SCOPE_TYPES = {"stale_only", "failed_only", "missing_only"}


@dataclass(frozen=True)
class ScopeDescriptor:
    type: str
    start: int | None = None
    end: int | None = None
    chapters: list[int] | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"type": self.type}
        if self.start is not None:
            payload["start"] = self.start
        if self.end is not None:
            payload["end"] = self.end
        if self.chapters is not None:
            payload["chapters"] = self.chapters
        return payload


class ScopeService:
    def build_scope(
        self,
        scope_type: str,
        *,
        scope_start: str | int | None = None,
        scope_end: str | int | None = None,
        scope_chapters: str | list[int] | None = None,
    ) -> dict[str, object]:
        normalized_type = scope_type.strip().lower()
        if normalized_type == "all":
            return ScopeDescriptor(type="all").to_dict()

        if normalized_type == "stale_only":
            return ScopeDescriptor(type="stale_only").to_dict()

        if normalized_type == "failed_only":
            return ScopeDescriptor(type="failed_only").to_dict()

        if normalized_type == "missing_only":
            return ScopeDescriptor(type="missing_only").to_dict()

        if normalized_type == "chapter_range":
            if scope_start is None or scope_end is None:
                raise ToolError(
                    code="invalid_arguments",
                    message="chapter_range 需要 scope_start 和 scope_end。",
                    status=400,
                )
            start = int(scope_start)
            end = int(scope_end)
            if start > end:
                raise ToolError(
                    code="invalid_arguments",
                    message="scope_start 不能大于 scope_end。",
                    status=400,
                )
            return ScopeDescriptor(type="chapter_range", start=start, end=end).to_dict()

        if normalized_type == "chapter_list":
            if scope_chapters is None or scope_chapters == "":
                raise ToolError(
                    code="invalid_arguments",
                    message="chapter_list 需要 scope_chapters。",
                    status=400,
                )
            try:
                if isinstance(scope_chapters, str):
                    chapters = [int(item.strip()) for item in scope_chapters.split(",") if item.strip()]
                else:
                    chapters = [int(item) for item in scope_chapters]
            except ValueError as exc:
                raise ToolError(
                    code="invalid_arguments",
                    message="scope_chapters 必须是逗号分隔的整数列表。",
                    status=400,
                ) from exc
            chapters = sorted(dict.fromkeys(chapters))
            if not chapters:
                raise ToolError(
                    code="invalid_arguments",
                    message="scope_chapters 不能为空。",
                    status=400,
                )
            return ScopeDescriptor(type="chapter_list", chapters=chapters).to_dict()

        raise ToolError(
            code="invalid_arguments",
            message=f"不支持的 scope_type: {scope_type}",
            status=400,
        )


def get_stage_scope_types(stage: str) -> set[str]:
    normalized_stage = stage.strip().lower()
    return set(STAGE_SCOPE_TYPES.get(normalized_stage, BASE_SCOPE_TYPES))


def ensure_scope_supported(
    scope: dict[str, object],
    *,
    stage: str,
    allowed_types: set[str] | None = None,
) -> None:
    scope_type = str(scope.get("type") or "").strip().lower()
    supported_types = allowed_types or get_stage_scope_types(stage)
    if scope_type in supported_types:
        return
    raise ToolError(
        code="invalid_arguments",
        message=f"stage={stage.strip().lower()} 暂不支持 {scope_type}。",
        status=400,
    )


def scope_matches_chapters(scope_value: object, chapter_indexes: list[int]) -> bool:
    if not isinstance(scope_value, dict):
        return False

    scope_type = str(scope_value.get("type") or "").strip().lower()
    if scope_type == "all":
        return True
    if scope_type == "chapter_range":
        start = int(scope_value["start"])
        end = int(scope_value["end"])
        return any(start <= chapter_index <= end for chapter_index in chapter_indexes)
    if scope_type == "chapter_list":
        scoped_chapters = {int(item) for item in scope_value.get("chapters", [])}
        return any(chapter_index in scoped_chapters for chapter_index in chapter_indexes)
    if scope_type in DYNAMIC_SCOPE_TYPES:
        return True
    return False
