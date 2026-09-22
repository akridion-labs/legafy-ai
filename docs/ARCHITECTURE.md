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

---

## Measured against the Dependency Rule (22 Sep 2026)

Scored by walking the real import graph, not by reading the layout. Script in
the commit that added this section; re-run it before believing this table.

| Diagnostic | Result |
|---|---|
| Business rules testable without DB, web server or framework | ✅ 221 tests run offline, no server, no key |
| All source dependencies point inward | ❌ **4 outward imports** |
| Database swappable without touching business logic | ⚠️ partial — `cascade` takes a store, but `get_store()` is a singleton |
| Use cases independent of delivery mechanism | ✅ `service.py` takes DTOs; one catalogue serves REST **and** MCP |
| Framework confined to the outermost circle | ❌ `docx` in `pipeline`, `httpx` in `sources` |
| Component graph cycle-free | ✅ measured: **no cycles** |
| Main wires all dependencies | ❌ use cases call `get_router()` / `get_audit_vault()` themselves |

**4 of 7 → roughly 7/10.** The half that holds is the half that earns its keep:
the use-case layer is genuinely delivery-independent, which is *why* adding the
MCP transport did not touch a single business rule, and why the same seven tools
serve HTTP and stdio from one definition.

### The four outward imports, and what each actually costs

| Import | Verdict |
|---|---|
| `service` → `providers.get_router()` | **Real.** Service locator inside a use case. |
| `service` → `security.get_audit_vault()` | **Real.** Same pattern. |
| `pipeline.assembler` → `providers.router` | **Real**, same root cause. |
| `sources.watcher` → `security.get_audit_vault()` | **Real**, and it is a *local* import inside a function — a lazy import to dodge a cycle is the smell that says the dependency points the wrong way. |
| `pipeline.renderers` → `docx` | **Mislabelled, not misbuilt.** Every docx import is function-local and confined to one module whose entire job is rendering. It is an adapter filed under `pipeline`. |
| `sources.watcher` → `httpx` | Same: an adapter filed under `sources`. |

So two of the six are my layer model being wrong about the folder names, and
four are one root cause: **dependencies are fetched, not injected.**

### The cost, made visible

`tests/test_api.py` calls **four** cache-reset functions in one fixture —
`reset_settings_cache`, `reset_audit_vault_cache`, `reset_tenancy_cache`,
`reset_router_cache`. Those functions exist in production code *only* so the
tests can undo a global. That is the bill for the service-locator pattern, and
it is the honest measure of what the violation costs today: about ten lines and
some fixture noise.

### Decision: not fixing this now

Injecting a `ProviderRouter` and an `AuditVault` through `service.py` and the
assembler is a real refactor across working, fully tested code — on a product
with **zero users and zero verified jurisdiction data**. A clean-architecture
refactor at this stage is the textbook shape of vanity engineering: it would
feel like progress and change nothing a customer can see.

Nothing on the near-term roadmap is blocked by it either. Swapping to Ollama on
the server is already a settings change. Adding a state is data. OAuth lives in
the outer circles. The violation is inert.

**Revisit when any of these becomes true**, and not before:

- A second application needs to reuse the use-case layer (then the globals bite).
- Provider selection has to vary *per request* — per tenant, per document type —
  rather than per process.
- Tests start needing more than a reset function to isolate a use case.
