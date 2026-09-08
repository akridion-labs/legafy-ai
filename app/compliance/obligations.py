"""The legal-obligation ledger and the IP / copyright screen.

What this answers
-----------------
A founder searching an idea does not want a list of Act names. They want three
sentences per duty:

1. **What am I obliged to do?**      -> ``duty``  (from the jurisdiction data)
2. **How do I get this off my desk?** -> ``how_to_close`` (domain playbook)
3. **What happens if I don't?**       -> ``if_ignored``   (domain playbook)

Why exposure is categorical, never numeric
------------------------------------------
Invariant #1 of this repo is that no fine, threshold or section number exists
unless a human verified it from a whitelisted primary source. So this module
never says "you will be fined X". It names the *kind* of consequence — filing
refused, registration cancelled, contract unenforceable, personal liability of
directors, transaction unwound at diligence — which is the part that actually
changes a founder's decision, and the part that is stable across amendments.
``quantum`` stays ``NOT_VERIFIED`` until the legal team populates
``penalty_schedule`` in the jurisdiction file.

Why playbooks are keyed by domain, not per obligation
-----------------------------------------------------
Token economy, and honesty. Thirty obligations across seven domains produce
seven playbooks, referenced by key, instead of thirty near-identical paragraphs
of prose. It also means a legal reviewer edits one playbook, not thirty copies,
and a per-obligation override in the jurisdiction JSON (``how_to_close`` /
``if_ignored`` on the obligation) always wins.

The IP screen
-------------
Copyright, trade mark, patent and trade-secret exposure is almost never
declared by a founder as an activity flag — it is implicit in the sentence they
typed ("Spotify for regional podcasts", "we scrape court judgments", "built on
an open-source model"). So this channel is *inferential and labelled as such*:
every finding carries the phrase that triggered it, and no finding ever moves
the traffic light on its own. It raises questions to a lawyer; it does not
answer them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

QUANTUM_NOTE = (
    "Consequences below are categorical, not quantified. Legafy does not state "
    "penalty amounts, limitation periods or section numbers unless a reviewer has "
    "verified them from the primary source linked against the instrument."
)


@dataclass(frozen=True)
class Playbook:
    how_to_close: tuple[str, ...]
    if_ignored: tuple[str, ...]


# One entry per instrument domain used in data/jurisdictions/*.json.
DOMAIN_PLAYBOOK: dict[str, Playbook] = {
    "corporate_structure": Playbook(
        how_to_close=(
            "Fix the entity type before anyone is paid or issued equity — converting later "
            "re-opens every agreement signed under the old form.",
            "Run incorporation and every subsequent allotment through the registry portal, "
            "and keep the filing acknowledgements with the cap table.",
            "Maintain statutory registers and minutes from day one; reconstructing them "
            "retrospectively is what diligence finds.",
        ),
        if_ignored=(
            "Filings rejected or taken on record late, leaving the cap table unprovable.",
            "Personal liability of promoters and directors for acts done in an unregistered "
            "or wrongly constituted entity.",
            "Investment diligence stalls: an unclean allotment history is a standard reason "
            "for a term sheet to be re-priced or withdrawn.",
        ),
    ),
    "business_registration": Playbook(
        how_to_close=(
            "Register the establishment with the state department for the address you "
            "actually operate from, including a co-working desk.",
            "Display the registration and renew on its own cycle — this is a state clock, "
            "not the union one.",
        ),
        if_ignored=(
            "Inspection findings and closure or sealing action against the premises.",
            "Registration refused later, when a licence, tender or bank account depends on it.",
        ),
    ),
    "labour": Playbook(
        how_to_close=(
            "Classify every worker honestly as employee or contractor before the first "
            "payment; the label on the invoice does not decide it.",
            "Register with the social-security authorities once headcount crosses the "
            "applicable threshold, and enrol from that month rather than retrospectively.",
            "Constitute the workplace committees the moment the entity has a workplace, "
            "even a small one, and keep the appointment record.",
        ),
        if_ignored=(
            "Contributions recovered for the whole unregistered period, with interest and "
            "damages on the arrears.",
            "Misclassified contractors re-characterised as employees, converting a cost "
            "line into a backdated liability.",
            "Prosecution of the officer in default, and orders for reinstatement or "
            "compensation in individual disputes.",
            "Statutory complaints that cannot be defended where the mandatory committee or "
            "policy was never constituted.",
        ),
    ),
    "taxation": Playbook(
        how_to_close=(
            "Take the registration when the trigger is crossed — turnover, inter-state "
            "supply or a platform obligation — not at year end.",
            "Withhold at source on every payment that attracts it, including to founders "
            "and overseas vendors, and deposit within the cycle.",
            "Get equity, ESOP and convertible instruments valued at the time of issue; a "
            "retrospective valuation is not a defence.",
        ),
        if_ignored=(
            "Demand for the tax that should have been collected, plus interest, recovered "
            "from the business rather than the customer.",
            "Input credit denied to your own customers, which is a commercial problem "
            "before it is a legal one.",
            "Disallowance of expenses on which tax was not withheld, inflating taxable income.",
            "Registration suspended or cancelled, which stops invoicing entirely.",
        ),
    ),
    "data_protection": Playbook(
        how_to_close=(
            "Write down what personal data you collect, why, where it sits and who it goes "
            "to; the inventory is the precondition for every other duty here.",
            "Take consent that is specific and withdrawable, and keep the notice that was "
            "shown at the time it was taken.",
            "Put a processing agreement in place with every vendor that touches user data "
            "before you send them any.",
            "Name a grievance contact and actually answer, and have a breach-notification "
            "runbook written before you need it.",
        ),
        if_ignored=(
            "Regulatory inquiry and directions to stop the processing, which can mean "
            "switching off the feature that depends on it.",
            "Financial penalties assessed against the entity as a data fiduciary.",
            "Contractual breach of enterprise customers' data terms — usually the first "
            "consequence a B2B startup actually feels.",
            "For children's or health data, exposure attaches even where the processing "
            "was well-intentioned and consented to by the wrong person.",
        ),
    ),
    "intellectual_property": Playbook(
        how_to_close=(
            "Get a written, present-tense assignment of copyright and inventions from every "
            "founder, employee and contractor, signed before their work is merged.",
            "Clear the name against the trade-mark register and the company register before "
            "you print anything, and file in the classes you actually trade in.",
            "Keep a licence inventory for every third-party asset, dataset, model and "
            "open-source component, and record the licence terms next to it.",
            "Treat anything you would not publish as a trade secret: access control, "
            "confidentiality terms, exit checklist.",
        ),
        if_ignored=(
            "The company does not own its own product: without assignment, code and designs "
            "stay with the individual who made them, and a contractor can license them again.",
            "Injunction and takedown against the infringing feature, brand or dataset, which "
            "lands on the product rather than on a balance sheet.",
            "Rebrand forced by an opposition or a passing-off claim after the name is on "
            "contracts, invoices and app stores.",
            "Copyleft obligations propagating to your own source where an open-source "
            "component was linked without reading its licence.",
            "Diligence failure: unassigned IP is the single most common reason an acquisition "
            "is held in escrow or repriced.",
        ),
    ),
    "contract": Playbook(
        how_to_close=(
            "Write the deal down before work starts. An arrangement recorded only in chat "
            "is the one that gets disputed, and it is disputed at the worst moment.",
            "Pay the stamp duty of the state of execution at the time of execution — the rate "
            "differs by state for the same document, and it cannot be cured cheaply later.",
            "Drop foreign-template non-competes: a post-employment restraint is void in India "
            "to that extent. Protect with confidentiality, assignment and notice periods instead.",
            "Negotiate indemnity, liability cap and termination as three separate questions; "
            "they are the clauses that decide what a dispute costs.",
        ),
        if_ignored=(
            "An insufficiently stamped agreement is not admissible in evidence until the duty "
            "and a penalty are paid — a signed contract you cannot produce is not a contract.",
            "A restraint that is void does not merely fail; it leaves the departing person free "
            "while you believed you were protected.",
            "Unregistered instruments in the compulsorily registrable class do not affect the "
            "property at all, however clearly they were drafted.",
            "Unlimited liability by silence: with no cap, exposure is whatever the loss turns "
            "out to be.",
        ),
    ),
    "dispute_resolution": Playbook(
        how_to_close=(
            "Name the seat, the number of arbitrators, the appointing mechanism and the "
            "language in the clause itself. 'Arbitration in India' is not a clause.",
            "State the governing law and the seat separately — they are different choices with "
            "different consequences, especially across borders.",
            "Diarise the statutory notice window the moment a cheque is returned; the remedy "
            "is lost by silence, not by defeat.",
        ),
        if_ignored=(
            "A preliminary fight about how to fight, decided by a court, before the actual "
            "dispute is even heard.",
            "A cross-border award that cannot be enforced where the assets are.",
            "A dishonour remedy forfeited entirely because the notice went out a week late.",
        ),
    ),
    "consumer": Playbook(
        how_to_close=(
            "Say what the product does in the words the customer will use, and keep the "
            "advertised claim provable.",
            "Publish refund, cancellation and grievance terms and staff the grievance route.",
        ),
        if_ignored=(
            "Complaints before the consumer forum, where the standard is what the customer "
            "reasonably understood, not what the terms said.",
            "Directions to withdraw a claim or advertisement and to compensate a class of "
            "customers.",
        ),
    ),
    "cross_border": Playbook(
        how_to_close=(
            "Establish the route before money moves: reporting for inbound investment, and "
            "an authorised channel for outbound payments.",
            "File the event-based reports on their own clocks; these are not part of the "
            "annual accounts cycle.",
        ),
        if_ignored=(
            "Compounding proceedings for a contravention that is otherwise commercially "
            "ordinary, with the entity and its officers both in scope.",
            "Investment held to be irregular, which blocks the next round until it is "
            "regularised.",
        ),
    ),
    "general": Playbook(
        how_to_close=(
            "Identify the authority named against the instrument and read the obligation at "
            "the linked primary source before acting on it.",
        ),
        if_ignored=(
            "Regulatory action by the named authority. The specific consequence has not been "
            "verified for this instrument.",
        ),
    ),
}


def build_obligation_ledger(grounding: dict[str, Any]) -> dict[str, Any]:
    """Turn the grounding bundle into duty / remediation / exposure triples.

    Playbooks are emitted once and referenced by key, so a thirty-obligation
    response carries seven paragraphs rather than thirty.
    """
    obligations: list[dict[str, Any]] = []
    used_domains: set[str] = set()

    def harvest(block: dict[str, Any], tier: str) -> None:
        code = block.get("code", "")
        for instrument in block.get("instruments", []):
            domain = instrument.get("domain", "general")
            if domain not in DOMAIN_PLAYBOOK:
                domain = "general"
            for ob in instrument.get("obligations", []):
                used_domains.add(domain)
                entry: dict[str, Any] = {
                    "key": ob.get("key", ""),
                    "lane": str(ob.get("lane", "AMBER")).upper(),
                    "duty": ob.get("summary", ""),
                    "ref": instrument["id"],
                    "jurisdiction": code,
                    "tier": tier,
                    "playbook": domain,
                    "verify_at": instrument.get("citation_url", ""),
                    "quantum": instrument.get("penalty_status", "NOT_VERIFIED"),
                }
                # A reviewer's per-obligation text always beats the domain default.
                if ob.get("how_to_close"):
                    entry["how_to_close"] = ob["how_to_close"]
                if ob.get("if_ignored"):
                    entry["if_ignored"] = ob["if_ignored"]
                obligations.append(entry)

    harvest(grounding.get("union", {}), "union")
    for state in grounding.get("states", []):
        harvest(state, "state")

    order = {"RED": 0, "AMBER": 1, "GREEN": 2}
    obligations.sort(key=lambda o: (order.get(o["lane"], 1), o["jurisdiction"], o["key"]))

    return {
        "count": len(obligations),
        "by_lane": {
            lane: sum(1 for o in obligations if o["lane"] == lane)
            for lane in ("RED", "AMBER", "GREEN")
        },
        "obligations": obligations,
        "playbooks": {
            domain: {
                "how_to_close": list(DOMAIN_PLAYBOOK[domain].how_to_close),
                "if_ignored": list(DOMAIN_PLAYBOOK[domain].if_ignored),
            }
            for domain in sorted(used_domains)
        },
        "quantum_note": QUANTUM_NOTE,
    }


# ---------------------------------------------------------------------------
# IP / copyright screen
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class IPVector:
    id: str
    title: str
    lane: str
    question: str
    check: tuple[str, ...]
    if_ignored: str
    patterns: tuple[str, ...]


# Word-boundary patterns, matched against concept + vertical. Deliberately
# conservative: a missed vector is a question not asked, a false positive is a
# founder told to do a clearance search they did not strictly need.
IP_VECTORS: tuple[IPVector, ...] = (
    IPVector(
        id="ip.assignment",
        title="Ownership of what has already been built",
        lane="AMBER",
        question="Has every person who wrote code, drew a screen or named the product "
        "assigned that work to the company in writing?",
        check=(
            "Signed assignment from each founder, covering work done before incorporation.",
            "Assignment (not just an NDA) in every contractor and agency contract.",
            "Employment agreements with an inventions and works clause.",
        ),
        if_ignored="The company cannot prove it owns its own product. This is discovered at "
        "diligence, when the leverage is entirely with the buyer.",
        patterns=(
            r"\bfreelanc\w*", r"\bcontractor\b", r"\bagency\b", r"\boutsourc\w*",
            r"\bco-?founder", r"\bintern\b", r"\bbuilt by\b", r"\bdeveloper\b",
        ),
    ),
    IPVector(
        id="ip.brand_clearance",
        title="Name and brand clearance",
        lane="AMBER",
        question="Has the product name been cleared against the trade-mark register and "
        "existing traders in the same class?",
        check=(
            "Register search in the classes you will actually trade in.",
            "Company- and domain-name check for an existing trader with the same name.",
            "Decide before launch; a rebrand after contracts and app-store listings is "
            "expensive in a way a search is not.",
        ),
        if_ignored="Opposition or a passing-off claim forces a rebrand after the name is "
        "already on invoices, contracts and store listings.",
        patterns=(
            r"\bbrand\w*", r"\btrade\s?mark\w*", r"\btrademark\w*", r"\blogo\b",
            r"\bname(?:d|s)? (?:it|the (?:app|product|company))\b", r"\bapp store\b",
        ),
    ),
    IPVector(
        id="ip.third_party_content",
        title="Third-party content, data and scraping",
        lane="RED",
        question="Where does the content or dataset come from, and what does its licence or "
        "the source's terms of use actually permit?",
        check=(
            "Written licence or documented terms for every dataset, feed and media asset.",
            "Scraping: check the source's terms of use and access controls separately from "
            "whether the material is copyrightable.",
            "Aggregating or republishing third-party work needs a permission, not an "
            "attribution line.",
        ),
        if_ignored="Injunction and takedown against the feature the data feeds, plus a claim "
        "from the source. Removing the dataset later usually removes the product.",
        patterns=(
            r"\bscrap\w*", r"\bcrawl\w*", r"\baggregat\w*", r"\brepublish\w*",
            r"\bthird[- ]party (?:content|data|feed)", r"\bdataset\w*", r"\bweb data\b",
            r"\bcatalog\w*\b", r"\blyrics\b", r"\bstock (?:photo|image|footage)\w*",
            r"\bjudgment\w*", r"\bnews articles?\b",
        ),
    ),
    IPVector(
        id="ip.model_training",
        title="Training or fine-tuning on collected material",
        lane="RED",
        question="Was the training or fine-tuning corpus licensed for that use, and can you "
        "show where each part of it came from?",
        check=(
            "Provenance record for every corpus: source, licence, date, permitted use.",
            "Check the model weights' own licence — many restrict commercial or derivative use.",
            "Separate the question of input rights from output rights; they are not the same "
            "and both need an answer.",
        ),
        if_ignored="An unlicensed corpus contaminates every downstream model. The remedy "
        "sought is usually deletion of the model, not damages.",
        patterns=(
            r"\bfine[- ]?tun\w*", r"\btrain(?:ing|ed|s)? (?:a |our |the )?(?:model|llm|ai)",
            r"\bllm\b", r"\bfoundation model\b", r"\bembedding\w*", r"\bcorpus\b",
        ),
    ),
    IPVector(
        id="ip.open_source",
        title="Open-source licence obligations",
        lane="AMBER",
        question="Do any dependencies carry copyleft or attribution terms that reach your own "
        "source once you distribute or host the product?",
        check=(
            "Generate a dependency licence inventory and keep it in CI, not in a spreadsheet.",
            "Flag strong-copyleft and network-copyleft licences before they are linked in.",
            "Ship the attribution notices the permissive licences require.",
        ),
        if_ignored="A copyleft component can oblige you to release your own source, or force "
        "a re-architecture late, when the component is load-bearing.",
        patterns=(
            r"\bopen[- ]?source\b", r"\bgpl\b", r"\bagpl\b", r"\bapache 2", r"\bmit licen[cs]e",
            r"\bfork(?:ed|ing)?\b", r"\bself[- ]host\w*",
        ),
    ),
    IPVector(
        id="ip.clone_risk",
        title="Similarity to an existing product",
        lane="AMBER",
        question="Is the product described by reference to an existing one, and if so does the "
        "similarity extend past the idea to the expression?",
        check=(
            "Ideas and functionality are not protected; specific code, copy, screens, icons "
            "and databases are.",
            "Do not carry over UI copy, icon sets, schema or sample data from the reference "
            "product.",
            "Check whether the incumbent holds design registrations or patents in the feature "
            "you are copying.",
        ),
        if_ignored="A claim aimed at the parts you actually copied — screens, copy, schema — "
        "which is a product rewrite rather than a legal argument.",
        patterns=(
            r"\b(?:like|similar to|clone of|version of|alternative to) [A-Z][\w.]+",
            r"\buber for\b", r"\bnetflix for\b", r"\bspotify for\b", r"\bairbnb for\b",
        ),
    ),
    IPVector(
        id="ip.trade_secret",
        title="Confidential information and departing people",
        lane="AMBER",
        question="Is anything in the product confidential rather than registered, and is it "
        "protected as such?",
        check=(
            "Confidentiality terms in every founder, employee, contractor and pilot agreement.",
            "Access control that matches the sensitivity; an unrestricted repository is hard "
            "to call a secret afterwards.",
            "Exit checklist: revoke access, retrieve devices, confirm deletion in writing.",
        ),
        if_ignored="Once information is out, there is no register to fall back on — a trade "
        "secret that was not kept secret is generally not protectable at all.",
        patterns=(
            r"\bproprietary algorithm\w*", r"\btrade secret\w*", r"\bsecret sauce\b",
            r"\bconfidential\b", r"\bformula\b",
        ),
    ),
    IPVector(
        id="ip.ugc_takedown",
        title="User-generated content and intermediary conduct",
        lane="AMBER",
        question="If users upload material, is there a working notice-and-takedown route and "
        "a published grievance contact?",
        check=(
            "Publish terms that prohibit infringing uploads and reserve the right to remove.",
            "Operate an actual takedown route with recorded response times.",
            "Name a grievance officer and answer at that address.",
        ),
        if_ignored="Safe-harbour treatment as an intermediary depends on conduct. Lose it and "
        "the platform answers for what its users posted.",
        patterns=(
            r"\buser[- ]generated\b", r"\bupload\w*", r"\bmarketplace\b", r"\bcommunity\b",
            r"\buser (?:posts|content|videos|photos)", r"\bforum\b",
        ),
    ),
)

# Flags that make a vector applicable regardless of wording.
FLAG_TO_VECTOR: dict[str, str] = {
    "user_generated_content": "ip.ugc_takedown",
    "operates_digital_service": "ip.assignment",
}


def screen_ip(
    business_concept: str, industry_vertical: str = "", activity_flags: set[str] | None = None
) -> dict[str, Any]:
    """Infer IP and copyright exposure from how the idea was described.

    Every finding carries the phrase that triggered it. This channel is
    advisory by construction: it never moves the traffic light, because a
    keyword is evidence of a question worth asking, not of a breach.
    """
    haystack = f"{business_concept} {industry_vertical}"
    flags = activity_flags or set()
    forced = {FLAG_TO_VECTOR[f] for f in flags if f in FLAG_TO_VECTOR}

    findings: list[dict[str, Any]] = []
    for vector in IP_VECTORS:
        matched = sorted(
            {
                m.group(0).strip().lower()
                for pattern in vector.patterns
                for m in re.finditer(pattern, haystack, re.IGNORECASE)
            }
        )
        if not matched and vector.id not in forced:
            continue
        findings.append(
            {
                "id": vector.id,
                "title": vector.title,
                "lane": vector.lane,
                "question": vector.question,
                "check": list(vector.check),
                "if_ignored": vector.if_ignored,
                "matched_on": matched,
                "basis": "declared_flag" if not matched else "inferred_from_description",
            }
        )

    order = {"RED": 0, "AMBER": 1, "GREEN": 2}
    findings.sort(key=lambda f: order.get(f["lane"], 1))

    # Always returned, matched or not: these four are the ones every company gets
    # wrong, and their absence from the text is not evidence of their absence in
    # the business.
    baseline = [
        "Written IP assignment from every founder and contractor, signed and dated.",
        "Trade-mark clearance for the product name in the classes you trade in.",
        "Licence inventory for third-party datasets, media, models and dependencies.",
        "Confidentiality terms plus an access-revocation checklist for departures.",
    ]

    return {
        "findings": findings,
        "baseline_clearance": baseline,
        "channel": "INFERENTIAL",
        "note": (
            "Findings are inferred from the wording of the description and are prompts for "
            "diligence, not determinations. They do not change the traffic-light verdict. An "
            "IP clearance opinion requires a qualified practitioner and a search of the "
            "registers as they stand on the day."
        ),
    }
