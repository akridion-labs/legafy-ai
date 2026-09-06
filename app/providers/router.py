"""Model-agnostic router: walk the configured chain, retry, fail over.

Nothing above this layer knows which vendor answered.
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from app.config import Settings, get_settings
from app.providers.base import CompletionRequest, CompletionResult, LLMProvider, ProviderError
from app.providers.offline import OfflineProvider
from app.providers.remote import AnthropicProvider, OllamaProvider, OpenAIProvider

log = logging.getLogger("legafy.router")

BACKOFF_SECONDS = (0.5, 1.5)


class ProviderRouter:
    def __init__(self, settings: Settings, *, sleep=asyncio.sleep) -> None:
        self.settings = settings
        self._sleep = sleep  # injectable so tests do not actually wait
        builders = {
            "anthropic": lambda: AnthropicProvider(settings),
            "openai": lambda: OpenAIProvider(settings),
            "ollama": lambda: OllamaProvider(settings),
            "offline": OfflineProvider,
        }
        self._providers: list[LLMProvider] = [
            builders[name]() for name in settings.providers if name in builders
        ]
        if not self._providers:
            raise ValueError(f"No known providers in chain {settings.provider_chain!r}")

    @property
    def chain(self) -> list[str]:
        return [p.name for p in self._providers]

    def describe(self) -> list[dict]:
        return [p.describe() for p in self._providers]

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        last: Exception | None = None
        for provider in self._providers:
            if not provider.is_configured():
                log.debug("skipping unconfigured provider %s", provider.name)
                continue
            for attempt, delay in enumerate((0.0, *BACKOFF_SECONDS)):
                if delay:
                    await self._sleep(delay)
                try:
                    return await provider.complete(request)
                except ProviderError as exc:
                    last = exc
                    if not exc.retryable:
                        break
                    log.warning(
                        "provider %s attempt %d failed: %s", provider.name, attempt + 1, exc
                    )
            log.warning("failing over from provider %s", provider.name)
        raise last or ProviderError("router", "no configured provider in the chain")

    async def aclose(self) -> None:
        for provider in self._providers:
            await provider.aclose()


@lru_cache(maxsize=1)
def get_router() -> ProviderRouter:
    return ProviderRouter(get_settings())


def reset_router_cache() -> None:
    get_router.cache_clear()
