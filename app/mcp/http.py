"""Remote MCP over Streamable HTTP.

This is what lets a Claude subscription (claude.ai, Desktop, Cowork, Code) and
ChatGPT developer mode add Legafy as a custom connector: both connect only to
*remote* servers, and Claude's documented transport is Streamable HTTP at a
single POST endpoint. The stdio server in ``server.py`` covers local hosts;
this covers everything reached over the tunnel.

Auth. The MCP transport itself does not authenticate — the bearer token is
verified here, before the handler runs, and an unauthenticated request gets a
401 with a ``WWW-Authenticate`` challenge as the spec requires. Two ways to
present the token:

  * ``Authorization: Bearer <token>`` — correct, used by Claude Code
    (``--header``) and anything that can set headers.
  * ``/mcp/k/<token>`` — a URL-embedded key, for connector UIs that accept only
    a URL. It works, but the token then lives in a URL: browser history, proxy
    logs, and any screenshot of the settings pane. Treat such a URL as the
    credential itself, issue one per tenant, and rotate it if it is shared.
    Off by default; enable with ``LEGAFY_MCP_URL_TOKENS=true``.

Proper OAuth with Dynamic Client Registration is the destination for a public
multi-tenant launch (Claude supports DCR and calls back to
``claude.ai/api/mcp/auth_callback``). It is deliberately not built yet — see
docs/HOSTING_MCP.md.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from app.mcp.server import CURRENT_TENANT, build_server
from app.security.tenancy import QuotaExceeded, RateLimitExceeded, TenancyError, authenticate

log = logging.getLogger("legafy.mcp.http")

CHALLENGE = 'Bearer realm="legafy", error="invalid_token"'


def allowed_origins() -> set[str]:
    raw = os.getenv("LEGAFY_MCP_ALLOWED_ORIGINS", "")
    return {o.strip().rstrip("/") for o in raw.split(",") if o.strip()}


def _origin_refused(scope: Scope) -> str | None:
    """DNS-rebinding guard. Returns the offending Origin, or None to proceed.

    No MCP client sends `Origin` — Claude Desktop, Claude Code and the hosted
    connectors all call this server-side. A browser always does. So an `Origin`
    on this endpoint means a web page is driving it, and on a machine that is
    also on the tailnet that page may not be one of ours: a malicious site can
    resolve its own name to 127.0.0.1 (or to 100.x) and POST here with the
    victim's network position. Absent header -> allow. Present and not
    allowlisted -> refuse, before authentication and before any handler runs.
    """
    for key, value in scope.get("headers", []):
        if key == b"origin":
            origin = value.decode("latin-1").strip().rstrip("/")
            if origin and origin not in allowed_origins():
                return origin
    return None


def url_tokens_enabled() -> bool:
    return os.getenv("LEGAFY_MCP_URL_TOKENS", "").strip().lower() in {"1", "true", "yes", "on"}


def _authorization_from(scope: Scope) -> str | None:
    """Read the token from the Authorization header, or from a /k/<token> path."""
    for key, value in scope.get("headers", []):
        if key == b"authorization":
            return value.decode("latin-1")
    if url_tokens_enabled():
        # Match the trailing ".../k/<token>" wherever it sits: a mounted app may
        # see the full path or only the remainder, depending on the ASGI server
        # and Starlette version. Anchoring on the last two segments works for both.
        parts = [p for p in scope.get("path", "").split("/") if p]
        if len(parts) >= 2 and parts[-2] == "k":
            return f"Bearer {parts[-1]}"
    return None


@dataclass
class MCPHttp:
    """The mounted ASGI app; its session manager is created per app lifespan.

    A mounted sub-app's lifespan is not started by the parent, so ``app/main.py``
    enters :meth:`session` in its own lifespan. The manager is built there rather
    than at import because a StreamableHTTPSessionManager can only be run once —
    building it once at import means the second app instance in a process (a
    reload, a test client, a second worker in-process) dies on startup.
    """

    manager: Any = None

    @asynccontextmanager
    async def session(self) -> AsyncIterator[None]:
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

        # stateless: a Cloudflare tunnel offers no session affinity, and every
        # Legafy tool call is self-contained, so there is no conversation state
        # to pin to a worker. json_response returns plain JSON instead of an SSE
        # stream, which is what connector UIs handle most reliably.
        self.manager = StreamableHTTPSessionManager(
            app=build_server(), stateless=True, json_response=True
        )
        try:
            async with self.manager.run():
                yield
        finally:
            self.manager = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # pragma: no cover - transport is HTTP only
            return
        if self.manager is None:
            response = JSONResponse(
                {"error": "unavailable", "message": "MCP transport is not running."},
                status_code=503,
            )
            await response(scope, receive, send)
            return
        refused = _origin_refused(scope)
        if refused is not None:
            log.warning("MCP transport refused cross-origin request from %r", refused)
            response = JSONResponse(
                {
                    "error": "forbidden_origin",
                    "message": (
                        "This endpoint does not serve browser origins. If a first-party web "
                        "client genuinely needs it, add the origin to LEGAFY_MCP_ALLOWED_ORIGINS."
                    ),
                },
                status_code=403,
            )
            await response(scope, receive, send)
            return
        authorization = _authorization_from(scope)
        try:
            tenant, _ = await authenticate(authorization, "audit")
        except TenancyError as exc:
            log.warning("MCP transport refused request: %s", type(exc).__name__)
            # Being over quota is not the same as being unauthenticated: a 401
            # makes a client re-prompt for credentials it already has, and the
            # user sees "connection failed" instead of "you hit your limit".
            if isinstance(exc, RateLimitExceeded | QuotaExceeded):
                headers = {}
                if isinstance(exc, RateLimitExceeded):
                    headers["Retry-After"] = str(exc.retry_after_seconds)
                response = JSONResponse(
                    {"error": "rate_limited", "message": str(exc)},
                    status_code=429,
                    headers=headers,
                )
            else:
                response = JSONResponse(
                    {"error": "unauthorized", "message": str(exc)},
                    status_code=401,
                    headers={"WWW-Authenticate": CHALLENGE},
                )
            await response(scope, receive, send)
            return
        log.info("MCP request for %s (%s)", tenant.organization_name, tenant.tier.value)
        token = CURRENT_TENANT.set(tenant)
        try:
            await self.manager.handle_request(scope, receive, send)
        finally:
            CURRENT_TENANT.reset(token)


def build_mcp_http() -> MCPHttp:
    """Cheap: no server or manager is constructed until the lifespan starts."""
    return MCPHttp()
