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
