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
    "entryid": "entry_id",
    "candidateid": "candidate_id",
    "sourceterm": "source_term",
    "targetterm": "target_term",
    "suggestedterm": "suggested_term",
    "termgroupkey": "term_group_key",
    "relationrole": "relation_role",
    "scopelevel": "scope_level",
    "scopechapterid": "scope_chapter_id",
    "versionid": "version_id",
    "compareversionid": "compare_version_id",
    "stage": "stage",
    "stagerunid": "stage_run_id",
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
    "apikeyvaluefile": "api_key_value_file",
    "apikey": "api_key_value",
    "apikeyfile": "api_key_value_file",
    "apikeysecretref": "api_key_secret_ref",
    "apikeysecretreffile": "api_key_secret_ref_file",
    "keysecretref": "api_key_secret_ref",
    "keysecretreffile": "api_key_secret_ref_file",
    "profilekey": "profile_key",
    "presetkey": "preset_key",
    "routepresetkey": "route_preset_key",
    "bindingsjson": "bindings_json",
    "bindingsjsonfile": "bindings_json_file",
    "modelname": "model_name",
    "timeoutseconds": "timeout_seconds",
    "temperature": "temperature",
    "isdefault": "is_default",
    "status": "status",
    "note": "note",
    "notefile": "note_file",
    "fallbackprofilekeysjsonfile": "fallback_profile_keys_json_file",
    "definitionjsonfile": "definition_json_file",
    "workflowmode": "workflow_mode",
    "fromstage": "from_stage",
    "untilstage": "until_stage",
    "limit": "limit",
    "resume": "resume",
    "rerun": "rerun",
    "annotationid": "annotation_id",
    "locked": "locked",
    "agegroup": "age_group",
    "force": "force",
}


def build_help_text() -> str:
    return (
        "local_translation_workbench\n\n"
        "命令:\n"
        "  project.create\n"
        "  project.list / project.cancel / project.run_full\n"
        "  stage.run (chaptering/glossary/translation/review/export)\n"
        "  stage.cancel / stage.inspect_runs\n"
        "    可选标记: -Resume / -Rerun\n"
        "  provider.create / provider.list / provider.inspect / provider.set_key / provider.health_check\n"
        "  profile.create / profile.list / profile.inspect / profile.set_fallbacks\n"
        "  profile.terminal_fallback_set / profile.terminal_fallback_inspect / profile.terminal_fallback_clear\n"
        "  profile.route_set / profile.route_list / profile.route_inspect / profile.route_set_default\n"
        "  glossary.entry.create / glossary.entry.update / glossary.entry.delete / glossary.entry.lock / glossary.entry.unlock\n"
        "  glossary.candidate.create / glossary.candidate.update / glossary.candidate.approve / glossary.candidate.reject / glossary.candidate.delete / glossary.candidate.promote\n"
        "  glossary.denylist.add / glossary.denylist.list / glossary.denylist.delete\n"
        "  annotation.extract / annotation.inspect / annotation.approve / annotation.reject\n"
        "  inspect.project\n"
        "  inspect.glossary\n"
        "  inspect.synopsis\n"
        "  inspect.chapter / inspect.chapters\n"
        "  inspect.segment\n"
        "  inspect.translation\n"
        "  inspect.translation_samples\n"
        "  inspect.review\n"
        "  inspect.export\n"
        "  inspect.provider_calls / inspect.provider_costs\n"
        "\n"
        "参数:\n"
        "  复杂 JSON 或中文长文本可用 -XxxFile <utf8-file>，也可把参数值写成 @<utf8-file>\n"
        "  profile.route_set_default 可用 -WorkflowMode keep|single|multi 同步切换 workflow 默认值\n"
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
