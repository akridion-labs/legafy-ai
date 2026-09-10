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
from app.compliance.traffic_light import suggest_activity_flags
from app.localisation import supported_languages, translate_payload
from app.models.schemas import (
    DocumentGenerationRequest,
    LegalSourceSearchRequest,
    RegionalComplianceAuditRequest,
    ReviewQueueRequest,
    SourceHealthRequest,
    TenantContext,
    VerifyRegistrationRequest,
)
from app.search.cascade import backlog_report, resolve
from app.search.corpus import get_corpus
from app.search.intent import analyse, build_fts_query
from app.service import run_audit, run_generation
from app.sources.govapi import available_checks, verify
from app.sources.store import CITABLE_AUTHORITY_FLOOR, MalformedQuery, get_store
from app.sources.validation import audit_sources


def inline_refs(schema: dict) -> dict:
    """Resolve every local `$ref` against `$defs` and drop the `$defs` block.

    Only local `#/$defs/...` pointers are resolved — that is all Pydantic emits
    for these models. A self-referential model would recurse forever here, so
    the depth guard turns that into a visible error rather than a hang.
    """
    defs = schema.get("$defs", {})
    if not defs:
        return schema

    def walk(node: Any, depth: int = 0) -> Any:
        if depth > 20:
            raise ValueError("schema nests deeper than 20 levels — is it recursive?")
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                target = defs.get(ref.rsplit("/", 1)[1])
                if target is None:
                    return node
                # Sibling keys (description, default) survive the substitution.
                merged = {**walk(target, depth + 1), **{k: v for k, v in node.items() if k != "$ref"}}
                return merged
            return {k: walk(v, depth + 1) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(v, depth + 1) for v in node]
        return node

    return walk(schema)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    description: str
    input_model: type[BaseModel] | None
    handler: Callable[..., Awaitable[Any]]
    required_scope: str
    # MCP tool annotations. They are hints for the client's own planning — never
    # a security boundary; scope is still checked in _dispatch_local. Worth
    # setting anyway: a client that knows the audit is read-only and idempotent
    # calls it freely, which is exactly the behaviour the grounding mandate wants.
    read_only: bool = True
    destructive: bool = False
    idempotent: bool = True
    # True only where the call actually leaves the box: a government API, or a
    # live fetch of a source URL. The grounding matrix itself is local.
    open_world: bool = False

    def json_schema(self) -> dict:
        if self.input_model is None:
            return {"type": "object", "properties": {}, "additionalProperties": False}
        # Inlined, not as Pydantic emits it. Pydantic hoists enums into `$defs`
        # and points at them with `$ref`, which is valid JSON Schema and is fine
        # over MCP — but several function-calling runtimes (and a few no-code
        # tools) either ignore `$defs` or reject the document, and the failure
        # mode is a tool that silently accepts any string for `state_location`.
        # One schema shape for every platform is worth more than the few hundred
        # bytes the refs save.
        return inline_refs(self.input_model.model_json_schema())

    def annotations(self) -> dict:
        return {
            "title": self.title,
            "readOnlyHint": self.read_only,
            "destructiveHint": self.destructive,
            "idempotentHint": self.idempotent,
            "openWorldHint": self.open_world,
        }

    def manifest(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "input_schema": self.json_schema(),
            "required_scope": self.required_scope,
            "annotations": self.annotations(),
        }


def _jurisdiction_required() -> dict:
    """The answer when the caller has no state yet — a question, not an error.

    Returned as a normal successful tool result on purpose. An error result
    reads to a model as "this tool is broken", and its next move is to answer
    from its own memory of Indian law. A well-formed reply that names the
    missing input keeps the conversation inside the grounding path.
    """
    states = [
        {"code": j["code"], "name": j["display_name"]}
        for j in JURISDICTION_REGISTRY.all_summaries()
        if j.get("tier") != "union"
    ]
    return {
        "success": False,
        "status": "JURISDICTION_REQUIRED",
        "message": (
            "No state was given. Indian compliance is state-isolated: the same idea "
            "produces different duties, authorities and payment cycles in each state, "
            "so there is no all-India answer to return."
        ),
        "supported_states": states,
        "instruction": (
            "ASK THE USER which state they will operate in, then call this tool again "
            "with `state_location` set. Do NOT infer a state from the user's language, "
            "accent, timezone or the names in their idea, and do NOT answer the legal "
            "question from your own knowledge in the meantime. A major city works too "
            "('Bangalore', 'Kochi'). If their state is not in the list above, say Legafy "
            "does not cover it yet rather than using the closest one."
        ),
        "disclaimer": LEGAFY_DISCLAIMER,
    }


