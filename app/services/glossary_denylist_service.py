from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db.models import GlossaryDenylistRule, TranslationProject
from ..errors import ToolError


VALID_MATCH_TYPES = {"exact", "contains", "regex"}


class GlossaryDenylistService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_rule(
        self,
        *,
        project_id: int | None,
        source_term: str | None = None,
        pattern: str | None = None,
        match_type: str = "exact",
        reason_code: str = "manual_reject",
        note: str | None = None,
        status: str = "active",
    ) -> dict[str, object]:
        if project_id is not None:
            self._ensure_project(project_id)
        normalized_match_type = self._normalize_match_type(match_type)
        normalized_source_term = self._normalize_optional_text(source_term)
        normalized_pattern = self._normalize_optional_text(pattern)
        if normalized_match_type in {"exact", "contains"} and normalized_source_term is None:
            normalized_source_term = normalized_pattern
        if normalized_match_type == "regex" and normalized_pattern is None:
            normalized_pattern = normalized_source_term
        if normalized_source_term is None and normalized_pattern is None:
            raise ToolError(code="invalid_arguments", message="denylist rule 必须提供 source_term 或 pattern。", status=400)
        if normalized_match_type == "regex":
            self._compile_regex(normalized_pattern or "")
        rule = GlossaryDenylistRule(
            project_id=project_id,
            source_term=normalized_source_term,
            pattern=normalized_pattern,
            match_type=normalized_match_type,
            reason_code=self._normalize_optional_text(reason_code) or "manual_reject",
            note=self._normalize_optional_text(note),
            status=self._normalize_optional_text(status) or "active",
        )
        self.session.add(rule)
        self.session.flush()
        return self._rule_payload(rule)

    def list_rules(
        self,
        *,
        project_id: int | None = None,
        include_global: bool = True,
        status: str | None = "active",
    ) -> list[dict[str, object]]:
        statement = select(GlossaryDenylistRule)
        if project_id is not None:
            if include_global:
                statement = statement.where(
                    or_(
                        GlossaryDenylistRule.project_id == project_id,
                        GlossaryDenylistRule.project_id.is_(None),
                    )
                )
            else:
                statement = statement.where(GlossaryDenylistRule.project_id == project_id)
        if status:
            statement = statement.where(GlossaryDenylistRule.status == status)
        statement = statement.order_by(GlossaryDenylistRule.project_id.asc(), GlossaryDenylistRule.id.asc())
        return [self._rule_payload(row) for row in self.session.execute(statement).scalars().all()]

    def delete_rule(self, *, rule_id: int) -> dict[str, object]:
        rule = self.session.get(GlossaryDenylistRule, rule_id)
        if rule is None:
            raise ToolError(code="not_found", message=f"找不到 denylist rule {rule_id}。", status=404)
        payload = {"id": int(rule.id), "project_id": rule.project_id, "deleted": True}
        self.session.delete(rule)
        self.session.flush()
        return payload

    def filter_terms(self, *, project_id: int, terms: list[Any]) -> dict[str, list[Any]]:
        rules = self._load_active_rules(project_id=project_id)
        accepted_terms: list[Any] = []
        rejected_terms: list[dict[str, object]] = []
        for term in terms:
            source_term = self._read_term_source(term)
            matched_rule = self._match_rule(source_term=source_term, rules=rules)
            if matched_rule is None:
                accepted_terms.append(term)
                continue
            rejected_terms.append(
                {
                    **self._term_payload(term),
                    "rule": self._rule_payload(matched_rule),
                }
            )
        return {
            "accepted_terms": accepted_terms,
            "rejected_terms": rejected_terms,
        }

    def _load_active_rules(self, *, project_id: int) -> list[GlossaryDenylistRule]:
        statement = (
            select(GlossaryDenylistRule)
            .where(
                GlossaryDenylistRule.status == "active",
                or_(
                    GlossaryDenylistRule.project_id == project_id,
                    GlossaryDenylistRule.project_id.is_(None),
                ),
            )
            .order_by(GlossaryDenylistRule.project_id.asc(), GlossaryDenylistRule.id.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def _match_rule(
        self,
        *,
        source_term: str,
        rules: list[GlossaryDenylistRule],
    ) -> GlossaryDenylistRule | None:
        for rule in rules:
            if self._rule_matches(source_term=source_term, rule=rule):
                return rule
        return None

    def _rule_matches(self, *, source_term: str, rule: GlossaryDenylistRule) -> bool:
        if source_term == "":
            return False
        match_type = str(rule.match_type)
        source_pattern = str(rule.pattern or rule.source_term or "")
        if source_pattern == "":
            return False
        if match_type == "exact":
            return source_term == source_pattern
        if match_type == "contains":
            return source_pattern in source_term
        if match_type == "regex":
            return re.search(source_pattern, source_term) is not None
        return False

    def _ensure_project(self, project_id: int) -> TranslationProject:
        project = self.session.get(TranslationProject, project_id)
        if project is None:
            raise ToolError(code="not_found", message=f"找不到项目 {project_id}。", status=404)
        return project

    def _rule_payload(self, rule: GlossaryDenylistRule) -> dict[str, object]:
        return {
            "id": int(rule.id),
            "project_id": rule.project_id,
            "source_term": rule.source_term,
            "pattern": rule.pattern,
            "match_type": rule.match_type,
            "reason_code": rule.reason_code,
            "note": rule.note,
            "status": rule.status,
        }

    def _term_payload(self, term: Any) -> dict[str, object]:
        if isinstance(term, Mapping):
            return {str(key): value for key, value in term.items()}
        payload: dict[str, object] = {
            "source_term": getattr(term, "source_term", ""),
        }
        for source_attr, payload_key in (
            ("suggested_term", "suggested_term"),
            ("category", "category"),
            ("note", "note"),
            ("gender", "gender"),
            ("age_group", "age_group"),
            ("term_group_key", "term_group_key"),
            ("relation_role", "relation_role"),
        ):
            value = getattr(term, source_attr, None)
            if value is not None:
                payload[payload_key] = value
        return payload

    def _read_term_source(self, term: Any) -> str:
        if isinstance(term, Mapping):
            return str(term.get("source_term") or "").strip()
        return str(getattr(term, "source_term", "") or "").strip()

    def _normalize_match_type(self, value: str) -> str:
        match_type = (value or "exact").strip().lower()
        if match_type not in VALID_MATCH_TYPES:
            raise ToolError(
                code="invalid_arguments",
                message=f"不支持的 denylist match_type: {value}",
                status=400,
            )
        return match_type

    def _normalize_optional_text(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _compile_regex(self, pattern: str) -> None:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ToolError(code="invalid_arguments", message=f"无效 regex pattern: {pattern}", status=400) from exc
