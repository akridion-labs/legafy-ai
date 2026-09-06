"""Hosted and local model backends, all over plain httpx.

ponytail: three JSON POSTs do not need two vendor SDKs. Dropping `anthropic`
and `openai` removes two dependency trees from the CPU server image; the only
cost is that we pin the request/response shape ourselves, which is ~15 lines
per backend. Swap to an SDK if you start needing streaming or tool-use.
"""

from __future__ import annotations

import time

import httpx

from app.config import Settings
from app.providers.base import (
    CompletionRequest,
    CompletionResult,
    LLMProvider,
    ProviderError,
    ProviderUnavailable,
)

TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)


class _HttpProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=TIMEOUT)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _post(self, url: str, *, headers: dict, json: dict) -> dict:
        try:
            resp = await self._http().post(url, headers=headers, json=json)
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(self.name, f"transport error: {exc}") from exc
        if resp.status_code >= 400:
            # 4xx other than 408/429 is our bug, not a transient one — do not retry it.
            retryable = resp.status_code in (408, 429) or resp.status_code >= 500
            raise ProviderError(
                self.name, f"HTTP {resp.status_code}: {resp.text[:300]}", retryable=retryable
            )
        return resp.json()

    @staticmethod
    def _timed(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)


class AnthropicProvider(_HttpProvider):
    name = "anthropic"

    def is_configured(self) -> bool:
        return bool(self.settings.anthropic_api_key)

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        if not self.is_configured():
            raise ProviderUnavailable(self.name, "ANTHROPIC_API_KEY is not set")
        started = time.perf_counter()
        data = await self._post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.settings.anthropic_model,
                "max_tokens": request.max_tokens,
                "temperature": request.temperature,
                "system": request.system,
                "messages": [{"role": "user", "content": request.prompt}],
                **({"stop_sequences": list(request.stop)} if request.stop else {}),
            },
        )
        text = "".join(b.get("text", "") for b in data.get("content", []))
        usage = data.get("usage", {})
        return CompletionResult(
            text=text,
            provider=self.name,
            model=data.get("model", self.settings.anthropic_model),
            finish_reason=data.get("stop_reason") or "stop",
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            elapsed_ms=self._timed(started),
        )


class OpenAIProvider(_HttpProvider):
    """Also serves any OpenAI-compatible gateway via LEGAFY_OPENAI_BASE_URL."""

    name = "openai"

    def is_configured(self) -> bool:
        return bool(self.settings.openai_api_key)

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        if not self.is_configured():
            raise ProviderUnavailable(self.name, "OPENAI_API_KEY is not set")
        started = time.perf_counter()
        data = await self._post(
            f"{self.settings.openai_base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.settings.openai_api_key}",
                "content-type": "application/json",
            },
            json={
                "model": self.settings.openai_model,
                "max_tokens": request.max_tokens,
                "temperature": request.temperature,
                "messages": [
                    {"role": "system", "content": request.system},
                    {"role": "user", "content": request.prompt},
                ],
                **({"stop": list(request.stop)} if request.stop else {}),
            },
        )
        choice = (data.get("choices") or [{}])[0]
        usage = data.get("usage", {})
        return CompletionResult(
            text=(choice.get("message") or {}).get("content", ""),
            provider=self.name,
            model=data.get("model", self.settings.openai_model),
            finish_reason=choice.get("finish_reason") or "stop",
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            elapsed_ms=self._timed(started),
        )


class OllamaProvider(_HttpProvider):
    """Local CPU-server inference. No API key, no egress."""

    name = "ollama"

    def is_configured(self) -> bool:
        return bool(self.settings.ollama_base_url)

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        started = time.perf_counter()
        data = await self._post(
            f"{self.settings.ollama_base_url.rstrip('/')}/api/chat",
            headers={"content-type": "application/json"},
            json={
                "model": self.settings.ollama_model,
                "stream": False,
                "options": {
                    "temperature": request.temperature,
                    "num_predict": request.max_tokens,
                },
                "messages": [
                    {"role": "system", "content": request.system},
                    {"role": "user", "content": request.prompt},
                ],
            },
        )
        return CompletionResult(
            text=(data.get("message") or {}).get("content", ""),
            provider=self.name,
            model=data.get("model", self.settings.ollama_model),
            finish_reason="max_tokens" if data.get("done_reason") == "length" else "stop",
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            elapsed_ms=self._timed(started),
        )
