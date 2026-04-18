from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable


class GlossaryRelationGroupService:
    ROLE_PRIORITY = {
        "canonical": 0,
        "alias": 1,
        "title": 2,
        "variant": 3,
        "independent": 4,
    }

    def build_relation_groups(self, *, items: Iterable[object], member_id_field: str) -> list[dict[str, object]]:
        grouped: dict[str, list[object]] = defaultdict(list)
        for item in items:
            term_group_key = str(self._read(item, "term_group_key") or "").strip()
            if term_group_key == "":
                continue
            grouped[term_group_key].append(item)

        payload: list[dict[str, object]] = []
        for term_group_key, members in sorted(grouped.items()):
            if len(members) == 1 and str(self._read(members[0], "relation_role") or "independent") == "independent":
                continue
            payload.append(
                self._build_group_payload(
                    term_group_key=term_group_key,
                    members=members,
                    member_id_field=member_id_field,
                )
            )
        return payload

    def _build_group_payload(
        self,
        *,
        term_group_key: str,
        members: list[object],
        member_id_field: str,
    ) -> dict[str, object]:
        role_distribution = Counter(
            str(self._read(member, "relation_role") or "independent")
            for member in members
        )
        category_distribution = Counter(
            str(self._read(member, "category"))
            for member in members
            if self._read(member, "category") not in {None, ""}
        )
        category_values = set(category_distribution.keys())

        character_members = [
            member for member in members if str(self._read(member, "category") or "") == "character"
        ]
        gender_values = {
            str(self._read(member, "gender"))
            for member in character_members
            if self._read(member, "gender") not in {None, ""}
        }
        age_group_values = {
            str(self._read(member, "age_group"))
            for member in character_members
            if self._read(member, "age_group") not in {None, ""}
        }

        warnings: list[str] = []
        canonical_count = int(role_distribution.get("canonical", 0))
        if canonical_count == 0:
            warnings.append("missing_canonical")
        elif canonical_count > 1:
            warnings.append("multiple_canonical")
        if len(category_values) > 1:
            warnings.append("mixed_category")
        if len(gender_values) > 1:
            warnings.append("gender_conflict")
        if len(age_group_values) > 1:
            warnings.append("age_group_conflict")

        member_payload = sorted(
            [
                {
                    member_id_field: int(self._read(member, "id")),
                    "source_term": str(self._read(member, "source_term")),
                    "target_term": str(
                        self._read(member, "target_term")
                        or self._read(member, "suggested_term")
                        or ""
                    ),
                    "category": self._read(member, "category"),
                    "gender": self._read(member, "gender"),
                    "age_group": self._read(member, "age_group"),
                    "relation_role": str(self._read(member, "relation_role") or "independent"),
                    "status": self._read(member, "status"),
                    "locked": self._read(member, "locked"),
                }
                for member in members
            ],
            key=lambda item: (
                int(self.ROLE_PRIORITY.get(str(item["relation_role"]), 99)),
                str(item["source_term"]),
            ),
        )

        return {
            "term_group_key": term_group_key,
            "member_count": len(member_payload),
            "category_distribution": dict(category_distribution),
            "role_distribution": dict(role_distribution),
            "consistency": {
                "category_consistent": len(category_values) <= 1,
                "gender_consistent": len(gender_values) <= 1,
                "age_group_consistent": len(age_group_values) <= 1,
                "warnings": warnings,
            },
            "members": member_payload,
        }

    def _read(self, item: object, key: str):
        if isinstance(item, dict):
            return item.get(key)
        return getattr(item, key, None)
