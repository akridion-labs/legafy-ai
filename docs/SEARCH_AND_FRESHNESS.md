# Search, freshness, language and the token budget

Four subsystems added on top of the compliance engine. They share one rule: none
of them may make Legafy more confident than its verified data allows.

---

## 1. Why legal *news* is not the answer

The instinct is to pipe a legal news feed into the answer. That would destroy the
product. News is fast, unverified and written to be interesting; Legafy's value
is that its statements are traceable to a primary source a human has read.

So the freshness engine never answers a compliance question. It runs a different
loop:

```
watched primary sources → fetch → text → content hash
        │
        ├─ unchanged → touch last_seen, done
        └─ changed   → magnitude + priority → REVIEW QUEUE (a human reads it)
                                                    │
                                       reviewer verifies → jurisdiction file updated
                                                           → answers change
```

A change never edits an answer by itself. It schedules a human. That is the whole
design, and it is the difference between a compliance tool and a headline feed.

### The ranking algorithm

```
review_priority = authority × magnitude × coverage × recency × exposure
```

| Term | What it is | Why |
|---|---|---|
| **authority** | gazette 1.0 · statute repo 0.95 · ministry/regulator 0.90 · state portal 0.85 · court 0.80 · aggregator 0.25 | A gazette notification *is* the law. An aggregator repeating it is a pointer to go read the gazette. |
| **magnitude** | trigram Jaccard distance vs the previous snapshot | A CMS re-render should not page a reviewer like a real amendment does. Whitespace reflow scores 0.0. |
| **coverage** | 1.0 if it touches a tracked instrument, else 0.4 | Untracked documents still queue — they may be a gap in our matrix — but below ones that change an answer we already give. |
| **recency** | halves every 30 days | Old unreviewed changes fade but never hit zero, so nothing is silently dropped. |
| **exposure** | `1 + ln(1 + audits touching that jurisdiction)` | Read from the audit vault, which stores jurisdiction codes in clear. **This is the term that makes the queue ours** — change affecting answers we actually gave outranks change affecting none. |

Anything below authority 0.80 is indexed for orientation but can never support a
compliance claim. `include_non_citable: true` surfaces those, clearly marked.

Run it: `python -m app.sources.watcher`. Crawling is refused for any host not
already on a jurisdiction file's whitelist, so the watcher cannot wander onto a
blog and bring back something that looks official. JavaScript-rendered portals
are recorded as `FETCH_UNSUPPORTED` rather than skipped, so the gap stays visible.

---

## 2. Query understanding: intent, tone, and the trie

### Intent vs tone — kept deliberately separate

**Intent** selects the tool and the answer shape: `screen_idea`,
`find_source`, `draft_document`, `penalty_or_threshold`, `deadline_or_timeline`,
`compare_jurisdictions`.

**Tone** changes delivery *only*: `urgent`, `worried`, `exploratory`,
`adversarial`, `neutral`.

> A worried founder and a curious one get the **same lane on the same facts**.
> The worried one gets it in the first sentence with the next step attached; the
> curious one gets the reasoning first. `tone_affects_verdict` is hard-coded
> `False` and asserted in the test suite, so the property is stated in the
> response rather than merely promised in a comment.

`adversarial` is the interesting one. Asking "is there a loophole to avoid
professional tax" is a legitimate question about where an obligation actually
bites. The delivery guidance answers the legal position without moralising and
without helping structure avoidance — and explicitly forbids softening a RED lane
because the user pushed back.

### The data structures

**Phrase trie** (word-level, longest-match) over jurisdiction names, aliases and
instrument titles. One pass over the question extracts entities in
O(n × longest phrase). Longest-match is what makes `andhra pradesh` resolve to
`IN-AP` as a unit instead of colliding on `andhra`. A 50-term vocabulary and a
50,000-term one cost the same, which is what makes the municipal layer and other
countries a data change rather than a rewrite.

**Inverted index + BM25** (SQLite FTS5) for the documents themselves. BM25 over
official prose is a strong baseline; the signal that actually matters here is
source authority, not semantic nuance, so final rank is `bm25_relevance ×
authority_weight`.

**Query expansion** bridges the vocabulary gap that makes plain keyword search
fail on government pages: founders write "hiring", "payroll", "office"; the
statute says "employment", "professional tax", "establishment". The expansion
table is a plain dict — reviewable, and wrong entries are obvious.

**Jurisdiction is a hard filter, never a ranking boost.** A Telangana search must
not surface an Andhra Pradesh notification at a lower rank. Softening that into a
score would quietly break the isolation contract everywhere else in the system,
so there is a test that fails if it ever does.

