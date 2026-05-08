from __future__ import annotations

import json
from io import BytesIO
from urllib.error import HTTPError

import pytest

from tools.local_translation_workbench.app.errors import ToolError
from tools.local_translation_workbench.app.providers.openai_compatible import OpenAICompatibleProvider


class _FakeHttpResponse:
    def __init__(self, body: bytes) -> None:
        self.status = 200
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __iter__(self):
        return iter(self._body.splitlines(keepends=True))

    def __enter__(self) -> _FakeHttpResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_openai_compatible_provider_uses_stream_and_assembles_sse_chunks(monkeypatch) -> None:
    captured: dict[str, object] = {}
    sse_body = (
        'data: {"choices":[{"delta":{"role":"assistant"},"finish_reason":null}]}\n\n'
        'data: {"choices":[{"delta":{"content":"你好"},"finish_reason":null}]}\n\n'
        'data: {"choices":[{"delta":{"content":"，世界"},"finish_reason":null}]}\n\n'
        'data: {"choices":[{"delta":{"content":""},"finish_reason":"stop"}]}\n\n'
        'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":7,"total_tokens":19}}\n\n'
        "data: [DONE]\n\n"
    ).encode("utf-8")

    def fake_urlopen(request, timeout: int):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeHttpResponse(sse_body)

    monkeypatch.setattr(
        "tools.local_translation_workbench.app.providers.openai_compatible.urlopen",
        fake_urlopen,
    )

    provider = OpenAICompatibleProvider(
        base_url="https://codex-api.hk.pe/v1",
        api_key="sk-test",
    )

    result = provider.generate_text(
        prompt="请翻译这句话。",
        model_name="gpt-5.4",
        timeout_seconds=45,
    )

    assert captured["url"] == "https://codex-api.hk.pe/v1/chat/completions"
    assert captured["timeout"] == 45
    assert captured["headers"]["Content-type"] == "application/json"
    assert captured["body"]["stream"] is True
    assert captured["body"]["stream_options"] == {"include_usage": True}
    assert result.provider_name == "openai_compatible"
    assert result.model_name == "gpt-5.4"
    assert result.content == "你好，世界"
    assert result.usage is not None
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 7
    assert result.usage.total_tokens == 19


def test_openai_compatible_provider_wraps_timeout(monkeypatch) -> None:
    def fake_urlopen(request, timeout: int):
        raise TimeoutError("timed out")

    monkeypatch.setattr(
        "tools.local_translation_workbench.app.providers.openai_compatible.urlopen",
        fake_urlopen,
    )

    provider = OpenAICompatibleProvider(
        base_url="https://codex-api.hk.pe/v1",
        api_key="sk-test",
    )

    with pytest.raises(ToolError) as exc:
        provider.generate_text(
            prompt="请翻译这句话。",
            model_name="gpt-5.4",
            timeout_seconds=45,
        )

    assert exc.value.code == "provider_error"
    assert "超时" in exc.value.message


def test_openai_compatible_provider_enforces_total_stream_timeout(monkeypatch) -> None:
    sse_body = (
        'data: {"choices":[{"delta":{"content":"一"},"finish_reason":null}]}\n\n'
        'data: {"choices":[{"delta":{"content":"二"},"finish_reason":null}]}\n\n'
        "data: [DONE]\n\n"
    ).encode("utf-8")

    def fake_urlopen(request, timeout: int):
        _ = (request, timeout)
        return _FakeHttpResponse(sse_body)

    monotonic_values = iter([0.0, 1.0, 2.0, 4.0])

    monkeypatch.setattr(
        "tools.local_translation_workbench.app.providers.openai_compatible.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(
        "tools.local_translation_workbench.app.providers.openai_compatible.time.monotonic",
        lambda: next(monotonic_values),
    )

    provider = OpenAICompatibleProvider(
        base_url="https://codex-api.hk.pe/v1",
        api_key="sk-test",
    )

    with pytest.raises(ToolError) as exc:
        provider.generate_text(
            prompt="请翻译这句话。",
            model_name="gpt-5.4",
            timeout_seconds=3,
        )

    assert exc.value.code == "provider_error"
    assert "超时" in exc.value.message


