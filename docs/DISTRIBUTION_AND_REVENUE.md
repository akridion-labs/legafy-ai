# Distribution and revenue — Legafy AI, Akridion Labs

How Legafy reaches users on Claude and ChatGPT, and where the money actually comes
from. Written September 2026; the platform facts below carry the date they were
checked, because this is the fastest-moving part of the whole plan.

---

## The headline, before anything else

> **Neither Anthropic nor OpenAI pays you for building an MCP server.**

There is no revenue share, no payout, no per-call bounty, no store cut in your
favour. Checked 9 September 2026 against both vendors' own developer docs:

| | What it is | Do they pay you? |
|---|---|---|
| **Claude Connectors Directory** | A vetted, searchable list of remote MCP servers inside Claude | **No.** It is distribution. There is no revenue-share programme documented. |
| **Claude plugin marketplace** | A git repo Claude Code reads; `/plugin install` | **No.** Free to publish, no gatekeeper, no payout. |
| **ChatGPT Apps SDK** | Apps inside ChatGPT, built on MCP | **No.** OpenAI's own monetization page describes *external checkout* — you direct the user to your checkout and take the money yourself. |

OpenAI's in-ChatGPT payment sheet exists but is *"limited to select marketplaces
today"* and covers physical goods; supported processors are the usual PSPs
(Stripe, Adyen, PayPal and similar). For a compliance-software subscription in
India, none of that applies yet.

So the model is not "get paid by Claude". The model is:

**The platforms give you the cheapest customer acquisition available to a
two-person company. You bill the customer yourself.** Every line below is
built on that sentence.

---

## Part 1 — the four distribution surfaces, and what each one costs to open

### 1. Claude Code plugin marketplace — open today, costs nothing

Already built (`.claude-plugin/marketplace.json` + `plugins/legafy/`). A user runs:

```
/plugin marketplace add akridion-labs/legafy-ai
/plugin install legafy@akridion-labs
```

No review, no organisation plan, no waiting. It installs the connector *and* the
`legal-idea-screen` skill, which is the part that matters — the skill is what
makes the model reach for the grounding tool instead of answering from memory.

**This is where the first hundred users come from.** Publish the repo, put the
two lines in the README, and it works the same day. Reach is limited to Claude
Code users, who skew technical — which happens to be exactly the founder profile
Legafy is for.

### 2. Claude Connectors Directory — the real distribution, with a gate

This is the listing that puts Legafy in front of every Claude user, not only
Claude Code users. Requirements, from Anthropic's submission documentation:

| Requirement | Legafy's status |
|---|---|
| Remote MCP server over Streamable HTTP, `https://` | ✅ `POST /mcp/`, stateless JSON |
| **Every tool declares a `title` and the applicable `readOnlyHint`/`destructiveHint`** | ✅ **as of this change** — it was missing, and it is a hard blocker: the portal groups un-annotated tools separately and tells you to fix them before submitting |
| OAuth 2.0 for authenticated services | ⚠️ **the open gap.** Legafy uses bearer tokens. The portal also accepts a *custom connection* where the user supplies their own URL or credentials at connect time, which fits the current design — but OAuth with dynamic client registration is what a polished consumer listing wants |
| Privacy policy at an HTTPS URL | ❌ not written yet. Missing or incomplete privacy policies are called out as an **immediate rejection** |
| Public documentation URL | ⚠️ needs a public docs site, not a private repo |
| Test account credentials for the reviewer | ❌ mint a reviewer token with `scripts/sandbox.sh` and keep it alive |
| **A Team or Enterprise organisation on Claude.ai** | ❌ the submission portal lives in organisation settings; individual plans cannot submit |

That last row is a purchase decision, not an engineering one: **Akridion Labs
needs a Team plan before it can submit anything.** Worth knowing now rather than
on the day the code is ready.

The compliance step also asks you to acknowledge policies on financial
transactions, prompt injection and conversation-data collection. Legafy answers
all three well — it takes no payments, its citation guard is a prompt-injection
countermeasure, and the corpus is opt-in and question-only. Say so in the form;
these are strengths, not boxes.

### 3. Claude Desktop extension (MCPB) — the offline story

A packaged local server, submitted through a separate form, no organisation plan
needed. This is the version for a customer who will not send a business concept
to a hosted service at all — a law firm, or a company with a data-residency
policy. It runs the whole engine on their machine with the offline provider.

Nobody else in this category can offer that, because everyone else *is* the
cloud service. Worth building for that reason alone.

### 4. ChatGPT — same server, second audience

The Apps SDK speaks MCP, so the same `/mcp/` endpoint serves it. Monetisation is
entirely yours: link out to an Akridion Labs checkout. There is no ChatGPT-native
subscription to piggyback on for this category today.

Treat ChatGPT as **reach, not revenue**: an Indian founder is more likely to have
a ChatGPT subscription than a Claude one, so it is where discovery happens, while
conversion happens on your own site.

---

## Part 2 — where the money comes from

Five lines, ordered by how soon each can produce a rupee. The tier scaffolding
already exists in `app/security/tenancy.py`; this says what to charge for.

### Line 1 — Verified jurisdiction access (the core subscription)

