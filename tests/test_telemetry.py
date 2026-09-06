"""Tests for app.security.telemetry: the hash-chained audit vault.

Deterministic and offline. Every vault is built against a tmp_path file —
never the repo's real generated/ directory.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from app.models.schemas import LicenseTier, TenantContext
from app.security.telemetry import GENESIS_HASH, AuditVault

CONCEPT = "A marketplace that lets nurses swap unwanted hospital shifts for cash, super secret idea"


def _tenant() -> TenantContext:
    return TenantContext(
        token_id="tk_deadbeef",
        organization_name="Acme Robotics Pvt Ltd",
        tier=LicenseTier.DEVELOPER_FREE,
        expires_on="2099-01-01",
        rate_limit_per_minute=10,
        monthly_quota=500,
        scopes=["audit"],
    )


async def _append(vault: AuditVault, tenant: TenantContext, *, concept: str = CONCEPT, event="audit"):
    from app.models.schemas import Lane

    return await vault.append(
        event=event,
        tenant=tenant,
        business_concept=concept,
        industry_vertical="healthtech",
        jurisdiction_codes=["IN-TG"],
        activity_flags=["employs_persons"],
        traffic_light_lane=Lane.GREEN,
    )


# ---------------------------------------------------------------------------
# Digest behaviour
# ---------------------------------------------------------------------------
def test_digest_is_keyed_hmac_when_salt_present(tmp_path):
    vault = AuditVault(tmp_path / "vault.jsonl", salt="a-real-salt", strict=False)
    import hmac

    expected = hmac.new(b"a-real-salt", CONCEPT.encode("utf-8"), hashlib.sha256).hexdigest()
    assert vault.digest(CONCEPT) == expected


def test_empty_salt_in_strict_mode_raises_runtime_error(tmp_path):
    with pytest.raises(RuntimeError):
        AuditVault(tmp_path / "vault.jsonl", salt="", strict=True)


def test_empty_salt_in_non_strict_mode_falls_back_to_plain_sha256(tmp_path):
    vault = AuditVault(tmp_path / "vault.jsonl", salt="", strict=False)
    assert vault.digest(CONCEPT) == hashlib.sha256(CONCEPT.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Append + chain integrity
# ---------------------------------------------------------------------------
async def test_appending_n_records_yields_n_lines_and_valid_chain(tmp_path):
    vault_path = tmp_path / "vault.jsonl"
    vault = AuditVault(vault_path, salt="test-salt", strict=False)
    tenant = _tenant()

    for i in range(5):
        await _append(vault, tenant, concept=f"{CONCEPT} variant {i}")

    lines = [ln for ln in vault_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 5
    assert vault.record_count() == 5

    ok, reason = vault.verify_chain()
    assert ok is True
    assert reason is None


async def test_first_record_chains_to_genesis_hash(tmp_path):
    vault = AuditVault(tmp_path / "vault.jsonl", salt="test-salt", strict=False)
    record = await _append(vault, _tenant())
    assert record.prev_hash == GENESIS_HASH


async def test_clear_text_concept_never_appears_in_vault_bytes(tmp_path):
    vault_path = tmp_path / "vault.jsonl"
    vault = AuditVault(vault_path, salt="test-salt", strict=False)
    tenant = _tenant()

    secret_concept = "Zynthorquil neural payroll escrow for underwater basket weavers"
    for i in range(3):
        await _append(vault, tenant, concept=f"{secret_concept} #{i}")

    raw_bytes = vault_path.read_bytes()
    assert secret_concept.encode("utf-8") not in raw_bytes
    assert b"Zynthorquil" not in raw_bytes


async def test_record_count_and_read_records_survive_reopen(tmp_path):
    vault_path = tmp_path / "vault.jsonl"
    tenant = _tenant()

    vault1 = AuditVault(vault_path, salt="test-salt", strict=False)
    await _append(vault1, tenant)
    await _append(vault1, tenant)

    # Recreate the vault (as would happen on process restart) and confirm the
    # sequence / prev_hash chain is correctly recovered from the tail.
    vault2 = AuditVault(vault_path, salt="test-salt", strict=False)
    assert vault2.record_count() == 2
    third = await _append(vault2, tenant)
    assert third.seq == 3

    records = vault2.read_records()
    assert len(records) == 3
    assert [r["seq"] for r in records] == [1, 2, 3]

    ok, reason = vault2.verify_chain()
    assert ok is True, reason


def test_read_records_respects_limit(tmp_path):
    vault_path = tmp_path / "vault.jsonl"
    vault_path.write_text("", encoding="utf-8")
    vault = AuditVault(vault_path, salt="test-salt", strict=False)
    assert vault.read_records() == []
    assert vault.read_records(limit=5) == []


# ---------------------------------------------------------------------------
# Tamper evidence
# ---------------------------------------------------------------------------
async def test_mutating_a_middle_record_breaks_verify_chain(tmp_path):
    vault_path = tmp_path / "vault.jsonl"
    vault = AuditVault(vault_path, salt="test-salt", strict=False)
    tenant = _tenant()

    for i in range(5):
        await _append(vault, tenant, concept=f"{CONCEPT} variant {i}")

    ok, _ = vault.verify_chain()
    assert ok is True

    lines = vault_path.read_text(encoding="utf-8").splitlines()
    middle_index = 2  # third of five records
    record = json.loads(lines[middle_index])
    # Flip a field's value without touching record_hash, simulating a tamper
    # that doesn't bother recomputing the chain.
    record["outcome"] = "TAMPERED"
    lines[middle_index] = json.dumps(record, separators=(",", ":"))
    vault_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # A fresh vault instance re-reads from disk rather than trusting memory.
    reopened = AuditVault(vault_path, salt="test-salt", strict=False)
    ok, reason = reopened.verify_chain()
    assert ok is False
    assert reason is not None
    assert f"record {middle_index + 1}" in reason


async def test_flipping_a_single_byte_breaks_verify_chain(tmp_path):
    vault_path = tmp_path / "vault.jsonl"
    vault = AuditVault(vault_path, salt="test-salt", strict=False)
    tenant = _tenant()

    for i in range(4):
        await _append(vault, tenant, concept=f"{CONCEPT} variant {i}")

    raw = bytearray(vault_path.read_bytes())
    # Flip one byte inside the second line, well clear of line boundaries.
    lines = vault_path.read_text(encoding="utf-8").splitlines()
    target_line_start = len(("\n".join(lines[:1])) + "\n")
    flip_at = target_line_start + 10
    raw[flip_at] ^= 0x01
    vault_path.write_bytes(bytes(raw))

    reopened = AuditVault(vault_path, salt="test-salt", strict=False)
    ok, reason = reopened.verify_chain()
    assert ok is False
    assert reason is not None
