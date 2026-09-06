"""Multi-tenant token verification and volumetric rate limiting.

Every call into the compliance surface must be attributable to a licensed
Akridion tenant and bounded by that tenant's tier — a free-tier key must never
be able to exhaust the same capacity an enterprise tenant is paying for. This
module resolves bearer tokens to a :class:`TenantContext` without ever
persisting or logging a raw token, and enforces a sliding-window rate limit
plus a calendar-month quota per tenant.

NOTE ON THE MEMORY BACKEND: the in-process ``memory`` rate-limit backend
counts requests per Python process. Running multiple uvicorn workers (or
multiple container replicas) each gets its own independent counter, so the
effective ceiling becomes ``workers * limit`` — silently more generous than
configured. Any multi-worker or multi-instance deployment MUST set
``LEGAFY_RATELIMIT_BACKEND=redis`` with a shared ``LEGAFY_REDIS_URL`` so every
worker enforces against one shared counter.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import math
import time
import uuid
from collections import deque
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.models.schemas import LicenseTier, RateLimitSnapshot, TenantContext

logger = logging.getLogger(__name__)

__all__ = [
    "TIER_DEFAULTS",
    "TenancyError",
    "InvalidToken",
    "ExpiredToken",
    "InsufficientScope",
    "RateLimitExceeded",
    "QuotaExceeded",
    "RateLimiter",
    "TenantRegistry",
    "get_tenant_registry",
    "get_rate_limiter",
    "authenticate",
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class TenancyError(Exception):
    """Base class for every tenancy / authentication failure."""


class InvalidToken(TenancyError):
    """The bearer token is missing, malformed, or matches no known tenant."""


class ExpiredToken(TenancyError):
    """The token resolved to a tenant, but that tenant's licence has lapsed."""


class InsufficientScope(TenancyError):
    """The tenant's tier does not grant the scope the endpoint requires."""


class RateLimitExceeded(TenancyError):
    """The tenant has exceeded its per-minute request rate."""

    def __init__(self, retry_after_seconds: int, message: str | None = None) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message or f"Rate limit exceeded; retry after {retry_after_seconds}s.")


class QuotaExceeded(TenancyError):
    """The tenant has exhausted its calendar-month quota."""

    def __init__(self, monthly_quota: int, used: int, message: str | None = None) -> None:
        self.monthly_quota = monthly_quota
        self.used = used
        super().__init__(message or f"Monthly quota exhausted ({used}/{monthly_quota}).")


# ---------------------------------------------------------------------------
# Tier defaults
# ---------------------------------------------------------------------------
TIER_DEFAULTS: dict[LicenseTier, dict[str, Any]] = {
    LicenseTier.DEVELOPER_FREE: {
        "rate_limit_per_minute": 10,
        "monthly_quota": 500,
        "scopes": ["audit"],
    },
    LicenseTier.PREMIUM_HOSTED: {
        "rate_limit_per_minute": 60,
        "monthly_quota": 20000,
        "scopes": ["audit", "generate"],
    },
    LicenseTier.ENTERPRISE_B2B: {
        "rate_limit_per_minute": 1000,
        "monthly_quota": 1000000,
        "scopes": ["*"],
    },
}

# Development convenience ONLY. These are resolved into a tenant exclusively
# when Settings.bootstrap_tokens_enabled is true AND Settings.is_production is
# false (see TenantRegistry.load) — they are never valid in a production
# environment, regardless of this flag, by construction of that gate.
_BOOTSTRAP_TOKENS: dict[str, dict[str, Any]] = {
    "akridion_dev_99x": {
        "organization_name": "Akridion Labs (dev bootstrap)",
        "tier": LicenseTier.DEVELOPER_FREE,
    },
    "akridion_premium_77z": {
        "organization_name": "Akridion Labs (premium bootstrap)",
        "tier": LicenseTier.PREMIUM_HOSTED,
    },
    "AKRIDION_DEV_9821": {
        "organization_name": "Akridion Labs (enterprise bootstrap)",
        "tier": LicenseTier.ENTERPRISE_B2B,
    },
}
_BOOTSTRAP_EXPIRY = date(2099, 12, 31)


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _token_id(token: str) -> str:
    """Stable, non-secret identifier for a token. Never derived from or reversible to it."""
    return "tk_" + _sha256_hex(token)[:8]


def _month_key(when: datetime | None = None) -> str:
    return (when or datetime.now(UTC)).strftime("%Y-%m")


