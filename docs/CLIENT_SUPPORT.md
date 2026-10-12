# Running Legafy from Codex, ChatGPT and anything else

Legafy is one server behind two transports. Which client you use changes the
config file and almost nothing else — the tools, the schemas, the hard cap and
the traffic-light halt are identical everywhere, deliberately, because a
guardrail that varies by client is not a guardrail.

This document covers: setting it up in Codex, setting it up in ChatGPT, the two
timeouts that actually bite, how to see which clients are calling, and what may
and may not be tuned per client.

---

## 1. Codex (CLI)

Codex reads MCP servers from **`~/.codex/config.toml`**. There is also a
per-project `.codex/config.toml`, but it only applies to projects Codex
considers trusted, so start with the user-level one.

```toml
[mcp_servers.legafy]
command = "/Users/deepakbanavathu/Desktop/Legafy Ai/legafy-ai/.venv/bin/python"
args = ["-m", "app.mcp.server"]
# Document assembly is 6 sequential model calls on a real provider chain.
# Codex's default tool timeout is 60s and would cut that off mid-document.
tool_timeout_sec = 600

[mcp_servers.legafy.env]
LEGAFY_MCP_MODE = "local"
LEGAFY_ENV = "development"
LEGAFY_PROVIDER_CHAIN = "offline"
LEGAFY_TELEMETRY_SALT = "local-dev-salt-change-before-production"
```

**No `cwd` key**, exactly as in the Claude Desktop config, and for the same
reason: `pip install -e .` puts `app` on the interpreter's path so the working
directory stops mattering. If you skipped that step, see
`docs/RUNBOOK_DEPLOY.md` §1 — the symptom here is an immediate startup failure
with no useful message.

### The two timeouts, and which one you actually need to change

| Setting | Codex default | Legafy's real number | Change it? |
|---|---|---|---|
| `startup_timeout_sec` | 10 s | **0.83 s** measured, 5 cold starts, max 0.88 s | **No.** Leave the default. |
| `tool_timeout_sec` | 60 s | audits are sub-second; `generate_legal_structure` is **6 sequential model calls** | **Yes** — raise it, or disable that one tool. |

The startup number is measured, not estimated: a cold `python -m app.mcp.server`
to a completed `initialize` runs in well under a second, of which 0.3 s is
importing `app.tools`. There is nothing to tune there and raising the limit
"to be safe" would only delay the error when something is genuinely broken.

The tool timeout is the one that matters, and only for document generation.
Every read-only tool answers in milliseconds.

### Recommended for a research workflow

If Codex is where you research and Claude is where you build — which is the
point of having both — then Codex does not need the drafting tool at all. Expose
only the read-only six and the 60-second question disappears:

```toml
[mcp_servers.legafy]
command = "/Users/deepakbanavathu/Desktop/Legafy Ai/legafy-ai/.venv/bin/python"
args = ["-m", "app.mcp.server"]
enabled_tools = [
  "execute_regional_compliance_audit",
  "search_legal_sources",
  "verify_registration",
  "verify_source_health",
  "list_supported_jurisdictions",
  "list_source_review_queue",
]

[mcp_servers.legafy.env]
LEGAFY_MCP_MODE = "local"
LEGAFY_ENV = "development"
LEGAFY_PROVIDER_CHAIN = "offline"
LEGAFY_TELEMETRY_SALT = "local-dev-salt-change-before-production"
```

`enabled_tools` is an allow list; `disabled_tools` is a deny list applied after
it. Dropping `generate_legal_structure` in Codex is a scoping choice, not a
safety one — the RED halt is enforced inside the tool and cannot be configured
away from the client side.

Approvals are set with `default_tools_approval_mode` (`auto`, `prompt`, `writes`,
`approve`), with per-tool overrides under `tools.<tool>.approval_mode`. Every
Legafy tool except `generate_legal_structure` declares `readOnlyHint: true`, so
`writes` is the sensible setting: grounding runs without interrupting you,
drafting asks.

### Other knobs worth knowing

- `required = true` makes Codex fail to start if Legafy cannot initialise. Useful
  on a machine where an ungrounded answer is not acceptable.
- `enabled = false` disables the server without deleting the block.
- `env_vars = ["NAME"]` forwards a variable from your shell instead of writing
  its value into the file — the right way to pass a real
  `LEGAFY_TELEMETRY_SALT` or an API key.

### Verify it

```bash
codex mcp list
```

Then ask Codex something that never mentions law, compliance or Legafy:

> I want to build a marketplace for local tutors in Telangana that holds the
> student's payment until the class is finished.

**It should call `execute_regional_compliance_audit` on its own and come back
RED on the escrow.** If it answers from its own knowledge without calling the
tool, the automatic-invocation contract is not holding in Codex — see §4.

---

## 2. ChatGPT

