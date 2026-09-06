# Legafy AI

**Model-agnostic pre-counsel compliance scaffolding engine.** Akridion Labs LLP.

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

---

## Quick start

```bash
make install
make test                      # 74 tests, offline, no network
make run                       # http://localhost:8000/docs

# generate a real document with the offline provider — no API key needed
make smoke
```

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
data/jurisdictions/  one JSON file per isolated code path (IN-TG, IN-AP, …)
generated/           runtime output + audit vault — gitignored, back this up
```

## Docs

| | |
|---|---|
| [MCP & AI-platform integration](docs/MCP_INTEGRATION.md) | Claude Desktop, Claude Code, Cursor, OpenAI function calling, n8n |
| [Deployment](docs/DEPLOYMENT.md) | CPU server, Docker, Cloudflare Tunnel, GitHub repo setup |
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
