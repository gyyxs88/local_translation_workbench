from __future__ import annotations

from typing import Any

from .. import action_support as support
from ..services.glossary_denylist_service import GlossaryDenylistService
from ..services.glossary_management_service import GlossaryManagementService


def handle_glossary_entry_create(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = GlossaryManagementService(session).create_entry(
            project_id=int(support._require_argument(arguments, "project_id")),
            source_term=support._require_argument(arguments, "source_term"),
            target_term=support._require_argument(arguments, "target_term"),
            category=arguments.get("category", "entity"),
            note=support._read_optional_argument(arguments, "note"),
            gender=support._read_optional_argument(arguments, "gender"),
            age_group=support._read_optional_argument(arguments, "age_group"),
            status=arguments.get("status", "active"),
            locked=support._parse_bool(arguments.get("locked")),
            term_group_key=support._read_optional_argument(arguments, "term_group_key"),
            relation_role=arguments.get("relation_role", "independent"),
            scope_level=arguments.get("scope_level", "project_term"),
            scope_chapter_id=support._parse_optional_int(arguments.get("scope_chapter_id")),
        )
        session.commit()
        return {"ok": True, "action": "glossary.entry.create", "data": data}
    finally:
        session.close()


def handle_glossary_entry_update(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = GlossaryManagementService(session).update_entry(
            entry_id=support._parse_optional_int(arguments.get("entry_id")),
            project_id=support._parse_optional_int(arguments.get("project_id")),
            source_term=support._read_optional_argument(arguments, "source_term"),
            scope_level=arguments.get("scope_level", "project_term"),
            scope_chapter_id=support._parse_optional_int(arguments.get("scope_chapter_id")),
            target_term=support._read_optional_argument(arguments, "target_term"),
            category=support._read_optional_argument(arguments, "category"),
            note=support._read_optional_argument(arguments, "note"),
            gender=support._read_optional_argument(arguments, "gender"),
            age_group=support._read_optional_argument(arguments, "age_group"),
            status=support._read_optional_argument(arguments, "status"),
            locked=(
                support._parse_bool(arguments.get("locked"))
                if arguments.get("locked") is not None
                else None
            ),
            term_group_key=support._read_optional_argument(arguments, "term_group_key"),
            relation_role=support._read_optional_argument(arguments, "relation_role"),
        )
        session.commit()
        return {"ok": True, "action": "glossary.entry.update", "data": data}
    finally:
        session.close()


def handle_glossary_entry_delete(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = GlossaryManagementService(session).delete_entry(
            entry_id=support._parse_optional_int(arguments.get("entry_id")),
            project_id=support._parse_optional_int(arguments.get("project_id")),
            source_term=support._read_optional_argument(arguments, "source_term"),
            scope_level=arguments.get("scope_level", "project_term"),
            scope_chapter_id=support._parse_optional_int(arguments.get("scope_chapter_id")),
            force=support._parse_bool(arguments.get("force")),
        )
        session.commit()
        return {"ok": True, "action": "glossary.entry.delete", "data": data}
    finally:
        session.close()


def handle_glossary_entry_lock(arguments: dict[str, str]) -> dict[str, Any]:
    return _handle_glossary_entry_lock_state(arguments, locked=True, action="glossary.entry.lock")


def handle_glossary_entry_unlock(arguments: dict[str, str]) -> dict[str, Any]:
    return _handle_glossary_entry_lock_state(arguments, locked=False, action="glossary.entry.unlock")


def _handle_glossary_entry_lock_state(
    arguments: dict[str, str],
    *,
    locked: bool,
    action: str,
) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = GlossaryManagementService(session).set_entry_lock(
            locked=locked,
            entry_id=support._parse_optional_int(arguments.get("entry_id")),
            project_id=support._parse_optional_int(arguments.get("project_id")),
            source_term=support._read_optional_argument(arguments, "source_term"),
            scope_level=arguments.get("scope_level", "project_term"),
            scope_chapter_id=support._parse_optional_int(arguments.get("scope_chapter_id")),
        )
        session.commit()
        return {"ok": True, "action": action, "data": data}
    finally:
        session.close()


def handle_glossary_candidate_create(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = GlossaryManagementService(session).create_candidate(
            project_id=int(support._require_argument(arguments, "project_id")),
            chapter_id=int(support._require_argument(arguments, "chapter_id")),
            source_term=support._require_argument(arguments, "source_term"),
            suggested_term=support._require_argument(arguments, "suggested_term"),
            category=arguments.get("category", "entity"),
            note=support._read_optional_argument(arguments, "note"),
            gender=support._read_optional_argument(arguments, "gender"),
            age_group=support._read_optional_argument(arguments, "age_group"),
            status=arguments.get("status", "pending"),
            term_group_key=support._read_optional_argument(arguments, "term_group_key"),
            relation_role=arguments.get("relation_role", "independent"),
            scope_level=support._read_optional_argument(arguments, "scope_level"),
            scope_chapter_id=support._parse_optional_int(arguments.get("scope_chapter_id")),
        )
        session.commit()
        return {"ok": True, "action": "glossary.candidate.create", "data": data}
    finally:
        session.close()


def handle_glossary_candidate_update(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = GlossaryManagementService(session).update_candidate(
            candidate_id=int(support._require_argument(arguments, "candidate_id")),
            source_term=support._read_optional_argument(arguments, "source_term"),
            suggested_term=support._read_optional_argument(arguments, "suggested_term"),
            category=support._read_optional_argument(arguments, "category"),
            note=support._read_optional_argument(arguments, "note"),
            gender=support._read_optional_argument(arguments, "gender"),
            age_group=support._read_optional_argument(arguments, "age_group"),
            status=support._read_optional_argument(arguments, "status"),
            term_group_key=support._read_optional_argument(arguments, "term_group_key"),
            relation_role=support._read_optional_argument(arguments, "relation_role"),
        )
        session.commit()
        return {"ok": True, "action": "glossary.candidate.update", "data": data}
    finally:
        session.close()


def handle_glossary_candidate_approve(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = GlossaryManagementService(session).approve_candidate(
            candidate_id=int(support._require_argument(arguments, "candidate_id"))
        )
        session.commit()
        return {"ok": True, "action": "glossary.candidate.approve", "data": data}
    finally:
        session.close()


def handle_glossary_candidate_reject(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = GlossaryManagementService(session).reject_candidate(
            candidate_id=int(support._require_argument(arguments, "candidate_id"))
        )
        session.commit()
        return {"ok": True, "action": "glossary.candidate.reject", "data": data}
    finally:
        session.close()


def handle_glossary_candidate_delete(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = GlossaryManagementService(session).delete_candidate(
            candidate_id=int(support._require_argument(arguments, "candidate_id"))
        )
        session.commit()
        return {"ok": True, "action": "glossary.candidate.delete", "data": data}
    finally:
        session.close()


def handle_glossary_candidate_promote(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = GlossaryManagementService(session).promote_candidate(
            candidate_id=int(support._require_argument(arguments, "candidate_id")),
            locked=support._parse_bool(arguments.get("locked")),
            force=support._parse_bool(arguments.get("force")),
        )
        session.commit()
        return {"ok": True, "action": "glossary.candidate.promote", "data": data}
    finally:
        session.close()


def handle_glossary_denylist_add(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = GlossaryDenylistService(session).add_rule(
            project_id=support._parse_optional_int(arguments.get("project_id")),
            source_term=support._read_optional_argument(arguments, "source_term"),
            pattern=support._read_optional_argument(arguments, "pattern"),
            match_type=arguments.get("match_type", "exact"),
            reason_code=arguments.get("reason_code", "manual_reject"),
            note=support._read_optional_argument(arguments, "note"),
            status=arguments.get("status", "active"),
        )
        session.commit()
        return {"ok": True, "action": "glossary.denylist.add", "data": data}
    finally:
        session.close()


def handle_glossary_denylist_list(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = GlossaryDenylistService(session).list_rules(
            project_id=support._parse_optional_int(arguments.get("project_id")),
            include_global=support._parse_bool(arguments.get("include_global", "true")),
            status=support._read_optional_argument(arguments, "status") or "active",
        )
        return {"ok": True, "action": "glossary.denylist.list", "data": {"rules": data}}
    finally:
        session.close()


def handle_glossary_denylist_delete(arguments: dict[str, str]) -> dict[str, Any]:
    session = support._open_session()
    try:
        data = GlossaryDenylistService(session).delete_rule(
            rule_id=int(support._require_argument(arguments, "rule_id")),
        )
        session.commit()
        return {"ok": True, "action": "glossary.denylist.delete", "data": data}
    finally:
        session.close()


GLOSSARY_MANAGEMENT_ACTION_HANDLERS = {
    "glossary.entry.create": handle_glossary_entry_create,
    "glossary.entry.update": handle_glossary_entry_update,
    "glossary.entry.delete": handle_glossary_entry_delete,
    "glossary.entry.lock": handle_glossary_entry_lock,
    "glossary.entry.unlock": handle_glossary_entry_unlock,
    "glossary.candidate.create": handle_glossary_candidate_create,
    "glossary.candidate.update": handle_glossary_candidate_update,
    "glossary.candidate.approve": handle_glossary_candidate_approve,
    "glossary.candidate.reject": handle_glossary_candidate_reject,
    "glossary.candidate.delete": handle_glossary_candidate_delete,
    "glossary.candidate.promote": handle_glossary_candidate_promote,
    "glossary.denylist.add": handle_glossary_denylist_add,
    "glossary.denylist.list": handle_glossary_denylist_list,
    "glossary.denylist.delete": handle_glossary_denylist_delete,
}
