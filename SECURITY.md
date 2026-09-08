# Security posture — Legafy AI

Legal software has an unusual threat model. The obvious risks (data theft,
account takeover) are real but ordinary. The risk that is specific to this
product is **a confident wrong answer**: an output that looks like law, is
wrong, and gets relied on. Most of what follows is aimed at that.

Report a vulnerability to the Akridion Labs engineering owner of this
repository. Do not open a public issue.

---

## 1. What the backtrack found, and what was done

An adversarial pass was run against the running application — not a code read,
eleven live probes against a booted server. Six real defects were found. All
six are fixed and each has a regression test in `tests/test_security.py`; the
test names below are the lock.

| # | Finding | Severity | Fix | Test |
|---|---------|----------|-----|------|
| 1 | **Path traversal via `language`.** `language="../license_registry.example"` reached a file outside `data/glossary/`. The difference between "parsed but wrong shape" and "no such file" was an enumeration oracle for what exists on disk. | High | `LANGUAGE_CODE_RE` allow-list plus a resolved-parent check in `load_glossary`. | `test_glossary_refuses_paths_outside_its_directory` |
| 2 | **FTS5 syntax reaching the parser.** `a OR` raised `sqlite3.OperationalError` out of the tool handler — a 500 with an internal message attached. Not SQL injection (parameters were always bound), but a crash oracle. | Medium | `sanitise_fts_query` quotes **every** token as a literal, so no user text is ever parsed as syntax; `MalformedQuery` is handled in the tool. | `test_malformed_queries_never_reach_the_fts_parser`, `test_sanitiser_quotes_operators_as_literals` |
| 3 | **Databases holding user text were `0644`.** `sources.db` and `question_corpus.db` were group- and world-readable on a shared host. | High | `os.chmod(path, 0o600)` at creation for all three stores. | `test_source_index_is_not_group_or_world_readable`, `test_question_corpus_is_not_group_or_world_readable` |
| 4 | **CORS wildcard on a bearer-token API.** `allow_origins=["*"]` let any website drive an authenticated endpoint from a user's browser. | Medium | No CORS middleware at all by default; `LEGAFY_CORS_ORIGINS` names explicit origins; `*` is refused at production boot. | `test_production_refuses_a_cors_wildcard` |
| 5 | **Latent crash in telemetry.** `traffic_light_lane.value` on a value that is sometimes already a string. | Low | `getattr(lane, "value", lane)`. | covered by `tests/test_telemetry.py` |
| 6 | **17 published advisories in pinned dependencies** (`mcp` 1.2.0, `starlette` 0.41.3 and transitives). | High | Bumped to `mcp==1.30.0`, `starlette==1.6.0`, `fastapi==0.141.1`, `pydantic==2.13.3`, `pydantic-settings==2.14.2`. Unused `slowapi` and `python-json-logger` removed entirely. `pip-audit -r requirements.txt` → **no known vulnerabilities**. | CI: `make audit` |

Two probed properties held and are now pinned by tests rather than left to
luck:

* **Fetched page bodies never reach a model.** A crawled page can contain
  "IGNORE ALL PREVIOUS INSTRUCTIONS"; it can never say that *to a model*,
  because the body is indexed for matching and is not a field of any result.
  Prompt injection through the source corpus is closed by construction, not by
  filtering. — `test_search_results_never_carry_page_bodies`
* **Jurisdiction is a hard SQL filter, not a rank boost.** No FTS5 expression
  reopens it. — `test_jurisdiction_is_a_hard_filter_not_a_rank_boost`

---

## 2. Assumptions this system deliberately refuses to make

Zero-day exposure in an application like this comes less from exotic bugs than
from assumptions that quietly stop being true. The ones we found ourselves
making, and closed:

1. **"The caller declared their activity honestly."** Under-declaration is now
   its own AMBER signal, so a sparse request is visibly sparse rather than
   silently clean.
2. **"An instrument that applies means all of its obligations apply."** False,
   and it produced an ESOP tax duty on an NDA. Obligations carry their own
   `applies_when`, filtered once in the registry so every consumer — ledger,
   traffic light, compact response — sees the same applicable set.
3. **"No answer means no risk."** Now an explicit `L3_MISS` outcome that is
   recorded as a coverage gap and shown to the caller as *unanswered*, never
   backfilled from the open web.
4. **"The model will respect the instruction not to invent section numbers."**
   Never assumed. `CitationGuard` strips statute-shaped tokens from generated
   text mechanically, and the grounding data contains no section numbers or
   penalty amounts to leak in the first place.
5. **"Anonymised means unlinkable."** The question corpus stores no tenant, and
   `record()` has no parameter that could accept one — the guarantee is
   structural, so a future edit cannot casually add linkage.
   `test_corpus_has_no_tenant_channel` fails if that changes.
6. **"A description without an email in it is not sensitive."** False: an
   unlaunched startup idea is commercially sensitive and no regex helps. Hence
   opt-in per request, a 30-day cooling-off window before a row is exportable,
   and `purge()`.

---

## 3. Standing controls

**Authentication and tenancy.** Bearer tokens resolve to a tenant with a tier,
scopes, expiry, per-minute rate limit and monthly quota. Over MCP the
authenticated tenant is carried in a contextvar and re-checked per tool, so a
free-tier token cannot reach a paid tool through the transport. Refusals are
typed: 401 invalid/expired, 403 scope, 429 rate/quota with `Retry-After`.

**Production posture gate.** The service refuses to boot in production with a
template telemetry salt, bootstrap tokens enabled, a CORS wildcard, or no
licence registry. Failing to start is the correct behaviour; a misconfigured
legal engine that serves traffic is worse than one that does not.

**Audit vault.** Every request appends an HMAC-SHA256 record to a hash-chained
JSON-Lines vault (mode `0600`), with `prev_hash` → `record_hash` so any deletion
or edit breaks the chain. `GET /api/v1/audit-vault/verify` checks it. Business
concepts are digested, never stored in clear.

**Data at rest.** `generated/` holds the vault and the three SQLite stores, all
`0600`, all excluded from git. On the Akridion server it must sit on a
POSIX-permission filesystem — never the exFAT drive, which cannot express these
modes.

**Egress.** The crawler fetches only whitelisted government hosts. The provider
router talks only to configured model endpoints. Nothing else is reached.

---

## 4. Residual risk, stated plainly

* **Seed data is unverified.** Instrument titles and years are routing metadata
  compiled by machine. `verification_status: SEED_UNVERIFIED` says so on every
  response. Until a lawyer signs each jurisdiction file off, the correct read of
  any output is "these are the questions", not "these are the answers".
* **Machine translation is machine translation.** The Telugu layer carries
  `machine_translated: true`, keeps English as the controlling version, and never
  touches statute titles or operative contract text.
* **A determined caller can still ignore the traffic light.** RED halts document
  generation, which is enforced server-side. It cannot stop someone reading an
  AMBER response and acting on it without counsel. That is a documentation and
  UX problem, not a technical one, and the disclaimer is on every payload.
* **We do not certify templates.** The generated drafts are structurally
  complete and formatted for execution. Whether a clause is *right for a given
  deal* is a lawyer's call, and Legafy says so rather than implying otherwise.

## 5. Running the checks

```bash
make test      # ruff + 138 tests, including tests/test_security.py
pip-audit -r requirements.txt
```

Any change to `app/security/**`, `app/sources/store.py`, `app/localisation.py`
or `requirements.txt` must re-run both, and update the table in §1 if a finding
class changes.
