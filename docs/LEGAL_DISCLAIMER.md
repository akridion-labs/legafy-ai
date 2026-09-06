# Legal positioning and disclaimer

## What Legafy is

A **pre-counsel structural scaffolding** tool. It maps a described venture to
regulatory instruments that may apply, flags where the risk is high enough that
automation should stop, and drafts document structure so that the conversation
with a lawyer starts further along.

## What Legafy is not

Not a law firm. Not a lawyer. Not a substitute for one. Its output is not legal
advice, does not create an attorney-client relationship, and must not be signed,
filed or relied on without review by a lawyer qualified in the relevant
jurisdiction.

## The UPL posture, and how it is enforced in code

Operating a legal-automation product creates real exposure around the
unauthorised practice of law and product liability for generated material.
Legafy's answer is not a footer disclaimer; it is four enforced mechanisms:

1. **Defensive positioning.** Every generated artefact carries the disclaimer in
   its body, its DOCX core properties and its page footer, and is stamped
   `PRE-COUNSEL DRAFT — NOT EXECUTED`. The API root and every response envelope
   repeat it.

2. **The traffic-light boundary.** Low-risk work (mutual NDAs, basic structural
   outlines) runs automatically. High-risk vectors — escrow and customer funds,
   lending, insurance, securities and complex cap tables, cross-border personal
   data, children's or health or biometric data, multi-state tax gateways,
   foreign investment — force a hard stop with a counsel notice and a written
   brief of questions to put to a lawyer. `generate_legal_structure` refuses to
   run on RED, and no argument overrides that.

3. **Programmatic whitelist restraint.** Grounding never touches an open web
   search. Every instrument carries a `citation_url` on an authenticated
   government whitelist (`indiacode.nic.in`, `mca.gov.in`, state labour and
   commercial-tax portals). The citation guard rejects any URL, statute title,
   section reference, penalty amount or commencement claim that is not traceable
   to that whitelist.

4. **Absence by construction.** The data layer stores no section numbers and no
   penalties. A model cannot be prompted into leaking a fabricated fine from a
   field that does not exist, and generated text is scrubbed of statute-shaped
   tokens on the way out.

## Verification status

All jurisdiction files ship as `SEED_UNVERIFIED`. Instrument titles, years and
authorities are real. Everything finer — sections, thresholds, penalties,
commencement dates — is intentionally absent and must be sourced and reviewed by
a qualified person before a customer relies on it. Absences are claims too: the
note that Delhi has historically levied no professional tax is recorded as an
unverified assertion, not as settled fact.

## For customers

Legafy tells you what to ask your lawyer and hands them a structured starting
point. It does not tell you what the law requires of you, and it will stop
rather than guess.
