from __future__ import annotations

import os
from pathlib import Path

from ..errors import ToolError


class ProviderSecretResolver:
    DATABASE_REF = "database"

    def resolve(self, *, api_key_value: str | None, api_key_secret_ref: str | None) -> str:
        source, normalized_ref = self._normalize_ref(api_key_secret_ref)
        if source == "database":
            value = self._normalize_secret_value(api_key_value)
            if value:
                return value
            raise ToolError(
                code="invalid_arguments",
                message="provider 缺少 database api_key_value。",
                status=400,
            )
        if source == "env":
            env_name = normalized_ref[4:].strip()
            value = self._normalize_secret_value(os.getenv(env_name))
            if value:
                return value
            raise ToolError(
                code="invalid_arguments",
                message=f"provider secret ref {normalized_ref} 未设置或为空。",
                status=400,
            )
        if source == "file":
            path_text = normalized_ref[5:].strip()
            if not path_text:
                raise ToolError(
                    code="invalid_arguments",
                    message="provider secret ref file 路径不能为空。",
                    status=400,
                )
            path = Path(path_text).expanduser()
            try:
                value = self._normalize_secret_value(path.read_text(encoding="utf-8-sig"))
            except OSError as exc:
                raise ToolError(
                    code="invalid_arguments",
                    message=f"provider secret ref {normalized_ref} 读取失败。",
                    status=400,
                ) from exc
            if value:
                return value
            raise ToolError(
                code="invalid_arguments",
                message=f"provider secret ref {normalized_ref} 为空。",
                status=400,
            )
        raise ToolError(
            code="invalid_arguments",
            message=f"不支持的 provider secret ref: {normalized_ref}",
            status=400,
        )

    def inspect(self, *, api_key_value: str | None, api_key_secret_ref: str | None) -> dict[str, object]:
        source, normalized_ref = self._normalize_ref(api_key_secret_ref)
        if source == "database":
            value = self._normalize_secret_value(api_key_value)
            return {
                "is_set": bool(value),
                "source": "database" if value else "missing",
                "ref": None,
                "masked": self._mask_secret(value) if value else None,
            }
        try:
            self.resolve(api_key_value=api_key_value, api_key_secret_ref=normalized_ref)
            is_set = True
        except ToolError:
            is_set = False
        return {
            "is_set": is_set,
            "source": source,
            "ref": normalized_ref,
            "masked": "****" if is_set else None,
        }

    def normalize_secret_ref(self, api_key_secret_ref: str | None) -> str | None:
        _, normalized_ref = self._normalize_ref(api_key_secret_ref)
        return normalized_ref

    def _normalize_ref(self, api_key_secret_ref: str | None) -> tuple[str, str | None]:
        normalized_ref = None if api_key_secret_ref is None else api_key_secret_ref.strip()
        if not normalized_ref:
            return "database", None
        lowered = normalized_ref.lower()
        if lowered == self.DATABASE_REF:
            return "database", self.DATABASE_REF
        if lowered.startswith("env:"):
            if not normalized_ref[4:].strip():
                raise ToolError(
                    code="invalid_arguments",
                    message="provider secret ref env 名称不能为空。",
                    status=400,
                )
            return "env", normalized_ref
        if lowered.startswith("file:"):
            if not normalized_ref[5:].strip():
                raise ToolError(
                    code="invalid_arguments",
                    message="provider secret ref file 路径不能为空。",
                    status=400,
                )
            return "file", normalized_ref
        raise ToolError(
            code="invalid_arguments",
            message=f"不支持的 provider secret ref: {normalized_ref}",
            status=400,
        )

    def _normalize_secret_value(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    def _mask_secret(self, value: str) -> str:
        if len(value) <= 8:
            return "****"
        return f"{value[:5]}...{value[-4:]}"
