# Installing Legafy on any AI platform

There are exactly **two ways** to connect Legafy, and every platform supports at
least one of them. Pick by what the platform speaks, not by what it is called.

| | **Option A — Connect the server** | **Option B — Install the plugin** |
|---|---|---|
| What the user does | pastes a URL and a token | clicks install, then fills two fields |
| What it is | a remote MCP endpoint, or a stdio process | a packaged manifest that configures Option A for them |
| Where it lives | `https://your-host/mcp` | `.claude-plugin/marketplace.json` in this repo |
| Updates | you deploy, everyone gets it | you deploy; the manifest only changes for new config |
| Works on | anything that speaks MCP or JSON Schema | Claude Code today; the same manifest is the template elsewhere |
| Best for | teams, servers, CI, non-Claude platforms | individuals who should not have to think about URLs |

Both end at the same place: the five tools in `app/tools.py`, over the same
authenticated endpoint. Option B is Option A with the typing done for you.

---

## Option A — connect the server

### A1. Remote MCP over Streamable HTTP (the default, and the one to prefer)

One URL, one token, no install on the client machine.

```
URL:     https://legal-mcp.akridion.com/mcp/
Header:  Authorization: Bearer <your token>
```

Note the trailing slash. Without it Starlette answers `/mcp` with a 307 to
`/mcp/`; the MCP SDK follows redirects, but some clients do not, and a client
that does not follow gives you a silent empty tool list.

**Claude (web and desktop)** — Settings → Connectors → Add custom connector →
paste the URL. Add the bearer token when prompted for a header.

**ChatGPT** — Settings → Connectors → Advanced → Developer mode → add an MCP
server with the same URL and header. Developer mode accepts remote servers only,
which is why the HTTP transport is the primary one here.

**Cursor, Windsurf, VS Code, Zed, and anything else reading `mcp.json`** — see
`examples/mcp.json`, or use the HTTP form directly:

```json
{
  "mcpServers": {
    "legafy-ai": {
      "type": "http",
      "url": "https://legal-mcp.akridion.com/mcp/",
      "headers": { "Authorization": "Bearer ${LEGAFY_API_TOKEN}" }
    }
  }
}
```

### A2. Local stdio (development, and offline work)

The same tools, run as a subprocess on the machine. This is the mode to use when
testing changes to Legafy itself, because there is no deployment in the loop.
See `examples/claude_desktop_config.json`, and `docs/LOCAL_TESTING.md` for the
full runbook.

### A3. Platforms that do not speak MCP — use the JSON-Schema tool API

Every tool is published at `GET /tools` as a JSON-Schema manifest, and invoked
at `POST /tools/{name}/invoke`. Schemas are emitted with all `$ref`s inlined
precisely so that strict function-calling runtimes accept them unchanged.

```bash
curl -s https://legal-mcp.akridion.com/tools | jq '.tools[].name'

curl -s -X POST https://legal-mcp.akridion.com/tools/execute_regional_compliance_audit/invoke \
  -H "Authorization: Bearer $LEGAFY_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"business_concept":"marketplace for local tutors","industry_vertical":"marketplace",
       "state_location":"Telangana","activity_flags":["operates_digital_service"]}'
```

- **OpenAI function calling / Assistants** — each `tools[].input_schema` is a
  valid `parameters` object as-is.
- **Gemini / Vertex** — same, as a `FunctionDeclaration`.
- **LangChain, LlamaIndex, CrewAI** — either the MCP client adapters (Option A1)
  or `StructuredTool` built from `/tools`.
- **n8n, Make, Zapier** — an HTTP node against `/tools/{name}/invoke`.

There is no separate code path for any of these. `/tools`, `/mcp` and
`/api/v1/audit` all dispatch through the same handler, which is why REST and MCP
cannot drift apart.

---

## Option B — install the plugin

A plugin is a manifest that fills in Option A on the user's behalf. Two files:

```
.claude-plugin/marketplace.json        the catalogue (one per organisation)
plugins/legafy/.claude-plugin/plugin.json   the plugin (userConfig + mcpServers)
```

In Claude Code:

```
/plugin marketplace add akridion-labs/legafy-ai
/plugin install legafy@akridion-labs
```

The install prompts for the two `userConfig` fields the manifest declares — the
server URL and the API token — and writes them into the `mcpServers` block. The
token field is marked `sensitive`, so it is never shown in plain text.

The plugin also ships a skill (`plugins/legafy/skills/legal-idea-screen/`) that
tells the model *when* to call the grounding tool and how to present a RED
verdict. Tools without that instruction get called at the wrong moment; the
skill is the difference between "a tool exists" and "the tool is used correctly".

### Porting the plugin to another platform

The manifest is deliberately plain: two config fields and one HTTP server block.
For a platform with its own packaging format, copy those three facts across —
URL, Authorization header, and the tool list is discovered at runtime. Nothing
about the server assumes the Claude plugin format.

---

## Validate before you publish

```bash
make validate          # manifests, schema portability, config examples
make validate-live     # + a real MCP initialize / tools/list / tools/call
```

`scripts/validate_integration.py` catches the failures that are invisible until
someone tries to install: a marketplace entry pointing at a directory that does
not exist, a version mismatch between the catalogue and the manifest, a
`${user_config.x}` placeholder that was never declared (so the header ships
empty and every call 401s), a credential field not marked sensitive, and a tool
name or schema that some platform will reject.

To validate a deployed server rather than the local code:

```bash
python scripts/validate_integration.py --live \
  --url https://legal-mcp.akridion.com/mcp/ --token "$LEGAFY_API_TOKEN"
```

---

## Which token to issue

| Tier | Can screen ideas | Can draft documents | Can see the review queue |
|---|---|---|---|
| `DEVELOPER_FREE` | yes | no | no |
| `PREMIUM_HOSTED` | yes | yes | no |
| `ENTERPRISE_B2B` | yes | yes | yes |

Scope is enforced per tool on both transports — a free token calling
`generate_legal_structure` over MCP gets a 403, not a document. That is checked
by `tests/test_tenancy.py` and `tests/test_mcp.py`, because a paywall that only
exists on the REST path is not a paywall.
