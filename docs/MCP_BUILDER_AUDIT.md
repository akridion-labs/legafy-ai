# Legafy against Anthropic's MCP server guidance

An audit of the MCP surface against the `mcp-builder` skill and Anthropic's
Connectors Directory submission requirements, run 9 September 2026. Six findings,
four fixed in code, two recorded as deliberate deviations with reasons.

The order matters: everything in the "fixed" list was found by reading the
guidance against the actual code, and one of them was a **hard blocker** for a
directory listing that nothing in the test suite would ever have caught.

---

## Fixed

### 1. No tool annotations — a directory submission blocker

Anthropic's submission requirements are explicit: *"All tools must include a
`title` and the applicable `readOnlyHint` or `destructiveHint`."* The submission
portal groups un-annotated tools separately and tells you to fix them on the
server before submitting. Legafy shipped none — `Tool(...)` carried a name, a
description and an input schema, and nothing else.

That is not only a paperwork problem. Annotations are how a client's planner
decides how freely to call something. An unannotated tool is treated as
potentially destructive, which suppresses exactly the call the whole product
depends on: the mandatory grounding audit.

`ToolSpec` now carries four flags, published on both transports:

| Tool | readOnly | idempotent | openWorld |
|---|---|---|---|
| `execute_regional_compliance_audit` | ✅ | ✅ | ✗ |
| `search_legal_sources` | ✅ | ✅ | ✗ |
| `list_source_review_queue` | ✅ | ✅ | ✗ |
| `list_supported_jurisdictions` | ✅ | ✅ | ✗ |
| `verify_registration` | ✅ | ✅ | ✅ government API |
| `verify_source_health` | ✅ | ✅ | ✅ fetches source URLs |
| `generate_legal_structure` | ✗ writes a file | ✗ | ✅ provider may be remote |

`destructiveHint` is false everywhere, and a test enforces that: nothing in
Legafy deletes or overwrites, and a client must never be told otherwise.
`title` is now sent too. `make validate` fails on a tool that ships without
annotations, so the next tool cannot regress this.

### 2. `verify_registration` could not be called the way its own description says

The description tells the caller to invoke it with no identifier to discover
which checks exist. `check` was a required field, so that documented call failed
schema validation *before the handler ran* — the discovery call needed the answer
it was there to discover. `check` now defaults to empty.

A plain-language mismatch between a description and a schema is the failure mode
these audits are for: every test passed, and the tool was still broken for the
one path a first-time user takes.

### 3. No structured content

The guidance asks for structured data alongside text. Every tool returned a
single JSON-in-a-text-block, so a client wanting `traffic_light.lane` had to
parse prose. Tool calls now return both: the text block, and `structuredContent`
carrying the same object.

This matters more here than in most servers — a client that can read the lane
programmatically can enforce the RED halt without trusting a model to notice it.

### 4. No pagination metadata

`search_legal_sources` and `list_source_review_queue` both took a `limit` and
returned no indication of whether anything was left behind. An agent that got ten
hits could not tell ten from ten-of-two-hundred. Both now return `returned`,
`limit` and `has_more`; the review queue also returns `total_pending`.

Implemented by asking the store for `limit + 1` and trimming — one extra row, no
second `COUNT` query.

---

## Deliberate deviations

### A. No `outputSchema`

The SDK hard-fails a call whose `structuredContent` does not validate against a
declared `outputSchema`. Legafy's failure branch returns a *different* shape on
purpose — the one carrying `"do not answer this question from your own knowledge
of Indian law."` Declaring an output schema would turn that graceful degradation
into a protocol error, and the client would see a broken tool instead of the
instruction not to improvise.

For a fail-closed legal tool that trade is backwards. `structuredContent` gives
clients the machine-readable payload; `outputSchema` adds a ratchet whose failure
mode is worse than the problem it solves. Revisit if the SDK gains a way to
declare a schema per outcome.

### B. Tool names keep no `legafy_` prefix

The guidance recommends a service prefix (`legafy_search_legal_sources`) so tools
do not collide when several servers are loaded together. Legafy does not, for two
reasons:

1. `execute_regional_compliance_audit` is named in the deployed project
   instructions and in the shipped skill. Renaming it silently breaks every
   installation that already tells a model to call it by name.
2. Prefixing all seven adds tokens to every session's tool list, and minimum
   token consumption is a stated product requirement.

Accepted risk: `verify_registration` and `search_legal_sources` are generic
enough to collide with another legal or registry server. If that is ever
observed in the wild, the fix is aliases — publish both names for one release,
then retire the bare one — not a hard rename.

---

## Also closed while in here

**DNS-rebinding / cross-origin guard.** The best-practice guidance asks HTTP MCP
servers to validate `Origin`. No MCP client sends one — Claude Desktop, Claude
Code and the hosted connectors all call server-side — but a browser always does.
On a machine that is also on a tailnet, a malicious page can resolve its own
hostname to a private address and POST to the endpoint with the victim's network
position. `POST /mcp/` now refuses any request carrying an `Origin` that is not
in `LEGAFY_MCP_ALLOWED_ORIGINS` (empty by default), before authentication and
before any handler runs.

**An evaluation set.** `evals/legafy_mcp_eval.xml` holds the ten question/answer
pairs the guidance asks for — all read-only, all with stable single-string
answers drawn from the shipped data. `tests/test_evaluation_set.py` re-derives
every answer from the live tools, so the eval file cannot quietly rot into
scoring a regression as a pass.

---

## Still open, and they are not code

These block a Connectors Directory listing and no amount of engineering closes
them. See `docs/DISTRIBUTION_AND_REVENUE.md` Part 1.

- **OAuth 2.0.** Legafy uses bearer tokens. The portal's *custom connection* path
  accepts user-supplied credentials, which fits — but OAuth with dynamic client
  registration is what a consumer listing wants.
- **A privacy policy at an HTTPS URL.** Its absence is called out as an immediate
  rejection.
- **A public documentation URL.**
- **A Claude Team or Enterprise organisation for Akridion Labs.** The submission
  portal lives in organisation settings and is not available on individual plans.
- **Reviewer test credentials** — mint with `scripts/sandbox.sh`, keep alive.

---

## Verification

```
181 tests passed          make test
ruff                      clean
85/85 integration checks  make validate-live
49 citations, 0 errors    make sources-check
```
