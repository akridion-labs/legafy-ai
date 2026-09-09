<img src="assets/legafy-logo.svg" alt="Legafy AI" height="52">

# Legafy AI

**Model-agnostic pre-counsel compliance scaffolding engine.** Akridion Labs.

Legafy analyses a startup concept against isolated Indian state-level regulatory
code paths, tells you plainly when to stop and hire a lawyer, and assembles
20+ page structural documents without truncating them.

> Legafy is not a law firm. It does not practise law. Its output is not legal
> advice and creates no attorney-client relationship. See
> [docs/LEGAL_DISCLAIMER.md](docs/LEGAL_DISCLAIMER.md).

---

## What makes it different

**State isolation.** Telangana and Andhra Pradesh are separate code paths, not
variations of one. There is no fuzzy matching and no nearest-neighbour fallback:
an unmapped state raises an error rather than getting a confident wrong answer.
Union instruments are returned in their own block and never merged into a
state's.

**No fabricated law.** Section numbers, penalty amounts, thresholds and
commencement dates are not stored — `penalty_schedule` is `null` and
`penalty_status` is `NOT_VERIFIED` until a human reads the primary source. A
citation guard strips anything statute-shaped out of model output before it
reaches a user. A test asserts this across every data file, so a fabricated
penalty fails CI.

**Fail closed.** Ambiguity resolves to RED — halt and retain counsel — not to a
plausible answer. RED blocks document generation outright and is not overridable
by argument.

**Anti-truncation assembly.** Long documents are generated module by module.
A truncated stop is detected, the dangling sentence trimmed, and generation
resumed; any clause that never appeared gets a targeted repair pass. Shipping a
short document is treated as a bug, not a degraded mode.

**Provider-agnostic.** Anthropic, OpenAI (or any OpenAI-compatible gateway),
local Ollama, and a deterministic offline drafter for CI and air-gapped runs.
First healthy provider in the chain wins; the rest are failover.

**Freshness without a news feed.** A watcher diffs whitelisted government sources
and files *review candidates* ranked by authority × change magnitude × coverage ×
recency × exposure. A change schedules a human; it never edits an answer by itself.

**Tone-aware, truth-invariant.** A phrase trie and a rule table read intent and
tone off the question. Tone changes delivery — ordering, brevity, what leads —
never the verdict. `tone_affects_verdict` is hard-coded False and tested.

**Cheap over MCP.** `detail: "compact"` (default) is 60% smaller per call:
static contract text moves into the session-level tool description, proofs are
deduplicated, and signals that merely restate a duty are dropped. Every RED
signal, halt notice and proof pointer survives.

---

## Use it from Claude

```bash
/plugin marketplace add akridion-labs/legafy-ai
/plugin install legafy@akridion-labs
```

That installs the connector *and* the `legal-idea-screen` skill that tells the model how
to use it. For claude.ai, Claude Desktop, ChatGPT and everything else, see
[docs/HOSTING_MCP.md](docs/HOSTING_MCP.md).

---

## Quick start

**Python 3.11 through 3.14 all work.** Every pin is pure Python except
`pydantic-core`, which ships `cp314` wheels.

```bash
make install
make test                      # 167 tests, offline, no network
make run                       # http://localhost:8000/docs

# generate a real document with the offline provider — no API key needed
make smoke
```

**No `make`?** It is not installed by default on macOS or Windows, and nothing
here needs it — these are the commands `make` runs:

```bash
python3 -m venv .venv                              # Windows: python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt      # Windows: .venv\Scripts\pip install -r requirements-dev.txt
.venv/bin/pytest -q                                # Windows: .venv\Scripts\pytest -q
.venv/bin/uvicorn app.main:app --reload            # Windows: .venv\Scripts\uvicorn app.main:app --reload
```

A venv keeps its programs in `.venv/bin/` on macOS and Linux and in
`.venv\Scripts\` on Windows — that difference is behind almost every "command
not found" after installing. [docs/TESTING_PLAYBOOK.md](docs/TESTING_PLAYBOOK.md)
§0.5–§0.6 covers which terminal to open (zsh, bash, Git Bash, WSL, PowerShell)
and maps every `make` target to its plain equivalent.

Live example:

```bash
curl -s -X POST localhost:8000/api/v1/audit \
  -H "Authorization: Bearer akridion_dev_99x" -H 'content-type: application/json' \
  -d '{"business_concept":"A payroll tool for small clinics with staff rostering.",
       "industry_vertical":"B2B SaaS","state_location":"Telangana",
       "activity_flags":["employs_persons","has_workplace_in_state"]}' | jq '.traffic_light.lane'
