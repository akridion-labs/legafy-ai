"""Legafy AI MCP server (stdio).

Run it two ways:

  local  — the full engine runs in this process. Everything stays on the
           machine; no network egress except whatever provider you configure.
             LEGAFY_MCP_MODE=local python -m app.mcp.server

  remote — a thin bridge that forwards each tool call to a hosted Legafy
           instance (your Cloudflare-tunnelled server). This is the Tier-1
           open-source distribution: the client is free, the grounding engine
           behind it is yours.
             LEGAFY_MCP_MODE=remote LEGAFY_REMOTE_URL=https://legal-mcp.akridion.com \
             LEGAFY_API_TOKEN=... python -m app.mcp.server

Both modes expose the same tools from app/tools.py, so a client cannot tell
them apart — and neither can bypass the traffic-light halt.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from contextvars import ContextVar
from datetime import date

from app.models.schemas import LicenseTier, TenantContext
from app.tools import TOOLS, TOOLS_BY_NAME

log = logging.getLogger("legafy.mcp")

SERVER_INSTRUCTIONS = """Legafy AI — pre-counsel compliance scaffolding for Indian jurisdictions.

HOW TO USE THIS SERVER:
1. Call `execute_regional_compliance_audit` BEFORE answering any question about a business
   concept's legal exposure. Do not answer from your own knowledge of Indian law.
2. Treat the `union` and `state` blocks in the response as separate. Never merge them, and never
   apply one state's rule to another — Telangana and Andhra Pradesh are distinct code paths.
3. The response contains no section numbers, penalties or thresholds by design. Do not supply them
   yourself. If you cannot cite it from the tool output, say it is unverified.
4. If `traffic_light.lane` is RED, stop. Tell the user to retain counsel and do not draft the
   document. `generate_legal_structure` will refuse anyway.
5. Everything this server returns is structural scaffolding, not legal advice.
"""

# A local stdio session is one operator on one machine; tiering is enforced
# server-side in remote mode. ponytail: no local token store to manage.
LOCAL_TENANT = TenantContext(
    token_id="tk_localmcp",
    organization_name="Local MCP Session",
    tier=LicenseTier.DEVELOPER_FREE,
    expires_on=date(2099, 12, 31),
    rate_limit_per_minute=60,
    monthly_quota=100_000,
    scopes=["audit", "generate"],
)


# Set by the Streamable HTTP transport once it has verified the bearer token, so
# a remote MCP caller is dispatched as its real tenant. Unset over stdio, where
# the session is one operator on one machine.
CURRENT_TENANT: ContextVar[TenantContext | None] = ContextVar("legafy_mcp_tenant", default=None)


async def _dispatch_local(name: str, payload: dict) -> dict:
    spec = TOOLS_BY_NAME[name]
    tenant = CURRENT_TENANT.get() or LOCAL_TENANT
    # Scope is enforced here, not only at the transport: the transport
    # authenticates the connection, but every tool has its own scope and a
    # DEVELOPER_FREE token must not reach the paid generate tool through MCP
    # just because it was allowed to open a session.
    if not tenant.has_scope(spec.required_scope):
        raise PermissionError(
            f"Token for {tenant.organization_name!r} ({tenant.tier.value}) lacks the "
            f"{spec.required_scope!r} scope required by {name!r}."
        )
    return await spec.handler(
        payload, request_id=f"mcp_{uuid.uuid4().hex[:12]}", tenant=tenant
    )


async def _dispatch_remote(name: str, payload: dict) -> dict:
    import httpx

    base = os.environ["LEGAFY_REMOTE_URL"].rstrip("/")
    token = os.environ.get("LEGAFY_API_TOKEN", "")
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
        resp = await client.post(
            f"{base}/tools/{name}/invoke",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Legafy server returned HTTP {resp.status_code}: {resp.text[:400]}")
    return resp.json().get("result", {})


def build_server():
    try:
        from mcp.server import Server
        from mcp.types import TextContent, Tool
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "The MCP SDK is not installed. Run: pip install 'mcp>=1.2.0'"
        ) from exc

    mode = os.environ.get("LEGAFY_MCP_MODE", "local").lower()
    if mode == "remote" and not os.environ.get("LEGAFY_REMOTE_URL"):
        raise SystemExit("LEGAFY_MCP_MODE=remote requires LEGAFY_REMOTE_URL")
    dispatch = _dispatch_remote if mode == "remote" else _dispatch_local
    log.info("Legafy MCP server starting in %s mode", mode)

    server = Server("legafy-ai", instructions=SERVER_INSTRUCTIONS)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=t.name, description=t.description, inputSchema=t.json_schema())
            for t in TOOLS
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name not in TOOLS_BY_NAME:
            raise ValueError(f"Unknown tool {name!r}")
        try:
            result = await dispatch(name, arguments or {})
        except Exception as exc:
            # Fail closed and say so — never let the client fill the gap itself.
            log.exception("tool %s failed", name)
            result = {
                "success": False,
                "error": str(exc),
                "instruction": (
                    "The grounding call failed. Do not answer this question from your own "
                    "knowledge of Indian law; tell the user the compliance service is "
                    "unavailable and that counsel should be consulted."
                ),
            }
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    return server


async def amain() -> None:
    from mcp.server.stdio import stdio_server

    server = build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    asyncio.run(amain())


if __name__ == "__main__":
    main()
