# Legafy AI — MCP & AI-platform integration

Legafy exposes the same three tools over two transports. Both are served from
`app/tools.py`, so an MCP client and an HTTP client get identical guardrail
behaviour — a divergence between them would be a compliance hole.

| Transport | Who it is for | Entry point |
|---|---|---|
| **MCP (stdio)** | Claude Desktop, Claude Code, Cursor, Windsurf, Zed, any MCP host | `python -m app.mcp.server` |
| **HTTP + JSON Schema** | OpenAI function calling, Gemini, LangChain, LlamaIndex, n8n, Zapier, your own backend | `GET /mcp/tools`, `POST /mcp/tools/{name}/invoke` |

---

## 1. The tools

### `execute_regional_compliance_audit` — the grounding call
The mandatory first call. Resolves the named Indian state to its **isolated**
code path, returns union and state instruments in **separate blocks**, and
attaches a traffic-light verdict.

```jsonc
{
  "business_concept": "A payroll tool for small clinics, with staff rostering.",  // required, ≥12 chars
  "industry_vertical": "B2B SaaS",                                                // required
  "state_location": "Telangana",                                                  // required, must be mapped
  "entity_type": "private_limited",                                               // optional
  "activity_flags": ["employs_persons", "has_workplace_in_state"],                // optional but strongly advised
  "additional_states": ["Maharashtra"]                                            // optional; each resolved separately
}
```

Response shape (abridged):

```jsonc
{
  "isolation_contract": "The union block and the state block below are separate code paths…",
  "union":  { "code": "IN-CENTRAL", "instruments": [...] },
  "states": [ { "code": "IN-TG", "instruments": [...], "escalation_triggers": [...] } ],
  "traffic_light": { "lane": "AMBER", "automation_permitted": true, "red_lane": [], "counsel_brief": [...] },
  "source_whitelist": ["https://labour.telangana.gov.in", ...],
  "provenance_warning": "Instrument titles are seed metadata. Section numbers, thresholds and penalty amounts are intentionally not stored…",
  "disclaimer": "…not legal advice…"
}
```

**Note what is deliberately absent:** no section numbers, no penalty amounts, no
thresholds, no commencement dates. That is the anti-hallucination design. A
model must not fill those in from memory — the server-side citation guard strips
them from generated text, but a model answering in chat is on its honour, which
is why the server ships explicit instructions (below).

### `generate_legal_structure` — the 20+ page assembler
Runs the anti-truncation chunk pipeline and writes Markdown + DOCX into the
server's `generated/` directory. **Refuses to run if the traffic light is RED**,
returning `status: "HALTED_RED_LANE"`. That halt is not overridable by argument.

```jsonc
{
  "project_name": "Akridion Labs",
  "target_state": "Telangana",
  "framework_type": "founders_agreement",   // founders_agreement | employment_agreement | mutual_nda
                                            // | dpdp_data_policy | saas_terms_of_service | consulting_agreement
  "business_concept": "…",
  "activity_flags": ["employs_persons"],
  "parties": [{"name": "Deepak Banavathu", "role": "Founder"}],
  "output_formats": ["markdown", "docx"],
  "dry_run": false                          // true returns the clause plan without calling a model
}
```

### `list_supported_jurisdictions`
Which state code paths exist and their verification status. No arguments.

---

## 2. MCP over stdio

Two modes, same tools:

- **local** — the whole engine runs in the client's process. Nothing leaves the
  machine except your configured model provider's traffic.
- **remote** — a thin bridge that forwards each call to your hosted server over
  the Cloudflare tunnel. This is the Tier-1 distribution in the blueprint: the
  client is free and open-source, the grounding engine stays yours.

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or
`%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "legafy-ai": {
      "command": "/absolute/path/to/legafy-ai/.venv/bin/python",
      "args": ["-m", "app.mcp.server"],
      "cwd": "/absolute/path/to/legafy-ai",
      "env": {
        "LEGAFY_MCP_MODE": "local",
        "LEGAFY_ENV": "development",
        "LEGAFY_PROVIDER_CHAIN": "anthropic,offline",
        "ANTHROPIC_API_KEY": "sk-ant-…",
        "LEGAFY_TELEMETRY_SALT": "<openssl rand -hex 32>"
      }
    }
  }
}
```

