"""The safety matrix that decides whether automated drafting may proceed.

This module exists because Legafy's whole value proposition rests on knowing
when to get out of the way of a lawyer, not on drafting faster. It never
invents a statute section or a fine — that belongs to ``data/jurisdictions``
and, later, the citation guard — it only classifies declared and described
activity into GREEN / AMBER / RED lanes and produces the halt instruction and
counsel brief that every generated artefact must carry.

Detection runs on two independent channels that are never allowed to silently
agree with each other:

* declared ``activity_flags`` — authoritative, supplied by the caller;
* a keyword/phrase scan of the free-text concept — advisory only, and any hit
  on this channel that is *not* backed by a declared flag still escalates the
  lane, but is recorded as inferred and in need of confirmation. Fail closed
  means a keyword the founder typed and forgot to declare is treated as a risk,
  not ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.models.schemas import Lane, TrafficLightSignal, TrafficLightVerdictModel

# ---------------------------------------------------------------------------
# Risk vectors
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RiskVector:
    """One named risk category the matrix knows how to detect.

    ``flags`` are the declared :class:`~app.models.schemas.ActivityFlag`
    values (as their string ``.value``) that authoritatively trigger this
    vector. ``keywords`` are phrases scanned advisorily out of free text.
    ``instrument_refs`` is populated only for vectors sourced from a grounding
    bundle at evaluation time, not for the static catalogue below.
    """

    id: str
    lane: Lane
    title: str
    rationale: str
    keywords: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
    instrument_refs: tuple[str, ...] = ()


# Phrase lists are kept as plain tuples on each vector (rather than a single
# free-floating blob) precisely so a reviewer can audit, per risk category,
# exactly which words push automation into a hold. Indian-context terms
# (UPI, NBFC, escrow, KYC, Aadhaar, PAN, wallet, remittance, telemedicine,
# EHR, ABDM, gaming/wagering, crypto/VDA) are distributed across the vector
# they most directly evidence.

RED_RISK_VECTORS: tuple[RiskVector, ...] = (
    RiskVector(
        id="payment_escrow",
        lane=Lane.RED,
        title="Payment escrow / holding customer funds / payment aggregation",
        rationale=(
            "Routing or holding customer funds — escrow, nodal accounts, wallets, UPI "
            "collection or payment aggregation — can require RBI payment-aggregator or "
            "prepaid-instrument authorisation before launch."
        ),
        keywords=(
            "escrow", "nodal account", "payment aggregator", "payment aggregation",
            "hold customer funds", "holding customer funds", "pooled account",
            "wallet balance", "prepaid wallet", "upi",
        ),
        flags=("operates_escrow", "holds_customer_funds", "payment_aggregation"),
    ),
    RiskVector(
        id="lending_or_credit",
        lane=Lane.RED,
        title="Lending or credit",
        rationale=(
            "Extending credit or facilitating loans can require NBFC or other RBI "
            "authorisation and attracts fair-lending and recovery-practice obligations."
        ),
        keywords=(
            "lending", "loan origination", "credit line", "nbfc", "emi option",
            "buy now pay later", "bnpl", "microfinance", "peer-to-peer lending",
        ),
        flags=("lending_or_credit",),
    ),
    RiskVector(
        id="insurance_distribution",
        lane=Lane.RED,
        title="Insurance distribution",
        rationale=(
            "Distributing, underwriting or bundling insurance can require IRDAI "
            "registration as a corporate agent, broker or intermediary."
        ),
        keywords=("insurance distribution", "insurance broking", "insurtech", "policy underwriting"),
        flags=("insurance_distribution",),
    ),
    RiskVector(
        id="securities_or_investment",
        lane=Lane.RED,
        title="Securities, investment advice or complex cap tables",
        rationale=(
            "Securities issuance, investment advice, portfolio management and multi-class "
            "cap tables interact with SEBI and Companies Act securities rules."
        ),
        keywords=(
            "securities", "investment advice", "portfolio management",
            "multi-class cap table", "multi class cap table", "cap table", "convertible notes",
        ),
        flags=("securities_or_investment",),
    ),
    RiskVector(
        id="virtual_digital_assets",
        lane=Lane.RED,
        title="Virtual digital assets, crypto, gaming or wagering",
        rationale=(
            "Virtual digital assets, crypto instruments and real-money gaming or wagering "
            "carry their own tax, FIU-IND registration and state-gaming-law exposure."
        ),
        keywords=(
            "crypto", "cryptocurrency", "virtual digital asset", "vda", "nft",
            "wagering", "real money gaming", "betting",
        ),
        flags=("virtual_digital_assets",),
    ),
    RiskVector(
        id="cross_border_data",
        lane=Lane.RED,
        title="Cross-border personal data transfer / data localisation",
        rationale=(
            "Moving personal data outside India, or a data-localisation question, is subject "
            "to government restriction under the DPDP framework and must be assessed "
            "instrument by instrument, not assumed."
        ),
        keywords=(
            "cross-border data", "cross border data", "data localisation", "data localization",
            "servers outside india", "transfer data outside india", "international data routing",
        ),
        flags=("cross_border_data_transfer",),
    ),
    RiskVector(
        id="childrens_data",
        lane=Lane.RED,
        title="Children's data",
        rationale=(
            "Processing children's personal data carries heightened consent, "
            "verifiable-parental-consent and targeted-advertising restrictions."
        ),
        keywords=("children's data", "childrens data", "children data", "minors' data", "kids app"),
        flags=("processes_children_data",),
    ),
    RiskVector(
        id="health_data",
        lane=Lane.RED,
        title="Health data",
        rationale=(
            "Health data, including telemedicine and electronic health records under the "
            "ABDM ecosystem, is treated as sensitive and carries elevated security duties."
        ),
        keywords=(
            "health data", "telemedicine", "electronic health record", "ehr", "abdm",
            "medical records", "patient data",
        ),
        flags=("processes_health_data",),
    ),
    RiskVector(
        id="biometric_data",
        lane=Lane.RED,
        title="Biometric data",
        rationale=(
            "Biometric identifiers — fingerprint, facial or iris data, and Aadhaar-based "
            "KYC/e-KYC flows using PAN or Aadhaar — carry elevated consent and storage duties."
        ),
        keywords=("biometric", "aadhaar", "facial recognition", "fingerprint scan", "iris scan", "kyc", "e-kyc", "pan card"),
        flags=("processes_biometric_data",),
    ),
    RiskVector(
        id="foreign_investment_fema",
        lane=Lane.RED,
        title="Foreign investment / FEMA exposure",
        rationale=(
            "Foreign investment, FDI routing or cross-border remittance flows are subject to "
            "FEMA reporting and sectoral-cap approval that must be confirmed before closing."
        ),
        keywords=("fema", "foreign direct investment", "fdi", "foreign investment", "outward remittance", "remittance"),
        flags=("foreign_investment",),
    ),
    RiskVector(
        id="government_contracting",
        lane=Lane.RED,
        title="Government contracting",
        rationale=(
            "Government contracts and public procurement carry eligibility, integrity-pact "
            "and audit obligations distinct from private commercial contracting."
        ),
        keywords=("government contract", "government tender", "public procurement", "gem portal", "government e-marketplace"),
        flags=("government_contracting",),
    ),
    RiskVector(
        id="automated_decisioning",
        lane=Lane.RED,
        title="Automated decisioning with legal effect",
        rationale=(
            "Automated or algorithmic decisions that produce a legal or similarly "
            "significant effect on a person raise DPDP and consumer-protection exposure "
            "that a template cannot safely resolve."
        ),
        keywords=("automated decisioning", "automated decision-making", "algorithmic decision", "automated eligibility"),
        flags=("automated_decisioning",),
    ),
)

AMBER_RISK_VECTORS: tuple[RiskVector, ...] = (
    RiskVector(
        id="employment_persons",
        lane=Lane.AMBER,
        title="Employment of persons",
        rationale=(
            "Employing staff attaches statutory-benefit, working-hours and shops-and-"
            "establishments obligations that a lawyer should confirm before signature."
        ),
        keywords=("hiring employees", "full-time employees", "salaried staff", "employment agreement"),
        flags=("employs_persons",),
    ),
    RiskVector(
        id="contract_labour",
        lane=Lane.AMBER,
        title="Contract labour",
        rationale=(
            "Engaging contract labour above the state threshold requires principal-employer "
            "registration and contractor licensing that vary by state."
        ),
        keywords=("contract labour", "contract labor", "gig workers", "staffing agency"),
        flags=("engages_contract_labour",),
    ),
    RiskVector(
        id="consumer_commerce",
        lane=Lane.AMBER,
        title="Consumer-facing commerce",
        rationale=(
            "Selling directly to consumers attaches consumer-protection, returns and "
            "grievance-redressal duties that should be reviewed before launch."
        ),
        keywords=("consumer facing", "direct to consumer", "sell to consumers", "d2c commerce"),
        flags=("sells_to_consumers",),
    ),
    RiskVector(
        id="user_generated_content",
        lane=Lane.AMBER,
        title="User-generated content / intermediary posture",
        rationale=(
            "Hosting user-generated content raises an intermediary/safe-harbour posture "
            "and content-moderation due-diligence question under the IT Act framework."
        ),
        keywords=("user generated content", "user-generated content", "community forum", "content moderation"),
        flags=("user_generated_content",),
    ),
    RiskVector(
        id="ip_assignment_prior_employment",
        lane=Lane.AMBER,
        title="IP assignment where prior employment or university IP may be involved",
        rationale=(
            "IP built during a founder's prior employment or as a university project may "
            "already belong to someone else; assignment language should be reviewed before "
            "it is relied on as clean title."
        ),
        keywords=("prior employer ip", "university ip", "student project ip", "built during previous job", "moonlighting"),
    ),
    RiskVector(
        id="equity_vesting_acceleration",
        lane=Lane.AMBER,
        title="Equity vesting with acceleration",
        rationale=(
            "Single- or double-trigger acceleration clauses interact with tax and "
            "securities treatment and should be reviewed before signature."
        ),
        keywords=("vesting acceleration", "accelerated vesting", "double trigger", "single trigger acceleration"),
        flags=("equity_vesting_acceleration",),
    ),
)

ALL_RISK_VECTORS: tuple[RiskVector, ...] = RED_RISK_VECTORS + AMBER_RISK_VECTORS

MULTI_STATE_SIGNAL_ID = "multi_state_gateway"
UNDER_SPECIFIED_SIGNAL_ID = "under_specified_assessment"

# Concrete questions to put to a lawyer, keyed by signal id. A vector without
# an entry here still gets a generic fallback question built from its title.
COUNSEL_QUESTIONS: dict[str, str] = {
    "payment_escrow": (
        "Confirm whether routing customer funds through a nodal/escrow arrangement makes "
        "us a payment aggregator requiring authorisation."
    ),
    "lending_or_credit": "Confirm whether the credit or lending activity requires NBFC or other RBI authorisation.",
    "insurance_distribution": "Confirm whether distributing or underwriting insurance requires IRDAI registration.",
    "securities_or_investment": "Confirm whether the cap table, convertible instruments or advisory activity trigger securities regulation.",
    "virtual_digital_assets": "Confirm the regulatory and tax treatment of virtual digital assets, gaming or wagering features.",
    "cross_border_data": "Confirm whether the data flows require a cross-border transfer mechanism or trigger data localisation duties.",
    "childrens_data": "Confirm the heightened consent and processing restrictions applicable to children's personal data.",
    "health_data": "Confirm the additional safeguards required for health data, including telemedicine/EHR-specific duties.",
    "biometric_data": "Confirm the consent, storage and KYC requirements attached to biometric or Aadhaar-based identity data.",
    "foreign_investment_fema": "Confirm whether the foreign investment or remittance flows require FEMA reporting or sectoral approval.",
    "government_contracting": "Confirm the procurement-specific eligibility and compliance requirements for government contracting.",
    "automated_decisioning": "Confirm whether the automated decision requires a human-review path under applicable law.",
    "employment_persons": "Confirm the employment-contract and statutory-benefit obligations attaching to the declared hiring.",
    "contract_labour": "Confirm principal-employer registration and contractor-licensing thresholds for the contract labour arrangement.",
    "consumer_commerce": "Confirm consumer-protection, returns and grievance-redressal obligations for direct-to-consumer sales.",
    "user_generated_content": "Confirm the intermediary/safe-harbour posture and moderation duties for user-generated content.",
    "ip_assignment_prior_employment": "Confirm that IP assignment does not conflict with a founder's prior employer's or university's IP claims.",
    "equity_vesting_acceleration": "Confirm that vesting-acceleration triggers do not create unintended tax or securities consequences.",
    MULTI_STATE_SIGNAL_ID: "Confirm separate state registrations, professional tax and labour-welfare-fund enrolments for each state of operation.",
    UNDER_SPECIFIED_SIGNAL_ID: "Confirm the specific activities and jurisdictions involved before relying on this assessment for drafting.",
}


def _compile_keyword_pattern(keywords: tuple[str, ...]) -> re.Pattern[str] | None:
    if not keywords:
        return None
    alternatives = sorted((re.escape(k) for k in keywords), key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(alternatives) + r")\b", re.IGNORECASE)


_KEYWORD_PATTERNS: dict[str, re.Pattern[str] | None] = {
    vector.id: _compile_keyword_pattern(vector.keywords) for vector in ALL_RISK_VECTORS
}


def _matched_keywords(vector: RiskVector, text: str) -> list[str]:
    pattern = _KEYWORD_PATTERNS.get(vector.id)
    if pattern is None:
        return []
    seen: list[str] = []
    for m in pattern.finditer(text):
        hit = m.group(0).lower()
        if hit not in seen:
            seen.append(hit)
    return seen


def _counsel_question(signal_id: str, title: str) -> str:
    return COUNSEL_QUESTIONS.get(signal_id, f"Confirm the legal treatment of: {title}.")


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


@dataclass
class TrafficLightVerdict:
    lane: Lane
    headline: str
    automation_permitted: bool
    green: list[TrafficLightSignal] = field(default_factory=list)
    amber: list[TrafficLightSignal] = field(default_factory=list)
    red: list[TrafficLightSignal] = field(default_factory=list)
    mandatory_counsel_notice: str | None = None
    counsel_brief: list[str] = field(default_factory=list)

    def to_model(self) -> TrafficLightVerdictModel:
        return TrafficLightVerdictModel(
            lane=self.lane,
            headline=self.headline,
            automation_permitted=self.automation_permitted,
            green_lane=self.green,
            amber_lane=self.amber,
            red_lane=self.red,
            mandatory_counsel_notice=self.mandatory_counsel_notice,
            counsel_brief=self.counsel_brief,
        )

    def render_markdown(self) -> str:
        lines: list[str] = [
            "## Traffic-Light Evaluation Map",
            "",
            f"**Overall lane:** {self.lane.value} — {self.headline}",
            "",
            "| Lane | Signal | Why |",
            "|---|---|---|",
        ]
        for bucket in (self.red, self.amber, self.green):
            for signal in bucket:
                why = signal.rationale.replace("\n", " ").replace("|", "/")
                lines.append(f"| {signal.lane.value} | {signal.title} | {why} |")
        lines.append("")
        if not self.automation_permitted:
            lines.append("### Halt & Retain Counsel")
            lines.append("")
            lines.append(self.mandatory_counsel_notice or "Automation halted.")
            lines.append("")
        if self.counsel_brief:
            lines.append("### Counsel Brief")
            lines.append("")
            for i, question in enumerate(self.counsel_brief, start=1):
                lines.append(f"{i}. {question}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Matrix
# ---------------------------------------------------------------------------

_LANE_RANK: dict[Lane, int] = {Lane.GREEN: 0, Lane.AMBER: 1, Lane.RED: 2}


def _iter_grounding_instruments(grounding: dict) -> list[dict]:
    """Flatten every instrument out of a grounding bundle, union and state alike.

    Accepts both the single-state shape produced directly by
    ``JurisdictionRegistry.build_grounding_payload`` (a ``"state"`` key) and the
    multi-state shape produced by ``app.compliance.audit.build_grounding_bundle``
    (a ``"states"`` list) — the two blocks are still never merged into each
    other, only flattened for iteration here.
    """
    instruments: list[dict] = []
    union = grounding.get("union") or {}
    instruments.extend(union.get("instruments", []) or [])
    single_state = grounding.get("state")
    if single_state:
        instruments.extend(single_state.get("instruments", []) or [])
    for state in grounding.get("states", []) or []:
        instruments.extend(state.get("instruments", []) or [])
    return instruments


class TrafficLightMatrix:
    """Evaluates declared and described activity into a traffic-light verdict."""

    def evaluate(
        self,
        *,
        business_concept: str,
        industry_vertical: str,
        activity_flags: set[str],
        jurisdiction_codes: list[str],
        framework_type: str | None = None,
        grounding: dict | None = None,
    ) -> TrafficLightVerdict:
        red: list[TrafficLightSignal] = []
        amber: list[TrafficLightSignal] = []
        green: list[TrafficLightSignal] = []
        brief: list[str] = []
        seen_ids: set[str] = set()

        concept = business_concept or ""
        vertical = industry_vertical or ""
        scan_text = f"{concept} {vertical}"
        declared = {str(f) for f in (activity_flags or set())}

        def _add(vector_or_id: str, lane: Lane, title: str, rationale: str, matched_on: list[str],
                  instrument_refs: list[str] | None = None) -> None:
            if vector_or_id in seen_ids:
                return
            seen_ids.add(vector_or_id)
            signal = TrafficLightSignal(
                id=vector_or_id,
                lane=lane,
                title=title,
                rationale=rationale,
                matched_on=matched_on,
                instrument_refs=instrument_refs or [],
            )
            bucket = red if lane == Lane.RED else amber if lane == Lane.AMBER else green
            bucket.append(signal)
            brief.append(_counsel_question(vector_or_id, title))

        # -- multi-state isolation rule --------------------------------------
        unique_states = []
        for code in jurisdiction_codes or []:
            if code not in unique_states:
                unique_states.append(code)
        if len(unique_states) > 1:
            _add(
                MULTI_STATE_SIGNAL_ID,
                Lane.RED,
                "Multi-state operations",
                (
                    "Operating in more than one state ("
                    + ", ".join(unique_states)
                    + ") means state registrations, professional tax and welfare-fund "
                    "enrolments do not travel across state lines and must each be secured "
                    "separately."
                ),
                matched_on=list(unique_states),
            )

        # -- declared-flag and keyword channels -------------------------------
        for vector in ALL_RISK_VECTORS:
            matched_flags = sorted(set(vector.flags) & declared)
            matched_keywords = _matched_keywords(vector, scan_text)
            if matched_flags:
                _add(
                    vector.id,
                    vector.lane,
                    vector.title,
                    vector.rationale,
                    matched_on=matched_flags + matched_keywords,
                )
            elif matched_keywords:
                _add(
                    vector.id,
                    vector.lane,
                    vector.title,
                    (
                        f"{vector.rationale} This risk was inferred from the description "
                        f"(matched: {', '.join(matched_keywords)}) rather than a declared "
                        "activity flag, and must be confirmed before relying on it."
                    ),
                    matched_on=matched_keywords,
                )

        # -- grounding-sourced obligations ------------------------------------
        if grounding:
            for instrument in _iter_grounding_instruments(grounding):
                # An instrument only escalates the lane when the caller's declared
                # activity actually triggers it. Without this, an unfiltered
                # grounding bundle (no flags declared) would fold the entire union
                # catalogue in and every request would come out RED — which is not
                # fail-closed, it is fail-useless. Under-declaration is caught
                # separately by the under-specified AMBER signal below.
                applies = set(instrument.get("applies_when") or ())
                if applies and "any_entity" not in applies and not (applies & activity_flags):
                    continue
                instrument_id = instrument.get("id", "unknown-instrument")
                for obligation in instrument.get("obligations", []) or []:
                    # An obligation may narrow its parent instrument's trigger.
                    # The Income-tax Act applies to any entity; its ESOP duty does
                    # not apply to a venture with no equity instrument in scope.
                    ob_applies = set(obligation.get("applies_when") or ())
                    if ob_applies and not (ob_applies & activity_flags):
                        continue
                    lane_str = str(obligation.get("lane", "AMBER")).upper()
                    if lane_str not in ("RED", "AMBER"):
                        continue
                    lane = Lane.RED if lane_str == "RED" else Lane.AMBER
                    key = obligation.get("key", "obligation")
                    signal_id = f"{instrument_id}:{key}"
                    title = f"{instrument.get('title', instrument_id)} — {key.replace('_', ' ')}"
                    _add(
                        signal_id,
                        lane,
                        title,
                        obligation.get("summary", ""),
                        matched_on=[],
                        instrument_refs=[instrument_id],
                    )

        # -- fail-closed: under-specified assessment --------------------------
        # A near-empty concept is always under-specified, framework or not. A
        # non-trivial concept declaring zero activity flags is only treated as
        # under-specified when no framework_type was chosen either — choosing a
        # concrete document framework (mutual NDA, incorporation outline, ...)
        # is itself enough specification for a GREEN-lane request; an
        # open-ended audit of a concept with no declared flags at all is not.
        word_count = len(concept.strip().split())
        is_trivial_concept = word_count < 4
        is_unscoped_and_unflagged = not declared and word_count >= 4 and framework_type is None
        if is_trivial_concept or is_unscoped_and_unflagged:
            _add(
                UNDER_SPECIFIED_SIGNAL_ID,
                Lane.AMBER,
                "Under-specified assessment",
                (
                    "The business concept is empty, too short, or declares no activity flags "
                    "at all. Legafy fails closed rather than guessing: treat this assessment "
                    "as incomplete until the concept and flags are confirmed."
                ),
                matched_on=[],
            )

        # -- default green lane ------------------------------------------------
        if not red and not amber:
            headline_suffix = f" for a {framework_type}" if framework_type else ""
            _add(
                "standard_automation_lane",
                Lane.GREEN,
                "Standard automated lane",
                (
                    f"No high-risk activity indicators were declared or detected{headline_suffix}. "
                    "Automated drafting is permitted for standard structures (mutual NDAs, basic "
                    "incorporation outlines, standard internal policy skeletons, plain consulting "
                    "agreements with no data or funds handling)."
                ),
                matched_on=[],
            )

        overall_lane = max((s.lane for s in (*red, *amber, *green)), key=lambda lane: _LANE_RANK[lane], default=Lane.GREEN)
        automation_permitted = overall_lane != Lane.RED

        mandatory_counsel_notice: str | None = None
        if not automation_permitted:
            titles = ", ".join(s.title for s in red) or "an undeclared high-risk activity"
            mandatory_counsel_notice = (
                "Automated drafting is halted. The following trigger(s) require a "
                f"jurisdiction-qualified lawyer before any drafting, signature or filing "
                f"proceeds: {titles}. This tool produces pre-counsel scaffolding only and "
                "does not create an attorney-client relationship."
            )

        if overall_lane == Lane.RED:
            headline = "Halt & Retain Counsel — automation refused pending legal review."
        elif overall_lane == Lane.AMBER:
            headline = "Proceed with a recorded caveat — human review required before signature."
        else:
            headline = "Automated lane permitted."

        return TrafficLightVerdict(
            lane=overall_lane,
            headline=headline,
            automation_permitted=automation_permitted,
            green=green,
            amber=amber,
            red=red,
            mandatory_counsel_notice=mandatory_counsel_notice,
            counsel_brief=brief,
        )


TRAFFIC_LIGHT = TrafficLightMatrix()


def suggest_activity_flags(
    business_concept: str, industry_vertical: str = "", *, declared: set[str] | None = None
) -> list[dict[str, object]]:
    """Which activity flags the wording implies but the caller has not declared.

    The keyword scan that raises advisory risk signals already knows which
    vectors a description touches, and every vector names the declared flags
    that authoritatively trigger it. That mapping was previously used in one
    direction only. Running it the other way turns free text back into the
    vocabulary the grounding matrix filters on, which is what a caller needs
    to make its *second* call sharp.

    This is a suggestion channel and nothing more. It never sets a flag, never
    filters an obligation and never moves a lane — an undeclared duty is shown,
    not hidden, so a wrong guess here costs noise rather than a missed filing.
    """
    already = declared or set()
    scan_text = f"{business_concept or ''} {industry_vertical or ''}"
    found: dict[str, list[str]] = {}
    for vector in ALL_RISK_VECTORS:
        matched = _matched_keywords(vector, scan_text)
        if not matched:
            continue
        for flag in vector.flags:
            if flag in already:
                continue
            found.setdefault(flag, [])
            for phrase in matched:
                if phrase not in found[flag]:
                    found[flag].append(phrase)
    return [
        {"flag": flag, "matched_on": phrases}
        for flag, phrases in sorted(found.items())
    ]
