"""Provider-neutral contracts for local and remote-compatible model runtimes.

The platform defaults to local providers. Domain services should depend on these
contracts rather than importing a runtime SDK directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol


class ProviderError(RuntimeError):
    """A normalized provider/runtime failure."""


class UnsupportedCapability(ProviderError):
    """Raised when a provider is not configured for a requested capability."""


@dataclass(frozen=True)
class ProviderCapabilities:
    chat: bool = True
    streaming: bool = True
    structured_output: bool = False
    embeddings: bool = True
    vision: bool = False
    tool_calling: bool = False
    reranking: bool = False


@dataclass(frozen=True)
class ChatResult:
    content: str | None
    model: str
    finish_reason: str | None = None
    tool_calls: tuple[dict[str, Any], ...] = ()
    usage: dict[str, Any] = field(default_factory=dict)
    latency_ms: float | None = None


@dataclass(frozen=True)
class EmbeddingResult:
    model: str
    vectors: tuple[tuple[float, ...], ...]
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StreamEvent:
    event: str
    content: str | None = None
    tool_calls: tuple[dict[str, Any], ...] = ()


class LLMProvider(Protocol):
    provider_id: str
    capabilities: ProviderCapabilities

    def list_models(self) -> list[str]: ...

    def health_check(self) -> bool: ...

    def chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
    ) -> ChatResult: ...

    def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
    ) -> Iterator[StreamEvent]: ...

    def create_embeddings(
        self,
        *,
        model: str,
        inputs: list[str],
        options: dict[str, Any] | None = None,
    ) -> EmbeddingResult: ...
