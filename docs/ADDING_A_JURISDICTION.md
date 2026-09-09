# Adding a jurisdiction without assumption

Adding a state is the highest-risk change anyone makes to this repository. A
state that is honestly absent costs a user nothing — they get a clean refusal
and go elsewhere. A state that is *present and wrong* costs them a filing, a
registration, or a fine, and they have no way to tell the difference from the
outside. Assume nothing, and prefer an empty file to a plausible one.

This is the procedure, written up from adding Kerala (`IN-KL`).

---

## The rule

> **Nothing goes in a jurisdiction file because a neighbouring state has it.**

The cheapest way to add a state is to copy the nearest one and rename things.
It produces a file that passes every eye test and is subtly wrong, because the
one thing that varies most between Indian states is exactly the thing a copy
preserves: which authority levies what, on which cycle, under which instrument.

`make sources-check` now fails on the signature of that shortcut — an
instrument id carrying another state's prefix — but the guard is a backstop,
not a substitute for compiling the file by hand.

---

## Step 1 — find the state's own instruments, from the state's own sources

For each of the four things every state has an answer to, find **the state's
own** portal and read what it calls the instrument:

| | What to find | Where |
|---|---|---|
| Shops and establishments | the Act, and its year | the state labour department |
| Profession tax | **who levies it** — this is where states diverge most | state commercial taxes, or local self-government |
| Labour welfare fund | the Act and the contribution cycle | the state welfare fund board |
| Single window | the portal and what an acknowledgement actually permits | the state industries department |

Take titles from the state's own site or India Code. Do not take them from a
law-firm summary, a compliance blog, or a payroll vendor's wiki — those are
aggregator tier for a reason, and they propagate each other's errors.

### What this step found in Kerala

**Profession tax is not a state Act.** Telangana, Andhra Pradesh, Karnataka and
Maharashtra each have a dedicated state profession-tax Act. Kerala does not —
the levy runs through **local self-government institutions** under the Kerala
Municipality Act and the Kerala Panchayat Raj Act, on a **half-yearly** cycle
rather than a monthly one.

A file built by analogy would have contained a "Kerala Profession Tax Act" that
does not exist, pointing at a state department that does not levy it, on a
cycle that would put a founder's payroll calendar on the wrong clock. It would
have looked completely normal.

That single finding is why this document exists.

---

## Step 2 — when sources disagree, do not choose

The Kerala Labour Welfare Fund Act appears in public sources as **1975**, as
**1977** and as **1979** — including on official-adjacent repositories, whose
own filenames disagree with their own titles.

The wrong move is to pick the most common one. The right move:

```json
"title": "Kerala Labour Welfare Fund Act",
"commencement_note": "TITLE YEAR DELIBERATELY OMITTED. Public sources disagree …
  Rather than pick one and be confidently wrong, the year is left out and a
  reviewer must confirm it from the gazette or India Code."
```

A test asserts that instrument's title carries no year, so nobody helpfully
"fixes" it later. **An invented year is indistinguishable from a real one to
every reader, which is exactly what makes it dangerous.**

---

## Step 3 — declare what the state does *not* have

An absence is a claim like any other. If a state lacks something its neighbours
have, say so in `state_level_absences` with its own verification status and an
instruction for how to treat it:

```json
{
  "topic": "standalone_profession_tax_act",
  "assertion": "Kerala does not appear to have a dedicated state profession-tax Act …",
  "verification_status": "SEED_UNVERIFIED",
  "instruction": "Do not present this absence as settled until a reviewer has confirmed it."
}
```

Without this, a user asking "do I owe profession tax in Kerala?" gets silence,
and silence reads as "no". Silence is not an answer this system is allowed to
give.

---

## Step 4 — write the escalation triggers as traps, not as topics

`state_escalation_triggers` is where the state's local knowledge goes: the
things that surprise someone who has operated elsewhere. Kerala's:

- assuming the profession-tax obligation looks like Karnataka's — it does not;
- **moving an office between local bodies within the state**, which can change
  who assesses you even though the state has not changed;
- treating a single-window acknowledgement as the clearance itself.

If you cannot write at least one trap, you have not learned enough about the
state yet.

---

## Step 5 — courts

Add the state's High Court to `data/sources.json` at `authority_tier: "court"`
— **only if you have confirmed the hostname.**

For Kerala the court's own hostname could not be confirmed at compile time, so
the entry points at the government's own judgment portal
(`judgments.ecourts.gov.in`) and says why. An unverified court hostname is
precisely the kind of citation that looks right and is not.

---

## Step 6 — let the machine check the things a machine can

```bash
make sources-check
```

Which now fails on:

| Check | Why it exists |
|---|---|
| `foreign_instrument_id` | a `TG-` instrument in the Kerala file — the copy-paste tell |
| `alias_collision` | two states claiming "southcity"; one silently answers for the other |
| `no_aliases` | a user typing the state's own name would not resolve it |
| `section_number_in_summary` | invariant 1, enforced at the data layer |
| `penalty_amount_in_summary` | same |
| `unverified_penalty_present` | a schedule without `VERIFIED` status |
| `instrument_without_obligations` | an instrument that tells a founder nothing |
| `citation_outside_own_whitelist` | the global whitelist covering for a gap in the state's own |
| `duplicate_instrument_id` | two entries, one id |
| `jurisdiction_incomplete` | a missing required field |
| `bad_lane` | anything that is not GREEN, AMBER or RED |

Then add a test that the state resolves from its real aliases and that its
instruments are all its own — `test_kerala_resolves_and_is_isolated` is the
pattern to copy.

---

## Step 7 — ship it as SEED_UNVERIFIED, and mean it

A new state ships with `verification_status: SEED_UNVERIFIED`, every
`penalty_schedule: null`, every `penalty_status: NOT_VERIFIED`. The
`verification_note` should say what a reviewer specifically needs to check —
for Kerala, the profession-tax structure and the welfare fund year.

Only a named human, reading the primary source, moves any of that to
`VERIFIED`. That is the whole discipline: the machine can check that a file is
*structurally* honest; only a person can check that it is *true*.

---

## The checklist

```
[ ] Every instrument title read from the state's own portal or India Code
[ ] Profession tax: confirmed WHO levies it, not assumed from a neighbour
[ ] Any disputed year omitted, with a commencement_note explaining why
[ ] state_level_absences declared for anything the neighbours have and this state lacks
[ ] At least one escalation trigger that would surprise an outsider
[ ] Aliases cover the state name, its abbreviation, and its main cities
[ ] High Court added only if the hostname was confirmed
[ ] make sources-check    -> 0 errors
[ ] make test             -> a resolution + isolation test for the new state
[ ] verification_status: SEED_UNVERIFIED, and the note says what to verify first
```
