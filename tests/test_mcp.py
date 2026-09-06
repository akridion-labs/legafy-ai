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
