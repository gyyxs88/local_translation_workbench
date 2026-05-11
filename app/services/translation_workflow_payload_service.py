from __future__ import annotations

from ..token_usage import merge_token_usage_payloads


class TranslationWorkflowPayloadService:
    def build_parallel_generation_payload(
        self,
        *,
        results: list[dict[str, object]],
        model_profile_id: str,
    ) -> dict[str, object]:
        actual_model_profiles = self._actual_model_profiles(results)
        max_fallback_depth = self._max_fallback_depth(results)
        token_usage = merge_token_usage_payloads(item.get("token_usage") for item in results)
        payload = {
            "segment_count": len(results),
            "draft_count": len(results),
            "model_profile_id": actual_model_profiles[-1] if actual_model_profiles else model_profile_id,
            "model_name": self._last_value(results, "model_name"),
            "provider_name": self._last_value(results, "provider_name"),
            "fallback_depth": max_fallback_depth,
            "chain_role": self._last_value(results, "chain_role") or "primary",
            "chain_roles": self._chain_roles(results),
            "terminal_fallback_used": self._terminal_fallback_used(results),
            "actual_model_profiles": actual_model_profiles,
            "max_fallback_depth": max_fallback_depth,
            "succeeded_segment_count": len(results),
            "failed_segment_count": 0,
            "failed_segments": [],
        }
        if token_usage is not None:
            payload["token_usage"] = token_usage
        return payload

    def build_parallel_review_payload(
        self,
        *,
        results: list[dict[str, object]],
        model_profile_id: str,
    ) -> dict[str, object]:
        actual_model_profiles = self._actual_model_profiles(results)
        max_fallback_depth = self._max_fallback_depth(results)
        token_usage = merge_token_usage_payloads(item.get("token_usage") for item in results)
        payload = {
            "reviewed_segment_count": sum(int(item.get("reviewed_segment_count") or 0) for item in results),
            "review_count": sum(int(item.get("review_count") or 0) for item in results),
            "model_profile_id": actual_model_profiles[-1] if actual_model_profiles else model_profile_id,
            "model_name": self._last_value(results, "model_name"),
            "provider_name": self._last_value(results, "provider_name"),
            "fallback_depth": max_fallback_depth,
            "chain_role": self._last_value(results, "chain_role") or "primary",
            "chain_roles": self._chain_roles(results),
            "terminal_fallback_used": self._terminal_fallback_used(results),
            "actual_model_profiles": actual_model_profiles,
            "max_fallback_depth": max_fallback_depth,
            "succeeded_segment_count": len(results),
            "failed_segment_count": 0,
            "failed_segments": [],
        }
        if token_usage is not None:
            payload["token_usage"] = token_usage
        return payload

    def build_parallel_rewrite_payload(
        self,
        *,
        results: list[dict[str, object]],
        model_profile_id: str,
    ) -> dict[str, object]:
        actual_model_profiles = self._actual_model_profiles(results)
        max_fallback_depth = self._max_fallback_depth(results)
        rewritten_count = sum(int(item.get("rewritten_draft_count") or 0) for item in results)
        token_usage = merge_token_usage_payloads(item.get("token_usage") for item in results)
        payload = {
            "rewritten_draft_count": rewritten_count,
            "model_profile_id": actual_model_profiles[-1] if actual_model_profiles else model_profile_id,
            "model_name": self._last_value(results, "model_name"),
            "provider_name": self._last_value(results, "provider_name"),
            "fallback_depth": max_fallback_depth,
            "chain_role": self._last_value(results, "chain_role") or "primary",
            "chain_roles": self._chain_roles(results),
            "terminal_fallback_used": self._terminal_fallback_used(results),
            "actual_model_profiles": actual_model_profiles,
            "max_fallback_depth": max_fallback_depth,
            "succeeded_segment_count": len(results),
            "failed_segment_count": 0,
            "failed_segments": [],
        }
        if token_usage is not None:
            payload["token_usage"] = token_usage
        return payload

    def build_parallel_finalize_payload(
        self,
        *,
        results: list[dict[str, object]],
        model_profile_id: str,
    ) -> dict[str, object]:
        actual_model_profiles = self._actual_model_profiles(results)
        max_fallback_depth = self._max_fallback_depth(results)
        return {
            "translated_segments": len(results),
            "active_version_ids": [int(item["active_version_id"]) for item in results if item.get("active_version_id")],
            "model_profile_id": actual_model_profiles[-1] if actual_model_profiles else model_profile_id,
            "model_name": self._last_value(results, "model_name"),
            "fallback_depth": max_fallback_depth,
            "chain_role": self._last_value(results, "chain_role") or "primary",
            "chain_roles": self._chain_roles(results),
            "terminal_fallback_used": self._terminal_fallback_used(results),
            "actual_model_profiles": actual_model_profiles,
            "max_fallback_depth": max_fallback_depth,
            "succeeded_segment_count": len(results),
            "failed_segment_count": 0,
            "failed_segments": [],
        }

    def _actual_model_profiles(self, results: list[dict[str, object]]) -> list[str]:
        return sorted({str(item["model_profile_id"]) for item in results if item.get("model_profile_id")})

    def _max_fallback_depth(self, results: list[dict[str, object]]) -> int:
        return max((int(item.get("fallback_depth") or 0) for item in results), default=0)

    def _last_value(self, results: list[dict[str, object]], key: str) -> object:
        return next((item.get(key) for item in reversed(results) if item.get(key)), None)

    def _chain_roles(self, results: list[dict[str, object]]) -> list[str]:
        return sorted({str(item["chain_role"]) for item in results if item.get("chain_role")})

    def _terminal_fallback_used(self, results: list[dict[str, object]]) -> bool:
        return any(bool(item.get("terminal_fallback_used")) for item in results)
