# Running and testing Legafy on your Mac

Everything below runs on your machine. No server, no tunnel, no deployment.
You will test both install paths — the MCP server and the plugin — and read the
logs that prove which one actually fired.

## Python 3.14 works now

Your `python3` is 3.14.6. That used to be a blocker: `pydantic==2.10.4` had no
3.14 wheels. The security bump moved us to `pydantic==2.13.3`, whose
`pydantic-core==2.46.3` ships `cp314` arm64 macOS wheels, and every other pin is
pure Python. So use your system interpreter — no pyenv, no Homebrew Python.

Open **Terminal.app** (`Cmd-Space`, type "Terminal"). You get **zsh**. Then:

```bash
cd "/Users/deepakbanavathu/Desktop/Legafy Ai/legafy-ai"
python3 --version          # expect 3.14.x
```

Quote that path — "Legafy Ai" has a space in it, and without quotes zsh splits
it into two arguments and `cd` fails.

**If you have `make`:**

```bash
make install               # creates .venv and installs everything
make test                  # ruff + the full suite; expect 167 passed
```

**If `make: command not found`** — it is not installed by default on macOS. You
do not need it; these are the exact commands `make install` runs:

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q        # expect 167 passed
```

To get `make` anyway: `xcode-select --install` (Apple Command Line Tools).

A virtual environment keeps its programs in `.venv/bin/`, which is why every
command above is prefixed. Run `source .venv/bin/activate` once per terminal and
you can drop the prefix for the rest of that session.

If the install fails **on a wheel**, that is the one thing worth reporting — it
means a pin regressed, not that your Python is wrong.

`docs/TESTING_PLAYBOOK.md` has the same steps for Windows PowerShell, Git Bash
and WSL, plus a table of every `make` target and its plain equivalent.

---

## Step 1 — prove the engine works before involving Claude

```bash
make smoke            # or, without make:  ./scripts/smoke_test.sh
```

This runs an audit and assembles a 20+ page DOCX with the offline provider (no
API key, no network). It is the fastest way to know a problem is in the
integration rather than in the engine.

Then start the server and leave it running in its own terminal tab:

```bash
LEGAFY_LOG_LEVEL=DEBUG make run

# without make:
LEGAFY_LOG_LEVEL=DEBUG .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In a second tab:

```bash
curl -s localhost:8000/healthz | python3 -m json.tool
curl -s localhost:8000/tools | python3 -c 'import json,sys; print([t["name"] for t in json.load(sys.stdin)["tools"]])'
```

Seven tool names means the contract is live.

---

## Step 2 — validate the integration surface

```bash
make validate        # static: manifests, schemas, config examples
make validate-live   # + a real MCP initialize / tools/list / tools/call

# without make:
.venv/bin/python scripts/validate_integration.py
.venv/bin/python scripts/validate_integration.py --live
```

Run this before touching Claude. It fails on exactly the things that otherwise
show up as "the connector added but no tools appeared".

---

## Step 3 — Path A: add it as an MCP server

### A1. Claude Desktop, over stdio (recommended first test)

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "legafy-ai": {
      "command": "/Users/deepakbanavathu/Desktop/Legafy Ai/legafy-ai/.venv/bin/python",
      "args": ["-m", "app.mcp.server"],
      "cwd": "/Users/deepakbanavathu/Desktop/Legafy Ai/legafy-ai",
      "env": {
        "LEGAFY_MCP_MODE": "local",
        "LEGAFY_ENV": "development",
        "LEGAFY_LOG_LEVEL": "DEBUG",
        "LEGAFY_PROVIDER_CHAIN": "offline",
        "LEGAFY_TELEMETRY_SALT": "dev-salt-change-before-production"
      }
    }
  }
}
```

Use absolute paths — Claude Desktop does not expand `~` and does not inherit
your shell's `PATH`. Quit Claude Desktop completely (Cmd-Q, not just the window)
and reopen it. The tools appear under the connector icon.

Ask it: **"Screen this idea: a marketplace for local tutors in Telangana that
holds payments in escrow until a session finishes."**

You should see it call `execute_regional_compliance_audit` and come back RED on
the escrow.

### A2. Claude Code, over stdio

From inside the repo:

```bash
claude mcp add legafy-ai -- ./.venv/bin/python -m app.mcp.server
claude mcp list
```

### A3. Over HTTP, against your locally running server

With `make run` up, add a custom connector pointing at
`http://localhost:8000/mcp/` with header `Authorization: Bearer akridion_dev_99x`.