ChatGPT connects only to **remote** servers, so this is the Streamable HTTP
transport (`app/mcp/http.py`), not the stdio one:

```
URL:  https://<your-host>/mcp
Auth: Authorization: Bearer <token>
```

`docs/RUNBOOK_DEPLOY.md` §6 covers getting a public address, and §6a covers
testing HTTP compatibility locally with no public address at all — do that
first, it rules out every transport problem before a tunnel is involved.

Codex can also use a remote server (`url` plus a bearer token, OAuth, or
`codex mcp add <name> --url ...`), which is the better shape once the Akridion
server is running: one hosted engine, every client pointed at it, one vault.

---

## 3. Seeing which clients actually call

Every MCP client announces itself once, in the `initialize` handshake, as
`clientInfo: {name, version}`. Legafy records it on every vaulted call:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/api/v1/audit-vault/clients | python3 -m json.tool
```

```json
{
  "total_records": 12,
  "identified": 4,
  "unidentified": 8,
  "by_family": { "codex": 2, "claude-code": 1, "unknown": 1 },
  "by_name": { "Codex CLI 0.44.0": 2, "Claude Code 1.0": 1 },
  "lanes_by_family": { "codex": { "GREEN": 1, "RED": 1 } },
  "unmapped_names": { "some-agent-we-have-never-seen": 1 }
}
```

**`unidentified`** counts calls made before this existed, plus any client that
sends no `clientInfo`. Records written under schema version 1 have no client
fields and are not backfilled — the vault is append-only and hash-chained, so
rewriting history to improve a report is exactly the thing it exists to prevent.

**`unmapped_names` is the feature, not a defect.** `app/security/clients.py`
maps a self-reported name onto a family by substring. That table deliberately
contains only identifiers that have been *observed*. A client it does not
recognise is recorded as `unknown` **with its raw name intact**, which is how
you learn what Groq, Copilot or any new client actually calls itself — point it
at Legafy once, run one audit, read `unmapped_names`, add the row.

Do not add rows by guessing. A wrong mapping silently merges two clients'
usage and the report still looks plausible, which is worse than an honest
`unknown`. Ordering in that table is also load-bearing: Cursor reports itself as
`cursor-vscode` and Claude Code contains `claude`, so a generic row placed above
a specific one swallows it. `tests/test_client_attribution.py` pins both the
ordering rule and the known cases.

### What this is not

Client identity is **self-reported and unverified** — any client can send any
name. So it is usage evidence and nothing else. It never influences
authorisation, tier, rate limit, scope, or what any tool says about the law.
Access control stays with the bearer token (`app/security/tenancy.py`). Treat
the breakdown as a product metric, never as an access log.

The remote bridge (`LEGAFY_MCP_MODE=remote`) forwards the client that called
*it* as `X-Legafy-Client`, so a bridged call is attributed to Codex or Claude
rather than to the bridge process.

---

## 4. Tuning per client — what is legitimate, and what is not

Worth saying plainly, because "fine-tune per provider" can mean two very
different things and one of them would destroy the product.

### Never tunable per client

**What the law says, and whether a halt applies.** The lane, the RED halt, the
criminal and family hard cap, the citation guard, the refusal to state section
numbers. If Legafy gave a softer answer to one client than another, every
answer becomes unciteable, because "which client asked?" is not a legal
distinction. These are invariants in `CLAUDE.md` for this reason.

**Access.** Covered above: identity is self-reported.

### Legitimately tunable, per client

| Dimension | Why it differs | Where |
|---|---|---|
| Which tools are exposed | Codex for research needs no drafting tool | client config (`enabled_tools`) |
| Tool timeout | document assembly is 6 model calls | client config |
| Approval mode | read-only grounding should not prompt | client config |
| Default `detail` level | context budgets differ a lot between clients | server-side, **not yet built** |
| Wording of the invocation instruction | planners weight tool descriptions differently | server-side, **not yet built** |

The last two are real and currently **unbuilt on purpose**. Both would be tuned
against guesses right now, because until this release there was no record of any
client other than Claude ever calling the server. The breakdown in §3 is the
instrument that makes that tuning evidence-based rather than invented; collect a
week of real calls from Codex and Claude first, then tune.

The one tuning question worth answering early, because it is binary and
testable: **does the automatic-invocation contract hold outside Claude?**
Legafy's `SERVER_INSTRUCTIONS` and the `execute_regional_compliance_audit`
description both tell the model to call it unprompted when a user describes an
Indian venture. Claude Desktop honours server `instructions`; whether Codex
surfaces them to its planner at all is not documented and has not been tested.
If it does not, the fallback is to carry the instruction entirely in the tool
*description*, which every client reads — but confirm the behaviour before
changing anything, because the description is already long and padding it has
its own cost.

Run the tutor-escrow prompt in §1 against each client and record which ones call
the tool unprompted. That result belongs in this file.