**The product is not the code. The code is Apache-2.0 and anyone can run it.
The product is `data/jurisdictions/*.json` with `verification_status: VERIFIED`.**

Every instrument ships as `SEED_UNVERIFIED` today. The moment a named reviewer
has read the primary sources for a state and promoted it, that state becomes
something a founder will pay for and cannot get anywhere else in machine-readable
form — because, as `docs/LEGAL_DATA_SOURCES.md` records, no comprehensive
official machine-readable corpus of Indian state law exists.

- `DEVELOPER_FREE` — audits only, unverified states, rate-limited. The funnel.
- `PREMIUM_HOSTED` — verified states, drafting, the review queue.
- Price it per seat per month, in INR, at roughly the cost of one hour of a
  company secretary's time. A founder who compares it to a lawyer's hourly rate
  buys immediately; one who compares it to a SaaS tool does not.

**This line is gated on verification, not on engineering.** No amount of code
makes `SEED_UNVERIFIED` sellable. Selling a compliance claim you have not
verified is the one failure this whole architecture was built to prevent — do
not let a launch date be the thing that overrides it.

### Line 2 — B2B seats for the people founders already pay (highest value)

CA firms, company secretaries, incubators, accelerators and law-firm intake
desks all do the same unbilled work: a first-pass structural screen of a client's
idea. That is precisely what Legafy automates, and they have budget.

`ENTERPRISE_B2B` already exists: 1000/min, `*` scopes. What it sells is the
hash-chained audit vault — a firm can prove *what it told a client, when*, with
an integrity guarantee. That is a professional-indemnity argument, and it is
worth more than the tool.

One incubator with fifty portfolio companies is worth more than a thousand free
users, closes in a single conversation, and needs no directory listing at all.
**Start here while the directory submission is in review.**

### Line 3 — Per-document drafting

`generate_legal_structure` is metered, refuses on RED, and produces a 20+ page
DOCX. Sell it per document to users who do not want a subscription. It is the
natural upsell from a GREEN audit, and the RED halt is a feature you can charge
for honestly: *we refused to draft this and told you why.*

### Line 4 — White-label the grounding layer

Other Indian legaltech products have the same hallucination problem and no
appetite to build a jurisdiction matrix. Sell them the tool endpoints, not the
UI. This is the highest-margin line and needs no consumer distribution at all.

### Line 5 — Counsel handoff

The obvious idea — take a fee for sending a RED-lane user to a lawyer — is the
one to check with counsel **before** designing anything around it. India
regulates advocates' fee-sharing and solicitation, and a referral-fee model can
put the *lawyer* in breach even where the platform is fine. Legafy's own rule
applies to Legafy's business model: this is AMBER, name the exposure, do not
invent the rule. A neutral, unpaid directory of counsel carries none of that
risk and still delivers the user value — build that first.

---

## Part 3 — what the model must not do

- **Never charge for an unverified compliance claim.** See Line 1.
- **Never make the free tier answer legal questions without grounding.** A free
  tier that hallucinates is not marketing, it is liability, and the whole
  citation-guard architecture exists to prevent exactly that.
- **Never price per token.** It would pay you to bloat responses, and `compact`
  mode exists to shrink them. Price per seat or per document, so your incentive
  and the user's point the same way.
- **Never let the RED lane become an upsell.** The halt has to be free and
  unconditional, or it stops being trustworthy — which is the entire product.

---

## Part 4 — sequencing

**Now, no platform dependency**

1. Verify one state end to end (Telangana) and promote it to `VERIFIED`.
   Everything commercial is downstream of this.
2. Publish the repo and the plugin marketplace. Free, same day, no review.
3. Sell one `ENTERPRISE_B2B` seat to an incubator or a CA firm. Revenue before
   distribution.

**Next, to unlock the directory**

4. Buy a Claude Team plan for Akridion Labs — the submission portal needs it.
5. Write the privacy policy and put the docs on a public URL.
6. Stand up the public MCP origin on a VPS. **Not on `AKRIDION-AI-01`** — see
   `docs/DEPLOYMENT_AKRIDION_SERVER.md`; the server stays private and the S7
   security gate stays honestly closed.
7. Add OAuth 2.0 with dynamic client registration, then submit.

**After that**

8. Package the MCPB desktop extension for the offline/data-residency segment.
9. List on ChatGPT with checkout pointing at Akridion Labs.

---

## Part 5 — the name

The company is **Akridion Labs**. Two things to fix and one to decide:

- `README.md` said "Akridion Labs LLP". **Do not assert an entity type you have
  not registered** — it is a claim about a legal fact, in a legal-compliance
  product, of exactly the kind this repo refuses to make about anyone else. It
  now reads "Akridion Labs"; add the suffix on the day the incorporation
  certificate exists, and not before.
- The audit vault file is `akrigon_audit_vault.json` — a typo of Akridion,
  carried since the first commit. It is referenced in the Makefile, the docs and
  the backup instructions. Renaming it breaks every existing vault path, so it is
  a deliberate migration, not a find-and-replace. Left alone for now; noted so it
  is a decision rather than a surprise.
- Decide the public hostname before the directory submission: the listing slug is
  **permanent once published**, and it should match whatever the product is
  called for good.
