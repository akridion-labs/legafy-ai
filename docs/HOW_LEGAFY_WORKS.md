# How Legafy actually works

Written for someone who understands law and does not want to become a systems
engineer to run this. No prior knowledge assumed. If a sentence needs a computer
science degree, it is a bug in this document — tell me and I will rewrite it.

---

## 1. The problem in one paragraph

Ask any AI model "what do I need to open an office in Kerala and hire five
people" and it will answer. Fluently. With section numbers, penalty amounts and
deadlines. Some of it will be right, some will be a Karnataka rule wearing a
Kerala label, and some will be invented outright — and **nothing in the answer
tells you which is which.** That last part is the whole problem. A wrong answer
that announces itself is a nuisance; a wrong answer that reads exactly like a
right one is a liability.

Legafy does not make the model smarter. It takes the question away from the
model's memory and hands it to a curated file, then stops the model from
decorating the result.

---

## 2. What an MCP server is (and why it matters here)

MCP — Model Context Protocol — is a standard way for an AI assistant to call
out to a program you control. Think of it as the difference between a barrister
answering from memory and a barrister with a junior who fetches the actual file.

- Without MCP, Claude or ChatGPT answers from what it absorbed in training.
- With MCP, it can **call your server**, get back facts from your data, and
  answer from those.

An "MCP server" is just a program that exposes some named actions — here called
**tools** — that the assistant is allowed to invoke. Legafy exposes seven.

The crucial property: **the assistant does not get to choose what the tool
returns.** If Legafy says the lane is RED, the model cannot argue it down. That
is the source of every guarantee below.

---

## 3. The seven tools, in plain terms

| Tool | What it does | Think of it as |
|---|---|---|
| `execute_regional_compliance_audit` | Screens a business idea against one state | The first-pass file note |
| `generate_legal_structure` | Assembles a 20+ page pre-counsel document | The junior's first draft |
| `search_legal_sources` | Finds the official government page behind a duty | The library catalogue |
| `list_source_review_queue` | What changed, and what to read next | Your in-tray |
| `verify_registration` | Checks a GSTIN / Udyam / PAN against a government API | A registry search |
| `verify_source_health` | Are our citations still live and still official | Checking the links still work |
| `list_supported_jurisdictions` | Which states we cover | The contents page |

---

## 4. What happens when someone asks a question

A founder types: *"I want to build a marketplace for tutors and hold the fees
until the class is finished."* They say nothing about law. Here is the sequence.

**Step 1 — the assistant calls Legafy without being told to.** The tool's
description instructs it to. Describing an Indian venture is the trigger; the
user never has to say "use Legafy".

**Step 2 — the hard cap runs first.** Before anything else, the text is checked
for criminal and matrimonial matters. If it is one of those, everything stops.
See §7.

**Step 3 — the state question.** Obligations attach to a state, not to "India".
If the founder has not said where, Legafy does not guess and does not fail — it
returns the six states it covers and instructs the assistant to *ask*. The
founder says "Kerala".

**Step 4 — the grounding matrix.** Legafy opens the Kerala file and the union
(central) file. These are two separate blocks and are never merged. The Kerala
file is a document a human compiled by hand, by reading Kerala's own portals.

**Step 5 — the traffic light.** Every activity is screened. "Holds the fees"
matches escrow, which is **RED**: holding customer money can require RBI
authorisation. RED means halt and retain counsel, and it blocks the drafting
tool outright. It is not overridable by argument.

**Step 6 — the answer is assembled from the file, not from memory.** Each duty
carries a pointer to the official government page behind it.

**Step 7 — the citation guard.** Before anything reaches the founder, output is
stripped of anything statute-shaped that did not come from the data — invented
section numbers, invented penalties. If the model tried to add "under Section
12(3)", it does not survive this step.

**Step 8 — the audit vault.** A tamper-evident line is written recording what
was asked, what lane came back and when. Not the idea itself — only a
one-way hash of it. See §6.

---

## 5. The four promises, and how each is kept

These are not aspirations. Each has a test that fails the build if broken.

**"It will not invent a section number or a fine."**
Section numbers, penalty amounts and thresholds are simply **not stored**. Every
instrument ships `penalty_schedule: null` and `penalty_status: NOT_VERIFIED`
until a named human has read the primary source. A test walks every data file
and fails if a number appears where it should not. So the machine cannot recite
a penalty, because it does not have one to recite.

