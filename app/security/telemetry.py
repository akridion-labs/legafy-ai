"""Anonymised, append-only, tamper-evident audit vault for liability defence.

Every regional-compliance-audit call must leave a durable record Akridion can
show a regulator, an insurer, or a court: what was asked, which isolated
jurisdiction paths applied, and what lane the system landed on — without ever
persisting the clear-text business idea a founder typed in. This module makes
that guarantee mechanical: the business concept never reaches disk except as
a keyed digest, records are chained by hash so a single edited byte anywhere
in the file is detectable, and every record is fsync'd before the call
returns.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.config import get_settings
from app.models.schemas import AuditVaultRecord, Lane, TenantContext

logger = logging.getLogger(__name__)

__all__ = [
    "GENESIS_HASH",
    "AuditVault",
    "digest_is_degraded",
    "get_audit_vault",
    "reset_audit_vault_cache",
]

GENESIS_HASH = "0" * 64

# Flipped true the first time any AuditVault falls back to unsalted SHA-256
# because LEGAFY_TELEMETRY_SALT was empty in a non-production environment.
# /healthz reads this to report a "degraded" posture.
_digest_degraded = False


def digest_is_degraded() -> bool:
    return _digest_degraded


class AuditVault:
    """Hash-chained JSON Lines vault. One instance owns one file."""

    def __init__(self, path: Path, salt: str, *, strict: bool = False) -> None:
        self._path = Path(path)
        self._salt = salt
        self._strict = strict
        self._lock = asyncio.Lock()
        self._seq = 0
        self._prev_hash = GENESIS_HASH
        self._record_count = 0

        if not salt:
            if strict:
                raise RuntimeError(
                    "LEGAFY_TELEMETRY_SALT is empty; refusing to start the audit vault in "
                    "strict (production) mode. Set LEGAFY_TELEMETRY_SALT to a long random "
                    "secret before deploying — concept digests must not be unsalted."
                )
            global _digest_degraded
            _digest_degraded = True
            logger.warning(
                "LEGAFY_TELEMETRY_SALT is empty; audit vault concept digests are falling back "
                "to unsalted SHA-256. This is not acceptable for production."
            )

        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._recover_tail()

    # -- hashing -------------------------------------------------------------
    def digest(self, value: str) -> str:
        """Keyed digest of a business-concept string. Never store its input."""
        if self._salt:
            return hmac.new(
                self._salt.encode("utf-8"), value.encode("utf-8"), hashlib.sha256
            ).hexdigest()
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _canonical_bytes(record_without_hash: dict) -> bytes:
        return json.dumps(
            record_without_hash, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    # -- recovery on init -----------------------------------------------------
    def _recover_tail(self) -> None:
        if not self._path.exists():
            return
        last_line: str | None = None
        count = 0
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                count += 1
                last_line = line
        self._record_count = count
        if last_line is not None:
            record = json.loads(last_line)
            self._seq = record["seq"]
            self._prev_hash = record["record_hash"]

    # -- writes ---------------------------------------------------------------
    async def append(
        self,
        *,
        event: str,
        tenant: TenantContext,
        business_concept: str,
        industry_vertical: str,
        jurisdiction_codes: list[str],
        activity_flags: list[str],
        traffic_light_lane: Lane,
        red_signal_ids: list[str] | None = None,
        provider_used: str | None = None,
        outcome: str = "OK",
    ) -> AuditVaultRecord:
        async with self._lock:
            seq = self._seq + 1
            payload: dict = {
                "seq": seq,
                "record_id": str(uuid.uuid4()),
                "recorded_at": datetime.now(UTC).isoformat(),
                "event": event,
                "token_id": tenant.token_id,
                "organization_name": tenant.organization_name,
                "tier": tenant.tier.value,
                "concept_digest": self.digest(business_concept),
                "concept_length": len(business_concept),
                "industry_vertical": industry_vertical,
                "jurisdiction_codes": list(jurisdiction_codes),
                "activity_flags": list(activity_flags),
                "traffic_light_lane": traffic_light_lane.value,
                "red_signal_ids": list(red_signal_ids or []),
                "provider_used": provider_used,
                "outcome": outcome,
                "prev_hash": self._prev_hash,
                "schema_version": 1,
            }
            record_hash = hashlib.sha256(self._canonical_bytes(payload)).hexdigest()
            payload["record_hash"] = record_hash

            is_new_file = not self._path.exists()
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, separators=(",", ":")))
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            if is_new_file:
                try:
                    os.chmod(self._path, 0o600)
                except OSError:  # pragma: no cover - platform dependent
                    pass

            self._seq = seq
            self._prev_hash = record_hash
            self._record_count += 1

            return AuditVaultRecord.model_validate(payload)

    # -- reads ------------------------------------------------------------
    def record_count(self) -> int:
        return self._record_count

    def read_records(self, limit: int | None = None) -> list[dict]:
        if not self._path.exists():
            return []
        records: list[dict] = []
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        if limit is not None:
            records = records[-limit:]
        return records

    def verify_chain(self) -> tuple[bool, str | None]:
        """Walk the file front-to-back, recomputing and re-linking every hash."""
        if not self._path.exists():
            return True, None
        prev_hash = GENESIS_HASH
        with self._path.open("r", encoding="utf-8") as fh:
            for idx, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    return False, f"record {idx}: invalid JSON ({exc})"
                stored_hash = record.get("record_hash")
                without_hash = {k: v for k, v in record.items() if k != "record_hash"}
                recomputed = hashlib.sha256(self._canonical_bytes(without_hash)).hexdigest()
                if recomputed != stored_hash:
                    return False, f"record {idx}: record_hash mismatch (content tampered)"
                if record.get("prev_hash") != prev_hash:
                    return False, f"record {idx}: prev_hash does not chain to the preceding record"
                prev_hash = stored_hash
        return True, None


_vault_singleton: AuditVault | None = None


def get_audit_vault() -> AuditVault:
    global _vault_singleton
    if _vault_singleton is None:
        settings = get_settings()
        _vault_singleton = AuditVault(
            settings.vault_path, settings.telemetry_salt, strict=settings.is_production
        )
    return _vault_singleton


def reset_audit_vault_cache() -> None:
    """Test hook — drops the memoised AuditVault instance."""
    global _vault_singleton
    _vault_singleton = None
