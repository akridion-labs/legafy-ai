"""Legafy AI production API engine.

Two surfaces on one process:
  * REST      — /api/v1/*
  * Tool API  — /mcp/tools (JSON-Schema manifest) + /mcp/tools/{name}/invoke,
                for AI platforms that call functions over plain HTTP.
The native MCP stdio server lives in app/mcp/server.py and shares app/tools.py.
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
    RegionalComplianceAuditResponse,
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
from app.service import run_audit, run_generation
from app.tools import TOOLS_BY_NAME, manifest

logging.basicConfig(
    level=getattr(logging, get_settings().log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("legafy.api")
STARTED_AT = time.time()


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
        "Legafy AI %s up | env=%s | jurisdictions=%d | providers=%s",
        __version__,
        settings.env,
        len(JURISDICTION_REGISTRY.all_summaries()),
        ",".join(get_router().chain),
    )
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
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
            "tool_manifest": "/mcp/tools",
            "tool_invoke": "/mcp/tools/{tool_name}/invoke",
            "audit": "/api/v1/audit",
            "generate": "/api/v1/legal/generate-structure",
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
@app.get("/mcp/tools", tags=["tools"])
async def tool_manifest() -> dict:
    return manifest()


@app.post("/mcp/tools/{tool_name}/invoke", tags=["tools"])
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
@app.post("/api/v1/audit", response_model=RegionalComplianceAuditResponse, tags=["compliance"])
async def audit_endpoint(
    payload: RegionalComplianceAuditRequest,
    request: Request,
    auth: tuple[TenantContext, object] = Depends(require("audit")),
) -> RegionalComplianceAuditResponse:
    tenant, snapshot = auth
    response = await run_audit(payload, request_id=request.state.request_id, tenant=tenant)
    response.rate_limit = snapshot
    return response


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
