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


# -- mcp-builder audit: annotations, structured content, origin guard ---------


def test_only_the_drafting_tool_is_not_read_only():
    writers = {t.name for t in TOOLS if not t.read_only}
    assert writers == {"generate_legal_structure"}
    # A "destructive" legal tool would be a design error: nothing here deletes
    # or overwrites, and a client must never be told otherwise.
    assert not any(t.destructive for t in TOOLS)


def test_open_world_is_claimed_only_where_the_call_leaves_the_box():
    remote = {t.name for t in TOOLS if t.open_world}
    assert remote == {
        "generate_legal_structure",  # drafting provider may be remote
        "verify_registration",  # government API
        "verify_source_health",  # check_live fetches source URLs
    }


def test_annotations_reach_the_mcp_tool_list():
    pytest.importorskip("mcp")
    import asyncio

    from mcp.types import ListToolsRequest

    from app.mcp.server import build_server

    server = build_server()
    handler = server.request_handlers[ListToolsRequest]
    result = asyncio.run(handler(ListToolsRequest(method="tools/list"))).root
    by_name = {t.name: t for t in result.tools}
    assert by_name["execute_regional_compliance_audit"].annotations.readOnlyHint is True
    assert by_name["generate_legal_structure"].annotations.readOnlyHint is False
    assert by_name["execute_regional_compliance_audit"].title == "Regional Compliance Audit"


def test_tool_call_returns_structured_content_and_text():
    pytest.importorskip("mcp")
    import asyncio

    from mcp.types import CallToolRequest, CallToolRequestParams

    from app.mcp.server import build_server

    server = build_server()
    handler = server.request_handlers[CallToolRequest]
    request = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="list_supported_jurisdictions", arguments={}),
    )
    result = asyncio.run(handler(request)).root
    assert result.content and result.content[0].type == "text"
    # The whole point: a client can read the verdict without parsing prose.
    assert isinstance(result.structuredContent, dict)
    assert "jurisdictions" in result.structuredContent


def test_browser_origins_are_refused_before_authentication(monkeypatch):
    """A page that can reach the tunnel or the tailnet must not drive the tools."""
    from app.mcp.http import _origin_refused, allowed_origins

    monkeypatch.delenv("LEGAFY_MCP_ALLOWED_ORIGINS", raising=False)
    assert allowed_origins() == set()
    assert _origin_refused({"headers": []}) is None  # no Origin: a real MCP client
    assert _origin_refused({"headers": [(b"origin", b"https://evil.example")]}) == (
        "https://evil.example"
    )

    monkeypatch.setenv("LEGAFY_MCP_ALLOWED_ORIGINS", "https://console.akridion.com/")
    assert _origin_refused({"headers": [(b"origin", b"https://console.akridion.com")]}) is None


# -- automatic invocation: the connector must fire without being asked -------


def test_the_audit_description_tells_the_model_to_call_it_unprompted():
    """The trigger clause is the whole mechanism on the bare-connector path.

    A user who adds Legafy as a connector (rather than installing the plugin)
    gets no skill — only this description and the server instructions. If the
    trigger language is trimmed, the model waits to be asked, and a founder who
    types "here's my idea" gets an ungrounded answer.
    """
    description = TOOLS_BY_NAME["execute_regional_compliance_audit"].description
    lowered = description.lower()
    for phrase in ("unprompted", "without being asked", "here's my idea", "call it anyway"):
        assert phrase in lowered, f"lost the trigger phrase: {phrase!r}"
    # And it must say that missing inputs are not an excuse to skip the call.
    assert "not a reason to skip" in description


def test_server_instructions_say_the_user_need_not_ask():
    from app.mcp.server import SERVER_INSTRUCTIONS

    assert "does not need to ask for it" in SERVER_INSTRUCTIONS
    assert "Never guess a state" in SERVER_INSTRUCTIONS


def test_a_missing_state_is_a_question_not_a_protocol_error():
    """The single biggest hole in automatic grounding, closed.

    When `state_location` was a required property the SDK rejected the call
    against inputSchema before any handler ran. The model got
    "Input validation error: 'state_location' is a required property" and
    nothing else — no instruction, no supported states, no hint that it must
    not improvise. The realistic next move is to guess a state or answer from
    memory. Both are the failure this engine exists to prevent.
    """
    pytest.importorskip("mcp")
    import asyncio

    from mcp.types import CallToolRequest, CallToolRequestParams

    from app.mcp.server import build_server

    server = build_server()
    handler = server.request_handlers[CallToolRequest]
    result = asyncio.run(
        handler(
            CallToolRequest(
                method="tools/call",
                params=CallToolRequestParams(
                    name="execute_regional_compliance_audit",
                    arguments={
                        "business_concept": "A marketplace for tutors holding fees in escrow.",
                        "industry_vertical": "Marketplace",
                    },
                ),
            )
        )
    ).root

    assert result.isError is False, "a missing state must not surface as a broken tool"
    payload = result.structuredContent
    assert payload["status"] == "JURISDICTION_REQUIRED"
    assert payload["supported_states"], "the model needs the list to ask a closed question"
    assert "ASK THE USER" in payload["instruction"]
    assert "do NOT answer the legal question from your own knowledge" in payload["instruction"]
    # The union catalogue is not a state a user can pick.
    assert "IN-CENTRAL" not in {s["code"] for s in payload["supported_states"]}


def test_wording_is_mapped_back_to_the_flags_the_matrix_filters_on():
    from app.compliance.traffic_light import suggest_activity_flags

    suggested = suggest_activity_flags(
        "A marketplace for local tutors that holds student payments in escrow.",
        "Marketplace",
    )
    by_flag = {s["flag"]: s["matched_on"] for s in suggested}
    assert "holds_customer_funds" in by_flag
    assert "escrow" in by_flag["holds_customer_funds"]

    # A flag the caller already declared is not suggested back at them.
    again = suggest_activity_flags(
        "A marketplace for local tutors that holds student payments in escrow.",
        "Marketplace",
        declared={"holds_customer_funds"},
    )
    assert "holds_customer_funds" not in {s["flag"] for s in again}


def test_suggestions_never_narrow_the_assessment():
    """Suggestion only. An inferred flag must not filter a duty out of sight.

    Getting a suggestion wrong should cost noise, never a missed obligation —
    so the undeclared call must return at least as many duties as the declared
    one, not fewer.
    """
    import asyncio

    from app.mcp.server import LOCAL_TENANT

    concept = "A marketplace for local tutors that holds student payments in escrow."

    def audit(flags):
        return asyncio.run(
            TOOLS_BY_NAME["execute_regional_compliance_audit"].handler(
                {
                    "business_concept": concept,
                    "industry_vertical": "Marketplace",
                    "state_location": "Kerala",
                    "activity_flags": flags,
                },
                request_id="t",
                tenant=LOCAL_TENANT,
            )
        )

    undeclared = audit([])
    declared = audit(["holds_customer_funds"])
    assert len(undeclared["obligations"]) >= len(declared["obligations"])
    assert undeclared["lane"] == "RED"  # inferred from the wording, with no flag declared
    assert "suggested_activity_flags" in undeclared
