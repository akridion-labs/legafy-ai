"""The tool catalogue — one definition, every transport.

`app/main.py` publishes these as JSON-Schema HTTP endpoints (for OpenAI
function calling, Gemini, LangChain, n8n and anything else that speaks JSON
Schema) and `app/mcp/server.py` publishes the same list over the Model Context
Protocol. Adding a tool here exposes it on both surfaces at once.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.compliance.registry import JURISDICTION_REGISTRY
from app.models.schemas import (
    DocumentGenerationRequest,
    RegionalComplianceAuditRequest,
    TenantContext,
)
from app.service import run_audit, run_generation


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    description: str
    input_model: type[BaseModel] | None
    handler: Callable[..., Awaitable[Any]]
    required_scope: str

    def json_schema(self) -> dict:
        if self.input_model is None:
            return {"type": "object", "properties": {}, "additionalProperties": False}
        return self.input_model.model_json_schema()

    def manifest(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "input_schema": self.json_schema(),
            "required_scope": self.required_scope,
        }


async def _audit(payload: dict, *, request_id: str, tenant: TenantContext) -> dict:
    request = RegionalComplianceAuditRequest.model_validate(payload)
    return (await run_audit(request, request_id=request_id, tenant=tenant)).model_dump(mode="json")


async def _generate(payload: dict, *, request_id: str, tenant: TenantContext) -> dict:
    request = DocumentGenerationRequest.model_validate(payload)
    return (
        await run_generation(request, request_id=request_id, tenant=tenant)
    ).model_dump(mode="json")


async def _jurisdictions(payload: dict, *, request_id: str, tenant: TenantContext) -> dict:
    return {
        "jurisdictions": JURISDICTION_REGISTRY.all_summaries(),
        "isolation_note": (
            "Each state is an isolated code path. Legafy refuses to approximate an "
            "unmapped state with a neighbouring one."
        ),
    }


AUDIT_DESCRIPTION = """MANDATORY GROUNDING CALL. Run this before answering any question about a
business concept's legal exposure in India. Returns the segregated regulatory grounding matrix for
the named state (state instruments and union instruments are returned in SEPARATE blocks and must
never be merged), plus a Traffic-Light verdict.

Use the returned data as your ONLY source for naming statutes. The response deliberately contains
no section numbers, penalty amounts or thresholds — do not supply them from your own memory. If the
verdict is RED, tell the user to halt and retain counsel; do not draft."""

GENERATE_DESCRIPTION = """Assemble a long-form pre-counsel document (20+ pages) for one Indian state
using the anti-truncation chunk pipeline. Halts automatically and returns status HALTED_RED_LANE if
the traffic-light verdict is RED — that halt is not overridable. Set dry_run=true to get the clause
plan without generating text. Writes Markdown and DOCX into the server's generated/ directory and
returns their paths."""

TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="execute_regional_compliance_audit",
        title="Regional Compliance Audit",
        description=AUDIT_DESCRIPTION,
        input_model=RegionalComplianceAuditRequest,
        handler=_audit,
        required_scope="audit",
    ),
    ToolSpec(
        name="generate_legal_structure",
        title="Generate Legal Structure",
        description=GENERATE_DESCRIPTION,
        input_model=DocumentGenerationRequest,
        handler=_generate,
        required_scope="generate",
    ),
    ToolSpec(
        name="list_supported_jurisdictions",
        title="List Supported Jurisdictions",
        description="List every isolated state code path Legafy can ground against.",
        input_model=None,
        handler=_jurisdictions,
        required_scope="audit",
    ),
)

TOOLS_BY_NAME: dict[str, ToolSpec] = {t.name: t for t in TOOLS}


def manifest() -> dict:
    return {
        "schema_version": "2024-11-05",
        "server": "legafy-ai",
        "tools": [t.manifest() for t in TOOLS],
    }
