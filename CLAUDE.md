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
                       obligations.py = duty -> how to close -> exposure, + IP screen
                       research.py    = the register searches a founder must run
  sources/validation.py  citation health: https, official host, whitelisted, not migrated
  sources/govapi.py    government verification APIs — the CALLER'S facts, never the law
  search/cascade.py    local-first retrieval: L0 matrix, L1 index, L3 recorded miss
  providers/           model-agnostic router: anthropic | openai | ollama | offline
  pipeline/            anti-truncation chunk assembly → Markdown → DOCX
  mcp/server.py        MCP stdio server exposing the same tools
data/jurisdictions/    one JSON file per isolated code path (IN-TG, IN-AP, IN-KL, …)
                       adding one: docs/ADDING_A_JURISDICTION.md — assume NOTHING
generated/             runtime output + audit vault (gitignored, never committed)
```

## Commands

```bash
make install      # venv + dev deps
make test         # ruff + pytest
make run          # uvicorn on :8000
make smoke        # end-to-end: audit + 20-page DOCX with the offline provider
make audit        # pip-audit against the pinned dependency set
make validate     # plugin manifests, tool schema portability, config examples
make validate-live # + a real MCP initialize / tools/list / tools/call
make sources-check # citations + the matrix itself: no foreign instrument prefixes,
                  #   no alias collisions, no section numbers or amounts in data
make sandbox      # isolated instance + minted token for a tester (docs/TESTING_PLAYBOOK.md)
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
6. **No local answer is an answer.** A retrieval miss is recorded as a coverage
   gap and returned as unanswered. It is never backfilled from the open web or
   from the model's own memory.
7. **Exposure is categorical.** "What happens if I don't" names kinds of
   consequence, never an amount, a limitation period or a section number.

8. **A token budget is not a safety dial.** `sections` may drop optional blocks;
   the lane, the halt notice, the counsel brief and every RED signal are
   unconditional.
9. **Tool schemas ship inlined.** No `$defs`/`$ref` — several function-calling
   runtimes ignore them, and the failure mode is an enum silently accepting
   any string.

10. **The citation is the product.** Legafy never states a rule, it points at the
    official page. A citation must be https, on a government host, on the
    whitelist that authorises it, and not on a migrated host. `make sources-check`
    in CI; `verify_source_health` for the agent.

11. **The court tier states doctrine, never authority.** `data/judicial_questions.json`
    carries what courts decide and how settled it is. No case name, no law-report
    citation, `authorities: []` until a reviewer has read the judgment on the
    court's own site. A fabricated citation is the worst thing this tool could emit.
12. **A verification is not a legal conclusion.** A government API can say a
    registration is live. It can never say anyone is compliant, never enters the
    grounding matrix, and never moves a lane.

13. **A state is compiled by hand, never by analogy.** The one thing that varies
    most between Indian states is which authority levies what, on which cycle —
    exactly what a copied file preserves. `make sources-check` fails on a foreign
    instrument prefix, but that is a backstop. Read `docs/ADDING_A_JURISDICTION.md`.
    When sources disagree on a title's year, OMIT the year and say why.

See `docs/ADDING_A_JURISDICTION.md` for how to add a state without assuming,
`docs/LEGAL_DATA_SOURCES.md` for the source hierarchy and what
machine-readable legal data actually exists in India,
`docs/POSITIONING_VS_LEGAL_PLUGIN.md` for how this sits next to Anthropic's
`legal` plugin, `docs/INSTALL_ANY_PLATFORM.md` for the two install paths,
`docs/LOCAL_TESTING.md` to run it on a Mac,
`docs/TESTING_PLAYBOOK.md` to hand to a tester (including one abroad), `SECURITY.md` for the audit findings and the assumptions this system
refuses to make, and `docs/SEARCH_DESIGN.md` for the retrieval cascade.

## Agent

Use the `legafy-python-dev` subagent for work under `app/**` and `tests/**`.
