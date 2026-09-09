# Legafy and Anthropic's `legal` plugin

Anthropic ships a first-party `legal` plugin (v1.3.0). It is worth being precise
about what it is, because the instinct to treat it as a competitor leads to
building the wrong thing. Read properly, it is the strongest distribution
argument Legafy has.

---

## 1. What it actually is

An **in-house legal team productivity plugin**. Nine skills — `review-contract`,
`triage-nda`, `compliance-check`, `vendor-check`, `brief`, `legal-response`,
`legal-risk-assessment`, `meeting-briefing`, `signature-request` — connected to
Slack, Box, Microsoft 365, DocuSign, Jira.

Three facts from its own README decide everything below:

1. **It assumes you already have a legal team.** The core artefact is
   `legal.local.md`, a playbook *you write*: your standard positions,
   acceptable ranges, escalation triggers. The plugin is a very good executor of
   a playbook. It does not have one.
2. **It is US-default and says so.** "The default playbook examples reflect U.S.
   legal positions and jurisdictions (Delaware, New York, California). If you
   operate under different legal systems … you must customize the playbook."
3. **It has no legal data source at all.** Its connectors are business systems —
   chat, storage, e-signature, CRM. Not one is a statute, a gazette, or a
   regulator. Its `.mcp.json` contains no legal corpus because there isn't one
   to contain.

That third point is the whole analysis.

---

## 2. Where the gap is, precisely

`/compliance-check` is its skill nearest to ours. Asked "we want to add
biometric authentication to our mobile app", it produces a table:

```
| Regulation/Policy | Relevance | Key Requirements |
| [GDPR / CCPA / HIPAA / etc.] | [How it applies] | [What you need to do] |
```

Filled in from **the model's own knowledge**. There is no grounding call, no
citation URL, no jurisdiction resolution, no distinction between a rule in force
and a rule notified but not commenced. Ask it about Telangana and it will
answer — fluently, with the confident texture of the surrounding table, from
training data of unknown vintage.

That is not a criticism of the plugin. For a Delaware SaaS company with counsel
reviewing the output, model knowledge plus a human lawyer is a reasonable
system. It becomes dangerous exactly where Legafy operates: **an Indian founder
with no lawyer, where state law differs from state law and the model's answer
cannot be checked against anything.**

Side by side:

| | `legal` plugin | Legafy |
|---|---|---|
| Assumes a legal team | yes — it executes their playbook | no — it exists because there isn't one |
| Jurisdiction | US-default, "customise it yourself" | Indian states as isolated code paths, unmapped state refused |
| Where facts come from | the model, plus your playbook file | a versioned grounding matrix with a citation URL per instrument |
| Section numbers, penalties | model produces them | structurally absent until a human verifies them |
| Can it say "I don't know" | not really — the template wants a filled table | a recorded `L3_MISS`, returned as unanswered |
| Stage of work | you have a document, review it | you have an idea, what applies |
| Verifiability | prose | hash-chained audit vault, per-duty proof pointer, `verify_source_health` |
| Failure mode | a plausible wrong regulation | a refusal, or a lane you can check |

Both use a traffic light. Theirs is GREEN/YELLOW/RED for routing an NDA to a
human; ours is GREEN/AMBER/RED for whether automation may proceed at all. Same
vocabulary, different question.

---

## 3. So don't compete — be the layer it is missing

The plugin's design is explicitly tool-agnostic and connector-driven. It is
*built* to be pointed at capabilities it does not have. Legafy is one.

**The move: Legafy becomes the grounding call behind `/compliance-check` for
India.** Install both. When the question is Indian, the model has an actual tool
that returns instruments, obligations, categorical exposure and citation URLs,
instead of reaching into training data. The plugin keeps doing what it is good
at — reading the user's contracts, drafting redlines, chasing signatures — with
facts underneath it.

Three concrete things this implies, in effort order:

1. **Ship an India playbook fragment.** Their `legal.local.md` is the extension
   point and it is a markdown file. An audit response already carries every
   input: standard positions per domain, escalation triggers (our RED lane),
   acceptable ranges. Publishing a maintained `legal.local.md` India section is
   a day of work and it makes Legafy the default answer to "we're not in
   Delaware".
2. **Say the lane mapping out loud** in our skill file, so a model holding both
   plugins routes correctly: our RED is their "full legal review"; our AMBER is
   their "counsel review"; our GREEN plus `automation_permitted` is their
   "standard approval". Interoperating on vocabulary costs nothing and prevents
   two tools contradicting each other in front of a founder.
3. **Do not build contract review.** They do it well, against a playbook, over
   the user's own document store. Rebuilding it wins nothing and splits our
   attention from the one thing nobody else has: verified Indian state-level
   grounding.

---

## 4. What they have that we should copy

Reading a competitor honestly means naming what they do better.

- **The `legal.local.md` pattern is excellent.** One file, plain markdown,
  version-controlled with the user's own repo, where an organisation encodes its
  positions. We have `data/jurisdictions/*.json` for *law*, but nothing for a
  *firm's* preferences ("we never accept uncapped liability"). Worth having.
- **Graceful degradation is stated as a feature.** "The plugin gracefully
  degrades when tools are unavailable — it will note gaps and suggest manual
  checks." That is the same instinct as our `L3_MISS`, applied to connectors. We
  should be as explicit about it in our skill file as they are in theirs.
- **The workflow surface is broader.** Signature routing, meeting briefings,
  templated responses to DSARs. These are real jobs in a legal team's week that
  we do not touch and should not.
- **Persona-first documentation.** Their README opens with four personas and
  what each does with it. Ours opens with architecture. Theirs is the better
  README.

---

## 5. What we shipped after reading it

Not a list of intentions — these are in the repository:

- **`integrations/legal.local.india.md`** — a maintained India playbook
  fragment for that plugin's own extension point. Positions and escalation
  triggers, no section numbers, with a standing instruction that a live Legafy
  audit outranks the file. This is item 1 of §3, done.
- **Lane mapping in our skill file**, so a model holding both plugins routes
  RED → full legal review, AMBER → counsel review, GREEN → standard approval,
  instead of the two tools contradicting each other in front of a founder.
- **`verify_registration`** — the counterparty check their `/vendor-check`
  cannot do without a legal data source: GSTIN, Udyam, PAN and CIN against
  government APIs, with the result scoped in the payload itself so "the GSTIN is
  active" cannot be read as "this vendor is compliant".
- **Graceful degradation made explicit**, the way theirs is: no API key means
  the tool says NOT_CONFIGURED and hands back the manual search; a retrieval
  miss is `L3_MISS` and returned as unanswered. Both are stated in the skill
  file rather than left as behaviour someone discovers.

Still deliberately not built: contract review, redlining, signature routing.
They do those well and rebuilding them wins nothing.

## 6. The one-sentence version

Anthropic's plugin makes a legal team faster at the work it already knows how to
do. Legafy tells a founder who has no legal team what the work *is* — grounded
in a specific Indian state, with a citation for every claim and a refusal where
we do not know. The plugin is a very good mouth; it has no memory of the law.
We are the memory.
