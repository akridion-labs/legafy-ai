# Legafy AI — roadmap

Where this goes after v1.0.0, and why in this order. Written to be argued with: every
phase says what it unlocks and what it costs, so items can be cut rather than quietly
carried forever.

---

## Where we are

Shipped and verified in v1.0.0:

- Isolated state code paths (TG, AP, MH, KA, DL) with union instruments kept separate
- Traffic-light matrix with a hard RED halt on automated drafting
- Citation guard — no section numbers, penalties or off-whitelist URLs survive to a user
- Anti-truncation chunk assembly, verified at ~30 pages with every clause present
- Hash-chained, HMAC-pseudonymised audit vault
- Three transports: REST, JSON-Schema tool API, and MCP (stdio + Streamable HTTP)
- Claude Code plugin marketplace install

The honest gap: **all jurisdiction data is `SEED_UNVERIFIED`.** Titles and authorities are
real; nothing finer has been reviewed. Everything below is worth less than fixing that.

---

## Phase 1 — make it trustworthy (before anyone pays)

**1.1 Verify the seed corpus.** Work each `data/jurisdictions/*.json` against its
whitelisted primary sources; fill `verified_citations`, set `verification_status:
VERIFIED`, record who verified it and when. Add a `reviewed_by` / `reviewed_on` field and
make `/healthz` report how many files are still unverified.

*Why first:* every other feature multiplies the value of this data, or multiplies the
damage of it being wrong. A retained lawyer doing five states is the highest-leverage
money in the whole plan.

**1.2 Staleness as a first-class state.** Law changes. Add `next_review_due` per
instrument and have the API degrade a verdict to AMBER with an explicit "this entry is
past review" note rather than silently serving stale confidence. A compliance tool that
cannot tell you how old its answer is has the wrong shape.

**1.3 OAuth + Dynamic Client Registration.** The gate between "I use this" and "customers
use this". Claude supports DCR and calls back to `claude.ai/api/mcp/auth_callback`; until
this exists, every customer connection is a long-lived token in a URL.

**1.4 Verdict permalinks.** Every audit already writes a vault record. Give it a
retrievable id so a founder can hand their lawyer `legafy.ai/v/<id>` and the lawyer sees
exactly what was assessed, when, against which data version. This is the artefact that
makes Legafy a participant in the legal process rather than a toy beside it.

---

## Phase 2 — location, deeper and wider

The isolation design was built so this is a data problem, not a code problem.

**2.1 Remaining Indian states and UTs.** 23 more state files. Each is a template fill plus
verification. Priority by where startups actually are: KA and MH are done, then TN, GJ,
UP, WB, HR, RJ.

**2.2 Municipal layer.** Trade licences, shop signage, fire NOC and property tax are
*city* instruments, not state ones — a Hyderabad GHMC obligation is not a Warangal one.
Add a `tier: "municipal"` block under each state, resolved from the city in the request.
This is where "location-based" stops being a synonym for "state" and starts being genuinely
useful, because it is exactly the layer founders discover too late.

**2.3 Zone and premises awareness.** SEZ, STPI, industrial park and IT-corridor status
change the applicable set. A concept plus a pincode is enough to route this.

**2.4 Cross-border, one country at a time.** The schema is not India-specific — the
isolation contract works for US states or EU member states unchanged. Sequence by where
Indian founders actually incorporate: Singapore, Delaware, UAE, UK. **Resist doing this
before Phase 1 is complete for India**; a shallow four-country product is worth less than
a verified one-country product, and is much harder to defend.

**2.5 Comparative mode.** "Telangana vs Karnataka for a 12-person engineering team" —
run both isolated paths and diff the obligations. High-value, and it falls out of the
existing architecture almost free, precisely because the paths never merged.

---

## Phase 3 — the IP and copyright screen

The most-requested capability that v1.0.0 explicitly does **not** have.

**3.1 Separate the question.** Regulatory compliance ("may I operate this way") and IP
clearance ("does this infringe someone") are different questions with different data
sources, different failure modes and different lawyers. They deserve a sibling tool,
`execute_ip_clearance_screen`, not a widened compliance tool.

**3.2 What it can honestly do.**

- **Trademark:** search the Indian TM registry and WIPO Global Brand Database for the
  proposed name in the relevant classes. Report hits with numbers and status. This is a
  real, checkable, sourceable answer.
- **Open-source licence exposure:** parse the dependency manifest, flag copyleft
  obligations against the distribution model. Deterministic, high value, no guessing.
- **Content provenance:** flag training-data, scraping and user-generated-content patterns
  that carry copyright exposure, as *questions for counsel* rather than verdicts.
- **Patent landscape:** surface adjacent published applications for orientation only.

**3.3 What it must refuse to do.** Freedom-to-operate opinions, infringement conclusions,
and "is this fair use". Those are legal opinions and the whole product posture depends on
not producing them. The traffic light extends naturally: name conflicts and copyleft in a
proprietary product go AMBER; a live opposition, a plausible infringement read, or any
"can we use this dataset" question goes RED.

