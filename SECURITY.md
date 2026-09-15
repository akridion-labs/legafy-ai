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
make test      # ruff + the full suite, including tests/test_security.py
make audit     # pip-audit against BOTH requirements.txt and requirements-dev.txt
```

Any change to `app/security/**`, `app/sources/store.py`, `app/localisation.py`
or `requirements.txt` must re-run both, and update the table in §1 if a finding
class changes.

---

## 6. When an advisory lands

§2 covers the zero-days that come from our own assumptions quietly ceasing to
be true. This section covers the other kind: a vulnerability published against
a dependency we ship. The difference matters, because nothing in our code
changed and nothing in our tests will go red.

### The honest framing

You cannot "have zero-day protection". A zero-day is by definition a hole with
no patch yet, and anyone selling otherwise is selling something. What is
buildable is three separate properties, and it is worth being clear which one a
given control gives you:

| Property | What it means | What gives it |
|---|---|---|
| **We would know** | An advisory against a pinned dependency surfaces within a day, without anyone remembering to look | The nightly `audit` job in CI |
| **It could not reach much** | A compromised dependency has little to steal and nowhere to go | The controls in §3, plus the boundaries below |
| **It could not be swapped in** | Nobody can serve us a different artifact under a version we pinned | Hash pinning — *not yet done, see below* |

The first is the one that matters most and is the one that was missing.

### What was missing, and is now closed

`make audit` existed and nothing called it. CI ran ruff and pytest on push, so
the audit only ever happened when someone chose to run it by hand. **A repo
that is not being pushed to is a repo that has stopped looking**, and quiet
weeks are exactly when an advisory sits undiscovered.

CI now runs `pip-audit` against both requirement files on every push, on every
pull request, and **nightly at 01:00 UTC** whether or not anything changed. The
nightly job does not wait behind the test matrix — on a nightly run there is no
new code to test, and the question is whether the world changed under code that
was already green. On failure it opens a labelled issue rather than sending an
email nobody opens, because a response needs a thing with a state and an owner.

### The procedure

1. **Read what it actually is.** Which package, which advisory, and — the part
   people skip — *is the vulnerable code path one we reach?* A deserialisation
   bug in a parser we never call is not the same emergency as one in the HTTP
   stack. Write the answer down in the issue; it is the difference between a
   patch tonight and a patch this week.
2. **Check reachability against the boundaries in §3.** The process runs as a
   non-root user in a container with no compilers, binds loopback only, and on
   `AKRIDION-AI-01` has no inbound path from the internet at all. Most
   dependency advisories need an attacker to reach the process first.
3. **Bump the pin, do not float it.** Change the `==` to the fixed version. Never
   loosen to `>=` to make the audit pass — that trades a known problem for an
   unknown one, on every future install.
4. **Run the full gate before deploying**: `make test`, `make audit`,
   `make validate-live`, `make sources-check`.
5. **Verify the vault survived.** `make audit-verify` must still return `(True, …)`.
   A dependency bump should never touch the hash chain, and the one time it
   appears to is the time you want to know immediately.
6. **If there is no fix yet** — the actual zero-day case — record it in the issue
   with the date, the reachability finding from step 1, and the mitigation
   chosen (pin to the last unaffected version, disable the feature that reaches
   it, or accept with a stated reason and a review date). An accepted risk with
   a date is a decision. An accepted risk without one is an oversight wearing a
   decision's clothes.

### The first finding, worked through

The nightly job justified itself the hour it was written. Runtime dependencies
were clean; **development dependencies had never been audited at all**, and
carried a live advisory:

> `pytest` 8.3.4 — PYSEC-2026-1845. pytest through 9.0.2 on UNIX relies on
> directories with the `/tmp/pytest-of-{user}` name pattern, which allows local
> users to cause a denial of service or possibly gain privileges. Fixed in 9.0.3.

Step 1, reachability: it needs a **local** attacker on the same machine, and
pytest is not in `requirements.txt`, so it never enters the runtime image. On a
single-user Mac this is close to theoretical. On `AKRIDION-AI-01` it is not
theoretical at all — that box has the `akridion` account, the COO account, and
a partner account, so a predictable temp path is a real multi-user surface
whenever tests run there.

Step 3, the bump, which is where it got interesting: `pytest==9.0.3` is a major
version, and `pytest-asyncio==0.25.0` **cannot resolve against it** — the audit
itself failed with `ResolutionImpossible` rather than reporting clean. Both pins
moved together (`pytest-asyncio==1.4.0`), and `asyncio_mode = "auto"` was already
explicit in `pyproject.toml`, so the 1.x default change did not bite.

The lesson worth keeping: a security bump is a dependency bump, and the audit
passing is not the same as the install resolving. Run step 4 in full — the whole
gate came back green, including `make audit-verify` returning `(True, …)`.

### Still open, deliberately

**Hash pinning is not done.** `==` pins a version number, not an artifact: if
PyPI ever served different bytes under the same version, pip would install them
without complaint. `pip-compile --generate-hashes` closes that, and the command is:

```bash
pip install pip-tools
pip-compile --generate-hashes --output-file requirements.lock requirements.txt
.venv/bin/pip install --require-hashes -r requirements.lock   # verify BEFORE committing
```

It is not shipped here for one reason: this project installs on at least three
Python versions — 3.14 on the Mac, 3.11 in Docker, whatever is on the server —
and `pydantic-core` ships a different wheel for each. A hash file generated and
verified on only one of them is a broken `make install` waiting for whoever
tries the others, which is the same class of papercut as the missing exec bit
and the `make` that was never there. Generate it on the machine you deploy
from, verify the install on all three, then commit it. Until that is done, the
honest statement is "versions are pinned", not "artifacts are pinned".

**The Docker base image is pinned by tag, not digest.** Same reasoning, same
fix, and the command is in the Dockerfile's own comment. A digest I could not
resolve and verify is not a digest worth writing down.
