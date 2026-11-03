"""LM Studio adapter contract tests; no live runtime is required."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.llm.contracts import ProviderCapabilities, UnsupportedCapability
from app.llm.lm_studio import LMStudioConfig, LMStudioProvider


class FakeClient:
    def __init__(self):
        self.chat_calls = []
        self.embedding_calls = []

        self.models = SimpleNamespace(
            list=lambda: SimpleNamespace(data=[SimpleNamespace(id="qwen-local")])
        )
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._chat_create)
        )
        self.embeddings = SimpleNamespace(create=self._embedding_create)

    def _chat_create(self, **kwargs):
        self.chat_calls.append(kwargs)
        if kwargs.get("stream"):
            return iter([
                SimpleNamespace(choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="hello", tool_calls=[]),
                        finish_reason=None,
                    )
                ]),
                SimpleNamespace(choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content=None, tool_calls=[]),
                        finish_reason="stop",
                    )
                ]),
            ])
        return SimpleNamespace(
            model=kwargs["model"],
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="hello", tool_calls=[]),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=2, completion_tokens=1),
        )

    def _embedding_create(self, **kwargs):
        self.embedding_calls.append(kwargs)
        return SimpleNamespace(
            model=kwargs["model"],
            data=[
                SimpleNamespace(index=1, embedding=[0.0, 1.0]),
                SimpleNamespace(index=0, embedding=[1.0, 0.0]),
            ],
            usage=SimpleNamespace(prompt_tokens=4, total_tokens=4),
        )


def test_provider_uses_loopback_and_lists_models():
    client = FakeClient()
    provider = LMStudioProvider(client=client)
    assert provider.provider_id == "lm_studio"
    assert provider.list_models() == ["qwen-local"]
    assert provider.health_check() is True


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/v1",
        "http://192.168.1.10:1234/v1",
        "http://localhost.example/v1",
    ],
)
def test_provider_rejects_non_loopback_endpoints(url):
    with pytest.raises(ValueError, match="loopback"):
        LMStudioProvider(LMStudioConfig(base_url=url), client=FakeClient())


def test_chat_completion_normalizes_response_and_usage():
    provider = LMStudioProvider(client=FakeClient())
    result = provider.chat_completion(
        model="qwen-local",
        messages=[{"role": "user", "content": "hello"}],
        options={"temperature": 0.1},
    )
    assert result.content == "hello"
    assert result.model == "qwen-local"
    assert result.finish_reason == "stop"
    assert result.usage["prompt_tokens"] == 2
    assert result.latency_ms is not None


def test_streaming_emits_normalized_events():
    provider = LMStudioProvider(client=FakeClient())
    events = list(provider.stream_chat(
        model="qwen-local",
        messages=[{"role": "user", "content": "hello"}],
    ))
    assert [event.event for event in events] == ["delta", "finish", "completed"]
    assert events[0].content == "hello"


def test_embeddings_preserve_input_order():
    provider = LMStudioProvider(client=FakeClient())
    result = provider.create_embeddings(model="embed-local", inputs=["a", "b"])
    assert result.vectors == ((1.0, 0.0), (0.0, 1.0))


def test_unsupported_vision_is_explicit():
    provider = LMStudioProvider(client=FakeClient())
    with pytest.raises(UnsupportedCapability, match="vision"):
        provider.vision_analysis(
            model="qwen-local",
            messages=[{"role": "user", "content": []}],
        )


def test_configured_vision_capability_uses_chat_endpoint():
    client = FakeClient()
    capabilities = ProviderCapabilities(vision=True)
    provider = LMStudioProvider(
        LMStudioConfig(capabilities=capabilities),
        client=client,
    )
    result = provider.vision_analysis(
        model="qwen-vl-local",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this page"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
            ],
        }],
    )
    assert result.content == "hello"


def test_tool_calls_are_disabled_unless_explicitly_enabled():
    provider = LMStudioProvider(client=FakeClient())
    with pytest.raises(UnsupportedCapability, match="tool calling"):
        provider.chat_completion(
            model="qwen-local",
            messages=[{"role": "user", "content": "run tool"}],
            options={"tools": [{"type": "function", "function": {"name": "demo"}}]},
        )


def test_structured_output_requires_explicit_capability_and_maps_schema():
    client = FakeClient()
    provider = LMStudioProvider(
        LMStudioConfig(
            capabilities=ProviderCapabilities(structured_output=True)
        ),
        client=client,
    )
    provider.generate_structured(
        model="qwen-local",
        messages=[{"role": "user", "content": "return JSON"}],
        schema={"name": "result", "schema": {"type": "object"}},
    )
    assert client.chat_calls[-1]["response_format"]["type"] == "json_schema"
