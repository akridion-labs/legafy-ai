# Legal Playbook — India (Legafy-maintained fragment)

Drop this into your `legal.local.md` when you use Anthropic's `legal` plugin
from India. That plugin's own README says its default positions reflect US
jurisdictions (Delaware, New York, California) and that you must customise the
playbook if you operate elsewhere. This is that customisation.

**Read this correctly.** These are *negotiating positions and escalation
triggers* — where a competent Indian counsel would push back and where they
would stop. They are not statements of law and they carry no section numbers.
For what actually applies to a specific venture in a specific state, call
Legafy's `execute_regional_compliance_audit`; this file is what a model should
assume in the absence of that call, not a substitute for it.

Maintained at `integrations/legal.local.india.md` in the Legafy repository.

---

## Jurisdiction defaults

- **Governing law**: India. Name the state for the seat, not just "India".
- **Seat of arbitration**: a named Indian city. "Arbitration in India" is not a
  clause — it produces a preliminary dispute about how to dispute.
- **Courts**: exclusive jurisdiction of the courts at the seat.
- **Escalation trigger**: any foreign governing law or foreign seat where the
  counterparty's assets and ours are both in India. That combination buys an
  award that is expensive to enforce where the money actually is.

## Contract formation

- **Standard position**: signed writing before work starts. An arrangement
  recorded only in chat or email is the one that gets disputed.
- **Stamp duty**: paid at the rate of the state of **execution**, at the time of
  execution. Rates differ by state for the same instrument.
- **Escalation trigger**: any agreement presented for signature that has not
  been stamped, or where the stamping state is unclear. An insufficiently
  stamped instrument is inadmissible in evidence until duty and penalty are
  paid — a signed contract you cannot produce is not a contract.
- **Registration**: leases of immovable property beyond the prescribed term must
  be registered. An unregistered instrument in that class does not affect the
  property at all, however clearly it is drafted.

## Restraint of trade — the position most often got wrong

- **Standard position**: **no post-employment non-compete.** A restraint on
  exercising a lawful profession, trade or business is void in India to that
  extent. A US-template non-compete imported unchanged is not a weak protection,
  it is an absent one.
- **Use instead**: confidentiality obligations, present-tense IP assignment,
  garden leave or notice period, and a narrowly drawn non-solicit of employees.
- **Escalation trigger**: any deal priced on the assumption that a non-compete
  will hold, or a founder departure being managed on that basis.

## Intellectual property

- **Standard position**: written, present-tense assignment of copyright and
  inventions from every founder, employee and contractor, signed before their
  work is merged. An NDA is not an assignment.
- **Pre-incorporation work**: assigned to the company expressly. This is the
  single most common diligence failure.
- **Brand**: cleared against the trade-mark register in the classes actually
  traded in, before the name is used in commerce. A clear company-name search on
  the company register is a different search with a different test.
- **Escalation trigger**: third-party datasets, media, model weights or
  open-source components with no recorded licence; any training corpus without
  documented provenance; any product described by reference to an incumbent's.

## Data protection

- **Standard position**: a processing inventory before anything else, specific
  and withdrawable consent, a written processing agreement with every vendor
  that touches user data, a named grievance contact that is actually answered,
  and a breach runbook written before it is needed.
- **Escalation trigger**: children's data, health data, biometric data, or any
  cross-border transfer. Also: enterprise customers' own data terms, which is
  usually the first consequence a B2B startup actually feels.

## Employment and contractors

- **Standard position**: classify honestly before the first payment. The label
  on the invoice does not decide it.
- **Statutory**: social-security registration once headcount crosses the
  applicable threshold, enrolled from that month, not retrospectively. Workplace
  committees constituted from the moment there is a workplace.
- **Escalation trigger**: a contractor cohort doing employee-shaped work; a
  manpower contractor whose remittances are unverified (the principal employer
  answers for them); moonlighting terms drafted as a restraint.

## Payments, escrow and regulated activity

- **Escalation trigger — stop and retain counsel, do not proceed on judgement**:
  holding customer funds, operating escrow, payment aggregation, lending,
  insurance distribution, securities or investment features, virtual digital
  assets, cross-border payments.
- **Standard position**: establish the authorisation route *before* building.
  Check the regulator's own list of authorised entities — for the venture and
  for any partner it intends to rely on.

## Consumer and platform

- **Standard position**: advertised claims provable; refund, cancellation and
  grievance terms published and staffed.
- **Platforms with user uploads**: a working notice-and-takedown route with
  recorded response times, and a published grievance officer. Safe-harbour
  treatment depends on conduct, not on a clause.

## Suppliers

- **Standard position**: verify the counterparty before the first invoice —
  GSTIN live and matching the legal name, company status on the register, and
  whether they are Udyam-registered.
- **MSME payment clock**: a registered micro or small supplier must be paid
  within the statutory period. The interest cannot be contracted out of, and the
  expense can be disallowed for tax.

## Lane mapping to the `legal` plugin's triage

| Legafy verdict | `legal` plugin routing |
|---|---|
| RED (`automation_permitted: false`) | full legal review |
| AMBER | counsel review |
| GREEN + `automation_permitted: true` | standard approval |

## Standing instruction

Where this file and the model's own recollection of Indian law disagree, this
file wins. Where this file and a live `execute_regional_compliance_audit`
response disagree, **the audit wins** — it is state-specific, dated and carries
a citation URL per instrument, and this file is a general default.

No section numbers, penalty amounts or limitation periods appear anywhere in
this file. That is deliberate. If a number is needed, it comes from the primary
source behind the citation, read by a person.
