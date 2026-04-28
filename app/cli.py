from __future__ import annotations

import json
import sys
from typing import Sequence

from .action_router import route_action
from .errors import ToolError


_ARGUMENT_NAME_MAP = {
    "action": "action",
    "projectid": "project_id",
    "requestid": "request_id",
    "sourcepath": "source_path",
    "sourcelanguage": "source_language",
    "targetlanguage": "target_language",
    "chapterid": "chapter_id",
    "chapterindex": "chapter_index",
    "segmentid": "segment_id",
    "segmentindex": "segment_index",
    "versionid": "version_id",
    "compareversionid": "compare_version_id",
    "stage": "stage",
    "scopetype": "scope_type",
    "scopestart": "scope_start",
    "scopeend": "scope_end",
    "scopechapters": "scope_chapters",
    "includesegments": "include_segments",
    "modelprofileid": "model_profile_id",
    "reviewmode": "review_mode",
    "maxrewriterounds": "max_rewrite_rounds",
    "providerkey": "provider_key",
    "providertype": "provider_type",
    "displayname": "display_name",
    "baseurl": "base_url",
    "apikeyvalue": "api_key_value",
    "apikey": "api_key_value",
    "profilekey": "profile_key",
    "presetkey": "preset_key",
    "routepresetkey": "route_preset_key",
    "bindingsjson": "bindings_json",
    "modelname": "model_name",
    "timeoutseconds": "timeout_seconds",
    "temperature": "temperature",
    "isdefault": "is_default",
    "status": "status",
    "note": "note",
    "fromstage": "from_stage",
    "untilstage": "until_stage",
    "limit": "limit",
    "resume": "resume",
    "rerun": "rerun",
}


def build_help_text() -> str:
    return (
        "local_translation_workbench\n\n"
        "命令:\n"
        "  project.create\n"
        "  project.list / project.cancel / project.run_full\n"
        "  stage.run (chaptering/glossary/translation/review/export)\n"
        "  stage.inspect_runs\n"
        "    可选标记: -Resume / -Rerun\n"
        "  provider.create / provider.list / provider.inspect / provider.set_key / provider.health_check\n"
        "  profile.create / profile.list / profile.inspect / profile.set_fallbacks\n"
        "  profile.route_set / profile.route_list / profile.route_inspect / profile.route_set_default\n"
        "  inspect.project\n"
        "  inspect.glossary\n"
        "  inspect.synopsis\n"
        "  inspect.chapter / inspect.chapters\n"
        "  inspect.segment\n"
        "  inspect.translation\n"
        "  inspect.review\n"
        "  inspect.export\n"
    )


def _parse_arguments(argv: Sequence[str]) -> dict[str, str]:
    arguments: dict[str, str] = {}
    index = 0
    while index < len(argv):
        token = argv[index]
        lowered = token.lower()
        if lowered in {"help", "-h", "--help", "/?"}:
            arguments["help"] = "true"
            index += 1
            continue
        if token.startswith("-"):
            key = _normalize_argument_name(token)
            if index + 1 < len(argv) and not argv[index + 1].startswith("-"):
                arguments[key] = argv[index + 1]
                index += 2
                continue
            arguments[key] = "true"
        index += 1
    return arguments


def _normalize_argument_name(token: str) -> str:
    normalized = token.lstrip("-").replace("_", "").lower()
    return _ARGUMENT_NAME_MAP.get(normalized, normalized)


def main(argv: list[str]) -> int:
    try:
        arguments = _parse_arguments(argv)
        if "help" in arguments:
            print(build_help_text())
            return 0
        result = route_action(arguments)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except ToolError as exc:
        action = _parse_arguments(argv).get("action")
        sys.stderr.write(json.dumps(exc.to_payload(action), ensure_ascii=False))
        sys.stderr.write("\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
