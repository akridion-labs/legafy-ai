"""Use cases shared by both transports.

The HTTP API and the MCP server are thin shells over this module. Putting the
logic here is what guarantees an MCP client and an HTTP client get byte-identical
guardrail behaviour — a divergence between the two would be a compliance hole.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.compliance.audit import (
    LEGAFY_DISCLAIMER,
    build_grounding_bundle,
    execute_regional_compliance_audit,
)
from app.compliance.citation_guard import CitationGuard
from app.compliance.registry import JURISDICTION_REGISTRY
from app.compliance.traffic_light import TRAFFIC_LIGHT
from app.config import get_settings
from app.models.schemas import (
    DocumentGenerationRequest,
    DocumentGenerationResponse,
    Lane,
    RegionalComplianceAuditRequest,
    RegionalComplianceAuditResponse,
    TenantContext,
)
from app.pipeline.assembler import ChunkAssembler
from app.pipeline.chunks import build_chunk_plan, build_table_of_contents, plan_to_dicts
from app.pipeline.prompts import build_system_prompt
from app.pipeline.renderers import render_document_markdown, render_docx, slugify, write_markdown
from app.providers.router import get_router
from app.security.telemetry import get_audit_vault

log = logging.getLogger("legafy.service")


async def run_audit(
    request: RegionalComplianceAuditRequest,
    *,
    request_id: str,
    tenant: TenantContext,
) -> RegionalComplianceAuditResponse:
    response = await execute_regional_compliance_audit(request, request_id=request_id)
    await get_audit_vault().append(
        event="regional_compliance_audit",
        tenant=tenant,
        business_concept=request.business_concept,
        industry_vertical=request.industry_vertical,
        jurisdiction_codes=[s.code for s in response.states],
        activity_flags=[f.value for f in request.activity_flags],
        traffic_light_lane=response.traffic_light.lane,
        red_signal_ids=[s.id for s in response.traffic_light.red_lane],
    )
    return response


async def run_generation(
    request: DocumentGenerationRequest,
    *,
    request_id: str,
    tenant: TenantContext,
) -> DocumentGenerationResponse:
    settings = get_settings()
    jurisdiction = JURISDICTION_REGISTRY.resolve(request.target_state)  # raises on unmapped
    flags = {f.value for f in request.activity_flags}
    grounding = build_grounding_bundle([jurisdiction.code], flags)

    verdict = TRAFFIC_LIGHT.evaluate(
        business_concept=request.business_concept,
        industry_vertical=request.industry_vertical,
        activity_flags=flags,
        jurisdiction_codes=[jurisdiction.code],
        framework_type=request.framework_type.value,
        grounding=grounding,
    )

    min_words = request.min_words or settings.min_document_words
    plan = build_chunk_plan(
        framework_type=request.framework_type,
        jurisdiction_display=jurisdiction.display_name,
        request=request,
        min_words=min_words,
    )

    def _envelope(status: str, **extra) -> DocumentGenerationResponse:
        return DocumentGenerationResponse(
            request_id=request_id,
            session_id=extra.pop("session_id", request_id),
            generated_at=datetime.now(UTC),
            framework_type=request.framework_type,
            jurisdiction_code=jurisdiction.code,
            status=status,
            traffic_light=verdict.to_model(),
            chunk_plan=plan_to_dicts(plan),
            disclaimer=LEGAFY_DISCLAIMER,
            **extra,
        )

    async def _log(lane: Lane, outcome: str, provider: str | None = None) -> None:
        await get_audit_vault().append(
            event="document_generation",
            tenant=tenant,
            business_concept=request.business_concept or request.project_name,
            industry_vertical=request.industry_vertical,
            jurisdiction_codes=[jurisdiction.code],
            activity_flags=sorted(flags),
            traffic_light_lane=lane,
            red_signal_ids=[s.id for s in verdict.to_model().red_lane],
            provider_used=provider,
            outcome=outcome,
        )

    # --- Guardrail: RED halts the automated lane. This is the product. -----
    if verdict.lane is Lane.RED:
        await _log(Lane.RED, "HALTED_RED_LANE")
        return _envelope("HALTED_RED_LANE")

    if request.dry_run:
        await _log(verdict.lane, "DRY_RUN")
        return _envelope("OUTLINE_COMPILED")

    guard = CitationGuard.from_grounding(grounding)
    assembler = ChunkAssembler(get_router(), settings, guard)
    document = await assembler.assemble(
        plan=plan,
        system_prompt=build_system_prompt(
            grounding, request.framework_type.value, jurisdiction.display_name
        ),
    )

    title = f"{request.project_name} — {request.framework_type.value.replace('_', ' ').title()}"
    meta = {
        "Jurisdiction": f"{jurisdiction.display_name} ({jurisdiction.code})",
        "Framework": request.framework_type.value,
        "Effective Date": request.effective_date.isoformat() if request.effective_date else "TBD",
        "Parties": ", ".join(f"{p.name} ({p.role})" for p in request.parties) or "TBD",
        "Session": document.session_id,
        "Status": "PRE-COUNSEL DRAFT — NOT EXECUTED",
    }
    markdown = render_document_markdown(
        title=title,
        meta=meta,
        toc=build_table_of_contents(plan),
        body=document.markdown,
        traffic_light_markdown=verdict.render_markdown(),
        disclaimer=LEGAFY_DISCLAIMER,
    )

    stem = f"{slugify(request.project_name)}-{request.framework_type.value}-{document.session_id[:8]}"
    out = settings.generated_path
    md_path = docx_path = None
    if "markdown" in request.output_formats:
        md_path = str(write_markdown(out / f"{stem}.md", markdown))
    if "docx" in request.output_formats:
        docx_path = str(
            render_docx(
                markdown_text=markdown,
                path=out / f"{stem}.docx",
                title=title,
                meta=meta,
                disclaimer=LEGAFY_DISCLAIMER,
            )
        )

    provider = document.chunks[0].report.provider if document.chunks else None
    await _log(verdict.lane, "DOCUMENT_ASSEMBLED", provider)

    return _envelope(
        "DOCUMENT_ASSEMBLED",
        session_id=document.session_id,
        chunk_reports=[c.report for c in document.chunks],
        total_words=document.total_words,
        estimated_pages=document.estimated_pages,
        markdown_path=md_path,
        docx_path=docx_path,
        citation_guard=document.guard_report,
    )