**3.4 Why this sells.** Compliance is a launch-time purchase; IP screening recurs on every
product name, feature and dependency bump. It is the surface that turns Legafy from a
once-a-year tool into a weekly one.

---

## Phase 4 — distribution: one screen, every platform

The goal in one sentence: **anyone describing a startup idea to any assistant gets the
legal screen without asking for it.**

**4.1 Directories.** Submit to the Anthropic connector directory and the ChatGPT app
directory. Both are where intent already exists.

**4.2 Framework-native packages.** Thin wrappers over the existing tool API for LangChain,
LlamaIndex, the Vercel AI SDK and n8n. Days of work each, and they meet developers where
they are.

**4.3 The IDE surface.** Legafy in Claude Code and Cursor while someone is *writing the
feature* is better placed than any dashboard. "You just added a payments SDK — that is a
RED-lane activity in your declared jurisdiction."

**4.4 Continuous compliance (blueprint Tier 3).** A GitHub Action that re-screens on every
PR: new dependency, new data field, new region in the deploy config. It turns a purchase
into a subscription because the check has to keep running.

**4.5 Embeddable widget.** An accelerator, a bank or a registrar embeds the screen in
their own founder onboarding. Their brand, your engine, per-seat licence.

---

## Phase 5 — the corpus, and the question of a legal model

Worth thinking about carefully, because the current design deliberately forecloses the
naive version.

**5.1 Read this before planning any training.** The audit vault stores an **HMAC digest**
of every business concept, never the text. That was the right call for liability and
privacy, and it means **today's telemetry cannot train anything.** Any corpus needs a
separate, explicit, opt-in pipeline — not a repurposing of the vault. Do not let anyone
plan around "we already have the data", because we deliberately do not.

**5.2 What is actually valuable, in order:**

1. **The question taxonomy.** Which concepts trigger which lanes, which counsel-brief
   questions recur, which states get asked about together. This is derivable from the
   vault *as it stands* — lanes, flags and jurisdictions are stored in clear — and needs
   no new consent. It tells you which instruments to verify first and which vectors to
   add. Start here; it is free and it compounds.
2. **The verified corpus.** Every instrument a reviewer promotes to `VERIFIED`, with its
   citation. That is a proprietary, checkable asset and the actual moat — more so than any
   model weight.
3. **Counsel outcomes.** When a RED verdict goes to a lawyer, what did they conclude? An
   opt-in feedback loop here is the only signal that tells you whether the traffic light is
   calibrated or just cautious. Nothing else in the system can tell you that.

**5.3 On a fine-tuned legal model.** The instinct is reasonable and the sequencing matters:

- The failure mode in this domain is *confident fabrication*, and fine-tuning on legal text
  makes a model **more** fluent at producing citation-shaped strings, not more accurate.
  The citation guard would still be doing the real work.
- Retrieval over a verified corpus gets most of the benefit with none of the fabrication
  risk, and its answers stay auditable — which matters more here than raw fluency.
- A model trained on user-submitted concepts creates a confidentiality problem: founders
  describe unlaunched ideas. Opt-in, aggressive de-identification, and a written data
  policy are the entry price, not a later cleanup.
- The realistic near-term win is a **small classifier**, not a legal LLM: predict lane and
  activity flags from free text, to catch the under-declaration that the keyword scan
  misses today. Narrow, evaluable against the labels the vault already holds, and it
  improves the guardrail rather than bypassing it.

**Recommendation:** taxonomy analytics now, verified-corpus retrieval next, an
activity-flag classifier after that. Revisit a fine-tuned model only when there is a
verified corpus large enough to evaluate one against — and evaluate it on whether it
*refuses* correctly, not on whether it sounds like a lawyer.

---

## Phase 6 — the wider surface

Ideas worth keeping visible even if none ship soon:

- **Cap-table and ESOP structural checks** against the state and union path
- **Vendor and DPA screening** — score an incoming contract against the DPDP posture
- **Registration pack generator** — the actual forms and portal links per state, the
  single most-asked founder question
- **Regulatory diff alerts** — subscribe a company profile, notify on instrument change.
  Depends entirely on 1.2 being real.
- **Multi-language** — Hindi and Telugu output; the audience is not English-first
- **Lawyer marketplace handoff** — a RED verdict is a qualified lead with a written brief
  attached. The counsel brief already exists; this is a routing problem, not a product one.
- **Insurance and banking partnerships** — underwriters and neobanks both want a
  standardised compliance posture at onboarding

---

## What to do next week

1. Verify one state end to end (Telangana) and promote it to `VERIFIED`. Everything else
   is speculation until one file proves the process.
2. Ship OAuth/DCR, so the next connector you hand out is not a token in a URL.
3. Add the municipal layer for Hyderabad only, as a proof that the tier extension works.
4. Run the taxonomy query over the vault — the lanes and flags are already there — and let
   what founders actually ask decide the order of everything above.
