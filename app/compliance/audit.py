"""The grounding tool itself — ``execute_regional_compliance_audit``.

This is the mandatory grounding step: every business-concept question must be
answered only after resolving the caller's declared jurisdictions through the
isolated state registry, folding the resulting obligations into the
traffic-light matrix, and attaching a disclaimer that this is pre-counsel
scaffolding, not legal advice. An unmapped state is refused here rather than
approximated — ``UnknownJurisdictionError`` is left to propagate so the HTTP
layer can turn it into a 422 instead of a confident wrong answer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.compliance.obligations import build_obligation_ledger, screen_ip
from app.compliance.registry import JURISDICTION_REGISTRY, Jurisdiction
from app.compliance.traffic_light import TRAFFIC_LIGHT
from app.models.schemas import (
    JurisdictionBlock,
    RegionalComplianceAuditRequest,
    RegionalComplianceAuditResponse,
)

LEGAFY_DISCLAIMER: str = (
    "This output is pre-counsel structural scaffolding produced by an automated "
    "compliance-analysis tool. It is not legal advice, it does not create an "
    "attorney-client relationship, and it must not be relied on as a substitute "
    "for one. Every citation, obligation and jurisdictional assertion in this "
    "material must be independently verified against its primary source before "
    "it is relied upon, and a jurisdiction-qualified lawyer must review this "
    "material before any document is signed or filed."
)


def collect_activity_flags(request: RegionalComplianceAuditRequest) -> set[str]:
    """Extract the caller's declared behavioural flags as plain strings.

    Declared flags are the authoritative channel the traffic-light matrix and
    the jurisdiction registry's instrument selection both key off of; nothing
    here infers a flag from free text — that inference lives in the
    traffic-light matrix's advisory keyword channel, kept separate on purpose.
    """
    return {flag.value for flag in request.activity_flags}


def _resolve_ordered_unique(raw_states: list[str]) -> list[Jurisdiction]:
    """Resolve each raw state string, collapsing exact repeats, never states.

    A state named twice (e.g. the primary ``state_location`` also listed in
    ``additional_states``) collapses silently to one entry. Two different
    states are always kept as two separate entries — this function never
    merges what the registry resolved as distinct isolation groups.
    """
    resolved: list[Jurisdiction] = []
    seen_codes: set[str] = set()
    for raw in raw_states:
        jurisdiction = JURISDICTION_REGISTRY.resolve(raw)  # UnknownJurisdictionError propagates
        if jurisdiction.code in seen_codes:
            continue
        seen_codes.add(jurisdiction.code)
        resolved.append(jurisdiction)
    return resolved


def build_grounding_bundle(state_codes: list[str], flags: set[str]) -> dict[str, Any]:
    """Assemble the segregated grounding bundle for one or more states.

    Each state's block comes from its own call to
    ``JurisdictionRegistry.build_grounding_payload`` and is kept in its own
    entry in ``states``; the union block is taken once (it does not vary by
    state) and is never merged into any state's entry.
    """
    payloads = [JURISDICTION_REGISTRY.build_grounding_payload(code, flags) for code in state_codes]
    if not payloads:
        return {
            "union": {},
            "states": [],
            "source_whitelist": [],
            "citable_hosts": [],
            "citable_instrument_titles": [],
            "provenance_warning": "",
            "isolation_contract": "",
        }

    union_block = payloads[0]["union"]
    source_whitelist: set[str] = set()
    citable_hosts: set[str] = set()
    citable_titles: set[str] = set()
    for payload in payloads:
        source_whitelist |= set(payload.get("source_whitelist", []))
        citable_hosts |= set(payload.get("citable_hosts", []))
        citable_titles |= set(payload.get("citable_instrument_titles", []))

    return {
        "union": union_block,
        "states": [payload["state"] for payload in payloads],
        "source_whitelist": sorted(source_whitelist),
        "citable_hosts": sorted(citable_hosts),
        "citable_instrument_titles": sorted(citable_titles),
        "provenance_warning": payloads[0]["provenance_warning"],
        "isolation_contract": payloads[0]["isolation_contract"],
    }


async def execute_regional_compliance_audit(
    request: RegionalComplianceAuditRequest, *, request_id: str
) -> RegionalComplianceAuditResponse:
    """Resolve jurisdictions, ground them, and evaluate the traffic-light verdict."""
    raw_states = [request.state_location, *request.additional_states]
    resolved = _resolve_ordered_unique(raw_states)
    state_codes = [jurisdiction.code for jurisdiction in resolved]

    flags = collect_activity_flags(request)
    grounding = build_grounding_bundle(state_codes, flags)

    verdict = TRAFFIC_LIGHT.evaluate(
        business_concept=request.business_concept,
        industry_vertical=request.industry_vertical,
        activity_flags=flags,
        jurisdiction_codes=state_codes,
        framework_type=None,
        grounding=grounding,
    )

    union_block = JurisdictionBlock(**grounding["union"])
    state_blocks = [JurisdictionBlock(**state) for state in grounding["states"]]

    return RegionalComplianceAuditResponse(
        success=True,
        request_id=request_id,
        generated_at=datetime.now(UTC),
        isolation_contract=grounding.get("isolation_contract", ""),
        union=union_block,
        states=state_blocks,
        traffic_light=verdict.to_model(),
        legal_obligations=build_obligation_ledger(grounding),
        ip_screen=screen_ip(request.business_concept, request.industry_vertical, flags),
        source_whitelist=grounding.get("source_whitelist", []),
        provenance_warning=grounding.get("provenance_warning", ""),
        disclaimer=LEGAFY_DISCLAIMER,
        rate_limit=None,
    )
