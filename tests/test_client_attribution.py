"""Which AI client called — recorded as evidence, never trusted as identity.

The invariant under test is narrow and matters: client identity is self-reported
in the MCP handshake, so it must reach the audit vault and must reach nothing
else. These tests pin the mapping, the isolation between callers, and the fact
that adding the field did not break a chain written before it existed.
"""

from __future__ import annotations

import json

import pytest

from app.models.schemas import Lane, LicenseTier, TenantContext
from app.security.clients import (
    CURRENT_CLIENT,
    client_context,
    get_client,
    normalise_client,
    set_client,
)
from app.security.telemetry import AuditVault


@pytest.fixture(autouse=True)
def _clear_client():
    """No test may leak a client identity into the next one."""
    CURRENT_CLIENT.set(None)
    yield
    CURRENT_CLIENT.set(None)


def _tenant() -> TenantContext:
    return TenantContext(
        token_id="tk_client_test",
        organization_name="Acme Robotics Pvt Ltd",
        tier=LicenseTier.DEVELOPER_FREE,
        expires_on="2099-01-01",
        rate_limit_per_minute=10,
        monthly_quota=500,
        scopes=["audit"],
    )


async def _append(vault: AuditVault, **kw):
    return await vault.append(
        event="regional_compliance_audit",
        tenant=_tenant(),
        business_concept="a tutoring marketplace in Hyderabad",
        industry_vertical="edtech",
        jurisdiction_codes=["IN-TG"],
        activity_flags=["employs_persons"],
        traffic_light_lane=kw.pop("lane", Lane.GREEN),
        **kw,
    )


# ---------------------------------------------------------------------------
# The family map
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Claude Code", "claude-code"),
        ("claude-code", "claude-code"),
        ("claude-ai", "claude"),
        ("Codex CLI", "codex"),
        ("ChatGPT", "chatgpt"),
        ("Visual Studio Code - Copilot", "copilot"),
        ("cursor-vscode", "cursor"),
        ("mcp-inspector", "mcp-inspector"),
        ("  CODEX  ", "codex"),
    ],
)
def test_known_clients_map_to_a_family(raw, expected):
    assert normalise_client(raw) == expected


def test_claude_code_is_matched_before_plain_claude():
    """Ordering bug guard: 'claude-code' contains 'claude'.

    If the generic row ever moves above the specific one, every Claude Code
    call silently merges into the Claude bucket and the breakdown quietly
    stops distinguishing two products.
    """
    assert normalise_client("Claude Code") != normalise_client("claude-ai")


def test_no_generic_needle_shadows_a_more_specific_one():
    """The structural guard behind every ordering bug in this table.

    Cursor reports itself as "cursor-vscode" and Claude Code as "claude-code":
    both contain another row's needle. Whenever one needle is a substring of
    another, the longer one MUST be checked first, or the specific client is
    silently absorbed into the generic bucket and the usage report is wrong in
    a way that looks fine.

    This catches the next such row at the moment it is added, which a
    case-by-case assertion would not.

    Its limit, stated so nobody over-trusts it: it compares needles to each
    other. It cannot see that Cursor *reports* "cursor-vscode" while neither
    needle contains the other — that case is pinned by the explicit
    ("cursor-vscode", "cursor") row in the mapping test above. Both are needed.
    """
    from app.security.clients import CLIENT_FAMILIES

    needles = [needle for needle, _ in CLIENT_FAMILIES]
    for i, earlier in enumerate(needles):
        for later in needles[i + 1 :]:
            # If the earlier needle is contained in the later one, every name
            # the later row was meant to catch also contains the earlier one —
            # so the earlier row always wins and the later is dead code.
            assert earlier not in later, (
                f"{earlier!r} is checked before {later!r} and is contained in it, "
                f"so nothing can ever reach {later!r}. "
                f"Move {later!r} above {earlier!r} in CLIENT_FAMILIES."
            )


@pytest.mark.parametrize("raw", [None, "", "   ", "some-client-nobody-has-seen"])
def test_unrecognised_clients_are_unknown_not_dropped(raw):
    assert normalise_client(raw) == "unknown"


def test_unknown_client_keeps_its_raw_name():
    """'unknown' is a prompt to extend the table, which needs the real name."""
    set_client("totally-new-agent", "9.9")
    recorded = get_client()
    assert recorded["client_family"] == "unknown"
    assert recorded["client_name"] == "totally-new-agent"


def test_client_name_is_bounded():
    """The vault is append-only; a client must not be able to bloat it."""
    set_client("x" * 5000, "v" * 5000)
    recorded = get_client()
    assert len(recorded["client_name"]) <= 120
    assert len(recorded["client_version"]) <= 60


