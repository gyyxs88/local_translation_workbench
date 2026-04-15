from __future__ import annotations

import json

from tools.local_translation_workbench.app.providers.openai_compatible import OpenAICompatibleProvider


class _FakeHttpResponse:
    def __init__(self, body: bytes) -> None:
        self.status = 200
        self._body = body

    def read(self) -> bytes:
        return self._body

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
    assert result.provider_name == "openai_compatible"
    assert result.model_name == "gpt-5.4"
    assert result.content == "你好，世界"
