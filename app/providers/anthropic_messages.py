from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..errors import ToolError
from .base import Provider, TextGenerationResult


@dataclass(frozen=True)
class AnthropicMessagesProvider(Provider):
    base_url: str
    api_key: str
    timeout: int = 60

    def generate_text(self, *, prompt: str, model_name: str, timeout_seconds: int) -> TextGenerationResult:
        endpoint = self._build_endpoint()
        payload = {
            "model": model_name,
            "max_tokens": 1024,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt,
                        }
                    ],
                }
            ],
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        http_request = Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
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

        content = self._parse_content(response_text)
        if not content.strip():
            raise ToolError(code="provider_error", message="翻译服务未返回有效译文。", status=502)
        return TextGenerationResult(
            content=content.strip(),
            provider_name="anthropic_messages",
            model_name=model_name,
        )

    def _build_endpoint(self) -> str:
        base_url = self.base_url.rstrip("/")
        if base_url.endswith("/v1"):
            return f"{base_url}/messages"
        return f"{base_url}/v1/messages"

    def _parse_content(self, response_text: str) -> str:
        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise ToolError(code="provider_error", message="翻译服务返回了无法解析的响应。", status=502) from exc

        if not isinstance(payload, dict):
            raise ToolError(code="provider_error", message="翻译服务返回了无法解析的响应。", status=502)

        content = payload.get("content")
        if not isinstance(content, list):
            raise ToolError(code="provider_error", message="翻译服务返回了无法解析的响应。", status=502)

        content_parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "text":
                continue
            text = block.get("text")
            if isinstance(text, str):
                content_parts.append(text)
        return "".join(content_parts)