def test_no_client_reads_back_as_all_none():
    assert get_client() == {
        "client_name": None,
        "client_version": None,
        "client_family": None,
    }


# ---------------------------------------------------------------------------
# Isolation between callers
# ---------------------------------------------------------------------------
def test_client_context_restores_the_previous_caller():
    set_client("Claude Code", "1.0")
    with client_context("Codex CLI", "2.0"):
        assert get_client()["client_family"] == "codex"
    assert get_client()["client_family"] == "claude-code"


def test_client_context_with_no_client_does_not_inherit_the_previous_one():
    """One process serves many callers over HTTP.

    An unattributed request must read as unattributed, never as whoever called
    immediately before it — that would put one customer's usage on another.
    """
    set_client("Claude Code", "1.0")
    with client_context(None):
        assert get_client()["client_name"] is None
    assert get_client()["client_family"] == "claude-code"


# ---------------------------------------------------------------------------
# What reaches the vault
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_client_identity_is_written_to_the_vault(tmp_path):
    vault = AuditVault(tmp_path / "vault.jsonl", salt="s", strict=False)
    set_client("Codex CLI", "0.44.0")
    record = await _append(vault)
    assert record.client_name == "Codex CLI"
    assert record.client_version == "0.44.0"
    assert record.client_family == "codex"
    assert record.schema_version == 2


@pytest.mark.asyncio
async def test_unattributed_calls_still_record(tmp_path):
    """Telemetry is best-effort; a missing client never blocks a legal answer."""
    vault = AuditVault(tmp_path / "vault.jsonl", salt="s", strict=False)
    record = await _append(vault)
    assert record.client_name is None
    assert record.client_family is None


@pytest.mark.asyncio
async def test_the_concept_is_still_never_stored_in_clear(tmp_path):
    """Adding a field must not have widened what the vault persists."""
    vault = AuditVault(tmp_path / "vault.jsonl", salt="s", strict=False)
    set_client("Codex CLI", "0.44.0")
    await _append(vault)
    raw = (tmp_path / "vault.jsonl").read_text()
    assert "tutoring marketplace" not in raw


# ---------------------------------------------------------------------------
# The chain survives the schema change
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_v1_records_still_verify_alongside_v2(tmp_path):
    """History must not need rewriting to add a field.

    Records written before client capture carry no client_* keys. The chain
    hashes whatever keys a record actually has, so a mixed file must verify —
    otherwise shipping this would have invalidated every existing vault.
    """
    path = tmp_path / "vault.jsonl"
    vault = AuditVault(path, salt="s", strict=False)
    set_client("Claude Code", "1.0")
    await _append(vault)

    # Hand-build the next record the way schema_version 1 wrote it: no
    # client_* keys at all, chained onto the real previous hash.
    import hashlib

    prev = json.loads(path.read_text().strip().splitlines()[-1])["record_hash"]
    legacy = {
        "seq": 2,
        "record_id": "legacy-0001",
        "recorded_at": "2026-01-01T00:00:00+00:00",
        "event": "regional_compliance_audit",
        "token_id": "tk_old",
        "organization_name": "Old Co",
        "tier": "DEVELOPER_FREE",
        "concept_digest": "0" * 64,
        "concept_length": 10,
        "industry_vertical": "edtech",
        "jurisdiction_codes": ["IN-TG"],
        "activity_flags": [],
        "traffic_light_lane": "GREEN",
        "red_signal_ids": [],
        "provider_used": None,
        "outcome": "OK",
        "prev_hash": prev,
        "schema_version": 1,
    }
    legacy["record_hash"] = hashlib.sha256(
        json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(legacy, separators=(",", ":")) + "\n")

    ok, reason = AuditVault(path, salt="s", strict=False).verify_chain()
    assert ok, reason


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_breakdown_counts_and_surfaces_unmapped_names(tmp_path):
    vault = AuditVault(tmp_path / "vault.jsonl", salt="s", strict=False)
    set_client("Codex CLI", "0.44.0")
    await _append(vault)
    await _append(vault, lane=Lane.RED)
    set_client("Claude Code", "1.0")
    await _append(vault)
    set_client("some-agent-we-have-never-seen", "0.1")
    await _append(vault)
    CURRENT_CLIENT.set(None)
    await _append(vault)

    report = vault.client_breakdown()
    assert report["by_family"]["codex"] == 2
    assert report["by_family"]["claude-code"] == 1
    assert report["identified"] == 4
    assert report["unidentified"] == 1
    # The only sanctioned route to extending CLIENT_FAMILIES.
    assert report["unmapped_names"] == {"some-agent-we-have-never-seen": 1}
    assert report["lanes_by_family"]["codex"] == {"GREEN": 1, "RED": 1}
