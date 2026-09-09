"""Pydantic contracts for Legafy AI.

These models are the single source of truth for both transports:
  * the HTTP API (``app/main.py``), and
  * the MCP tool surface (``app/mcp/server.py``), whose JSON Schemas are
    generated directly from these classes — the two can never drift.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class LicenseTier(str, Enum):
    DEVELOPER_FREE = "DEVELOPER_FREE"
    PREMIUM_HOSTED = "PREMIUM_HOSTED"
    ENTERPRISE_B2B = "ENTERPRISE_B2B"


class Lane(str, Enum):
    """Traffic-light lane. AMBER is a hold, RED is a hard stop."""

    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"


class ActivityFlag(str, Enum):
    """Declared product behaviours that drive instrument selection.

    These are deliberately behavioural ("holds customer funds") rather than
    sectoral ("fintech"), because obligations attach to conduct, not labels.
    """

    ANY_ENTITY = "any_entity"
    EMPLOYS_PERSONS = "employs_persons"
    HAS_WORKPLACE_IN_STATE = "has_workplace_in_state"
    ENGAGES_CONTRACT_LABOUR = "engages_contract_labour"
    CARRIES_ON_PROFESSION_IN_STATE = "carries_on_profession_in_state"
    ESTABLISHES_INDUSTRIAL_UNIT = "establishes_industrial_unit"
    SUPPLIES_GOODS_OR_SERVICES = "supplies_goods_or_services"
    SELLS_TO_CONSUMERS = "sells_to_consumers"
    OPERATES_DIGITAL_SERVICE = "operates_digital_service"
    PROCESSES_PERSONAL_DATA = "processes_personal_data"
    PROCESSES_CHILDREN_DATA = "processes_children_data"
    PROCESSES_HEALTH_DATA = "processes_health_data"
    PROCESSES_BIOMETRIC_DATA = "processes_biometric_data"
    CROSS_BORDER_DATA_TRANSFER = "cross_border_data_transfer"
    HOLDS_CUSTOMER_FUNDS = "holds_customer_funds"
    OPERATES_ESCROW = "operates_escrow"
    PAYMENT_AGGREGATION = "payment_aggregation"
    LENDING_OR_CREDIT = "lending_or_credit"
    INSURANCE_DISTRIBUTION = "insurance_distribution"
    SECURITIES_OR_INVESTMENT = "securities_or_investment"
    VIRTUAL_DIGITAL_ASSETS = "virtual_digital_assets"
    FOREIGN_INVESTMENT = "foreign_investment"
    CROSS_BORDER_PAYMENTS = "cross_border_payments"
    MULTI_STATE_OPERATIONS = "multi_state_operations"
    USER_GENERATED_CONTENT = "user_generated_content"
    USES_THIRD_PARTY_CONTENT = "uses_third_party_content"
    DEVELOPS_PROPRIETARY_TECHNOLOGY = "develops_proprietary_technology"
    AUTOMATED_DECISIONING = "automated_decisioning"
    GOVERNMENT_CONTRACTING = "government_contracting"


class EntityType(str, Enum):
    PRIVATE_LIMITED = "private_limited"
    LLP = "llp"
    OPC = "opc"
    PUBLIC_LIMITED = "public_limited"
    PARTNERSHIP = "partnership"
    SOLE_PROPRIETORSHIP = "sole_proprietorship"
    UNDECIDED = "undecided"


class FrameworkType(str, Enum):
    """Document frameworks the assembly pipeline knows how to build."""

    FOUNDERS_AGREEMENT = "founders_agreement"
    EMPLOYMENT_AGREEMENT = "employment_agreement"
    MUTUAL_NDA = "mutual_nda"
    DPDP_DATA_POLICY = "dpdp_data_policy"
    SAAS_TERMS_OF_SERVICE = "saas_terms_of_service"
    CONSULTING_AGREEMENT = "consulting_agreement"


# ---------------------------------------------------------------------------
# Tenancy
# ---------------------------------------------------------------------------
class TenantContext(BaseModel):
    """Resolved identity of the caller, attached to every request."""

    model_config = ConfigDict(frozen=True)

    token_id: str = Field(description="Stable non-secret identifier for the token")
    organization_name: str
    tier: LicenseTier
    expires_on: date
    rate_limit_per_minute: int
    monthly_quota: int
    scopes: list[str] = Field(default_factory=list)

    def has_scope(self, scope: str) -> bool:
        return "*" in self.scopes or scope in self.scopes


class RateLimitSnapshot(BaseModel):
    limit_per_minute: int
    remaining_this_minute: int
    monthly_quota: int
    used_this_month: int
    retry_after_seconds: int | None = None


# ---------------------------------------------------------------------------
# Traffic light
# ---------------------------------------------------------------------------
class TrafficLightSignal(BaseModel):
    """One matched risk vector."""

    id: str
    lane: Lane
    title: str
    rationale: str
    matched_on: list[str] = Field(default_factory=list)
    instrument_refs: list[str] = Field(default_factory=list)


class TrafficLightVerdictModel(BaseModel):
    lane: Lane
    headline: str
    automation_permitted: bool
    green_lane: list[TrafficLightSignal] = Field(default_factory=list)
    amber_lane: list[TrafficLightSignal] = Field(default_factory=list)
    red_lane: list[TrafficLightSignal] = Field(default_factory=list)
    mandatory_counsel_notice: str | None = None
    counsel_brief: list[str] = Field(
        default_factory=list,
        description="Questions to put to a qualified lawyer, in priority order.",
    )


# ---------------------------------------------------------------------------
# Tool 1 — execute_regional_compliance_audit
# ---------------------------------------------------------------------------
class RegionalComplianceAuditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_concept: str = Field(
        min_length=12,
        max_length=8000,
        description=(
            "Plain-language description of the product or venture. This string is "
            "never persisted in clear text; only a keyed hash reaches the audit vault."
        ),
    )
    industry_vertical: str = Field(
        min_length=2,
        max_length=120,
        description="e.g. 'B2B SaaS', 'healthtech', 'marketplace', 'lending'.",
    )
    state_location: str = Field(
        description=(
            "Indian state whose code path applies, e.g. 'Telangana', 'Andhra Pradesh', "
            "'Maharashtra'. Unmapped states are refused rather than approximated."
        )
    )
    entity_type: EntityType = EntityType.UNDECIDED
    activity_flags: list[ActivityFlag] = Field(
        default_factory=list,
        description="Declared behaviours. Anything undeclared is not assessed.",
    )
    additional_states: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Other states of operation. Each is resolved as its own isolated path.",
    )
    language: str | None = Field(
        default=None,
        max_length=8,
        description=(
            "Optional BCP-47-ish code (e.g. 'te' for Telugu). Translates the explanation "
            "layer only — statute titles, citations and operative text stay in English, "
            "which remains the controlling version."
        ),
    )
    detail: Literal["compact", "full"] = Field(
        default="compact",
        description=(
            "compact (default) returns lane, duties and a proof pointer per duty — roughly "
            "a tenth of the tokens, with the static contract text moved into the tool "
            "description where it is sent once per session rather than per call. "
            "full returns instrument-level metadata."
        ),
    )
    sections: list[
        Literal["obligations", "research_checklist", "ip_screen", "proofs"]
    ] | None = Field(
        default=None,
        description=(
            "Optional token lever. Name only the blocks you need and the rest are omitted; "
            "omit this field to get everything. The verdict, the halt notice, the counsel "
            "brief and every RED signal are ALWAYS returned and cannot be switched off — "
            "a caller must not be able to ask for a cheaper answer that hides a red light."
        ),
    )
    contribute_to_corpus: bool = Field(
        default=False,
        description=(
            "Opt in to contributing this question (identifiers scrubbed, no tenant or user "
            "linkage) to the anonymous question corpus that improves Legafy's classifiers. "
            "Off by default. Never set it on a user's behalf."
        ),
    )

    @field_validator("business_concept", "industry_vertical", "state_location")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class JurisdictionBlock(BaseModel):
    code: str
    display_name: str
    isolation_group: str
    verification_status: str
    instruments: list[dict[str, Any]] = Field(default_factory=list)
    verification_note: str | None = None
    declared_absences: list[dict[str, Any]] = Field(default_factory=list)
    escalation_triggers: list[str] = Field(default_factory=list)


class RegionalComplianceAuditResponse(BaseModel):
    success: bool = True
    request_id: str
    generated_at: datetime
    isolation_contract: str
    union: JurisdictionBlock
    states: list[JurisdictionBlock]
    traffic_light: TrafficLightVerdictModel
    legal_obligations: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Every applicable duty with how to close it and what exposure follows if it is "
            "not closed. Consequences are categorical; amounts are never stated unless "
            "verified against the primary source."
        ),
    )
    research_checklist: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "The official register searches this venture should have run, grouped by the "
            "phase of work they belong to. Where to look and why, never what you will find."
        ),
    )
    ip_screen: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Copyright, trade-mark, patent and trade-secret questions inferred from the "
            "description. Advisory only — it never changes the traffic-light verdict."
        ),
    )
    source_whitelist: list[str]
    provenance_warning: str
    disclaimer: str
    rate_limit: RateLimitSnapshot | None = None


# ---------------------------------------------------------------------------
# Tool 2 — generate_legal_structure (chunk-assembly pipeline)
# ---------------------------------------------------------------------------
class PartyDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=120)
    address: str | None = Field(default=None, max_length=400)


class DocumentGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_name: str = Field(min_length=2, max_length=200)
    target_state: str = Field(description="Indian state driving the jurisdiction module.")
    framework_type: FrameworkType
    business_concept: str = Field(default="", max_length=8000)
    industry_vertical: str = Field(default="general", max_length=120)
    entity_type: EntityType = EntityType.UNDECIDED
    activity_flags: list[ActivityFlag] = Field(default_factory=list)
    parties: list[PartyDescriptor] = Field(default_factory=list, max_length=12)
    effective_date: date | None = None
    output_formats: list[Literal["markdown", "docx"]] = Field(
        default_factory=lambda: ["markdown", "docx"]
    )
    min_words: int | None = Field(
        default=None,
        ge=500,
        le=60000,
        description="Override the configured floor (default ~10,000 words ≈ 20 pages).",
    )
    dry_run: bool = Field(
        default=False,
        description="Compile and return the chunk plan without invoking any model.",
    )


class ChunkReport(BaseModel):
    index: int
    module: str
    heading: str
    clause_ids: list[str]
    words: int
    continuations: int
    truncation_recovered: bool
    provider: str
    model: str
    elapsed_ms: int


class DocumentGenerationResponse(BaseModel):
    success: bool = True
    request_id: str
    session_id: str
    generated_at: datetime
    framework_type: FrameworkType
    jurisdiction_code: str
    status: Literal["OUTLINE_COMPILED", "DOCUMENT_ASSEMBLED", "HALTED_RED_LANE"]
    traffic_light: TrafficLightVerdictModel
    chunk_plan: list[dict[str, Any]] = Field(default_factory=list)
    chunk_reports: list[ChunkReport] = Field(default_factory=list)
    total_words: int = 0
    estimated_pages: float = 0.0
    markdown_path: str | None = None
    docx_path: str | None = None
    citation_guard: dict[str, Any] = Field(default_factory=dict)
    disclaimer: str
    rate_limit: RateLimitSnapshot | None = None


# ---------------------------------------------------------------------------
# Audit vault
# ---------------------------------------------------------------------------
class AuditVaultRecord(BaseModel):
    """One append-only, tamper-evident telemetry record.

    No clear-text business concept is ever stored — only a keyed digest.
    """

    seq: int
    record_id: str
    recorded_at: datetime
    event: str
    token_id: str
    organization_name: str
    tier: LicenseTier
    concept_digest: str = Field(description="HMAC-SHA256(concept, deployment salt)")
    concept_length: int
    industry_vertical: str
    jurisdiction_codes: list[str]
    activity_flags: list[str]
    traffic_light_lane: Lane
    red_signal_ids: list[str] = Field(default_factory=list)
    provider_used: str | None = None
    outcome: str = "OK"
    prev_hash: str
    record_hash: str
    schema_version: int = 1


# ---------------------------------------------------------------------------
# Service surface
# ---------------------------------------------------------------------------
class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    product: str
    version: str
    env: str
    jurisdictions_loaded: int
    provider_chain: list[str]
    audit_vault_records: int
    uptime_seconds: float


class ErrorEnvelope(BaseModel):
    success: bool = False
    error_code: str
    message: str
    detail: dict[str, Any] | None = None
    request_id: str | None = None


# ---------------------------------------------------------------------------
# Tool 3 — search_legal_sources (primary-source index)
# ---------------------------------------------------------------------------
class LegalSourceSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=400, description="Full-text query.")
    jurisdiction: str | None = Field(
        default=None,
        description=(
            "Restrict to one isolated code path, e.g. 'IN-TG'. This is a HARD FILTER: a "
            "Telangana search never returns an Andhra Pradesh document at a lower rank."
        ),
    )
    limit: int = Field(default=10, ge=1, le=50)
    natural_language: bool = Field(
        default=True,
        description=(
            "Treat `query` as a plain question: classify intent and tone, extract "
            "jurisdictions and instruments with the phrase trie, and expand founder "
            "vocabulary into the words official pages actually use. Set false to pass "
            "raw FTS5 syntax through."
        ),
    )
    include_non_citable: bool = Field(
        default=False,
        description=(
            "Include sources below the citable authority floor. Such documents are "
            "orientation only and can never support a compliance claim."
        ),
    )


class LegalSourceHit(BaseModel):
    doc_id: str
    title: str
    url: str
    authority_tier: str
    authority_weight: float
    jurisdiction: str
    instrument_ids: list[str] = Field(default_factory=list)
    last_changed: str | None = None
    revision: int = 1
    score: float
    citable: bool


class LegalSourceSearchResponse(BaseModel):
    success: bool = True
    query: str
    jurisdiction: str | None = None
    hits: list[LegalSourceHit] = Field(default_factory=list)
    index: dict[str, Any] = Field(default_factory=dict)
    usage_note: str
    disclaimer: str


class VerifyRegistrationRequest(BaseModel):
    """Check one of the caller's own registrations against a government API."""

    model_config = ConfigDict(extra="forbid")

    check: str = Field(
        description="Which check to run, e.g. 'gstin', 'udyam', 'pan', 'cin'. "
        "Call with an empty identifier to list what is available and enabled."
    )
    identifier: str = Field(
        default="",
        max_length=64,
        description=(
            "The registration number to check. It is sent to the government endpoint "
            "and is NOT stored by Legafy — not in the audit vault, not in any log line."
        ),
    )


class SourceHealthRequest(BaseModel):
    """Ask whether the citations Legafy hands out are still sound."""

    model_config = ConfigDict(extra="forbid")

    check_live: bool = Field(
        default=False,
        description=(
            "Also fetch every citation to check it is reachable, on a valid certificate, "
            "and not redirecting off the official host. Off by default: it makes tens of "
            "outbound requests to government portals and takes seconds, and a portal outage "
            "is not a defect in our data."
        ),
    )
    severity: Literal["ERROR", "WARN", "ALL"] = Field(
        default="ERROR",
        description="Minimum severity to return. ERROR is what must be fixed before shipping.",
    )


class ReviewQueueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jurisdiction: str | None = None
    limit: int = Field(default=25, ge=1, le=200)
