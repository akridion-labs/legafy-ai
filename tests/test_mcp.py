"""The MCP surface must expose exactly the same tools and schemas as HTTP."""

from __future__ import annotations

import pytest

from app.tools import TOOLS, TOOLS_BY_NAME, manifest


def test_manifest_matches_tool_catalogue():
    names = {t["name"] for t in manifest()["tools"]}
    assert names == set(TOOLS_BY_NAME)


def test_every_tool_publishes_a_valid_json_schema():
    for spec in TOOLS:
        schema = spec.json_schema()
        assert schema["type"] == "object"
        assert isinstance(schema.get("properties", {}), dict)


def test_audit_tool_instructs_the_model_not_to_improvise():
    description = TOOLS_BY_NAME["execute_regional_compliance_audit"].description
    assert "MANDATORY" in description
    assert "RED" in description


def test_server_builds_and_advertises_instructions():
    pytest.importorskip("mcp")
    from app.mcp.server import SERVER_INSTRUCTIONS, build_server

    server = build_server()
    assert server.name == "legafy-ai"
    for rule in ("Telangana", "RED", "not legal advice"):
        assert rule in SERVER_INSTRUCTIONS


def test_remote_mode_requires_a_url(monkeypatch):
    pytest.importorskip("mcp")
    from app.mcp.server import build_server

    monkeypatch.setenv("LEGAFY_MCP_MODE", "remote")
    monkeypatch.delenv("LEGAFY_REMOTE_URL", raising=False)
    with pytest.raises(SystemExit):
        build_server()


def test_generate_tool_requires_the_generate_scope():
    assert TOOLS_BY_NAME["generate_legal_structure"].required_scope == "generate"


# --- Remote MCP transport (Streamable HTTP) -------------------------------
def test_url_token_is_read_from_either_path_shape(monkeypatch):
    pytest.importorskip("mcp")
    from app.mcp import http

    monkeypatch.setenv("LEGAFY_MCP_URL_TOKENS", "true")
    for path in ("/k/TOK", "/mcp/k/TOK"):
        assert http._authorization_from({"headers": [], "path": path}) == "Bearer TOK"


def test_url_tokens_are_off_by_default(monkeypatch):
    pytest.importorskip("mcp")
    from app.mcp import http

    monkeypatch.delenv("LEGAFY_MCP_URL_TOKENS", raising=False)
    assert http._authorization_from({"headers": [], "path": "/mcp/k/TOK"}) is None


def test_header_wins_over_url_token(monkeypatch):
    pytest.importorskip("mcp")
    from app.mcp import http

    monkeypatch.setenv("LEGAFY_MCP_URL_TOKENS", "true")
    scope = {"headers": [(b"authorization", b"Bearer HEADER")], "path": "/mcp/k/URL"}
    assert http._authorization_from(scope) == "Bearer HEADER"


async def test_mcp_dispatch_enforces_tool_scope():
    """A DEVELOPER_FREE token must not reach the paid tool through MCP."""
    pytest.importorskip("mcp")
    from datetime import date

    from app.mcp.server import CURRENT_TENANT, _dispatch_local
    from app.models.schemas import LicenseTier, TenantContext

    free = TenantContext(
        token_id="tk_free",
        organization_name="Free Tenant",
        tier=LicenseTier.DEVELOPER_FREE,
        expires_on=date(2099, 1, 1),
        rate_limit_per_minute=10,
        monthly_quota=500,
        scopes=["audit"],
    )
    token = CURRENT_TENANT.set(free)
    try:
        with pytest.raises(PermissionError):
            await _dispatch_local(
                "generate_legal_structure",
                {
                    "project_name": "Test Co",
                    "target_state": "Telangana",
                    "framework_type": "mutual_nda",
                    "dry_run": True,
                },
            )
    finally:
        CURRENT_TENANT.reset(token)
