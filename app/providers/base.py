"""Provider-agnostic completion contract.

Every model backend — hosted API, local llama.cpp, or the deterministic offline
stub — implements :class:`LLMProvider`. Nothing above this layer knows which
vendor answered, which is what makes the platform genuinely model-agnostic.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


class ProviderError(RuntimeError):
    """Recoverable provider failure; the router will fail over."""

    def __init__(self, provider: str, message: str, *, retryable: bool = True) -> None:
        self.provider = provider
        self.retryable = retryable
        super().__init__(f"[{provider}] {message}")


class ProviderUnavailable(ProviderError):
    """Provider is not configured or not reachable."""

    def __init__(self, provider: str, message: str) -> None:
        super().__init__(provider, message, retryable=True)


@dataclass(frozen=True)
class CompletionRequest:
    system: str
    prompt: str
    max_tokens: int = 3000
    temperature: float = 0.15
    stop: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompletionResult:
    text: str
    provider: str
    model: str
    finish_reason: str
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_ms: int = 0

    @property
    def truncated(self) -> bool:
        """True when the backend stopped because it hit the output ceiling.

        This is the signal the anti-truncation pipeline exists to act on.
        """
        return self.finish_reason in {"max_tokens", "length", "truncated"}


class LLMProvider(abc.ABC):
    """Base class for all model backends."""

    name: str = "base"

    @abc.abstractmethod
    def is_configured(self) -> bool:
        """Cheap, non-network check that credentials/endpoints are present."""

    @abc.abstractmethod
    async def complete(self, request: CompletionRequest) -> CompletionResult:
        """Produce a completion or raise :class:`ProviderError`."""

    async def aclose(self) -> None:  # pragma: no cover - default no-op
        return None

    def describe(self) -> dict[str, Any]:
        return {"provider": self.name, "configured": self.is_configured()}