def test_openai_compatible_provider_retries_capacity_limit(monkeypatch) -> None:
    calls = {"count": 0}
    sse_body = (
        'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":null}]}\n\n'
        "data: [DONE]\n\n"
    ).encode("utf-8")

    def fake_urlopen(request, timeout: int):
        calls["count"] += 1
        if calls["count"] == 1:
            raise HTTPError(
                request.full_url,
                429,
                "Too Many Requests",
                {},
                BytesIO(
                    b'{"error":{"message":"You have exhausted your capacity on this model. Your quota will reset after 1s."}}'
                ),
            )
        return _FakeHttpResponse(sse_body)

    monkeypatch.setattr(
        "tools.local_translation_workbench.app.providers.openai_compatible.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(
        "tools.local_translation_workbench.app.providers.openai_compatible.time.sleep",
        lambda seconds: None,
    )

    provider = OpenAICompatibleProvider(
        base_url="https://codex-api.hk.pe/v1",
        api_key="sk-test",
    )

    result = provider.generate_text(
        prompt="ping",
        model_name="gpt-5.4",
        timeout_seconds=45,
    )

    assert calls["count"] == 2
    assert result.content == "ok"


def test_openai_compatible_provider_retries_no_available_channel(monkeypatch) -> None:
    calls = {"count": 0}
    sse_body = (
        'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":null}]}\n\n'
        "data: [DONE]\n\n"
    ).encode("utf-8")

    def fake_urlopen(request, timeout: int):
        calls["count"] += 1
        if calls["count"] == 1:
            raise HTTPError(
                request.full_url,
                502,
                "Bad Gateway",
                {},
                BytesIO(
                    b'{"error":{"code":"model_not_found","message":"No available channel for model deepseek-v4-pro under group codex-pro (distributor)"}}'
                ),
            )
        return _FakeHttpResponse(sse_body)

    monkeypatch.setattr(
        "tools.local_translation_workbench.app.providers.openai_compatible.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(
        "tools.local_translation_workbench.app.providers.openai_compatible.time.sleep",
        lambda seconds: None,
    )

    provider = OpenAICompatibleProvider(
        base_url="https://api.deepseek.com/v1",
        api_key="sk-test",
    )

    result = provider.generate_text(
        prompt="translate",
        model_name="deepseek-v4-pro",
        timeout_seconds=45,
    )

    assert calls["count"] == 2
    assert result.content == "ok"


def test_openai_compatible_provider_retries_empty_translation_response(monkeypatch) -> None:
    calls = {"count": 0}
    empty_body = (
        'data: {"choices":[{"delta":{"content":""},"finish_reason":"stop"}]}\n\n'
        "data: [DONE]\n\n"
    ).encode("utf-8")
    ok_body = (
        'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":null}]}\n\n'
        "data: [DONE]\n\n"
    ).encode("utf-8")

    def fake_urlopen(request, timeout: int):
        calls["count"] += 1
        if calls["count"] == 1:
            return _FakeHttpResponse(empty_body)
        return _FakeHttpResponse(ok_body)

    monkeypatch.setattr(
        "tools.local_translation_workbench.app.providers.openai_compatible.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(
        "tools.local_translation_workbench.app.providers.openai_compatible.time.sleep",
        lambda seconds: None,
    )

    provider = OpenAICompatibleProvider(
        base_url="https://codex-api.hk.pe/v1",
        api_key="sk-test",
    )

    result = provider.generate_text(
        prompt="translate",
        model_name="gpt-5.4",
        timeout_seconds=45,
    )

    assert calls["count"] == 2
    assert result.content == "ok"