Restart Claude Desktop. The tools appear under the connector icon.

### Claude Code

```bash
# local engine
claude mcp add legafy-ai --scope user \
  -- /abs/path/legafy-ai/.venv/bin/python -m app.mcp.server

# or the thin bridge to your hosted server
claude mcp add legafy-ai --scope user \
  -e LEGAFY_MCP_MODE=remote \
  -e LEGAFY_REMOTE_URL=https://legal-mcp.akridion.com \
  -e LEGAFY_API_TOKEN=lgf_… \
  -- python -m app.mcp.server
```

Or commit `.mcp.json` at the repo root to share it with the team — see
`examples/mcp.json`.

### Cursor / Windsurf / Zed
Same shape. Cursor reads `~/.cursor/mcp.json` or `.cursor/mcp.json`; the
`command`/`args`/`env` keys are identical to the Claude Desktop block above.

### Verifying a connection

```bash
make mcp          # runs the stdio server in the foreground; Ctrl-C to exit
npx @modelcontextprotocol/inspector python -m app.mcp.server   # interactive tool browser
```

---

## 3. HTTP tool API (non-MCP platforms)

```bash
curl -s https://legal-mcp.akridion.com/mcp/tools | jq '.tools[].name'
```

Returns each tool's JSON Schema, ready to paste into an OpenAI `tools` array:

```python
import httpx, openai

manifest = httpx.get("https://legal-mcp.akridion.com/mcp/tools").json()
tools = [
    {"type": "function",
     "function": {"name": t["name"], "description": t["description"],
                  "parameters": t["input_schema"]}}
    for t in manifest["tools"]
]

def call_legafy(name: str, args: dict) -> dict:
    r = httpx.post(f"https://legal-mcp.akridion.com/mcp/tools/{name}/invoke",
                   headers={"Authorization": f"Bearer {TOKEN}"}, json=args, timeout=600)
    r.raise_for_status()
    return r.json()["result"]
```

Gemini, LangChain and LlamaIndex all accept the same `input_schema` objects.
n8n and Zapier can hit `POST /mcp/tools/{name}/invoke` directly with a Bearer
header.

---

## 4. The system prompt your model needs

The MCP server advertises these instructions during initialisation, and hosts
that surface `instructions` will apply them automatically. For platforms that
do not, paste this into your system prompt:

```
Legafy AI is available as a compliance grounding tool.

1. Call execute_regional_compliance_audit BEFORE answering any question about a
   business concept's legal exposure in India. Do not answer from your own
   knowledge of Indian law.
2. Treat the `union` and `state` blocks as separate. Never merge them, and never
   apply one state's rule to another — Telangana and Andhra Pradesh are distinct
   code paths with distinct statutes, portals and authorities.
3. The response contains no section numbers, penalties or thresholds by design.
   Do not supply them yourself. If you cannot cite it from the tool output, say
   it is unverified.
4. If traffic_light.lane is RED, stop. Tell the user to retain counsel and do not
   draft the document.
5. Everything returned is structural scaffolding, not legal advice.
```

If a tool call fails, the server returns a failure envelope carrying the same
instruction — the model is told not to fill the gap from memory.

---

## 5. Auth and tiers

| Tier | Rate | Monthly quota | Scopes |
|---|---|---|---|
| `DEVELOPER_FREE` | 10/min | 500 | `audit` |
| `PREMIUM_HOSTED` | 60/min | 20,000 | `audit`, `generate` |
| `ENTERPRISE_B2B` | 1000/min | 1,000,000 | `*` |

`generate_legal_structure` needs the `generate` scope, so a free token gets 403
on it by design — that is the Tier-1 → Tier-2 upgrade boundary.

Mint a production token:

```bash
TOKEN="lgf_$(openssl rand -hex 24)"
printf %s "$TOKEN" | shasum -a 256      # store this hash in data/license_registry.json
echo "$TOKEN"                            # give this to the customer, once
```

The server stores `token_sha256`, never the token. Local stdio sessions in
`local` mode do not need a token; `remote` mode does.