The cost of this promise, stated plainly: Legafy will often tell a founder
"there is a penalty exposure here, of this kind, and you must confirm the amount
from the source" rather than naming a figure. That is the honest answer. A
figure would be more satisfying and occasionally wrong, which in this domain is
worse than useless.

**"It will not apply Karnataka's rule to Kerala."**
Each state is a separate file and a separate code path. There is no fuzzy
matching and no nearest-neighbour fallback. An unmapped state — Goa, today —
produces a refusal, not an approximation.

This one is load-bearing and it is worth seeing why. Kerala has **no dedicated
state profession-tax Act.** Telangana, Andhra Pradesh, Karnataka and Maharashtra
each do. In Kerala the levy runs through the municipality or panchayat for your
address, on a half-yearly cycle instead of a monthly one. A tool that reasoned
"Kerala is like Karnataka" would produce a Kerala Profession Tax Act that does
not exist, pointing at a department that does not levy it, on the wrong payment
calendar — and it would look completely normal on the page.

**"When it does not know, it says so."**
A question the local corpus cannot answer is returned as *unanswered* and
recorded as a coverage gap for the compliance team. It is never backfilled from
the open web or from the model's memory. An unanswered legal question is a safe
outcome; a plausible invented one is not.

**"Ambiguity resolves to stop, not to a guess."**
Anything unclear resolves RED. RED blocks document generation.

---

## 6. The audit vault — the part a lawyer will care about most

Every call appends one line to a file. Each line carries a hash of the line
before it, so the file forms a chain. Change any past entry and every subsequent
hash stops matching, and `make audit-verify` returns false.

What that gives you: **you can prove what this system told a client, and when.**
For a CA firm or a law firm's intake desk, that is a professional-indemnity
argument, and it is worth more than the screening itself.

What the vault deliberately does *not* contain: the business concept in clear
text. Only a keyed one-way hash of it. You can prove a given idea was screened,
by re-hashing it; you cannot read anyone's ideas out of the file. If the server
is compromised, the attacker gets a list of hashes.

---

## 7. The hard cap: what Legafy refuses, absolutely

Two areas are refused outright, in code, before any other processing:

**Criminal matters.** FIR, chargesheet, bail, prosecution, POCSO, NDPS.
**Matrimonial and family matters.** Divorce, custody, maintenance, domestic
violence, dowry, 498A.

The refusal is total. No lane, no obligations, no draft, no "general
information", no "here is how it usually works". The response instructs the
assistant to stop, tell the person plainly that this is outside scope, and point
them to a lawyer — including that free legal aid is available through the State
and District Legal Services Authorities. A refusal that leaks substance is not a
refusal, and a test asserts that the refusal payload carries no lane, no
obligations and no proofs.

**Why, when there is obvious demand.** Two reasons, and the second is the one
that matters.

The first is severity. A wrong corporate answer costs a filing or a fine. A
wrong criminal answer costs someone's liberty. There is no amber lane in
criminal law.

The second is that these matters are **adversarial and about real people**.
Anything the tool produced would be produced for one side of a dispute, on facts
it cannot see, about a family it does not know. Whatever one believes about
trends in how such cases are filed — and people hold that view sincerely and in
both directions — it is a question about contested facts in individual
proceedings. That is exactly what a lawyer is for, and exactly what a pattern-
matching tool is worst at. Building it in would also make Legafy a partisan
instrument in somebody else's fight, which is not a position a compliance
product survives.

**What is *not* refused, and why that distinction is careful.** The POSH Act —
prevention of sexual harassment at the workplace — is a genuine employer duty:
a policy, an Internal Committee, an annual return. That is corporate compliance
and it is in scope. Background verification, fraud-detection features, AML and
KYC are likewise ordinary business obligations. These are checked *first*, so an
employer asking about their POSH obligations is never refused. What is refused
is an individual's proceeding.

---

## 8. Where the freshness comes from

Two channels, deliberately different, because their inputs differ in authority.

**Government pages** (`make watch`). Whitelisted official sources only —
gazette, ministry, regulator, state portal. A page changes, the change is
detected, and a *review candidate* is filed, ranked by authority × size of
change × how many instruments it touches × recency. **It never edits an answer
by itself.** It schedules a human.

**Court feeds** (`make courts`). Twelve RSS feeds — the Supreme Court, the High
Court for each state we cover, plus NCLAT, ITAT, CCI, the National Consumer
Commission and SAT. A judgment whose title touches something Legafy tracks
becomes a **lead**: a title, a link, a date. Nothing more.

