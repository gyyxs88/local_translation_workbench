from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..errors import ToolError
from .base import Provider, TextGenerationResult, TextGenerationUsage


@dataclass(frozen=True)
class OpenAICompatibleProvider(Provider):
    base_url: str
    api_key: str
    timeout: int = 60

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        endpoint = self._build_endpoint()
        payload = {
            "model": model_name,
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        http_request = Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with urlopen(http_request, timeout=timeout_seconds or self.timeout) as response:
                response_text = response.read().decode("utf-8")
        except HTTPError as exc:
            message = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else str(exc)
            raise ToolError(code="provider_error", message=f"翻译服务调用失败: {message}", status=502) from exc
        except URLError as exc:
            raise ToolError(code="provider_error", message=f"翻译服务不可用: {exc.reason}", status=502) from exc

        content, usage = self._parse_response(response_text)
        if not content.strip():
            raise ToolError(code="provider_error", message="翻译服务未返回有效译文。", status=502)
        return TextGenerationResult(
            content=content.strip(),
            provider_name="openai_compatible",
            model_name=model_name,
            usage=usage,
        )

    def _build_endpoint(self) -> str:
        base_url = self.base_url.rstrip("/")
        if base_url.endswith("/v1"):
            return f"{base_url}/chat/completions"
        return f"{base_url}/v1/chat/completions"

    def _parse_response(self, response_text: str) -> tuple[str, TextGenerationUsage | None]:
        stripped_text = response_text.lstrip()
        if stripped_text.startswith("{"):
            return self._parse_json_response(stripped_text)
        return self._parse_streaming_response(response_text)

    def _parse_streaming_response(self, response_text: str) -> tuple[str, TextGenerationUsage | None]:
        content_parts: list[str] = []
        usage: TextGenerationUsage | None = None
        for raw_line in response_text.splitlines():
            line = raw_line.strip()
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise ToolError(code="provider_error", message="翻译服务返回了无法解析的流式响应。", status=502) from exc
            usage_payload = chunk.get("usage")
            if isinstance(usage_payload, dict):
                usage = TextGenerationUsage.from_payload(
                    {
                        "input_tokens": usage_payload.get("prompt_tokens"),
                        "output_tokens": usage_payload.get("completion_tokens"),
                        "total_tokens": usage_payload.get("total_tokens"),
                    }
                )
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            piece = delta.get("content")
            if isinstance(piece, str):
                content_parts.append(piece)
        return "".join(content_parts), usage

    def _parse_json_response(self, response_text: str) -> tuple[str, TextGenerationUsage | None]:
        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise ToolError(code="provider_error", message="翻译服务返回了无法解析的响应。", status=502) from exc

        if not isinstance(payload, dict):
            raise ToolError(code="provider_error", message="翻译服务返回了无法解析的响应。", status=502)

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ToolError(code="provider_error", message="翻译服务返回了无法解析的响应。", status=502)

        first_choice = choices[0] if isinstance(choices[0], dict) else {}
        message_payload = first_choice.get("message") if isinstance(first_choice, dict) else {}
        content_value = message_payload.get("content") if isinstance(message_payload, dict) else None
        content = self._extract_message_content(content_value)
        usage_payload = payload.get("usage")
        usage = None
        if isinstance(usage_payload, dict):
            usage = TextGenerationUsage.from_payload(
                {
                    "input_tokens": usage_payload.get("prompt_tokens"),
                    "output_tokens": usage_payload.get("completion_tokens"),
                    "total_tokens": usage_payload.get("total_tokens"),
                }
            )
        return content, usage

    def _extract_message_content(self, content_value: object) -> str:
        if isinstance(content_value, str):
            return content_value
        if isinstance(content_value, list):
            parts: list[str] = []
            for item in content_value:
                if not isinstance(item, dict):
                    continue
                if item.get("type") != "text":
                    continue
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
            return "".join(parts)
        return ""
