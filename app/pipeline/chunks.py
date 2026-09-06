"""Chunk plan: the indexed clause map the assembly loop walks.

The five modules named in the blueprint are mandatory and always appear in
this order; each framework appends its own modules after them.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.schemas import DocumentGenerationRequest, FrameworkType

MODULE_SEQUENCE: tuple[str, ...] = (
    "Preamble",
    "Equity Vesting",
    "Intellectual Property Assignment",
    "Data Privacy",
    "Localized Jurisdiction",
)


@dataclass(frozen=True)
class ClauseSpec:
    id: str
    heading: str
    guidance: str


@dataclass(frozen=True)
class ChunkSpec:
    index: int
    module: str
    heading: str
    clauses: tuple[ClauseSpec, ...]
    min_words: int

    @property
    def clause_ids(self) -> list[str]:
        return [c.id for c in self.clauses]


# (module, [(heading, guidance), ...]) — guidance is drafting instruction only,
# never a legal assertion.
_CORE: dict[str, list[tuple[str, str]]] = {
    "Preamble": [
        ("Effective Date and Parties", "Identify each party by the descriptors supplied and fix the effective date."),
        ("Definitions", "Define every capitalised term the document will use. Alphabetical."),
        ("Recitals of Operational Scope", "State what the venture does, in the words of the supplied concept."),
        ("Interpretation", "Standard construction rules: headings, singular/plural, business days."),
    ],
    "Equity Vesting": [
        ("Capital Contribution and Initial Allocation", "Record contributions and the initial split as a schedule reference."),
        ("Vesting Commencement and Schedule", "Describe cliff, vesting cadence and the commencement trigger structurally."),
        ("Acceleration Events", "Single- and double-trigger acceleration mechanics."),
        ("Leaver Provisions", "Good leaver / bad leaver treatment of vested and unvested interests."),
        ("Repurchase Mechanics", "Repurchase right, valuation method reference, and completion mechanics."),
    ],
    "Intellectual Property Assignment": [
        ("Present Assignment of Work Product", "Assign work product created for the venture, with a further-assurance obligation."),
        ("Pre-Existing and Excluded IP", "Carve out prior IP and require it to be scheduled."),
        ("Moral Rights and Waivers", "Address moral rights to the extent waivable."),
        ("Third-Party and Open Source Materials", "Require disclosure of third-party and open-source components and their licence terms."),
        ("Confidential Information", "Confidentiality obligation covering technical and commercial information."),
    ],
    "Data Privacy": [
        ("Roles and Processing Scope", "Fix which party determines purpose and means, and the categories processed."),
        ("Notice, Lawful Basis and Consent Records", "Require a notice surface and retained records of the basis relied on."),
        ("Data Principal Rights Handling", "Access, correction, erasure and grievance handling, with response ownership."),
        ("Security Safeguards", "Organisational and technical measures, access control and logging."),
        ("Retention, Deletion and Return", "Retention limits and deletion or return on termination."),
        ("Breach Response and Notification", "Internal escalation path and notification ownership."),
    ],
    "Localized Jurisdiction": [
        ("Governing Law", "State the governing law by reference to the named state only. No other state."),
        ("Venue and Dispute Resolution", "Seat and venue within the named state; escalation before formal proceedings."),
        ("Arbitration Procedure", "Appointment, seat, language and award finality, structurally."),
        ("Severability and Survival", "Severability, survival of the listed clauses, and entire-agreement."),
        ("Notices and Counterparts", "Notice addresses, deemed receipt and counterpart execution."),
    ],
}

_EXTRA: dict[FrameworkType, dict[str, list[tuple[str, str]]]] = {
    FrameworkType.FOUNDERS_AGREEMENT: {
        "Governance and Deadlock": [
            ("Board and Reserved Matters", "Composition and the list of matters requiring supermajority consent."),
            ("Deadlock Resolution", "Escalation ladder and the mechanism if it fails."),
            ("Information Rights", "Reporting cadence and inspection rights."),
        ],
        "Transfer Restrictions": [
            ("Restriction on Transfer", "General prohibition and permitted transferees."),
            ("Right of First Refusal", "Offer, acceptance window and completion."),
            ("Tag-Along and Drag-Along", "Thresholds expressed structurally, not numerically."),
        ],
        "Commitment and Restrictive Covenants": [
            ("Time Commitment", "Full-time commitment and outside-activity disclosure."),
            ("Non-Solicitation", "Employees and customers, for a period stated in the schedule."),
            ("Restrictive Covenant Reasonableness", "Blue-pencil and reasonableness acknowledgement."),
        ],
        "Indemnity, Liability and Termination": [
            ("Mutual Indemnity", "Scope, procedure and conduct of claims."),
            ("Limitation of Liability", "Caps and excluded losses, expressed by reference to the schedule."),
            ("Termination and Exit", "Termination events, consequences and wind-down."),
        ],
    },
    FrameworkType.DPDP_DATA_POLICY: {
        "Processors and Sub-processors": [
            ("Engagement Conditions", "Written terms, flow-down obligations and approval of sub-processors."),
            ("Audit and Assurance", "Evidence the processor must produce and how often."),
        ],
        "Cross-Border and Localisation Posture": [
            ("Transfer Assessment", "Record where data rests and moves; flag every transfer for counsel."),
            ("Vendor Register", "Maintain a register of processors and hosting locations."),
        ],
        "Grievance Redressal": [
            ("Grievance Officer", "Appointment, published contact route and response ownership."),
            ("Escalation and Records", "Escalation path and retention of grievance records."),
        ],
    },
    FrameworkType.MUTUAL_NDA: {
        "Term and Return of Materials": [
            ("Term and Survival", "Term of the obligation and survival of confidentiality."),
            ("Return or Destruction", "Return, destruction and certification on request."),
            ("Permitted Disclosures", "Compelled disclosure and the notification obligation."),
        ],
    },
    FrameworkType.EMPLOYMENT_AGREEMENT: {
        "Engagement Terms": [
            ("Role, Reporting and Location", "Position, reporting line and the named-state work location."),
            ("Remuneration Structure", "Structure only; amounts live in the schedule."),
            ("Leave and Working Hours", "Refer to the state-specific policy; do not state entitlements."),
        ],
        "Termination": [
            ("Notice and Garden Leave", "Notice mechanics and garden leave."),
            ("Post-Termination Obligations", "Return of property and continuing obligations."),
        ],
    },
    FrameworkType.SAAS_TERMS_OF_SERVICE: {
        "Service Terms": [
            ("Licence and Restrictions", "Scope of the licence and prohibited uses."),
            ("Availability and Support", "Availability commitment structure and support channels."),
            ("Fees and Billing", "Billing cycle and adjustment mechanics; no amounts."),
        ],
        "Liability and Termination": [
            ("Warranties and Disclaimers", "Limited warranty and disclaimer of the rest."),
            ("Limitation of Liability", "Cap structure and excluded losses."),
            ("Suspension and Termination", "Grounds, notice and effect."),
        ],
    },
    FrameworkType.CONSULTING_AGREEMENT: {
        "Engagement and Deliverables": [
            ("Scope of Services", "Statement-of-work mechanics and change control."),
            ("Independent Contractor Status", "No employment, no agency, tax responsibility of the consultant."),
            ("Fees and Expenses", "Invoicing and expense approval mechanics."),
        ],
    },
}


def build_chunk_plan(
    *,
    framework_type: FrameworkType,
    jurisdiction_display: str,
    request: DocumentGenerationRequest,
    min_words: int,
) -> list[ChunkSpec]:
    modules: list[tuple[str, list[tuple[str, str]]]] = [(m, _CORE[m]) for m in MODULE_SEQUENCE]
    modules += list(_EXTRA.get(framework_type, {}).items())

    total_clauses = sum(len(c) for _, c in modules)
    per_clause = max(220, min_words // max(total_clauses, 1))

    plan: list[ChunkSpec] = []
    for i, (module, clauses) in enumerate(modules, start=1):
        specs = tuple(
            ClauseSpec(id=f"{i}.{j}", heading=h, guidance=g)
            for j, (h, g) in enumerate(clauses, start=1)
        )
        heading = module
        if module == "Localized Jurisdiction":
            heading = f"Localized Jurisdiction — {jurisdiction_display}"
        plan.append(
            ChunkSpec(
                index=i,
                module=module,
                heading=heading,
                clauses=specs,
                min_words=per_clause * len(specs),
            )
        )
    return plan


def plan_to_dicts(plan: list[ChunkSpec]) -> list[dict]:
    return [
        {
            "index": c.index,
            "module": c.module,
            "heading": c.heading,
            "min_words": c.min_words,
            "clauses": [{"id": s.id, "heading": s.heading} for s in c.clauses],
        }
        for c in plan
    ]


def build_table_of_contents(plan: list[ChunkSpec]) -> str:
    lines = ["## Table of Contents", ""]
    for chunk in plan:
        lines.append(f"{chunk.index}. **{chunk.heading}**")
        lines.extend(f"    - {s.id} {s.heading}" for s in chunk.clauses)
    return "\n".join(lines) + "\n"
