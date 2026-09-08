"""Legafy AI production API engine.

Three surfaces on one process, all sharing app/tools.py:
  * REST         — /api/v1/*
  * Tool API     — /tools (JSON-Schema manifest) + /tools/{name}/invoke, for AI
                   platforms that call functions over plain HTTP.
  * Remote MCP   — /mcp, Streamable HTTP. This is what a Claude custom connector
                   or a ChatGPT developer-mode connector points at.
The stdio MCP server for local hosts lives in app/mcp/server.py.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.compliance.audit import LEGAFY_DISCLAIMER
from app.compliance.registry import JURISDICTION_REGISTRY, UnknownJurisdictionError
from app.config import get_settings
from app.models.schemas import (
    DocumentGenerationRequest,
    DocumentGenerationResponse,
    ErrorEnvelope,
    HealthResponse,
    RegionalComplianceAuditRequest,
    TenantContext,
)
from app.providers.router import get_router
from app.security.telemetry import digest_is_degraded, get_audit_vault
from app.security.tenancy import (
    ExpiredToken,
    InsufficientScope,
    InvalidToken,
    QuotaExceeded,
    RateLimitExceeded,
    authenticate,
    get_tenant_registry,
)
from app.service import run_generation
from app.tools import TOOLS_BY_NAME, manifest

logging.basicConfig(
    level=getattr(logging, get_settings().log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("legafy.api")
STARTED_AT = time.time()


try:
    from app.mcp.http import build_mcp_http

    MCP_HTTP = build_mcp_http()
except Exception as exc:  # pragma: no cover - MCP SDK absent or incompatible
    MCP_HTTP = None
    logging.getLogger("legafy.api").warning("Remote MCP transport unavailable: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    problems = settings.validate_production_posture()
    if problems:
        raise RuntimeError(
            "Refusing to start in production with an unsafe posture:\n  - "
            + "\n  - ".join(problems)
        )
    JURISDICTION_REGISTRY.load()
    get_tenant_registry().load()
    settings.generated_path.mkdir(parents=True, exist_ok=True)
    log.info(
        "Legafy AI %s up | env=%s | jurisdictions=%d | providers=%s | mcp_http=%s",
        __version__,
        settings.env,
        len(JURISDICTION_REGISTRY.all_summaries()),
        ",".join(get_router().chain),
        MCP_HTTP is not None,
    )
    if MCP_HTTP is None:
        yield
    else:
        # A mounted sub-app's lifespan is not run by the parent, so the session
        # manager has to be started here or /mcp fails on its first request.
        async with MCP_HTTP.session():
            yield
    await get_router().aclose()


app = FastAPI(
    title="Legafy AI Universal Routing Gateway",
    description=(
        "Model-agnostic pre-counsel compliance scaffolding engine by Akridion Labs. "
        "Not a law firm; output is not legal advice."
    ),
    version=__version__,
    lifespan=lifespan,
)
# No CORS by default. This API is called by servers and MCP clients, which are
# not subject to CORS at all; a wildcard here only widens the browser attack
# surface on an endpoint that takes a bearer token. Set LEGAFY_CORS_ORIGINS to
# the specific origins of a first-party web UI if one is ever built.
_cors_origins = get_settings().cors_origin_list
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["authorization", "content-type", "x-request-id"],
        max_age=600,
    )


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = request.headers.get("x-request-id") or f"req_{uuid.uuid4().hex[:16]}"
    response = await call_next(request)
    response.headers["x-request-id"] = request.state.request_id
    return response


# --- Error handling -------------------------------------------------------
def _error(status: int, code: str, message: str, request: Request, detail=None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=ErrorEnvelope(
            error_code=code,
            message=message,
            detail=detail,
            request_id=getattr(request.state, "request_id", None),
        ).model_dump(),
    )


@app.exception_handler(UnknownJurisdictionError)
async def _unknown_jurisdiction(request: Request, exc: UnknownJurisdictionError):
    return _error(
        422,
        "unknown_jurisdiction",
        str(exc),
        request,
        {"supported": exc.supported, "received": exc.raw},
    )


@app.exception_handler(InvalidToken)
async def _invalid_token(request: Request, exc: InvalidToken):
    return _error(401, "invalid_token", str(exc), request)


@app.exception_handler(ExpiredToken)
async def _expired_token(request: Request, exc: ExpiredToken):
    return _error(401, "expired_token", str(exc), request)


@app.exception_handler(InsufficientScope)
async def _scope(request: Request, exc: InsufficientScope):
    return _error(403, "insufficient_scope", str(exc), request)


@app.exception_handler(RateLimitExceeded)
async def _rate_limited(request: Request, exc: RateLimitExceeded):
    response = _error(429, "rate_limit_exceeded", str(exc), request)
    response.headers["Retry-After"] = str(exc.retry_after_seconds)
    return response


@app.exception_handler(QuotaExceeded)
async def _quota(request: Request, exc: QuotaExceeded):
    return _error(
        429, "monthly_quota_exceeded", str(exc), request,
        {"monthly_quota": exc.monthly_quota, "used": exc.used},
    )


# --- Auth dependency ------------------------------------------------------
def require(scope: str):
    async def dependency(authorization: str | None = Header(default=None)):
        return await authenticate(authorization, scope)

    return dependency


# --- Service surface ------------------------------------------------------
@app.get("/", tags=["service"])
async def root() -> dict:
    settings = get_settings()
    return {
        "product": "Legafy AI",
        "vendor": "Akridion Labs LLP",
        "version": __version__,
        "positioning": "Pre-counsel structural scaffolding. Not a law firm. Not legal advice.",
        "endpoints": {
            "health": "/healthz",
            "openapi": "/docs",
            "mcp_streamable_http": "/mcp",
            "tool_manifest": "/tools",
            "tool_invoke": "/tools/{tool_name}/invoke",
            "audit": "/api/v1/audit",
            "generate": "/api/v1/legal/generate-structure",
        },
        "mcp": {
            "transport": "streamable-http",
            "url": f"{settings.public_base_url.rstrip('/')}/mcp",
            "auth": "Authorization: Bearer <token>",
        },
        "public_base_url": settings.public_base_url,
        "disclaimer": LEGAFY_DISCLAIMER,
    }


@app.get("/healthz", response_model=HealthResponse, tags=["service"])
async def healthz() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="degraded" if digest_is_degraded() else "ok",
        product="Legafy AI",
        version=__version__,
        env=settings.env,
        jurisdictions_loaded=len(JURISDICTION_REGISTRY.all_summaries()),
        provider_chain=get_router().chain,
        audit_vault_records=get_audit_vault().record_count(),
        uptime_seconds=round(time.time() - STARTED_AT, 1),
    )


# --- Tool API (JSON Schema, for non-MCP AI platforms) ---------------------
# These live under /tools, not /mcp: the whole /mcp subtree belongs to the
# Streamable HTTP transport mounted at the bottom of this file.
@app.get("/tools", tags=["tools"])
async def tool_manifest() -> dict:
    return manifest()


@app.post("/tools/{tool_name}/invoke", tags=["tools"])
async def invoke_tool(tool_name: str, payload: dict, request: Request):
    spec = TOOLS_BY_NAME.get(tool_name)
    if spec is None:
        return _error(404, "unknown_tool", f"No tool named {tool_name!r}", request,
                      {"available": sorted(TOOLS_BY_NAME)})
    tenant, snapshot = await authenticate(request.headers.get("authorization"), spec.required_scope)
    result = await spec.handler(payload, request_id=request.state.request_id, tenant=tenant)
    return {"success": True, "tool": tool_name, "result": result,
            "rate_limit": snapshot.model_dump()}


# --- REST -----------------------------------------------------------------
@app.post("/api/v1/audit", tags=["compliance"])
async def audit_endpoint(
    payload: RegionalComplianceAuditRequest,
    request: Request,
    auth: tuple[TenantContext, object] = Depends(require("audit")),
) -> dict:
    # Routed through the tool handler so REST and MCP cannot diverge — including
    # the optional localisation pass.
    tenant, snapshot = auth
    result = await TOOLS_BY_NAME["execute_regional_compliance_audit"].handler(
        payload.model_dump(mode="json"), request_id=request.state.request_id, tenant=tenant
    )
    result["rate_limit"] = snapshot.model_dump()
    return result


@app.post(
    "/api/v1/legal/generate-structure",
    response_model=DocumentGenerationResponse,
    tags=["documents"],
)
async def generate_endpoint(
    payload: DocumentGenerationRequest,
    request: Request,
    auth: tuple[TenantContext, object] = Depends(require("generate")),
) -> DocumentGenerationResponse:
    tenant, snapshot = auth
    response = await run_generation(payload, request_id=request.state.request_id, tenant=tenant)
    response.rate_limit = snapshot
    return response


@app.get("/api/v1/jurisdictions", tags=["compliance"])
async def jurisdictions(auth=Depends(require("audit"))) -> dict:
    return {"jurisdictions": JURISDICTION_REGISTRY.all_summaries()}


@app.get("/api/v1/audit-vault/verify", tags=["compliance"])
async def verify_vault(auth=Depends(require("audit"))) -> dict:
    ok, reason = get_audit_vault().verify_chain()
    return {"intact": ok, "reason": reason, "records": get_audit_vault().record_count()}


# --- Remote MCP (Streamable HTTP) -----------------------------------------
# Mounted last so it owns the whole /mcp subtree. This is the endpoint a Claude
# custom connector or a ChatGPT developer-mode connector points at.
if MCP_HTTP is not None:
    # Starlette answers a bare /mcp with a 307 to /mcp/. Clients that follow
    # redirects (the MCP SDK does) are fine either way; give out the /mcp/ form
    # in connector settings so there is no hop at all.
    app.mount("/mcp", MCP_HTTP)
