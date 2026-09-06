"""Tests for app.security.tenancy: token resolution, scopes, rate + quota limits.

Deterministic and offline: every registry is a temp JSON file under tmp_path,
never the repo's own data/ or generated/ directories, and the rate limiter
under test always uses the memory backend.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

import pytest

from app.config import Settings
from app.models.schemas import LicenseTier
from app.security import tenancy


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _settings(tmp_path, **overrides) -> Settings:
    kwargs = {
        "LEGAFY_ENV": "development",
        "LEGAFY_LICENSE_REGISTRY_PATH": str(tmp_path / "registry.json"),
        "LEGAFY_BOOTSTRAP_TOKENS_ENABLED": False,
    }
    kwargs.update(overrides)
    return Settings(**kwargs)


def _write_registry(tmp_path, entries: dict) -> None:
    (tmp_path / "registry.json").write_text(json.dumps(entries), encoding="utf-8")


# ---------------------------------------------------------------------------
# Token resolution
# ---------------------------------------------------------------------------
def test_valid_token_resolves_to_correct_tier_and_scopes(tmp_path):
    token = "premium-token-abc123"
    _write_registry(
        tmp_path,
        {
            "tenant-a": {
                "organization_name": "Beta SaaS",
                "tier": "PREMIUM_HOSTED",
                "token_sha256": _sha256(token),
                "expires_on": "2099-01-01",
            }
        },
    )
    registry = tenancy.TenantRegistry(_settings(tmp_path))

    ctx = registry.resolve(f"Bearer {token}")

    assert ctx.tier == LicenseTier.PREMIUM_HOSTED
    assert ctx.organization_name == "Beta SaaS"
    assert ctx.scopes == ["audit", "generate"]
    assert ctx.rate_limit_per_minute == tenancy.TIER_DEFAULTS[LicenseTier.PREMIUM_HOSTED][
        "rate_limit_per_minute"
    ]
    assert ctx.token_id.startswith("tk_")


@pytest.mark.parametrize("scheme", ["Bearer", "Token", ""])
def test_resolve_accepts_bearer_token_or_bare_token(tmp_path, scheme):
    token = "raw-dev-token-xyz"
    _write_registry(
        tmp_path,
        {
            "tenant-a": {
                "organization_name": "Acme Robotics",
                "tier": "DEVELOPER_FREE",
                "token": token,
                "expires_on": "2099-01-01",
            }
        },
    )
    registry = tenancy.TenantRegistry(_settings(tmp_path))
    header = f"{scheme} {token}".strip() if scheme else token

    ctx = registry.resolve(header)

    assert ctx.tier == LicenseTier.DEVELOPER_FREE


def test_per_tenant_overrides_win_over_tier_defaults(tmp_path):
    token = "enterprise-override-token"
    _write_registry(
        tmp_path,
        {
            "tenant-a": {
                "organization_name": "Gamma Holdings",
                "tier": "ENTERPRISE_B2B",
                "token_sha256": _sha256(token),
                "expires_on": "2099-01-01",
                "rate_limit_per_minute": 42,
                "monthly_quota": 777,
                "scopes": ["audit"],
            }
        },
    )
    registry = tenancy.TenantRegistry(_settings(tmp_path))

    ctx = registry.resolve(f"Bearer {token}")

    assert ctx.rate_limit_per_minute == 42
    assert ctx.monthly_quota == 777
    assert ctx.scopes == ["audit"]


@pytest.mark.parametrize("authorization", [None, "", "   ", "Bearer "])
def test_missing_or_blank_authorization_raises_invalid_token(tmp_path, authorization):
    _write_registry(tmp_path, {})
    registry = tenancy.TenantRegistry(_settings(tmp_path))

    with pytest.raises(tenancy.InvalidToken):
        registry.resolve(authorization)


def test_unknown_token_raises_invalid_token(tmp_path):
    _write_registry(
        tmp_path,
        {
            "tenant-a": {
                "organization_name": "Acme Robotics",
                "tier": "DEVELOPER_FREE",
                "token_sha256": _sha256("the-real-token"),
                "expires_on": "2099-01-01",
            }
        },
    )
    registry = tenancy.TenantRegistry(_settings(tmp_path))

    with pytest.raises(tenancy.InvalidToken):
        registry.resolve("Bearer not-a-real-token")


def test_expired_token_raises_expired_token(tmp_path):
    token = "expired-token"
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    _write_registry(
        tmp_path,
        {
            "tenant-a": {
                "organization_name": "Acme Robotics",
                "tier": "DEVELOPER_FREE",
                "token_sha256": _sha256(token),
                "expires_on": yesterday,
            }
        },
    )
    registry = tenancy.TenantRegistry(_settings(tmp_path))

    with pytest.raises(tenancy.ExpiredToken):
        registry.resolve(f"Bearer {token}")


# ---------------------------------------------------------------------------
# Bootstrap tokens (dev convenience)
# ---------------------------------------------------------------------------
def test_bootstrap_tokens_resolve_when_enabled_and_not_production(tmp_path):
    settings = _settings(tmp_path, LEGAFY_BOOTSTRAP_TOKENS_ENABLED=True)
    registry = tenancy.TenantRegistry(settings)

    ctx = registry.resolve("Bearer akridion_dev_99x")

    assert ctx.tier == LicenseTier.DEVELOPER_FREE


def test_no_registry_and_bootstrap_disabled_raises_runtime_error(tmp_path):
    settings = _settings(tmp_path, LEGAFY_BOOTSTRAP_TOKENS_ENABLED=False)
    registry = tenancy.TenantRegistry(settings)

    with pytest.raises(RuntimeError):
        registry.load()


def test_production_never_accepts_bootstrap_tokens_even_if_enabled(tmp_path):
    settings = _settings(
        tmp_path, LEGAFY_ENV="production", LEGAFY_BOOTSTRAP_TOKENS_ENABLED=True
    )
    registry = tenancy.TenantRegistry(settings)

    with pytest.raises(RuntimeError):
        registry.load()


# ---------------------------------------------------------------------------
# Scope enforcement via authenticate()
# ---------------------------------------------------------------------------
async def test_authenticate_raises_insufficient_scope_for_ungranted_scope(tmp_path, monkeypatch):
    token = "dev-scope-token"
    _write_registry(
        tmp_path,
        {
            "tenant-a": {
                "organization_name": "Acme Robotics",
                "tier": "DEVELOPER_FREE",  # only has the "audit" scope
                "token_sha256": _sha256(token),
                "expires_on": "2099-01-01",
            }
        },
    )
    registry = tenancy.TenantRegistry(_settings(tmp_path))
    limiter = tenancy.RateLimiter(backend="memory")
    monkeypatch.setattr(tenancy, "get_tenant_registry", lambda: registry)
    monkeypatch.setattr(tenancy, "get_rate_limiter", lambda: limiter)

    with pytest.raises(tenancy.InsufficientScope):
        await tenancy.authenticate(f"Bearer {token}", required_scope="generate")


async def test_authenticate_succeeds_and_returns_snapshot(tmp_path, monkeypatch):
    token = "dev-scope-token-2"
    _write_registry(
        tmp_path,
        {
            "tenant-a": {
                "organization_name": "Acme Robotics",
                "tier": "DEVELOPER_FREE",
                "token_sha256": _sha256(token),
                "expires_on": "2099-01-01",
            }
        },
    )
    registry = tenancy.TenantRegistry(_settings(tmp_path))
    limiter = tenancy.RateLimiter(backend="memory")
    monkeypatch.setattr(tenancy, "get_tenant_registry", lambda: registry)
    monkeypatch.setattr(tenancy, "get_rate_limiter", lambda: limiter)

    ctx, snapshot = await tenancy.authenticate(f"Bearer {token}", required_scope="audit")

    assert ctx.tier == LicenseTier.DEVELOPER_FREE
    assert snapshot.used_this_month == 1


# ---------------------------------------------------------------------------
# Rate limiter — sliding window
# ---------------------------------------------------------------------------
async def test_rate_limiter_allows_exactly_limit_then_raises_with_retry_after():
    limiter = tenancy.RateLimiter(backend="memory")
    limit = 3
    for _ in range(limit):
        snapshot = await limiter.consume("tk_test1", limit_per_minute=limit, monthly_quota=1000)
    assert snapshot.remaining_this_minute == 0

    with pytest.raises(tenancy.RateLimitExceeded) as exc_info:
        await limiter.consume("tk_test1", limit_per_minute=limit, monthly_quota=1000)

    assert exc_info.value.retry_after_seconds >= 1
    assert exc_info.value.retry_after_seconds <= 60


async def test_rate_limiter_is_isolated_per_token():
    limiter = tenancy.RateLimiter(backend="memory")
    limit = 2
    for _ in range(limit):
        await limiter.consume("tk_tenant_a", limit_per_minute=limit, monthly_quota=1000)
    # A different token must have its own, untouched window.
    snapshot = await limiter.consume("tk_tenant_b", limit_per_minute=limit, monthly_quota=1000)
    assert snapshot.remaining_this_minute == limit - 1


async def test_rate_limiter_quota_exhaustion_raises_quota_exceeded():
    limiter = tenancy.RateLimiter(backend="memory")
    quota = 2
    for _ in range(quota):
        await limiter.consume("tk_quota_test", limit_per_minute=1000, monthly_quota=quota)

    with pytest.raises(tenancy.QuotaExceeded) as exc_info:
        await limiter.consume("tk_quota_test", limit_per_minute=1000, monthly_quota=quota)

    assert exc_info.value.monthly_quota == quota
    assert exc_info.value.used == quota


async def test_rate_limiter_peek_does_not_mutate_state():
    limiter = tenancy.RateLimiter(backend="memory")
    before = await limiter.peek("tk_peek_test", limit_per_minute=5, monthly_quota=100)
    assert before.remaining_this_minute == 5
    assert before.used_this_month == 0

    await limiter.consume("tk_peek_test", limit_per_minute=5, monthly_quota=100)

    after_peek = await limiter.peek("tk_peek_test", limit_per_minute=5, monthly_quota=100)
    assert after_peek.remaining_this_minute == 4
    assert after_peek.used_this_month == 1

    # Peeking again must not have consumed anything further.
    still_after_peek = await limiter.peek("tk_peek_test", limit_per_minute=5, monthly_quota=100)
    assert still_after_peek.remaining_this_minute == 4
    assert still_after_peek.used_this_month == 1


async def test_rate_limiter_reset_clears_counters():
    limiter = tenancy.RateLimiter(backend="memory")
    await limiter.consume("tk_reset_test", limit_per_minute=1, monthly_quota=1)
    with pytest.raises(tenancy.RateLimitExceeded):
        await limiter.consume("tk_reset_test", limit_per_minute=1, monthly_quota=1)

    await limiter.reset("tk_reset_test")

    snapshot = await limiter.consume("tk_reset_test", limit_per_minute=1, monthly_quota=1)
    assert snapshot.used_this_month == 1