async def _audit(payload: dict, *, request_id: str, tenant: TenantContext) -> dict:
    request = RegionalComplianceAuditRequest.model_validate(payload)
    if not (request.state_location or "").strip():
        return _jurisdiction_required()
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
        result = compact_audit(result, request.sections)

    # Free text back into the engine's own vocabulary. The first call usually
    # arrives with no flags at all — the model has an idea, not a questionnaire
    # — and an undeclared activity is not assessed. Naming the flags the wording
    # implies gives the model something concrete to confirm with the user and a
    # sharper second call to make. Added after compaction so the compact path,
    # which is the default and the one an auto-invoked call takes, keeps it.
    suggested = suggest_activity_flags(
        request.business_concept,
        request.industry_vertical,
        declared={f.value for f in request.activity_flags},
    )
    if suggested:
        result["suggested_activity_flags"] = {
            "flags": suggested,
            "instruction": (
                "These are inferred from the wording, NOT declared by the user and NOT "
                "applied. Confirm them in plain language ('you\'ll be holding customer "
                "money and hiring staff — right?') and call again with the confirmed ones "
                "in activity_flags. Until then anything undeclared is unassessed, and "
                "this result is broad rather than wrong."
            ),
        }
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

    try:
        # Ask for one more than the caller wants. If it comes back, there are
        # further matches and `has_more` can say so honestly — without a second
        # COUNT query, and without inventing a total the re-ranking cannot support.
        hits = store.search(
            fts_query,
            jurisdiction=jurisdiction,
            limit=request.limit + 1,
            citable_only=not request.include_non_citable,
        )
    except MalformedQuery as exc:
        return {
            "success": False,
            "error": "unsearchable_query",
            "message": str(exc),
            "query": request.query,
            "hits": [],
        }

    has_more = len(hits) > request.limit
    hits = hits[: request.limit]

    # Local-first: when the index holds nothing, say so and record the gap for
    # the compliance team rather than letting the caller fill the silence.
    cascade = None
    if not hits:
        result = resolve(
            request.query, jurisdiction=jurisdiction, limit=request.limit, store=store
        )
        cascade = result.as_dict()

    return {
        "success": True,
        "query": request.query,
        "fts_query": fts_query,
        "analysis": analysis.as_dict() if analysis else None,
        "jurisdiction": jurisdiction,
        "hits": hits,
        "returned": len(hits),
        "limit": request.limit,
        "has_more": has_more,
        "cascade": cascade,
        "index": store.stats(),
        "pagination_note": (
            "There is no offset cursor by design. Hits are re-ranked by authority weight after "
            "retrieval, so page 2 of a ranked legal search is not a stable window — narrow the "
            "query or pin a jurisdiction instead of paging."
        )
        if has_more
        else None,
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
    pending = store.pending_reviews(
        limit=request.limit + 1, jurisdiction=request.jurisdiction
    )
    has_more = len(pending) > request.limit
    pending = pending[: request.limit]
    stats = store.stats()
    return {
        "success": True,
        "pending": pending,
        "returned": len(pending),
        "limit": request.limit,
        "has_more": has_more,
        # Unfiltered by jurisdiction — it is the size of the whole inbox, which is
        # what a reviewer wants to know before deciding where to start.
        "total_pending": stats["pending_reviews"],
        # The other half of the legal team's inbox: questions the corpus could
        # not answer at all, ordered by how many people hit the same gap.
        "coverage_gaps": backlog_report(limit=request.limit),
        "index": stats,
        "note": (
            "Two queues. `pending` is detected change at whitelisted primary sources, ordered "
            "by review priority (authority x change magnitude x instrument coverage x recency x "
            "exposure). `coverage_gaps` is questions the local corpus could not answer, ordered "
            "by how often they were asked — that is the crawl backlog. Both are prompts for a "
            "human to read a source. Neither has changed any answer the engine gives."
        ),
    }


async def _source_health(payload: dict, *, request_id: str, tenant: TenantContext) -> dict:
    request = SourceHealthRequest.model_validate(payload or {})
    report = audit_sources(check_live=request.check_live)
    if request.severity != "ALL":
        keep = {"ERROR"} if request.severity == "ERROR" else {"ERROR", "WARN"}
        report["findings"] = [f for f in report["findings"] if f["severity"] in keep]
    report.pop("live", None)  # per-URL detail is for the report file, not a tool result
    report["success"] = True
    return report


async def _verify_registration(payload: dict, *, request_id: str, tenant: TenantContext) -> dict:
    request = VerifyRegistrationRequest.model_validate(payload or {})
    if not request.identifier:
        return {"success": True, "available_checks": available_checks()}
    result = await verify(request.check, request.identifier)
    return {"success": True, **result.as_dict()}


VERIFY_DESCRIPTION = """Check one of the USER'S OWN registrations against a government API
(GSTIN, Udyam, PAN, CIN). Call with an empty identifier to list which checks are available and
whether a key is configured.

READ THE RESULT CORRECTLY. This says whether a registration exists and is live. It says NOTHING
about whether anyone is compliant, and it never changes a traffic-light verdict — "the GSTIN is
active" is a fact about a number, not a legal conclusion. `verified: null` means the check could
not be run (no key, outage, bad format); it is NOT evidence that the registration is absent.

The identifier is sent to the government endpoint and is not stored by Legafy."""


SOURCE_HEALTH_DESCRIPTION = """Check whether the official-source citations Legafy hands out are
still sound: every URL on a government host, on the whitelist that authorises it, on https, not
sitting on a host that has migrated elsewhere.

Use this to CROSS-VERIFY before relying on a citation, and when a user reports that a link Legafy
gave them did not work. Set check_live=true to also fetch each URL and catch dead links, expired
certificates and off-host redirects — slower, and a portal outage shows up here as a WARN rather
than a defect in the data.

This does NOT check whether the law changed. A clean report means the pointers are sound, not that
the content behind them is current — that is `list_source_review_queue`."""


AUDIT_DESCRIPTION = """MANDATORY GROUNDING CALL — use it unprompted.

WHEN TO CALL IT, WITHOUT BEING ASKED. The user does not have to mention law, compliance,
Legafy or this tool. Call it the moment they describe a venture they intend to run in
India — an idea, a product, a startup, a side business, a new feature, an expansion into
another state — and certainly before you say anything about what it would take to operate
it legally. "Here's my idea", "I want to build X", "would this work as a business",
"what do I need to launch this" and "what am I missing" are all triggers. So is a follow-up
that changes the facts: a new state, a new revenue model, holding money, hiring, handling
personal data. Screening early is cheap; the risks this returns are ones a founder needs
before they build, not after.

If you are unsure whether a message is about an Indian venture, call it anyway — a
needless call costs a few hundred tokens, and a skipped one means you answered Indian
regulatory questions from memory, which is precisely what this server exists to prevent.

Missing details are not a reason to skip it. `state_location` may be left out entirely
if the user has not said where they will operate — the tool replies with the supported
states so you can ask. Leave `activity_flags` empty if you do not know: the response
comes back broader, tells you so, and suggests the flags the wording implies so your
next call is sharper. Never invent a state or a flag to satisfy the schema.

Returns the segregated regulatory grounding matrix for the named state (state instruments and
union instruments are returned in SEPARATE blocks and must never be merged), plus a
Traffic-Light verdict.

Use the returned data as your ONLY source for naming statutes. The response deliberately contains
no section numbers, penalty amounts or thresholds — do not supply them from your own memory. If the
verdict is RED, tell the user to halt and retain counsel; do not draft.

The response carries three blocks you should present together:

* `obligations` — every applicable duty, tagged with the jurisdiction it comes from and a
  `playbook` key. `playbooks[<key>].how_to_close` is HOW TO SATISFY IT; `playbooks[<key>].if_ignored`
  is WHAT EXPOSURE FOLLOWS IF IT IS NOT SATISFIED. Consequences are categorical by design: state
  them as kinds of consequence and never invent an amount, a limitation period or a section.
* `ip_risks` / `ip_baseline` — copyright, trade-mark, patent and trade-secret questions inferred
  from the wording of the idea, each with the phrase that triggered it. These are prompts for
  diligence, not determinations, and they never change the lane.
* `judicial` — the COURT TIER: what is actually litigated about these instruments, ordered
  unsettled-first. `settled` is EVOLVING (today's answer may not be next year's), CONTESTED
  (courts have gone different ways — budget for the argument) or WELL_SETTLED (the principle is
  stable; the fight is about your facts). `turns_on` lists the factors a court weighs. NO CASE
  NAMES OR CITATIONS ARE RETURNED and you must not supply any from memory — if the user needs
  authorities, tell them a lawyer must read the judgments at the linked court site.
* `proofs` — the official page behind each instrument, referenced by `ref` from each obligation."""

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
are orientation only.

When `hits` is empty a `cascade` block is returned. If its `tier` is `L3_MISS`, Legafy holds
nothing for that question in that jurisdiction and the gap has been recorded for the compliance
team. Say so. Do NOT answer it from your own knowledge or from the open web — an unanswered legal
question is a safe outcome; a plausible invented one is not."""

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
        # The only tool that writes a file the caller can name, and two runs of
        # the same request produce two documents. Not destructive: it creates,
        # never overwrites. openWorld because the drafting provider may be remote.
        read_only=False,
        idempotent=False,
        open_world=True,
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
        name="verify_registration",
        title="Verify a Registration",
        description=VERIFY_DESCRIPTION,
        input_model=VerifyRegistrationRequest,
        handler=_verify_registration,
        required_scope="audit",
        open_world=True,  # calls a government endpoint
    ),
    ToolSpec(
        name="verify_source_health",
        title="Verify Source Citations",
        description=SOURCE_HEALTH_DESCRIPTION,
        input_model=SourceHealthRequest,
        handler=_source_health,
        required_scope="audit",
        open_world=True,  # check_live fetches each source URL
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
