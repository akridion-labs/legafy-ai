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

from app.compact import compact_audit
from app.compliance.audit import LEGAFY_DISCLAIMER
from app.compliance.registry import JURISDICTION_REGISTRY
from app.localisation import supported_languages, translate_payload
from app.models.schemas import (
    DocumentGenerationRequest,
    LegalSourceSearchRequest,
    RegionalComplianceAuditRequest,
    ReviewQueueRequest,
    TenantContext,
)
from app.search.corpus import get_corpus
from app.search.intent import analyse, build_fts_query
from app.service import run_audit, run_generation
from app.sources.store import CITABLE_AUTHORITY_FLOOR, get_store


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
    result = (await run_audit(request, request_id=request_id, tenant=tenant)).model_dump(mode="json")

    if request.contribute_to_corpus:
        # Opt-in only, identifiers scrubbed, and there is no tenant argument to pass.
        analysis = analyse(request.business_concept)
        get_corpus().record(
            question=request.business_concept,
            intent=analysis.intent,
            tone=analysis.tone,
            jurisdictions=[s["code"] for s in result.get("states", [])],
            activity_flags=[f.value for f in request.activity_flags],
            lane=result.get("traffic_light", {}).get("lane"),
        )

    if request.detail == "compact":
        result = compact_audit(result)
    if request.language:
        # Explanation layer only — see app/localisation.py for what stays English.
        result = await translate_payload(result, request.language)
    return result


async def _generate(payload: dict, *, request_id: str, tenant: TenantContext) -> dict:
    request = DocumentGenerationRequest.model_validate(payload)
    return (
        await run_generation(request, request_id=request_id, tenant=tenant)
    ).model_dump(mode="json")


async def _jurisdictions(payload: dict, *, request_id: str, tenant: TenantContext) -> dict:
    return {
        "jurisdictions": JURISDICTION_REGISTRY.all_summaries(),
        "languages": supported_languages(),
        "isolation_note": (
            "Each state is an isolated code path. Legafy refuses to approximate an "
            "unmapped state with a neighbouring one."
        ),
    }


async def _search_sources(payload: dict, *, request_id: str, tenant: TenantContext) -> dict:
    request = LegalSourceSearchRequest.model_validate(payload)
    store = get_store()

    analysis = analyse(request.query) if request.natural_language else None
    fts_query = build_fts_query(request.query, analysis) if analysis else request.query
    # A jurisdiction named in the question is honoured only when the caller did not
    # pin one explicitly. It stays a hard filter either way.
    jurisdiction = request.jurisdiction
    if jurisdiction is None and analysis and len(analysis.jurisdictions) == 1:
        jurisdiction = analysis.jurisdictions[0]

    hits = store.search(
        fts_query,
        jurisdiction=jurisdiction,
        limit=request.limit,
        citable_only=not request.include_non_citable,
    )
    return {
        "success": True,
        "query": request.query,
        "fts_query": fts_query,
        "analysis": analysis.as_dict() if analysis else None,
        "jurisdiction": jurisdiction,
        "hits": hits,
        "index": store.stats(),
        "usage_note": (
            "These are pointers to primary sources, not assertions about their contents. "
            f"Only documents at or above authority weight {CITABLE_AUTHORITY_FLOOR} may support "
            "a compliance statement, and only after a human has read them. Jurisdiction is a "
            "hard filter: results from another state are never returned at a lower rank."
        ),
        "disclaimer": LEGAFY_DISCLAIMER,
    }


async def _review_queue(payload: dict, *, request_id: str, tenant: TenantContext) -> dict:
    request = ReviewQueueRequest.model_validate(payload or {})
    store = get_store()
    return {
        "success": True,
        "pending": store.pending_reviews(
            limit=request.limit, jurisdiction=request.jurisdiction
        ),
        "index": store.stats(),
        "note": (
            "Detected changes at whitelisted primary sources, ordered by review priority "
            "(authority x change magnitude x instrument coverage x recency x exposure). "
            "A queued item is a prompt for a human to read the source. It is not a finding, "
            "and nothing here has changed any answer the engine gives."
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

SEARCH_DESCRIPTION = """Search Legafy's index of INDIAN GOVERNMENT PRIMARY SOURCES (gazette,
ministry, regulator and state department pages). Use it to find the official page behind an
obligation, or to check what a state portal currently says.

This returns POINTERS WITH AUTHORITY WEIGHTS, not answers. A hit is a document to read, not a
statement of law — do not paraphrase a hit as though it were the rule. `jurisdiction` is a hard
filter, so a Telangana query never surfaces an Andhra Pradesh page. Hits below the citable floor
are orientation only."""

REVIEW_DESCRIPTION = """List detected changes at watched primary sources, ordered by review
priority. Operational tool for the compliance team: it says which source page moved and how much,
so a human knows what to read next. It never changes an answer on its own."""

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
        name="search_legal_sources",
        title="Search Primary Legal Sources",
        description=SEARCH_DESCRIPTION,
        input_model=LegalSourceSearchRequest,
        handler=_search_sources,
        required_scope="audit",
    ),
    ToolSpec(
        name="list_source_review_queue",
        title="List Source Review Queue",
        description=REVIEW_DESCRIPTION,
        input_model=ReviewQueueRequest,
        handler=_review_queue,
        required_scope="review",
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
