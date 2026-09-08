# The Legafy Grounded Retrieval Cascade

How a question becomes a grounded answer, why the data structures are the ones
they are, how the legal team keeps the corpus current, and where a vector index
belongs — including why it is a named seam rather than a shipped layer today.

---

## 1. The design constraint everything else follows from

A general search engine optimises **recall**: show me everything that might be
relevant, I'll judge. A legal engine must optimise **provenance**: show me only
what you can prove, and say nothing where you cannot.

That inverts three normal instincts:

| Normal search | Legafy |
|---|---|
| Fuzzy-match the query so nothing is missed | Exact-match the jurisdiction; a near miss on state is a wrong answer, not a partial one |
| Rank by relevance | Rank by **authority × relevance**; a blog that matches perfectly still loses to a gazette that matches loosely |
| Always return something | Returning nothing is a valid, recorded outcome |
| Fall back to the web | The web is a restocking path behind a human, never an answer path |

Every structure below exists to serve that inversion.

---

## 2. The cascade

Four tiers, cheapest and most authoritative first. Execution stops at the first
tier that answers. Implemented in `app/search/cascade.py`.

```
question
   │
   ├─ L0  Instrument resolution ····· in-memory grounding matrix
   │        phrase trie + token overlap, jurisdiction-partitioned
   │        answers: "which law is this, and where is the official page"
   │
   ├─ L1  Local primary-source index  SQLite FTS5, BM25
   │        jurisdiction applied as a SQL filter BEFORE ranking
   │        answers: "show me the page behind that duty"
   │
   ├─ L2  Semantic recall ··········· SEAM — not built. §6.
   │
   └─ L3  Miss ······················ recorded as a coverage gap
            told to the caller as unanswered; never backfilled from the web
```

**L3 is the tier that matters.** Every legal-AI failure that has reached the
press is the same failure: no local answer, so the model produced one. Making
"we do not hold this" a first-class, *recorded* outcome is what prevents it —
and the miss log doubles as the crawl backlog, ordered by how many people hit
the same gap. Product roadmap as a side effect of honesty.

---

## 3. The data structures, and why each one

Nothing here is a structure for its own sake; each earns its place by making a
specific failure impossible or a specific path cheap.

**Phrase trie (word-level, longest-match) — `app/search/intent.py`.**
Multi-word legal phrases must beat their constituent words: "payment
aggregator" is not "payment" plus "aggregator", and "shops and establishments"
is one concept. A hash set of unigrams gets this wrong every time; a regex
alternation over hundreds of phrases backtracks. A trie walked once over the
token stream is **O(n) in the question, independent of how many phrases we
know** — so the phrase book can grow to thousands of entries without the
classifier getting slower. `__slots__` on the nodes because there will
eventually be a lot of them.

**Hash-partition on jurisdiction — `app/sources/store.py`.**
The partition is applied as a SQL `WHERE` before ranking, not as a score
adjustment after it. This is the single most important line in the search path:
as a boost, an Andhra Pradesh notification could out-rank a Telangana one on a
strong lexical match, and the product's core promise would fail *while looking
like it worked*. `test_jurisdiction_is_a_hard_filter_not_a_rank_boost` probes it
with FTS5 expressions designed to reopen it.

**Inverted index + BM25 (SQLite FTS5).**
Official prose is a near-ideal BM25 corpus: consistent vocabulary, no slang, no
SEO. Term saturation and length normalisation are exactly right for statutory
text. It is also stdlib — no search server, no new dependency, one file to back
up. A dense retriever would have to beat this before it earns its dependency,
and on this corpus it does not.

**Authority-weighted scoring.**
`score = bm25_relevance × authority_weight`, gazette 1.00 → aggregator 0.25,
with a citable floor at 0.80. Below the floor a document may orient a reviewer
and can never support a compliance statement. This is the ranking signal that
actually matters here, and it is the one a generic search engine does not have.

**Obligation DAG walk — `app/compliance/obligations.py`.**
`activity flags → instruments → obligations → domain playbook` is a directed
acyclic graph, traversed once per audit and memoised at the playbook layer. That
memoisation is why a thirty-obligation response carries seven remediation
paragraphs instead of thirty: the fan-in at the playbook node is where the
duplication lives, so that is where it is collapsed.

**Proof deduplication by instrument id.**
Instruments are emitted once into a `proofs` map and referenced by id from each
duty. Measured effect on a real MCP call: 60% fewer characters, no information
lost — every duty still resolves to a title, an official URL, a jurisdiction and
a verification status.