def _extract_token(authorization: str | None) -> str | None:
    """Accept "Bearer <token>", "Token <token>", or a bare token."""
    if authorization is None:
        return None
    value = authorization.strip()
    if not value:
        return None
    parts = value.split(None, 1)
    if len(parts) == 2 and parts[0].lower() in {"bearer", "token"}:
        token = parts[1].strip()
    else:
        token = value
    return token or None


# ---------------------------------------------------------------------------
# Tenant registry
# ---------------------------------------------------------------------------
class TenantRegistry:
    """Resolves bearer tokens to a :class:`TenantContext`.

    Source order, decided once per :meth:`load`:

      1. A JSON file at ``settings.registry_path``, if it exists — entries may
         carry a raw ``token`` (development) or a ``token_sha256`` digest
         (production, preferred); see ``data/license_registry.example.json``.
      2. The built-in bootstrap tokens, but ONLY when
         ``settings.bootstrap_tokens_enabled`` is true and the environment is
         not production.

    Neither source available is a hard failure: it means production has been
    deployed with no way to authenticate anyone, which must not boot quietly.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Keyed by lowercase hex sha256 of the raw token.
        self._entries: dict[str, TenantContext] = {}
        self._loaded = False

    def load(self, force: bool = False) -> None:
        if self._loaded and not force:
            return

        registry_path: Path = self._settings.registry_path
        if registry_path.exists():
            entries = self._load_file(registry_path)
        elif self._settings.bootstrap_tokens_enabled and not self._settings.is_production:
            entries = self._load_bootstrap()
        else:
            raise RuntimeError(
                f"No tenant registry found at {registry_path!s} and bootstrap tokens are "
                "disabled (or this is a production environment, where bootstrap tokens are "
                "always refused). Publish a real registry file — see "
                "data/license_registry.example.json for the format — at "
                "LEGAFY_LICENSE_REGISTRY_PATH, or set LEGAFY_BOOTSTRAP_TOKENS_ENABLED=true in "
                "a non-production environment for local development."
            )

        self._entries = entries
        self._loaded = True

    def _load_bootstrap(self) -> dict[str, TenantContext]:
        out: dict[str, TenantContext] = {}
        for raw_token, meta in _BOOTSTRAP_TOKENS.items():
            tier: LicenseTier = meta["tier"]
            defaults = TIER_DEFAULTS[tier]
            ctx = TenantContext(
                token_id=_token_id(raw_token),
                organization_name=meta["organization_name"],
                tier=tier,
                expires_on=_BOOTSTRAP_EXPIRY,
                rate_limit_per_minute=defaults["rate_limit_per_minute"],
                monthly_quota=defaults["monthly_quota"],
                scopes=list(defaults["scopes"]),
            )
            out[_sha256_hex(raw_token)] = ctx
        return out

    def _load_file(self, path: Path) -> dict[str, TenantContext]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        out: dict[str, TenantContext] = {}
        for key, entry in raw.items():
            if key.startswith("_"):
                continue  # e.g. "_README"
            if not isinstance(entry, dict):
                continue

            token_sha256 = entry.get("token_sha256")
            if token_sha256:
                token_sha256 = str(token_sha256).lower()
            else:
                raw_token = entry.get("token")
                if not raw_token:
                    raise ValueError(
                        f"Registry entry {key!r} has neither 'token' nor 'token_sha256'."
                    )
                token_sha256 = _sha256_hex(raw_token)

            tier = LicenseTier(entry["tier"])
            defaults = TIER_DEFAULTS[tier]
            ctx = TenantContext(
                token_id="tk_" + token_sha256[:8],
                organization_name=entry.get("organization_name", key),
                tier=tier,
                expires_on=date.fromisoformat(entry["expires_on"]),
                rate_limit_per_minute=entry.get(
                    "rate_limit_per_minute", defaults["rate_limit_per_minute"]
                ),
                monthly_quota=entry.get("monthly_quota", defaults["monthly_quota"]),
                scopes=list(entry.get("scopes", defaults["scopes"])),
            )
            out[token_sha256] = ctx
        return out

    @property
    def tokens_loaded(self) -> int:
        return len(self._entries)

    def resolve(self, authorization: str | None) -> TenantContext:
        self.load()  # no-op once already loaded
        token = _extract_token(authorization)
        if not token:
            raise InvalidToken("Missing or malformed Authorization header.")

        token_sha256 = _sha256_hex(token)
        matched: TenantContext | None = None
        # Constant-time compare against every known digest — never short-circuit
        # on the first mismatch, so lookup time does not leak how close a guess
        # came to a real token.
        for known_sha256, ctx in self._entries.items():
            if hmac.compare_digest(known_sha256, token_sha256):
                matched = ctx
        if matched is None:
            raise InvalidToken("Token not recognised.")
        if matched.expires_on < date.today():
            raise ExpiredToken(
                f"Token for {matched.organization_name!r} expired on {matched.expires_on}."
            )
        return matched


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------
class RateLimiter:
    """Sliding 60-second window request limiter plus a calendar-month quota.

    Backends:
      * ``memory`` (default) — an in-process deque per token. See the module
        docstring's multi-worker caveat.
      * ``redis`` — a sorted-set sliding window (ZREMRANGEBYSCORE / ZCARD /
        ZADD / EXPIRE) plus an INCR quota counter keyed by calendar month.
        ``redis.asyncio`` is imported lazily; if it is not installed or the
        connection fails, a warning is logged once and the limiter degrades
        to the memory backend for the rest of the process lifetime.
    """

    def __init__(self, backend: str = "memory", redis_url: str | None = None) -> None:
        self._backend = backend
        self._redis_url = redis_url
        self._redis: Any = None
        self._redis_warned = False
        self._lock = asyncio.Lock()
        self._windows: dict[str, deque[float]] = {}
        self._quota: dict[str, dict[str, int]] = {}

    async def _get_redis(self) -> Any:
        if self._backend != "redis":
            return None
        if self._redis is not None:
            return self._redis
        try:
            import redis.asyncio as redis_asyncio
        except Exception as exc:  # pragma: no cover - exercised only without the dep
            self._degrade(f"redis package unavailable ({exc})")
            return None
        try:
            client = redis_asyncio.from_url(self._redis_url or "redis://localhost:6379/0")
            await client.ping()
        except Exception as exc:
            self._degrade(f"could not reach redis at {self._redis_url!r} ({exc})")
            return None
        self._redis = client
        return client

    def _degrade(self, reason: str) -> None:
        if not self._redis_warned:
            logger.warning(
                "Rate limiter degrading from redis to the memory backend: %s. "
                "This is a single-process caveat only — see module docstring.",
                reason,
            )
            self._redis_warned = True
        self._backend = "memory"
        self._redis = None

    async def consume(
        self, token_id: str, limit_per_minute: int, monthly_quota: int
    ) -> RateLimitSnapshot:
        client = await self._get_redis()
        if client is not None:
            return await self._via_redis(
                client, token_id, limit_per_minute, monthly_quota, mutate=True
            )
        return await self._via_memory(token_id, limit_per_minute, monthly_quota, mutate=True)

    async def peek(
        self, token_id: str, limit_per_minute: int, monthly_quota: int
    ) -> RateLimitSnapshot:
        client = await self._get_redis()
        if client is not None:
            return await self._via_redis(
                client, token_id, limit_per_minute, monthly_quota, mutate=False
            )
        return await self._via_memory(token_id, limit_per_minute, monthly_quota, mutate=False)

    async def reset(self, token_id: str | None = None) -> None:
        """Test hook: clears counters for one token, or every token."""
        async with self._lock:
            if token_id is None:
                self._windows.clear()
                self._quota.clear()
            else:
                self._windows.pop(token_id, None)
                self._quota.pop(token_id, None)

        client = await self._get_redis()
        if client is None:
            return
        if token_id is None:
            async for key in client.scan_iter(match="legafy:rl:*"):
                await client.delete(key)
            async for key in client.scan_iter(match="legafy:quota:*"):
                await client.delete(key)
        else:
            await client.delete(f"legafy:rl:{token_id}")
            async for key in client.scan_iter(match=f"legafy:quota:{token_id}:*"):
                await client.delete(key)

    # -- memory backend ----------------------------------------------------
    async def _via_memory(
        self, token_id: str, limit_per_minute: int, monthly_quota: int, *, mutate: bool
    ) -> RateLimitSnapshot:
        async with self._lock:
            now = time.monotonic()
            window = self._windows.setdefault(token_id, deque())
            cutoff = now - 60.0
            while window and window[0] <= cutoff:
                window.popleft()

            month_key = _month_key()
            quota_bucket = self._quota.setdefault(token_id, {})
            used_this_month = quota_bucket.get(month_key, 0)

            def retry_after() -> int:
                return max(1, math.ceil(window[0] + 60.0 - now))

            if not mutate:
                return RateLimitSnapshot(
                    limit_per_minute=limit_per_minute,
                    remaining_this_minute=max(0, limit_per_minute - len(window)),
                    monthly_quota=monthly_quota,
                    used_this_month=used_this_month,
                    retry_after_seconds=(
                        retry_after() if len(window) >= limit_per_minute and window else None
                    ),
                )

            if len(window) >= limit_per_minute:
                raise RateLimitExceeded(retry_after_seconds=retry_after())
            if used_this_month >= monthly_quota:
                raise QuotaExceeded(monthly_quota=monthly_quota, used=used_this_month)

            window.append(now)
            quota_bucket[month_key] = used_this_month + 1

            return RateLimitSnapshot(
                limit_per_minute=limit_per_minute,
                remaining_this_minute=max(0, limit_per_minute - len(window)),
                monthly_quota=monthly_quota,
                used_this_month=used_this_month + 1,
                retry_after_seconds=None,
            )

    # -- redis backend -------------------------------------------------------
    async def _via_redis(
        self,
        client: Any,
        token_id: str,
        limit_per_minute: int,
        monthly_quota: int,
        *,
        mutate: bool,
    ) -> RateLimitSnapshot:
        window_key = f"legafy:rl:{token_id}"
        month_key = f"legafy:quota:{token_id}:{_month_key()}"
        now = time.time()
        cutoff = now - 60.0
        try:
            await client.zremrangebyscore(window_key, 0, cutoff)
            current = await client.zcard(window_key)
            used_this_month = int(await client.get(month_key) or 0)

            async def retry_after() -> int:
                oldest = await client.zrange(window_key, 0, 0, withscores=True)
                oldest_ts = oldest[0][1] if oldest else now
                return max(1, math.ceil(oldest_ts + 60.0 - now))

            if not mutate:
                retry = await retry_after() if current >= limit_per_minute else None
                return RateLimitSnapshot(
                    limit_per_minute=limit_per_minute,
                    remaining_this_minute=max(0, limit_per_minute - current),
                    monthly_quota=monthly_quota,
                    used_this_month=used_this_month,
                    retry_after_seconds=retry,
                )

            if current >= limit_per_minute:
                raise RateLimitExceeded(retry_after_seconds=await retry_after())
            if used_this_month >= monthly_quota:
                raise QuotaExceeded(monthly_quota=monthly_quota, used=used_this_month)

            member = f"{now!r}:{uuid.uuid4().hex[:8]}"
            await client.zadd(window_key, {member: now})
            await client.expire(window_key, 60)
            new_used = await client.incr(month_key)
            if new_used == 1:
                await client.expire(month_key, 60 * 60 * 24 * 40)  # comfortably covers a month

            return RateLimitSnapshot(
                limit_per_minute=limit_per_minute,
                remaining_this_minute=max(0, limit_per_minute - (current + 1)),
                monthly_quota=monthly_quota,
                used_this_month=int(new_used),
                retry_after_seconds=None,
            )
        except (RateLimitExceeded, QuotaExceeded):
            raise
        except Exception as exc:
            self._degrade(f"redis operation failed ({exc})")
            return await self._via_memory(token_id, limit_per_minute, monthly_quota, mutate=mutate)


# ---------------------------------------------------------------------------
# Singletons + request-path helper
# ---------------------------------------------------------------------------
_registry_singleton: TenantRegistry | None = None
_rate_limiter_singleton: RateLimiter | None = None


def get_tenant_registry() -> TenantRegistry:
    global _registry_singleton
    if _registry_singleton is None:
        _registry_singleton = TenantRegistry(get_settings())
    return _registry_singleton


def get_rate_limiter() -> RateLimiter:
    global _rate_limiter_singleton
    if _rate_limiter_singleton is None:
        settings = get_settings()
        _rate_limiter_singleton = RateLimiter(
            backend=settings.ratelimit_backend, redis_url=settings.redis_url
        )
    return _rate_limiter_singleton


def reset_tenancy_cache() -> None:
    """Test hook — drops both singletons so new settings take effect."""
    global _registry_singleton, _rate_limiter_singleton
    _registry_singleton = None
    _rate_limiter_singleton = None


async def authenticate(
    authorization: str | None, required_scope: str
) -> tuple[TenantContext, RateLimitSnapshot]:
    """Resolve a bearer token, enforce scope, then enforce rate + quota."""
    tenant = get_tenant_registry().resolve(authorization)
    if not tenant.has_scope(required_scope):
        raise InsufficientScope(
            f"Token for {tenant.organization_name!r} lacks the {required_scope!r} scope."
        )
    snapshot = await get_rate_limiter().consume(
        tenant.token_id, tenant.rate_limit_per_minute, tenant.monthly_quota
    )
    return tenant, snapshot
