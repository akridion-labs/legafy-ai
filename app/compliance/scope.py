"""The hard cap: what Legafy refuses to touch, enforced before anything else.

Legafy is a **pre-counsel corporate compliance** tool. It screens a business
idea against a state's regulatory code paths. That is the whole product.

Two neighbouring areas of law get asked about constantly and must be refused
outright, not answered carefully:

**Criminal matters.** An FIR, a bail application, a chargesheet, a prosecution.
A wrong answer here does not cost a filing fee — it costs somebody's liberty.
There is no "broadly right" in criminal law, no traffic-light amber, and no
version of this that is safe to automate for a person who is not a lawyer.

**Matrimonial and family matters.** Divorce, custody, maintenance, domestic
violence, dowry and sexual-offence proceedings. The same reasoning applies, and
one more: these matters are adversarial and intensely personal, so a tool that
produced *any* substantive output would be producing it for one side of a
dispute about a real family, on facts it cannot see.

Both refuse identically and completely: no lane, no obligations, no draft, no
"general information", no "here is how it usually works". A refusal that leaks
substance is not a refusal.

## Why this is a module and not a paragraph in the docs

A rule written only in a README is a rule the next tool forgets. This runs at
the top of every handler that takes free text — the audit, the drafter and the
source search — so a new tool cannot be added that quietly bypasses it.

## Why the trigger list is short

Precision beats coverage here. A founder's corporate question legitimately
contains words like "fraud", "penalty", "offence" and "prosecution" — a
payments product screens for fraud, a labour statute names an offence. Matching
those would refuse the product's actual job. The phrases below are the ones
that only appear when somebody is asking about a *proceeding involving a
person*, and the corporate carve-outs are checked first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Checked FIRST. Each of these is a genuine corporate-compliance duty that sits
# next to a criminal or family-law word, and refusing them would refuse the
# product's actual job.
#
#   POSH          — every Indian employer above the threshold owes an Internal
#                   Committee and a policy. That is an employer obligation, and
#                   it is in scope. An individual's complaint or proceeding is
#                   not, and is caught by the criminal list below.
#   background    — pre-employment verification is an HR process.
#   fraud/AML/KYC — building detection into a product is engineering plus
#                   regulatory duty, not a criminal matter.
CORPORATE_CARVE_OUTS = (
    "posh act",
    "prevention of sexual harassment",
    "sexual harassment of women at workplace",
    "internal committee",
    "internal complaints committee",
    "workplace harassment policy",
    "background verification",
    "background check",
    "employee verification",
    "fraud detection",
    "fraud prevention",
    "anti-money laundering",
    "money laundering compliance",
    "aml",
    "kyc",
    "whistleblower policy",
    "code of conduct",
)


@dataclass(frozen=True)
class ScopeRefusal:
    category: str
    matched_on: list[str]

    def as_dict(self) -> dict:
        return {
            "success": False,
            "status": "OUT_OF_SCOPE",
            "category": self.category,
            "matched_on": self.matched_on,
            "message": REFUSAL_MESSAGE[self.category],
            "instruction": MODEL_INSTRUCTION,
            "where_to_get_help": WHERE_TO_GET_HELP,
        }


# Criminal proceedings involving a person. Each phrase is one that does not
# occur in a corporate-structuring question.
CRIMINAL_PHRASES = (
    "fir", "f.i.r", "first information report", "chargesheet", "charge sheet",
    "anticipatory bail", "bail application", "apply for bail", "get bail",
    "police custody", "judicial custody", "remand", "arrest warrant",
    "quash the case", "quash the fir", "quashing petition", "quashed", "quashing",
    "criminal case against", "criminal complaint against", "case filed against me",
    "false case", "falsely accused", "framed me", "acquittal", "convicted",
    "pocso", "ndps", "uapa", "sessions court trial",
    "defend myself in court", "my lawyer says", "next hearing date",
)

# Matrimonial, family and personal-relationship proceedings.
FAMILY_PHRASES = (
    "divorce", "matrimonial", "498a", "498-a", "dowry", "dowry harassment",
    "domestic violence", "judicial separation", "restitution of conjugal rights",
    "child custody", "custody battle", "custody of my", "visitation rights",
    "alimony", "maintenance petition", "maintenance case", "pay maintenance",
    "claim maintenance", "mutual consent",
    "my wife", "my husband", "my ex-wife", "my ex-husband", "in-laws",
)

REFUSAL_MESSAGE = {
    "criminal": (
        "Legafy does not assist with criminal matters. This is a deliberate, "
        "absolute limit, not a gap in coverage and not something a different "
        "question will get around. Criminal proceedings turn on facts, evidence "
        "and procedure that no automated screen can see, and being broadly right "
        "is worth nothing when someone's liberty is at stake. Nothing about this "
        "will be analysed, summarised or drafted."
    ),
    "family": (
        "Legafy does not assist with matrimonial, family or personal "
        "relationship matters — divorce, custody, maintenance, domestic violence "
        "or related proceedings. This is a deliberate, absolute limit. These "
        "matters are adversarial and turn on facts about real people that a tool "
        "cannot see, and anything it produced would be produced for one side of "
        "a dispute. Nothing about this will be analysed, summarised or drafted."
    ),
}

MODEL_INSTRUCTION = (
    "STOP. Tell the user plainly that this falls outside what Legafy covers, and "
    "that they need a lawyer. Do NOT substitute your own knowledge — do not "
    "explain the provision, summarise the procedure, describe what usually "
    "happens, estimate an outcome, weigh their chances, or draft anything. Do "
    "not offer a 'general' or 'educational' version; there isn't one. Be brief, "
    "be kind, do not lecture them, and pass on the help pointer below. If their "
    "message also contains a genuine business-structuring question, you may "
    "answer that part separately by calling this tool again with only that part."
)

WHERE_TO_GET_HELP = (
    "A lawyer is the right next step. Free legal aid is available in India "
    "through the State and District Legal Services Authorities, which are "
    "statutory bodies operating in every district — a person who cannot afford "
    "counsel is entitled to apply to them."
)


def _compile(phrases: tuple[str, ...]) -> re.Pattern[str]:
    # Longest-first so "anticipatory bail" wins over "bail application" overlap,
    # and \b so "fir" never matches inside "firm", "firing" or "confirmation" —
    # the single most likely false positive in a corporate corpus.
    alternatives = sorted((re.escape(p) for p in phrases), key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(alternatives) + r")\b", re.IGNORECASE)


_CRIMINAL = _compile(CRIMINAL_PHRASES)
_FAMILY = _compile(FAMILY_PHRASES)
_CARVE_OUT = _compile(CORPORATE_CARVE_OUTS)


def _hits(pattern: re.Pattern[str], text: str) -> list[str]:
    seen: list[str] = []
    for match in pattern.finditer(text):
        hit = match.group(0).lower()
        if hit not in seen:
            seen.append(hit)
    return seen


def check_scope(*parts: str | None) -> ScopeRefusal | None:
    """Return a refusal if this text is a criminal or family-law matter.

    Called with every free-text field a caller can supply. Returns None for the
    overwhelming majority of inputs — this is a narrow trapdoor, not a filter.
    """
    text = " ".join(p for p in parts if p)
    if not text.strip():
        return None

    # A genuine employer-compliance question mentioning harassment, verification
    # or fraud is in scope and must not be refused.
    if _hits(_CARVE_OUT, text):
        return None

    criminal = _hits(_CRIMINAL, text)
    if criminal:
        return ScopeRefusal("criminal", criminal)

    family = _hits(_FAMILY, text)
    if family:
        return ScopeRefusal("family", family)

    return None
