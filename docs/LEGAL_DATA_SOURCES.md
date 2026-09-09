# Where the law actually comes from

Written as an advocate would brief a junior: which source is authoritative for
what, which are not sources at all, what machine-readable access genuinely
exists in India as of September 2026, and why Legafy crawls rather than calls
an API.

---

## 1. The hierarchy Legafy encodes

`AUTHORITY_WEIGHT` in `app/sources/store.py` is not arbitrary. It is the order a
court would take them in.

| Weight | Tier | What it is | What it settles |
|---|---|---|---|
| 1.00 | `gazette` | The Gazette of India, state gazettes | **What the law is, and from when.** A provision exists when it is notified. Passage and commencement are different dates. |
| 0.95 | `statute_repository` | India Code | The consolidated bare act, as amended. Convenient and near-authoritative; still a repository, not the notification. |
| 0.90 | `ministry` / `regulator` | MCA, MeitY, Labour, MSME / RBI, SEBI, IRDAI | Subordinate rules, circulars, directions, FAQs. For a regulator this is often *the operative rule*. |
| 0.85 | `state_portal` | State labour, commercial taxes, single-window | The state clock: registrations, renewals, forms. Frequently the only place a state rule appears at all. |
| 0.80 | `court` | Supreme Court, High Courts | What the text *means*. Below the gazette because a judgment interprets; it does not enact. **This is the citable floor.** |
| 0.25 | `aggregator` | Indian Kanoon, law firm notes, legal news | Orientation only. Never supports a compliance statement. Useful for finding the primary source, then discarded. |

The floor at 0.80 is the product's spine: a document below it can be indexed
for a human to read, and can never be the reason Legafy says anything.

**Where an advocate would say we are still thin:** we have no court tier
populated. Judicial interpretation is what turns a bare provision into advice —
"is a delivery rider an employee" is not answered by the Code on Wages, it is
answered by the cases about it. That is a coverage gap, not a design gap, and
it is the next thing worth funding. It is recorded honestly rather than papered
over.

---

## 2. Is there a legal API we can call? Mostly no — and that is the finding

We checked rather than assumed.

**Nyaykosh / "Law as Code"** — `lawascode.negd.in`. The most promising thing in
the space: a versioned REST API returning JSON provisions *and penalties*, plus
LegalDocML/Akoma Ntoso XML and the official PDF, with a compliance simulator on
top. Exactly the shape we would want.

The catch is size: **four Acts indexed** at the time of checking, all central
(DPDP 2023, Aadhaar 2016, the 2025 online-gaming Act, and one more). No state
coverage — which is the half of Indian compliance that actually differs, and the
half Legafy exists for. Its own footer says "informational purposes only — not
legal advice", so it is a source to verify against, not an oracle to trust.

*Our position:* watch it, and adopt it per-instrument the moment it covers one
of ours. If Nyaykosh publishes a verified penalty for an Act we carry, that is
the cleanest possible route out of `penalty_status: NOT_VERIFIED` — a
machine-readable penalty with a citation, reviewed by our legal team, is
exactly the evidence our invariant demands. **Add it as a `statute_repository`
tier source, not a `gazette` one.**

**API Setu** — `apisetu.gov.in`, the Government of India's official API
gateway. Real and official, but it is largely an identity and
document-verification exchange (DigiLocker-style: verify a PAN, fetch a
certificate) with onboarding requirements. It is not a statute or compliance
corpus. Useful later if Legafy ever verifies a user's own registrations; it does
not help us know the law.

**eCourts data** — the government's own eCourts services are a web portal, not a
documented public API. What exists as an "eCourts API" is **third-party**
(ecourtsindia.com and similar) reselling scraped court data. That matters for
us specifically: a third-party mirror of court data is an **aggregator (0.25)**,
not a court (0.80), however accurate it happens to be. Using one to populate our
court tier would silently launder authority, which is the one thing this
architecture must not do. If we want court coverage at 0.80 we take it from the
court's own site.

**MCA21 / GST / EPFO** — these have portals and verification lookups (GSTIN
search, Udyam search) rather than open corpora. They are what
`data/research_registers.json` points a founder at, and correctly so: those are
searches a human runs against their own facts, not data we should hold.

**The honest summary.** There is no comprehensive, official, machine-readable
corpus of Indian central *and* state law. Nyaykosh is the first serious attempt
and is early. So a crawl-and-verify pipeline over official portals is not a
workaround — right now it is the only route to state-level coverage, and the
state level is where the money and the mistakes are.

---

## 3. Why crawling still ends at a human

Everything above is about *finding* the law. None of it changes the rule that
nothing a crawler finds alters an answer until a named reviewer has read the
source and edited `data/jurisdictions/*.json`. An auto-updating legal corpus is
an auto-updating liability: the failure mode is not a wrong answer, it is a
wrong answer nobody chose to give.

The crawler's job is to tell a human *what to read next*, ranked. That is
`app/sources/watcher.py` and the review queue.

---

## 4. Are the citations we hand out actually valid?

This is a separate question from "is the law current", and it has its own
module: `app/sources/validation.py`, exposed as the `verify_source_health`
tool and `make sources-check`.

It checks each citation is:

- **https** — a citation over plain HTTP can be rewritten in transit;
- **on a government host** — `.gov.in`, `.nic.in`, `.org.in`;
- **on the whitelist that authorises it** — otherwise the citation guard would
  strip any statement resting on it, which is a silent failure;
- **not on a host that has migrated**;
- and, with `check_live`, **reachable, on a valid certificate, and not
  redirecting off-host**.

### It immediately found a real one

`indiacode.nic.in` — our single most-cited host, behind the Contract Act, the
Stamp Act, the Registration Act, POSH, Consumer Protection and more — **has
migrated to `indiacode.gov.in`**. The old host still answers, with a migration
notice. Every automated check that looks only at a status code sees `200 OK` and
reports health. A founder sees a page that is not the Act.

Fixed across all eight data files, and locked with two tests plus a
`KNOWN_MIGRATIONS` map so the class of defect is named rather than rediscovered.

The same pass surfaced four instruments citing hosts (`epfindia`, `esic`, `rbi`,
`consumeraffairs`) present in the *global* whitelist but absent from the union
file's own — a backstop covering for a gap. Now listed explicitly.

**Run it in CI offline; run `--live` weekly.** A CI job that fails whenever a
government portal has an outage is a CI job everyone learns to ignore.

---

## 5. What to add next, in the order an advocate would want it

1. **Court tier.** Supreme Court and High Court judgments on the instruments we
   already carry. Without interpretation we describe duties but cannot say what
   they mean in a contested case.
2. **Nyaykosh per-instrument adoption** as it grows — the cleanest path to
   verified penalties.
3. **State gazettes.** Union gazette is watched; state gazettes are where state
   rules commence, and state rules are our whole differentiator.
4. **Commencement tracking as a first-class field.** Several instruments we
   carry are notified in parts. "In force for whom, since when" deserves to be
   data, not a note.
