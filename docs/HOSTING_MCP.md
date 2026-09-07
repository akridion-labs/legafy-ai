# Hosting Legafy as a connector

Three ways people reach Legafy, in the order you should ship them.

| Path | Who | What they need from you |
|---|---|---|
| **1. Plugin marketplace** | Claude Code users on your team | a public/private git repo |
| **2. Custom connector** | your Claude subscription — claude.ai, Desktop, Cowork | a public HTTPS URL + a token |
| **3. ChatGPT connector** | your ChatGPT subscription | the same URL, plan permitting |

All three hit the same `/mcp` endpoint and the same guardrails.

---

## 0. What has to be true first

Legafy's remote MCP endpoint is Streamable HTTP at `POST /mcp`, mounted on the same
FastAPI process as the REST API. So "hosting the MCP server" is not a second deployment —
it is the deployment in `docs/DEPLOYMENT.md`, and the tunnel that already fronts it.

```bash
curl -s https://legal-mcp.akridion.com/healthz
curl -si -X POST https://legal-mcp.akridion.com/mcp | head -3
# expect: 401 + WWW-Authenticate: Bearer realm="legafy"
```

A 401 there is the correct answer — it proves the transport is live and refusing
anonymous callers. A 502 means the tunnel is up but the API is not; a connection error
means the tunnel is down.

---

## 1. Plugin marketplace (Claude Code)

This is the "add it like a marketplace" path. The repo is the marketplace:
`.claude-plugin/marketplace.json` at the root lists the plugin in `plugins/legafy/`.

```bash
/plugin marketplace add akridion-labs/legafy-ai
/plugin install legafy@akridion-labs
```

Claude Code then prompts for the two `userConfig` values declared in
`plugins/legafy/.claude-plugin/plugin.json`:

- **Legafy server URL** — `https://legal-mcp.akridion.com/mcp`
- **Legafy API token** — marked `sensitive`, so it goes to secure storage, not the repo

The plugin ships the `legal-idea-screen` skill alongside the connector, so a user who
installs it gets both the tools and the instructions for using them properly. Updating
the plugin is a `git push`; users get it with `claude plugin update legafy`.

Same flow works for a private repo — anyone with read access can add the marketplace.

---

## 2. Claude custom connector (your subscription)

Custom connectors using remote MCP are available on Free, Pro, Max, Team and Enterprise
plans, across claude.ai, Cowork and Claude Desktop. Free is limited to one custom
connector.

**Settings → Connectors → Add custom connector**, then paste the URL.

The catch: that dialog takes a URL, and optionally an OAuth client ID and secret. It has
no field for a static `Authorization` header. Two options today:

### Option A — URL-embedded token (works now)

```bash
# in .env on the server
LEGAFY_MCP_URL_TOKENS=true
```

Then give the connector:

```
https://legal-mcp.akridion.com/mcp/k/lgf_<token>
```

The server reads the trailing `/k/<token>` segment as the bearer token.

**Understand what you are trading.** That URL *is* the credential. It lands in browser
history, in any proxy or CDN access log, and in any screenshot of the settings pane. It
does not expire on its own. So: issue one token per person, never share the URL in a
group chat or a ticket, and rotate it the moment it goes anywhere you did not intend. For
your own single-operator use this is a reasonable trade. For customers it is not — ship
Option B before you sell this.

### Option B — OAuth with Dynamic Client Registration (the real answer)

Claude supports the MCP authorization spec with DCR enabled, and calls back to
`https://claude.ai/api/mcp/auth_callback`. A customer then clicks "Connect", authenticates
against *your* identity provider, and never handles a token at all — which is also what
makes per-customer revocation, expiry and audit real rather than a spreadsheet of URLs.

This is not built yet. It is the top infrastructure item on the roadmap, and it is the
gate between "I use this" and "customers use this".

### Claude Code, without the plugin

```bash
claude mcp add --transport http legafy https://legal-mcp.akridion.com/mcp \
  --header "Authorization: Bearer lgf_<token>"
claude mcp list          # should report connected
```

Claude Code can set headers, so it needs no URL token.

---

## 3. ChatGPT

ChatGPT connects only to remote MCP servers, so the same URL applies. Two things shape
what you get:

- **Plan.** Full MCP support including write actions is in beta on Business, Enterprise
  and Edu. Pro users can connect MCP servers with read/fetch permissions only — which
  means `execute_regional_compliance_audit` (a read) works, while
  `generate_legal_structure` (which writes files server-side) may not be offered.
- **Auth.** OAuth and OpenID Connect are supported. The URL-token workaround from Option A
  works here too, with the same caveats.

Enable **Settings → Connectors → Advanced → Developer mode**, add the connector with your
`/mcp` URL, and the three tools appear. `search`/`fetch` tools are no longer required, so
Legafy's tool set connects as-is.

If your ChatGPT plan will not expose the drafting tool, that is a platform limit, not a
server problem — the compliance screen, which is the valuable half, still works.

---

## 4. Every other platform

Anything that speaks JSON Schema function calling — Gemini, LangChain, LlamaIndex, n8n,
Zapier, your own backend — uses the HTTP tool API instead:

```bash
curl -s https://legal-mcp.akridion.com/tools | jq '.tools[].name'
curl -s -X POST https://legal-mcp.akridion.com/tools/execute_regional_compliance_audit/invoke \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"business_concept":"...","industry_vertical":"SaaS","state_location":"Telangana"}'
```

Same tools, same guardrails, no MCP client required. `docs/MCP_INTEGRATION.md` has the
copy-paste for OpenAI function calling.

---

## 5. Issuing tokens

```bash
TOKEN="lgf_$(openssl rand -hex 24)"
printf %s "$TOKEN" | shasum -a 256     # store the hash in data/license_registry.json
echo "$TOKEN"                           # hand this over once; it is never recoverable
```

The server stores `token_sha256` and never the token itself. Tier decides what the holder
can reach: `DEVELOPER_FREE` gets the compliance screen, `PREMIUM_HOSTED` and
`ENTERPRISE_B2B` also get document drafting. Scope is enforced per tool call, on both
transports — a free token that opens an MCP session still gets refused at
`generate_legal_structure`.

---

## 6. Before you hand the URL to anyone else

- [ ] `LEGAFY_ENV=production` and the posture check passes on boot
- [ ] Real `LEGAFY_TELEMETRY_SALT`; `/healthz` says `ok`, not `degraded`
- [ ] `LEGAFY_BOOTSTRAP_TOKENS_ENABLED=false` — the `akridion_dev_99x` demo tokens must be
      dead in production
- [ ] One token per person, hashes in the registry, the plaintext nowhere on the server
- [ ] `LEGAFY_RATELIMIT_BACKEND=redis` if you run more than one worker
- [ ] `generated/` backed up off-box, `make audit-verify` returning intact
- [ ] Jurisdiction files reviewed and promoted past `SEED_UNVERIFIED` for any state a
      paying user will actually rely on
