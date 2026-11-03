"""LM Studio adapter using its OpenAI-compatible local API."""
from __future__ import annotations

import ipaddress
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from app.llm.contracts import (
    ChatResult,
    EmbeddingResult,
    ProviderCapabilities,
    ProviderError,
    StreamEvent,
    UnsupportedCapability,
)


@dataclass(frozen=True)
class LMStudioConfig:
    base_url: str = "http://127.0.0.1:1234/v1"
    api_key: str = "lm-studio"
    timeout_seconds: float = 120.0
    capabilities: ProviderCapabilities = ProviderCapabilities()


def _validate_local_base_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("LM Studio base_url must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("LM Studio base_url must not contain credentials, query or fragment")
    host = parsed.hostname.casefold()
    is_local = host == "localhost"
    if not is_local:
        try:
            is_local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_local = False
    if not is_local:
        raise ValueError("LM Studio endpoint must use loopback; remote endpoints are disabled")
    return value.rstrip("/")


def _value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _as_dict(item: Any) -> dict[str, Any]:
    if item is None:
        return {}
    if isinstance(item, dict):
        return item
    dump = getattr(item, "model_dump", None)
    if callable(dump):
        return dump()
    return {}


class LMStudioProvider:
    """Local-only LM Studio adapter; SDK client can be injected for tests."""

    provider_id = "lm_studio"

    def __init__(self, config: LMStudioConfig | None = None, *, client: Any | None = None) -> None:
        self.config = config or LMStudioConfig()
        self.base_url = _validate_local_base_url(self.config.base_url)
        self.capabilities = self.config.capabilities
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError(
                    "Install the optional LLM dependencies: pip install -e '.[llm]'"
                ) from exc
            client = OpenAI(
                base_url=self.base_url,
                api_key=self.config.api_key,
                timeout=self.config.timeout_seconds,
            )
        self._client = client

    def _require(self, capability: str) -> None:
        if not getattr(self.capabilities, capability, False):
            raise UnsupportedCapability(
                f"LM Studio provider capability is disabled: {capability}"
            )

    def list_models(self) -> list[str]:
        try:
            response = self._client.models.list()
            return [
                str(_value(item, "id"))
                for item in _value(response, "data", [])
                if _value(item, "id")
            ]
        except Exception as exc:
            raise ProviderError(f"LM Studio model listing failed: {type(exc).__name__}") from exc

    def health_check(self) -> bool:
        try:
            self.list_models()
            return True
        except ProviderError:
            return False

    def chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
    ) -> ChatResult:
        self._require("chat")
        request_options = dict(options or {})
        tools = request_options.get("tools")
        if tools and not self.capabilities.tool_calling:
            raise UnsupportedCapability("LM Studio tool calling is disabled")
        started = time.perf_counter()
        try:
            response = self._client.chat.completions.create(
                model=model,
                messages=messages,
                **request_options,
            )
        except Exception as exc:
            raise ProviderError(f"LM Studio chat request failed: {type(exc).__name__}") from exc
        elapsed_ms = (time.perf_counter() - started) * 1000
        choices = _value(response, "choices", [])
        if not choices:
            raise ProviderError("LM Studio returned an empty chat completion")
        choice = choices[0]
        message = _value(choice, "message")
        content = _value(message, "content")
        tool_calls = _value(message, "tool_calls", []) or []
        return ChatResult(
            content=str(content) if content is not None else None,
            model=str(_value(response, "model", model)),
            finish_reason=_value(choice, "finish_reason"),
            tool_calls=tuple(_as_dict(call) for call in tool_calls),
            usage=_as_dict(_value(response, "usage")),
            latency_ms=round(elapsed_ms, 3),
        )

    def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
    ) -> Iterator[StreamEvent]:
        self._require("streaming")
        request_options = dict(options or {})
        tools = request_options.get("tools")
        if tools and not self.capabilities.tool_calling:
            raise UnsupportedCapability("LM Studio tool calling is disabled")
        try:
            stream = self._client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                **request_options,
            )
            for chunk in stream:
                choices = _value(chunk, "choices", []) or []
                if not choices:
                    continue
                delta = _value(choices[0], "delta")
                content = _value(delta, "content")
                calls = _value(delta, "tool_calls", []) or []
                if content or calls:
                    yield StreamEvent(
                        event="delta",
                        content=str(content) if content is not None else None,
                        tool_calls=tuple(_as_dict(call) for call in calls),
                    )
                finish_reason = _value(choices[0], "finish_reason")
                if finish_reason:
                    yield StreamEvent(event="finish", content=str(finish_reason))
            yield StreamEvent(event="completed")
        except UnsupportedCapability:
            raise
        except Exception as exc:
            raise ProviderError(
                f"LM Studio streaming request failed: {type(exc).__name__}"
            ) from exc

    def create_embeddings(
        self,
        *,
        model: str,
        inputs: list[str],
        options: dict[str, Any] | None = None,
    ) -> EmbeddingResult:
        self._require("embeddings")
        if not inputs:
            raise ValueError("Embedding inputs must not be empty")
        try:
            response = self._client.embeddings.create(
                model=model,
                input=inputs,
                **dict(options or {}),
            )
        except Exception as exc:
            raise ProviderError(
                f"LM Studio embedding request failed: {type(exc).__name__}"
            ) from exc
        data = sorted(_value(response, "data", []), key=lambda item: _value(item, "index", 0))
        vectors = tuple(
            tuple(float(value) for value in _value(item, "embedding", []))
            for item in data
        )
        if len(vectors) != len(inputs) or any(not vector for vector in vectors):
            raise ProviderError("LM Studio returned an incomplete embedding batch")
        return EmbeddingResult(
            model=str(_value(response, "model", model)),
            vectors=vectors,
            usage=_as_dict(_value(response, "usage")),
        )

    def vision_analysis(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
    ) -> ChatResult:
        self._require("vision")
        return self.chat_completion(model=model, messages=messages, options=options)

    def generate_structured(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> ChatResult:
        self._require("structured_output")
        request_options = dict(options or {})
        request_options["response_format"] = {
            "type": "json_schema",
            "json_schema": schema,
        }
        return self.chat_completion(model=model, messages=messages, options=request_options)

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            close()