Some clients refuse plaintext `http://` for remote connectors. If yours does,
use the stdio route above for local testing and keep HTTP for the deployed
server behind the Cloudflare tunnel.

---

## Step 4 — Path B: add it as a plugin

In Claude Code:

```bash
/plugin marketplace add ~/Desktop/Legafy\ Ai/legafy-ai
/plugin install legafy@akridion-labs
```

Adding the marketplace from a **local path** is the point here — it installs
your working copy, so you are testing the manifest you are about to publish
rather than whatever is on GitHub.

The install asks for two values:

- **Legafy server URL** — `http://localhost:8000/mcp/` while testing
- **Legafy API token** — `akridion_dev_99x` (the dev bootstrap token, which is
  refused outright in production)

Then:

```bash
/plugin list          # legafy should be enabled
/mcp                  # legafy's seven tools should be listed
```

The plugin also installs the `legal-idea-screen` skill, so the model knows when
to reach for the grounding tool instead of answering from memory. Test that it
actually loaded by asking a legal question *without* naming the tool — if the
skill is working, the tool gets called anyway.

---

## Step 5 — cross-verify from the logs

Three independent records. If a call really happened, it is in all three.

**1. Server log** (the `make run` tab, at `LEGAFY_LOG_LEVEL=DEBUG`) — every
request with its `x-request-id`, the tenant that authenticated, and the tool.

**2. The audit vault** — the tamper-evident record, one line per call:

```bash
tail -3 generated/akrigon_audit_vault.json | python3 -m json.tool
make audit-verify
# without make:
.venv/bin/python -c "from app.security.telemetry import get_audit_vault; print(get_audit_vault().verify_chain())"
```

`make audit-verify` recomputes the hash chain end to end. `(True, ...)` means no
record has been edited or removed since it was written. Note what the vault does
*not* contain: your business concept in clear text. Only its keyed digest, by
design.

**3. Which lane came back** — the vault's `traffic_light_lane` should match what
Claude told you on screen. If Claude said "you're fine" and the vault says RED,
that is the bug worth reporting: the model is talking over the tool.

For the stdio path there is no HTTP log, so the vault is the record. Claude
Desktop's own MCP log is at:

```bash
tail -f ~/Library/Logs/Claude/mcp-server-legafy-ai.log
```

### The quick cross-check, end to end

```bash
# before
wc -l generated/akrigon_audit_vault.json
# ... ask Claude to screen an idea ...
# after
wc -l generated/akrigon_audit_vault.json          # +1
tail -1 generated/akrigon_audit_vault.json | python3 -m json.tool | grep -E 'lane|jurisdiction|event'
make audit-verify                                  # chain still intact
```

One new line, the lane matching what you were shown, chain intact. That is the
whole verification.

---

## When it does not work

| Symptom | Cause | Fix |
|---|---|---|
| Connector added, no tools | trailing slash, or the client did not follow the 307 | use `/mcp/` |
| `401 invalid_token` | token missing from the header | check the plugin's token field was actually filled |
| `403 insufficient_scope` | free tier calling the drafting tool | expected — that is the paywall working |
| Claude Desktop shows nothing | relative path, or app not fully quit | absolute paths, Cmd-Q, reopen |
| `ModuleNotFoundError: app` | `cwd` not set in the config | set `cwd` to the repo root |
| Everything comes back RED | no `activity_flags` declared | declare what the product actually does |
| `make: command not found` | not installed by default on macOS | you do not need it — use the plain commands above, or `xcode-select --install` |
| `pytest: command not found` | calling the system pytest, not the venv's | use `.venv/bin/pytest`, or `source .venv/bin/activate` first |
| `cd: no such file or directory` | the space in "Legafy Ai" split the path | quote it: `cd "/Users/.../Legafy Ai/legafy-ai"` |
| install fails on a wheel | a pin regressed for 3.14 | report it — do not switch Python |

## Resetting between tests

```bash
rm -rf generated/*.db          # search index, question corpus, miss log
# Leave generated/akrigon_audit_vault.json alone: it is append-only and
# hash-chained on purpose. Deleting it destroys the record you are verifying.
```
