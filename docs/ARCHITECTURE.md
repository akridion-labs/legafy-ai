# Architecture

## Request path

```
MCP client (Claude Desktop/Code, Cursor)          HTTP client (OpenAI, n8n, your app)
        │  stdio                                          │  JSON Schema
        ▼                                                 ▼
   app/mcp/server.py  ─────────► app/tools.py ◄────── app/main.py
                                      │
                                      ▼
                                app/service.py            ← the only guardrail path
                     ┌────────────────┼────────────────┐
                     ▼                ▼                ▼
          compliance/registry   compliance/         security/
          (state isolation)     traffic_light       tenancy + telemetry
                     │           (halt or go)       (tiers, limits, vault)
                     ▼
              pipeline/assembler ──► providers/router ──► anthropic|openai|ollama|offline
                     │                                      (failover chain)
                     ▼
              citation_guard ──► renderers ──► Markdown + DOCX in generated/
```

Both transports funnel through `app/service.py`. That is deliberate: if MCP had
its own code path it could drift from HTTP, and a drift in a guardrail is a
compliance hole rather than a bug.

## The five guardrails

| Guardrail | Where | What it refuses |
|---|---|---|
| State isolation | `compliance/registry.py` | Cross-state fallback, fuzzy state names, union-over-state merging |
| Traffic light | `compliance/traffic_light.py` | Automated drafting on RED vectors |
| Citation guard | `compliance/citation_guard.py` | Section refs, penalties, off-whitelist URLs, commencement claims in model output |
| Absence by construction | `data/jurisdictions/*.json` | Storing a penalty or section at all until verified |
| Production posture | `config.py` | Booting with a template salt, bootstrap tokens or no registry |

## Two detection channels in the traffic light

Declared `activity_flags` are authoritative. A keyword scan of the free-text
concept is advisory — but a keyword hit that is *not* backed by a declared flag
still escalates the lane and is recorded as inferred. A founder who typed
"escrow" and forgot to tick the box gets stopped anyway.

Instrument-sourced signals only escalate when the caller's declared activity
actually triggers that instrument, and an obligation may narrow its parent's
trigger further (the Income-tax Act applies to any entity; its ESOP duty does
not apply to a venture with no equity in scope). Without that, an
under-declared request folds in the whole union catalogue and everything comes
out RED — which is not fail-closed, it is fail-useless.

## Anti-truncation loop

Per module: generate → if the stop reason is a token ceiling **and** something is
still missing, trim the dangling sentence and continue from the tail → repeat up
to `LEGAFY_CHUNK_CONTINUATIONS` → targeted repair pass for any clause heading
that never appeared → sanitize → stitch. A trailing 400 characters of the
previous module rides into the next prompt so clause numbering and defined terms
stay consistent.

The continuation loop stops as soon as every clause is present and the module
meets its word budget. Looping past that point is how a 20-page target becomes a
240-page one — it is guarded, and the guard is tested.

Generation is strictly sequential. Concurrency would cost clause-numbering and
defined-term continuity, and the wall-clock win is not worth it.

## Audit vault

Append-only JSON Lines at `generated/akrigon_audit_vault.json`, mode 0600. Each
record stores an HMAC-SHA256 digest of the business concept — never the text —
plus the jurisdictions, declared flags, lane, RED signal ids and outcome. Records
are hash-chained (`prev_hash` → `record_hash`), so `make audit-verify` detects
any post-hoc edit. Writes are fsynced under an asyncio lock.

## Where the seams are

- **Rate limiting** is per-process in memory. Multi-worker deployments need
  `LEGAFY_RATELIMIT_BACKEND=redis`.
- **Jurisdiction data** is loaded once at boot; adding a state needs a restart,
  not a rebuild.
- **The offline provider** produces structurally valid but generic prose. It
  exists to prove the pipeline, not to draft anything anyone should read.
