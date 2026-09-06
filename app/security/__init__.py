"""Tenancy, rate limiting and the tamper-evident audit vault.

This package exists because Legafy sits directly in front of jurisdiction data
and generated legal artefacts for paying tenants: every call must be
attributable to a licensed organisation, bounded by that organisation's tier,
and provably recorded for liability defence — without ever putting a clear-text
business concept, or a raw bearer token, at rest.
"""

from __future__ import annotations

from app.security.telemetry import (
    AuditVault,
    get_audit_vault,
    reset_audit_vault_cache,
)
from app.security.tenancy import (
    ExpiredToken,
    InsufficientScope,
    InvalidToken,
    QuotaExceeded,
    RateLimiter,
    RateLimitExceeded,
    TenancyError,
    TenantRegistry,
    authenticate,
    get_rate_limiter,
    get_tenant_registry,
    reset_tenancy_cache,
)

__all__ = [
    "reset_tenancy_cache",
    "AuditVault",
    "ExpiredToken",
    "InsufficientScope",
    "InvalidToken",
    "QuotaExceeded",
    "RateLimitExceeded",
    "RateLimiter",
    "TenancyError",
    "TenantRegistry",
    "authenticate",
    "get_audit_vault",
    "get_rate_limiter",
    "get_tenant_registry",
    "reset_audit_vault_cache",
]