**Content-addressed change detection.**
SHA-256 for "did this move", trigram Jaccard for "how much". Order-insensitive
and stable against reflowed whitespace, so a CMS re-render does not page a
reviewer at the same priority as a substantive amendment.

**Review-priority scoring.**
`authority × magnitude × instrument_coverage × recency_decay × exposure`, with
recency as a 30-day half-life and exposure as `1 + log1p(hits)`. It decides
**what a human reads next** and never what a user is told.

---

## 4. Complexity, honestly

| Stage | Cost | Note |
|---|---|---|
| Intent + tone classification | O(n) in question length | trie walk, no model |
| L0 instrument resolution | O(m) instruments in the partition | m is a few hundred; a linear pass beats any index that has to stay in sync |
| L1 BM25 | O(log N) index seek + O(k) candidates | N = indexed documents |
| Obligation walk | O(instruments × obligations) | bounded by the matrix, not by input |
| Playbook fan-in | O(distinct domains) ≈ 7 | the memoisation that pays for itself |

No stage depends on model latency. A cached audit is a millisecond-scale
operation, which is what "immediate response" actually requires — not a faster
model.

---

## 5. How the legal team keeps this current

Three inboxes, all data — no code change, no redeploy:

1. **Change queue** (`list_source_review_queue` → `pending`). A watched primary
   source moved. Ordered by review priority. The reviewer reads the source and
   resolves the item `VERIFIED` / `NO_CHANGE_NEEDED` / `REJECTED`.
2. **Coverage gaps** (`list_source_review_queue` → `coverage_gaps`). Questions
   the corpus could not answer, ordered by how many people asked. This is the
   crawl backlog.
3. **Jurisdiction files** (`data/jurisdictions/*.json`). The law itself. Adding
   a state is one new file; adding an instrument is one new object. Section
   numbers and penalty amounts may be filled in **only** from the whitelisted
   `citation_url`, and only alongside flipping `penalty_status` to a verified
   value. Until then `null` / `NOT_VERIFIED` is what the API returns, which is
   the honest answer.

Per-obligation `how_to_close` and `if_ignored` overrides in the jurisdiction
file always beat the domain playbook, so a reviewer can make one duty more
specific without touching code.

The workflow is deliberately a **pull, not a push**: nothing a crawler finds
changes an answer until a named human has read the source and edited the data.
An auto-updating legal corpus is an auto-updating liability.

---

## 6. The vector layer — where it goes, and why it is not built yet

**Where it goes.** L2, between the lexical index and the miss. Same SQLite file
via `sqlite-vec` (a loadable extension, not a server), so the one-file backup
property survives. Retrieval is hybrid, fused by reciprocal rank:
`RRF(d) = Σ 1/(60 + rank_i(d))` over the BM25 and vector rankings — rank fusion
rather than score fusion, because BM25 scores and cosine similarities are not on
comparable scales and normalising them is a fudge factor nobody can justify to a
regulator.

**The jurisdiction partition still applies before both rankers.** A vector index
is not permitted to soften it. Semantic similarity across states is exactly the
failure mode this product exists to prevent, and embeddings are very good at
producing it.

**Why it is a seam and not a layer today.** The honest reason: on a corpus of a
few hundred official documents, approximate nearest-neighbour recall is slower
and less accurate than BM25, and it buys a model dependency for a system whose
entire value proposition is that it does not guess. Shipping it now would be
building the impressive part before the useful part.

**The trigger to build it**, written down so it is a decision and not a mood:

> \>5,000 indexed documents **and** a sustained L3 miss rate above 15%, where a
> sampled review shows the misses are *paraphrase* misses (the corpus holds the
> answer, the wording differed) rather than *coverage* misses (we simply do not
> have the document).

If the misses are coverage misses — which is what we expect first — the money
goes into crawling, not embeddings. A vector index over documents you do not
have retrieves nothing, beautifully.

**When it is built**, the embedding model runs locally (the Akridion server has
the GPU), so no question text leaves the box to be embedded. That constraint is
not negotiable and it rules out hosted embedding APIs.

---

## 7. What "understanding the tone" does and does not do

`app/search/intent.py` classifies the tone of a question — panicked, exploratory,
adversarial, procedural — and it changes **delivery only**: ordering, directness,
whether the counsel brief leads. `QueryAnalysis.tone_affects_verdict` is `False`
and is asserted in tests.

A frightened founder and a calm one asking the same question about the same
venture get the same lane. Softening a RED because someone sounds anxious is the
single most tempting and most damaging thing this system could learn to do.