```

The bootstrap tokens above work in development only; production refuses to start
with them enabled.

---

## Layout

```
app/
  main.py            FastAPI engine: REST + JSON-Schema tool endpoints
  service.py         use cases shared by HTTP and MCP — one guardrail path
  tools.py           the tool catalogue; both transports read from here
  config.py          env-driven settings + production posture check
  models/schemas.py  Pydantic contracts (source of truth for both transports)
  security/          tiers, sliding-window rate limits, hash-chained audit vault
  compliance/        grounding matrix, citation guard, traffic-light matrix
  providers/         anthropic | openai | ollama | offline, with failover
  pipeline/          chunk plan → anti-truncation assembly → Markdown → DOCX
  mcp/server.py      MCP stdio server (local engine or remote bridge)
  mcp/http.py        remote MCP over Streamable HTTP — the connector endpoint
  compact.py         proof-without-noise response mode (60% fewer tokens)
  localisation.py    regional language for the explanation layer only
  search/            phrase trie, intent+tone classifier, opt-in question corpus
  sources/           primary-source index (FTS5), change detection, review queue
plugins/legafy/      Claude Code plugin: connector + legal-idea-screen skill
data/jurisdictions/  one JSON file per isolated code path (IN-TG, IN-AP, …)
generated/           runtime output + audit vault — gitignored, back this up
```

## Docs

| | |
|---|---|
| [Hosting & connectors](docs/HOSTING_MCP.md) | Plugin marketplace, Claude custom connector, ChatGPT, token issuing |
| [Search, freshness & language](docs/SEARCH_AND_FRESHNESS.md) | the ranking algorithm, the trie, the corpus privacy line, the token budget |
| [Roadmap](ROADMAP.md) | Verification, municipal layer, IP screening, the corpus question |
| [MCP & AI-platform integration](docs/MCP_INTEGRATION.md) | Claude Desktop, Claude Code, Cursor, OpenAI function calling, n8n |
| [Deployment](docs/DEPLOYMENT.md) | generic Linux server, Docker, Cloudflare Tunnel, GitHub repo setup |
| [Deployment — Akridion server](docs/DEPLOYMENT_AKRIDION_SERVER.md) | the real box: Win11 + WSL2 + RTX 5070, the F: drive trap, port map, why no tunnel goes on it |
| [Distribution & revenue](docs/DISTRIBUTION_AND_REVENUE.md) | what Claude and ChatGPT actually pay (nothing), and the five lines that do |
| [MCP builder audit](docs/MCP_BUILDER_AUDIT.md) | this server against Anthropic's MCP guidance: what was fixed, what was deliberately not |
| [Architecture](docs/ARCHITECTURE.md) | how the guardrails fit together |
| [Legal disclaimer](docs/LEGAL_DISCLAIMER.md) | positioning and UPL posture |
| [CLAUDE.md](CLAUDE.md) | repo guide for Claude Code, plus the invariants |

## Tiers

| Tier | Rate | Monthly | Scopes |
|---|---|---|---|
| `DEVELOPER_FREE` | 10/min | 500 | `audit` |
| `PREMIUM_HOSTED` | 60/min | 20,000 | `audit`, `generate` |
| `ENTERPRISE_B2B` | 1000/min | 1,000,000 | `*` |

## Status of the jurisdiction data

Every instrument currently ships as `SEED_UNVERIFIED`. The titles, years and
administering authorities are real and were compiled for routing; the section
numbers, thresholds and penalties are **deliberately absent**, not pending. Before
Legafy makes a compliance claim to a paying customer, a reviewer must work
through each file against its whitelisted primary sources and promote it to
`VERIFIED`. The schema is built to make that a data task, not a code change.

## Licence

Apache-2.0. See [LICENSE](LICENSE), including the no-legal-advice notice.
