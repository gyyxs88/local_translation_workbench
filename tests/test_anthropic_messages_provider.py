from __future__ import annotations

import json
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from tools.local_translation_workbench.app.errors import ToolError
from tools.local_translation_workbench.app.providers.anthropic_messages import AnthropicMessagesProvider


class _FakeHttpResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeHttpResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_anthropic_messages_provider_assembles_text_and_ignores_thinking(monkeypatch) -> None:
    captured: dict[str, object] = {}
    response_body = json.dumps(
        {
            "content": [
                {"type": "thinking", "thinking": "先思考一下"},
                {"type": "text", "text": "你好"},
                {"type": "text", "text": "，世界"},
                {"type": "tool_use", "id": "x"},
            ]
        },
        ensure_ascii=False,
    ).encode("utf-8")

    def fake_urlopen(request, timeout: int):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeHttpResponse(response_body)

    monkeypatch.setattr(
        "tools.local_translation_workbench.app.providers.anthropic_messages.urlopen",
        fake_urlopen,
    )

    provider = AnthropicMessagesProvider(
        base_url="https://example.com/v1",
        api_key="sk-test",
    )

    result = provider.generate_text(
        prompt="请翻译这句话。",
        model_name="claude-3-5-sonnet-latest",
        timeout_seconds=45,
    )

    assert captured["url"] == "https://example.com/v1/messages"
    assert captured["timeout"] == 45
    assert captured["headers"]["X-api-key"] == "sk-test"
    assert captured["headers"]["Anthropic-version"] == "2023-06-01"
    assert captured["headers"]["Content-type"] == "application/json"
    assert captured["body"]["model"] == "claude-3-5-sonnet-latest"
    assert captured["body"]["max_tokens"] == 1024
    assert captured["body"]["temperature"] == 0
    assert captured["body"]["messages"] == [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "请翻译这句话。",
                }
            ],
        }
    ]
    assert result.provider_name == "anthropic_messages"
    assert result.model_name == "claude-3-5-sonnet-latest"
    assert result.content == "你好，世界"


def test_anthropic_messages_provider_raises_when_text_missing(monkeypatch) -> None:
    def fake_urlopen(request, timeout: int):
        return _FakeHttpResponse(
            json.dumps(
                {
                    "content": [
                        {"type": "thinking", "thinking": "没有可直接返回的译文"},
                    ]
                },
                ensure_ascii=False,
            ).encode("utf-8")
        )

    monkeypatch.setattr(
        "tools.local_translation_workbench.app.providers.anthropic_messages.urlopen",
        fake_urlopen,
    )

    provider = AnthropicMessagesProvider(
        base_url="https://example.com",
        api_key="sk-test",
    )

    with pytest.raises(ToolError) as exc:
        provider.generate_text(
            prompt="请翻译这句话。",
            model_name="claude-3-5-sonnet-latest",
            timeout_seconds=45,
        )

    assert exc.value.code == "provider_error"
    assert exc.value.status == 502
    assert "未返回有效译文" in exc.value.message


def test_anthropic_messages_provider_wraps_http_502_error(monkeypatch) -> None:
    def fake_urlopen(request, timeout: int):
        raise HTTPError(
            url=request.full_url,
            code=502,
            msg="Bad Gateway",
            hdrs=None,
            fp=BytesIO(b"bad gateway"),
        )

    monkeypatch.setattr(
        "tools.local_translation_workbench.app.providers.anthropic_messages.urlopen",
        fake_urlopen,
    )

    provider = AnthropicMessagesProvider(
        base_url="https://example.com",
        api_key="sk-test",
    )

    with pytest.raises(ToolError) as exc:
        provider.generate_text(
            prompt="请翻译这句话。",
            model_name="claude-3-5-sonnet-latest",
            timeout_seconds=45,
        )

    assert exc.value.code == "provider_error"
    assert exc.value.status == 502
    assert "翻译服务调用失败" in exc.value.message


def test_anthropic_messages_provider_wraps_invalid_json_error(monkeypatch) -> None:
    def fake_urlopen(request, timeout: int):
        return _FakeHttpResponse(b"{invalid json")

    monkeypatch.setattr(
        "tools.local_translation_workbench.app.providers.anthropic_messages.urlopen",
        fake_urlopen,
    )

    provider = AnthropicMessagesProvider(
        base_url="https://example.com",
        api_key="sk-test",
    )

    with pytest.raises(ToolError) as exc:
        provider.generate_text(
            prompt="请翻译这句话。",
            model_name="claude-3-5-sonnet-latest",
            timeout_seconds=45,
        )

    assert exc.value.code == "provider_error"
    assert exc.value.status == 502
    assert "无法解析" in exc.value.message


def test_anthropic_messages_provider_wraps_url_error(monkeypatch) -> None:
    def fake_urlopen(request, timeout: int):
        raise URLError("temporary failure")

    monkeypatch.setattr(
        "tools.local_translation_workbench.app.providers.anthropic_messages.urlopen",
        fake_urlopen,
    )

    provider = AnthropicMessagesProvider(
        base_url="https://example.com",
        api_key="sk-test",
    )

    with pytest.raises(ToolError) as exc:
        provider.generate_text(
            prompt="请翻译这句话。",
            model_name="claude-3-5-sonnet-latest",
            timeout_seconds=45,
        )

    assert exc.value.code == "provider_error"
    assert exc.value.status == 502
    assert "不可用" in exc.value.message


def test_anthropic_messages_provider_wraps_invalid_response_shape(monkeypatch) -> None:
    def fake_urlopen(request, timeout: int):
        return _FakeHttpResponse(json.dumps(["not", "an", "object"]).encode("utf-8"))

    monkeypatch.setattr(
        "tools.local_translation_workbench.app.providers.anthropic_messages.urlopen",
        fake_urlopen,
    )

    provider = AnthropicMessagesProvider(
        base_url="https://example.com",
        api_key="sk-test",
    )

    with pytest.raises(ToolError) as exc:
        provider.generate_text(
            prompt="请翻译这句话。",
            model_name="claude-3-5-sonnet-latest",
            timeout_seconds=45,
        )

    assert exc.value.code == "provider_error"
    assert exc.value.status == 502
    assert "无法解析" in exc.value.message
