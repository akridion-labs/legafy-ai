"""Tests for the jurisdiction registry — state isolation and anti-hallucination invariants."""

from __future__ import annotations

import json

import pytest

from app.compliance.registry import (
    JURISDICTION_DIR,
    JURISDICTION_REGISTRY,
    UnknownJurisdictionError,
)


def test_telangana_resolves_case_insensitively():
    assert JURISDICTION_REGISTRY.resolve("Telangana").code == "IN-TG"
    assert JURISDICTION_REGISTRY.resolve("telangana").code == "IN-TG"


def test_andhra_pradesh_resolves_and_instruments_disjoint_from_telangana():
    ap = JURISDICTION_REGISTRY.resolve("Andhra Pradesh")
    tg = JURISDICTION_REGISTRY.resolve("Telangana")
    assert ap.code == "IN-AP"

    ap_ids = {instrument["id"] for instrument in ap.instruments}
    tg_ids = {instrument["id"] for instrument in tg.instruments}
    assert ap_ids, "Andhra Pradesh should carry at least one instrument"
    assert tg_ids, "Telangana should carry at least one instrument"
    assert ap_ids.isdisjoint(tg_ids)


@pytest.mark.parametrize("bad_state", ["Goa", "Karnatka", ""])
def test_unmapped_state_raises(bad_state):
    with pytest.raises(UnknownJurisdictionError):
        JURISDICTION_REGISTRY.resolve(bad_state)


def test_none_state_raises():
    with pytest.raises(UnknownJurisdictionError):
        JURISDICTION_REGISTRY.resolve(None)  # type: ignore[arg-type]


def test_union_code_is_refused_as_a_state():
    # The union framework is a distinct tier and must never resolve as a state.
    with pytest.raises(UnknownJurisdictionError):
        JURISDICTION_REGISTRY.resolve("IN-CENTRAL")


def test_build_grounding_payload_keeps_union_and_state_blocks_separate():
    payload = JURISDICTION_REGISTRY.build_grounding_payload("Telangana", {"employs_persons"})
    assert payload["state"]["code"] == "IN-TG"
    assert payload["union"]["code"] == "IN-CENTRAL"

    state_ids = {instrument["id"] for instrument in payload["state"]["instruments"]}
    union_ids = {instrument["id"] for instrument in payload["union"]["instruments"]}
    assert state_ids.isdisjoint(union_ids)


def test_no_andhra_instrument_id_ever_appears_in_a_telangana_payload():
    tg_payload = JURISDICTION_REGISTRY.build_grounding_payload("Telangana", set())
    ap_payload = JURISDICTION_REGISTRY.build_grounding_payload("Andhra Pradesh", set())

    tg_ids = {instrument["id"] for instrument in tg_payload["state"]["instruments"]}
    ap_ids = {instrument["id"] for instrument in ap_payload["state"]["instruments"]}
    assert not (tg_ids & ap_ids)

    # Even the full, unfiltered instrument set for AP must never leak into TG's payload.
    ap_full_ids = {instrument["id"] for instrument in JURISDICTION_REGISTRY.resolve("Andhra Pradesh").instruments}
    assert ap_full_ids.isdisjoint(tg_ids)


def test_every_instrument_in_every_data_file_is_penalty_unverified():
    """The anti-hallucination invariant: no seed file may assert a penalty."""
    files = sorted(p for p in JURISDICTION_DIR.glob("*.json") if not p.name.startswith("_"))
    assert files, "expected at least one jurisdiction data file on disk"

    checked = 0
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for instrument in payload.get("instruments", []):
            checked += 1
            assert instrument.get("penalty_schedule") is None, (
                f"{path.name}:{instrument.get('id')} has a non-null penalty_schedule"
            )
            assert instrument.get("penalty_status") == "NOT_VERIFIED", (
                f"{path.name}:{instrument.get('id')} penalty_status is not NOT_VERIFIED"
            )
    assert checked > 0, "expected at least one instrument across all jurisdiction files"