Everything except BM25 is a scored rule table, not a model: auditable, fast, and
when it misfires you can see which phrase did it. The classifier we would
eventually train has labels only because this one runs first.

---

## 3. The question corpus — training data the vault cannot be

The audit vault stores an HMAC digest of every business concept and never the
text. Right call for liability; it also means the vault **can never train
anything**. So the corpus is a separate, opt-in store.

**Stored:** the question (scrubbed), classified intent and tone, jurisdictions
touched, lane returned.

**Never stored:** tenant, token id, organisation, IP, session — any identifier
that could link two questions to one person. `record()` has no tenant parameter.
That is not an oversight: there is nowhere to put one, so no future edit casually
starts linking rows to a customer. A test asserts the schema has no identity
column.

**Scrubbed:** URLs, emails, phone numbers, Aadhaar/PAN/GSTIN/CIN patterns, bank
numbers, money amounts, social handles.

### The residual risk, stated plainly

Founders describe unlaunched ideas. "An app matching retired cricket coaches with
schools in Warangal" is not PII by any regex and is still commercially sensitive.
Scrubbing cannot fix that — only consent can. Hence: opt-in per request,
defaulting off; a 30-day cooling-off window before a row is exportable; and
`purge()`.

**Do not turn this on by default to grow the corpus faster.** A legal-tech
company that quietly harvests unlaunched startup ideas has a much larger problem
than a small corpus.

What to do with it, in order: **taxonomy analytics first** (`corpus.taxonomy()` —
which intents and jurisdictions dominate, which lanes fire; this tells you which
instruments to verify next), then an **activity-flag classifier** to catch the
under-declaration the keyword scan misses. A fine-tuned legal model comes last,
if at all — see `ROADMAP.md` §5.3 for why fluency is the wrong objective here.

---

## 4. Regional language — and the line around it

**Never translated:** instrument titles, statutory references, party names,
defined terms, and the operative text of any generated agreement.

A statute's title is its identifier. "తెలంగాణ దుకాణాలు మరియు సంస్థల చట్టం, 1988"
matches nothing on any portal and cannot be looked up. Contract operative text
stays in English because that is the language it is enforceable in — a bilingual
contract needs an explicit controlling-language clause to be safe.

**Translated:** the explanation layer — what the obligation means, why the lane
is what it is, the questions for the lawyer. That is where language access
genuinely changes who can use this, and where a wording slip is recoverable
rather than dangerous.

Every translated payload carries `machine_translated: true`, the provider that
did it, `controlling_language: "en"`, and `source_en` with the original for every
field changed — so a reader or a lawyer can always check the rendering.

`data/glossary/te.json` fixes the vocabulary so one concept does not get three
words across a document. It is marked `UNVERIFIED` and **needs a Telugu-speaking
reviewer** before the machine-translation banner comes off. Adding Hindi, Tamil
or Kannada is a new glossary file, not new code.

```jsonc
{ "state_location": "Telangana", "language": "te", ... }
```

Translation runs through the same provider router as everything else, so it is
model-agnostic. With no provider configured it returns English and says
`TRANSLATION_UNAVAILABLE` rather than guessing.

---

## 5. The token budget

An MCP tool result is pasted into the model's context on **every call**. The full
audit response was ~15,000 characters, and most of it was identical every time.

`detail: "compact"` (now the default) removes three kinds of noise:

1. **Static contract text** — the isolation contract, provenance warning and
   disclaimer are the same on every call, so they live in the tool description
   and MCP server instructions, which are sent **once per session**.
2. **Repeated proofs** — instruments are listed once in a `proofs` map; each duty
   references one by id instead of carrying a copy.
3. **Instrument-derived signals** — an AMBER signal generated from an obligation
   restates the duty it came from. Only risk-vector signals survive, because
   those carry information the duty list does not.

Measured over the live MCP transport:

| | chars | ≈ tokens |
|---|---|---|
| `detail: "full"` | 19,188 | 4,797 |
| `detail: "compact"` | 7,726 | 1,931 |
| **saved per call** | **11,462** | **~2,865 (60%)** |

Nothing decision-critical is dropped: every RED signal with its reasoning, the
halt notice, the counsel brief, the state traps and every proof pointer are kept
in full. A test asserts each of those survives compaction.

A **proof** is four fields — title, official URL, jurisdiction, verification
status. Enough to check the statement against its source, and nothing more. Prose
about an instrument is noise: the model can read the title, and the founder needs
the link, not a paraphrase.
