from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..errors import ToolError
from .base import Provider, TextGenerationResult


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

        content = self._parse_streaming_content(response_text)
        if not content.strip():
            raise ToolError(code="provider_error", message="翻译服务未返回有效译文。", status=502)
        return TextGenerationResult(
            content=content.strip(),
            provider_name="openai_compatible",
            model_name=model_name,
        )

    def _build_endpoint(self) -> str:
        base_url = self.base_url.rstrip("/")
        if base_url.endswith("/v1"):
            return f"{base_url}/chat/completions"
        return f"{base_url}/v1/chat/completions"

    def _parse_streaming_content(self, response_text: str) -> str:
        content_parts: list[str] = []
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
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            piece = delta.get("content")
            if isinstance(piece, str):
                content_parts.append(piece)
        return "".join(content_parts)
