# Buyer discovery: is the customer the founder or the legal team?

This document exists because of assumption 4 in `ROADMAP.md`. It holds the five
questions to ask, the rules for asking them, and two scope decisions that were
made while the question was being framed — recorded here so they are not
relitigated from memory later.

Nothing in here requires code. That is the point.

---

## 1. The decision it is testing

Legafy was built for a pre-incorporation founder screening an idea. That reader
was assumed, never chosen. The competing reader is an in-house legal, company
secretarial or compliance person at a company already operating in more than one
Indian state.

The evidence that the assumption may be wrong came out of the tool itself. Asked
to screen a Telangana healthtech idea, it returned, unprompted:

> "Deploying employees across Telangana and another state under one payroll —
> professional tax, welfare fund and shops-and-establishments registration do
> not travel across the border."

Hard state isolation is Legafy's one genuine differentiator, and that sentence
is a multi-state employer's problem. A first-time founder in one city does not
have it yet.

**What the interviews decide.** If the second reader is real, the roadmap
reorders around them and assumption 2's concierge test should be run on legal
teams rather than founders. If they are not, assumption 4 is closed and the
founder stays the buyer with evidence behind them for the first time.

---

## 2. How to ask

Five conversations, twenty minutes each, people you can already reach. The point
is to learn what is true, not to find out whether people like Legafy.

**Do not describe Legafy.** Not at the start, not in the middle. The moment the
product is on the table, everyone becomes polite and the data is gone. If they
ask what you are building, say you are trying to understand how compliance
actually gets done before you build anything, and go back to asking.

**Ask about the last time, never about "usually".** "How do you usually handle
state registrations?" gets you a job description. "Walk me through the last one"
gets you what happened.

**Ask for numbers and names.** Which state, which month, who chased it, how long
it sat, what the tool was called, what it cost. Specifics are checkable; opinions
are not.

**Never ask whether they would use it, pay for it, or like it.** Every answer to
those questions is worthless. Budget is established by what they already bought,
not by what they say they would buy.

**Write it down within the hour**, in their words, including the phrases that
surprised you. Their vocabulary is the product's vocabulary.

---

## 3. The five questions

**Q1. Tell me about the last time a state-level rule caught you out — the wrong
state's rule applied, a registration nobody knew about, an inspection you were
not ready for. What happened, and who found it?**

> Tests whether the multi-state problem is real and remembered, or theoretical.
> Listen for whether they name a state, and whether they mention professional
> tax, labour welfare fund or shops and establishments without being prompted.
> If nothing comes to mind, that is a finding — do not help them think of one.

**Q2. Walk me through what you actually did the last time the company started
operating in a new state. From the decision to the first hire there.**

> Tests where the work sits and how long it takes. Listen for who did it — them,
> a consultant, a CA, a law firm, a vendor portal — and for the step that took
> longest. The step they complain about is the product surface, if there is one.

**Q3. What do you do today when you need to know whether a particular rule
applies to you in a state you are not already in? Show me, if you can.**

> Tests the current alternative, which is the thing Legafy would have to beat.
> "I ask our consultant" and "I search and hope" are different worlds. If they
> open a tool, get its name and ask how it is kept current.

**Q4. What does the company already pay for in this area — tools, retainers,
consultants? Who signs for it and when was it last renewed?**

> Tests whether budget exists and who owns it. A named line item that already
> renews is the single most valuable thing you can learn. No line item means any
> sale is a new-budget sale, which is a different and much slower company.

**Q5. What went wrong the last time you relied on something — a person, a tool,
an update service — to tell you a rule had changed?**

> Tests the regulatory-change problem specifically, which is the closest thing
> Legafy already has to a second product. Listen for how they found out, how
> late they were, and what it cost. Also listen for whether they trust automated
> updates at all; if they do not, that is a constraint on the whole direction.

---

## 4. Reading the answers

**The hypothesis survives if** at least three of five describe a multi-state
incident unprompted in Q1 or Q2, *and* at least two name an existing budget line
in Q4. Both halves matter: a real problem with nobody funding it is a hobby.

**The hypothesis is falsified if** they do not recognise the problem, or they
recognise it and it belongs entirely to an external consultant who is paid to
own it. In the second case the buyer is the consultant, not the company, and
that is a different product with a different sales motion — write it down and
stop rather than redesigning around it in the same week.

**Watch for the third answer**, which is neither: they recognise the problem,
have no budget, and solve it with a spreadsheet maintained by one person. That
is a real market with no money in it yet, and it means the next question is
timing, not product.

---

## 5. Scope decisions recorded while framing this

### 5.1 e-Discovery — out of scope, permanently

Considered because the founder works in e-discovery professionally and the
adjacency looked plausible. It is not adjacent. Reasons, in order of weight:

1. **The Indian market does not exist in the assumed form.** India has no
   US-style discovery. Under Order XI CPC, discovery and inspection is not
   available as of right — a court must be satisfied on several criteria before
   ordering it. Vidhi Centre for Legal Policy's consultation paper on reforming
   the regime records that the stage is skipped in most civil cases and that
   interrogatories are rarely used; it does not discuss litigation holds or
   spoliation sanctions, because the Indian regime has no equivalent doctrines.
   India's e-discovery industry is therefore the back office for US and UK
   matters — an LPO business — not a domestic legal-technology market.
2. **The security posture inverts.** Legafy's data is public law, and the design
   deliberately avoids holding client material: a business concept is never
   persisted in clear text, only a keyed hash reaches the audit vault. An
   e-discovery tool must hold the client's entire document population, including
   privileged material. That is the opposite design, and it drags in SOC 2,
   ISO 27001 and client audit rights before the first sale.
3. **The moat does not travel.** The hand-compiled, jurisdiction-isolated
   instrument matrix — the asset that took the work — is worth nothing against
   Relativity, Everlaw or Disco.

**What was kept instead.** Two patterns transfer and are already in the codebase:
the hash-chained audit vault is structurally a chain-of-custody log, and the
authority-tier floor is the same discipline as defensible sourcing. Keep both.
Do not build the product.

### 5.2 Trade marks — in scope, but as a checklist, not a search

Trade-mark work fits: it is a primary-source lookup against a government
register, which is the pattern `verify_registration` already implements, and
`ip_risks` / `ip_baseline` already carry name clearance.

The constraint is that IP India's public trade-mark search is a CAPTCHA-gated
web portal with no documented public API. Scraping it would put the reliability
of a legal answer on a screen-scrape, which contradicts the authority-tier rule
the whole system is built on.

**So the scope is a class recommender and a clearance checklist, not a clearance
search.** Legafy can say which Nice classes a described activity likely falls
in, what a proper search must cover, what the register's status codes mean, and
hand over the register link. It must not say a mark is clear — that is a legal
opinion, it stays AMBER, and the traffic light exists to refuse exactly this.

Renewal and watch-list scaffolding is acceptable. The determination is not ours.

**This is not scheduled.** It is recorded so that when it is built, it is built
to this shape. Assumption 1 still gates it.

---

## Sources

- Vidhi Centre for Legal Policy, *Rediscovering Discovery and Inspection*
  (consultation paper) — <https://vidhilegalpolicy.in>
- IP India, Public Search of Trade Marks —
  <https://tmrsearch.ipindia.gov.in/tmrpublicsearch/tmsearch.aspx>
- TeamLease RegTech — <https://teamleaseregtech.com/>
- Lexplosion / Komrisk — <https://lexplosion.in/compliance-management-software/>
- Avantis — <https://avantis.co.in/>