Leads sit at **aggregator authority, 0.25** — well below the 0.80 floor required
to support any statement. So a lead can say "go and read this"; it can never be
quoted. The reviewer opens the judgment on the court's own site. The module
never fetches the judgment text at all.

**Why not The Hindu and the Times of India.** A newspaper's legal page is a
journalist's summary of a judgment. Using it as input means the thing Legafy
exists to prevent — a confident restatement of law by someone who has not read
the primary source — has already happened, twice, before the data arrives. The
court feeds carry the same information one hop closer to the source *and* carry
the link to the judgment. If a news channel is added later it must obey the same
lead-only rule: headline and link, never a paragraph of the article, never
citable. The code is structured so that is the only way it can be added.

### Where the leads are filed

Each feed declares the cabinet its leads belong in, so the weekly output sorts
itself:

| Cabinet | What lands there |
|---|---|
| `corporate` | Companies Act, LLP, shareholders, directors, insolvency, competition, securities |
| `labour` | Employment, PF/ESI, shops and establishments, contract labour, gratuity |
| `taxation` | GST, income tax, profession tax |
| `ip` | Trade marks, copyright, patents, trade secrets, non-compete |
| `consumer` | Consumer protection, e-commerce, unfair trade practice |
| `disputes` | Arbitration, stamping, specific relief |
| `templates` | Founder documents for corporate upkeep — see below |

There is no `relationship` cabinet, and that is deliberate. Everything that
would go in one falls inside the hard cap in §7. Note that "corporate
maintenance" — keeping filings, registers and returns current — is a
`templates` matter and has nothing to do with the maintenance in a matrimonial
proceeding; the cap is written to keep those apart, and a test proves it.

---

## 9. What it does not do

Said plainly, because a tool that oversells is the risk it is meant to remove.

- **It is not a lawyer** and creates no attorney-client relationship.
- **It does not tell you the law.** It points at the official page and tells you
  to read it. The citation is the product.
- **It covers six states**, not all of India: Telangana, Andhra Pradesh,
  Karnataka, Kerala, Maharashtra, Delhi. Others are refused, not approximated.
- **Everything currently ships `SEED_UNVERIFIED`.** Titles, years and
  administering authorities were compiled for routing and are real. Section
  numbers and penalties are deliberately absent, not pending. Before Legafy
  makes a compliance claim to a paying customer, a reviewer must work through
  each file against its primary sources and promote it to `VERIFIED`.
- **It does not do criminal or family law.** §7.

---

## 10. A note on "AI makes mistakes — how much does this reduce them?"

This is the right question and it deserves an honest answer rather than a
number picked because it sounds good.

**There is no measured figure yet, so do not publish one.** Not 80%, not any
other. In a product whose entire promise is "we do not state things we have not
verified", an unverified accuracy claim on the front page would be the first
thing a serious buyer tested and the fastest way to lose them. It would also be
the exact behaviour the tool is built to prevent, committed by the tool's own
marketing.

**What can be said today**, because it follows from the architecture and is
covered by tests:

> Legafy cannot state a section number, penalty amount or threshold that a human
> has not verified, because those values are not stored and a guard strips them
> from model output. It cannot apply one state's rule to another, because states
> are separate code paths with no fallback. When it has no answer it returns
> none rather than improvising.

That is a claim about **failure modes eliminated by construction**, which is
stronger and more defensible than a percentage.

**How to earn a real number.** `evals/legafy_mcp_eval.xml` already holds ten
questions with verified answers. The measurement to run:

1. Take 100 real Indian state-compliance questions.
2. Answer each with a plain model, no Legafy. Have a lawyer mark every answer
   for invented section numbers, wrong-state rules and invented penalties.
3. Answer each through Legafy. Mark the same way.
4. Publish both numbers, the question set and the marking criteria.

Run that and you will have a defensible figure and the method behind it, which
is worth far more in a legal sale than a round number nobody can check. Until
then, sell the failure modes.

---

## 11. Where to go next

| You want to | Read |
|---|---|
| Install and test it on your own machine | `docs/RUNBOOK_DEPLOY.md` §1–§3 |
| Put it on the Akridion server | `docs/RUNBOOK_DEPLOY.md` §4 |
| Connect it to Claude and to ChatGPT | `docs/RUNBOOK_DEPLOY.md` §5–§6 |
| Add a seventh state | `docs/ADDING_A_JURISDICTION.md` |
| Sell it | `docs/DISTRIBUTION_AND_REVENUE.md` |
| Know why each guardrail exists | `SECURITY.md` and `CLAUDE.md` |
