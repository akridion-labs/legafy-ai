# Legafy AI — repository guide for Claude Code

Model-agnostic **pre-counsel compliance scaffolding** engine by Akridion Labs.
Not a law firm. Output is not legal advice.

## Layout

```
app/
  main.py              FastAPI engine: HTTP + JSON-Schema tool endpoints
  config.py            env-driven settings, production posture checks
  models/schemas.py    Pydantic contracts — SINGLE source of truth for HTTP + MCP
  security/            tenancy (tiers, rate limits) + hashed append-only audit vault
  compliance/          grounding matrix, citation guard, traffic-light guardrails
  providers/           model-agnostic router: anthropic | openai | ollama | offline
  pipeline/            anti-truncation chunk assembly → Markdown → DOCX
  mcp/server.py        MCP stdio server exposing the same tools
data/jurisdictions/    one JSON file per isolated code path (IN-TG, IN-AP, …)
generated/             runtime output + audit vault (gitignored, never committed)
```

## Commands

```bash
make install      # venv + dev deps
make test         # ruff + pytest
make run          # uvicorn on :8000
make smoke        # end-to-end: audit + 20-page DOCX with the offline provider
make up / down    # docker compose stack (api + cloudflared [+ redis])
```

## Invariants — do not break these

1. **No fabricated law.** Section numbers, penalties and thresholds exist only
   in `data/jurisdictions/*.json` with a whitelisted `citation_url`, or not at
   all (`null` + `penalty_status: NOT_VERIFIED`).
2. **State isolation.** No cross-state fallback, no fuzzy state matching, no
   merging union instruments into a state block. Unmapped state → error.
3. **Fail closed.** Ambiguity resolves RED (halt, retain counsel).
4. **Pseudonymity at rest.** Business concepts are HMAC-SHA256 digested before
   any disk write or log line.
5. **Truncation is a bug.** Long-document paths must detect and continue.

## Agent

Use the `legafy-python-dev` subagent for work under `app/**` and `tests/**`.
