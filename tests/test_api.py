"""HTTP + tool-manifest tests against the real app, offline provider only."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings, reset_settings_cache
from app.security.telemetry import reset_audit_vault_cache
from app.security.tenancy import reset_tenancy_cache

DEV = {"Authorization": "Bearer akridion_dev_99x"}
ENT = {"Authorization": "Bearer AKRIDION_DEV_9821"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LEGAFY_ENV", "development")
    monkeypatch.setenv("LEGAFY_BOOTSTRAP_TOKENS_ENABLED", "true")
    monkeypatch.setenv("LEGAFY_PROVIDER_CHAIN", "offline")
    monkeypatch.setenv("LEGAFY_TELEMETRY_SALT", "test-salt")
    monkeypatch.setenv("LEGAFY_GENERATED_DIR", str(tmp_path))
    monkeypatch.setenv("LEGAFY_AUDIT_VAULT_PATH", str(tmp_path / "vault.json"))
    monkeypatch.setenv("LEGAFY_LICENSE_REGISTRY_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setenv("LEGAFY_MIN_DOCUMENT_WORDS", "800")
    monkeypatch.setenv("LEGAFY_CHUNK_MAX_TOKENS", "700")
    reset_settings_cache()
    reset_audit_vault_cache()
    reset_tenancy_cache()
    from app.providers.router import reset_router_cache

    reset_router_cache()
    get_settings()
    with TestClient(__import__("app.main", fromlist=["app"]).app) as c:
        yield c


def test_health_and_root(client):
    assert client.get("/healthz").json()["product"] == "Legafy AI"
    assert "tool_manifest" in client.get("/").json()["endpoints"]


def test_tool_manifest_is_json_schema(client):
    manifest = client.get("/tools").json()
    names = {t["name"] for t in manifest["tools"]}
    assert "execute_regional_compliance_audit" in names
    schema = next(t for t in manifest["tools"] if t["name"] == "execute_regional_compliance_audit")
    assert schema["input_schema"]["type"] == "object"
    assert "business_concept" in schema["input_schema"]["properties"]


def test_auth_is_required(client):
    assert client.post("/api/v1/audit", json={}).status_code == 401


def test_audit_returns_isolated_state_path(client):
    resp = client.post(
        "/api/v1/audit",
        headers=DEV,
        json={
            "business_concept": "A scheduling tool for dental clinics with staff rostering.",
            "industry_vertical": "B2B SaaS",
            "state_location": "Telangana",
            "activity_flags": ["employs_persons", "has_workplace_in_state"],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # Compact is the default: one obligation ledger tagged by jurisdiction,
    # proofs deduped by instrument.
    assert body["jurisdictions"] == ["IN-TG"]
    assert {o["jurisdiction"] for o in body["obligations"]} == {"IN-TG", "IN-CENTRAL"}
    state_refs = {o["ref"] for o in body["obligations"] if o["jurisdiction"] == "IN-TG"}
    union_refs = {o["ref"] for o in body["obligations"] if o["jurisdiction"] == "IN-CENTRAL"}
    assert not (state_refs & union_refs), "union instrument leaked into the state block"
    # Every duty must resolve to a playbook that says how to close it and what
    # follows if it is not closed.
    assert all(o["playbook"] in body["playbooks"] for o in body["obligations"])


def test_full_detail_returns_the_segregated_blocks(client):
    resp = client.post(
        "/api/v1/audit",
        headers=DEV,
        json={
            "business_concept": "A scheduling tool for dental clinics with staff rostering.",
            "industry_vertical": "B2B SaaS",
            "state_location": "Telangana",
            "activity_flags": ["employs_persons", "has_workplace_in_state"],
            "detail": "full",
        },
    )
    body = resp.json()
    assert [s["code"] for s in body["states"]] == ["IN-TG"]
    assert body["union"]["code"] == "IN-CENTRAL"
    state_ids = {i["id"] for i in body["states"][0]["instruments"]}
    union_ids = {i["id"] for i in body["union"]["instruments"]}
    assert not (state_ids & union_ids)


def test_unmapped_state_is_refused_not_approximated(client):
    resp = client.post(
        "/api/v1/audit",
        headers=DEV,
        json={
            "business_concept": "A marketplace for local tailors and boutiques.",
            "industry_vertical": "marketplace",
            "state_location": "Atlantis",
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "unknown_jurisdiction"


def test_escrow_concept_trips_red_lane(client):
    resp = client.post(
        "/api/v1/audit",
        headers=DEV,
        json={
            "business_concept": "We hold buyer funds in an escrow account until delivery is confirmed.",
            "industry_vertical": "fintech",
            "state_location": "Maharashtra",
            "activity_flags": ["operates_escrow", "holds_customer_funds"],
        },
    )
    body = resp.json()
    assert body["lane"] == "RED"
    assert body["automation_permitted"] is False
    assert body["halt"]


def test_scope_is_enforced_on_generation(client):
    """DEVELOPER_FREE has audit scope only."""
    resp = client.post(
        "/api/v1/legal/generate-structure",
        headers=DEV,
        json={
            "project_name": "Test",
            "target_state": "Telangana",
            "framework_type": "mutual_nda",
            "dry_run": True,
        },
    )
    assert resp.status_code == 403


def test_dry_run_returns_a_chunk_plan(client):
    resp = client.post(
        "/api/v1/legal/generate-structure",
        headers=ENT,
        json={
            "project_name": "Akridion Test",
            "target_state": "Telangana",
            "framework_type": "mutual_nda",
            "business_concept": "A simple mutual confidentiality arrangement for vendor talks.",
            "dry_run": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "OUTLINE_COMPILED"
    assert len(body["chunk_plan"]) >= 5


def test_red_lane_halts_generation(client):
    resp = client.post(
        "/api/v1/legal/generate-structure",
        headers=ENT,
        json={
            "project_name": "Payments Co",
            "target_state": "Telangana",
            "framework_type": "founders_agreement",
            "business_concept": "We route customer money through an escrow and settle to sellers.",
            "activity_flags": ["operates_escrow"],
        },
    )
    assert resp.json()["status"] == "HALTED_RED_LANE"
    assert resp.json()["markdown_path"] is None


def test_generation_writes_a_document(client, tmp_path):
    resp = client.post(
        "/api/v1/legal/generate-structure",
        headers=ENT,
        json={
            "project_name": "Akridion Labs",
            "target_state": "Telangana",
            "framework_type": "mutual_nda",
            "business_concept": "A mutual confidentiality arrangement covering vendor discussions.",
            "output_formats": ["markdown"],
            "min_words": 800,
        },
    )
    body = resp.json()
    assert body["status"] == "DOCUMENT_ASSEMBLED"
    assert body["total_words"] >= 800
    assert body["citation_guard"]["missing_clauses"] == []
    assert (tmp_path / body["markdown_path"].split("/")[-1]).exists()


def test_audit_vault_chain_holds_after_traffic(client):
    client.post(
        "/api/v1/audit",
        headers=DEV,
        json={
            "business_concept": "A quiet little bookshop inventory tracker for one shop.",
            "industry_vertical": "retail",
            "state_location": "Delhi",
        },
    )
    body = client.get("/api/v1/audit-vault/verify", headers=DEV).json()
    assert body["intact"] is True
    assert body["records"] >= 1
