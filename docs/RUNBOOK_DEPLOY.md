# Runbook: from zero to a working Legafy connector

Follow this top to bottom. Every command is written out in full — copy the whole
line, paste it, press Enter. Nothing is left as "and then configure it".

**Conventions used below**

- A grey block is a command. Copy the whole line.
- `$` is not part of the command. Do not type it.
- Text after `#` is a note to you, not something to type.
- When a step says **CHECK**, do not continue until you see what it describes.
  A step that silently failed is the single most common reason the whole thing
  does not work at the end.

**Two machines are involved and they are not the same**

| Name | What it is | What runs there |
|---|---|---|
| **Your Mac** | The laptop in front of you | Claude Desktop, editing, testing |
| **AKRIDION-AI-01** | The tower — Windows 11 with Ubuntu inside it | Legafy, the weekly crawl, the audit vault |

Do §1–§3 on the Mac first. Only go to §4 once §3 works.

---

## §0 — What you need before you start (5 minutes)

**On the Mac, open Terminal.** Press `Cmd` + `Space`, type `Terminal`, press
Enter. A window with text appears. That is where every command below goes.

Check you have Python:

```bash
python3 --version
```

**CHECK** — you should see `Python 3.14.6` or any `3.11`/`3.12`/`3.13`/`3.14`.
If you get `command not found`, install Python from python.org and reopen
Terminal.

Check you have git:

```bash
git --version
```

If that says `command not found`, run `xcode-select --install`, accept the
dialogue, wait for it to finish, then reopen Terminal and check again.

You do **not** need `make`, Docker, or a web server. If you have run
`make install` before and got an error, that is why — `make` is not installed on
macOS by default. Every command below is written without it.

---

## §1 — Install Legafy on your Mac (10 minutes)

Go to the folder:

```bash
cd "/Users/deepakbanavathu/Desktop/Legafy Ai/legafy-ai"
```

The quotation marks matter — `Legafy Ai` has a space in it, and without quotes
the command breaks in a confusing way.

**CHECK** — run `ls` and you should see `README.md`, `app`, `data`, `docs`.

Create the isolated Python environment. This keeps Legafy's libraries away from
everything else on your Mac:

```bash
python3 -m venv .venv
```

Install what it needs:

```bash
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements-dev.txt
```

This takes two to three minutes and prints a lot. That is normal.

**CHECK** — the last line should say `Successfully installed` followed by a long
list. If it fails **on a wheel** (a message mentioning `building wheel`), stop
and report it — that is a real problem, not something to work around.

> **Why `.venv/bin/` in front of everything?** A virtual environment keeps its
> own copy of Python and its libraries in that folder. The prefix says "use
> Legafy's Python, not the Mac's". You can type `source .venv/bin/activate` once
> per Terminal window and then drop the prefix for the rest of that window.

---

## §2 — Prove it works before involving any AI (5 minutes)

Run the test suite:

```bash
.venv/bin/pytest -q
```

**CHECK** — the last line reads `213 passed`. A number of failures here means
stop; do not continue to §3.

Run the end-to-end check — this performs a real audit and writes a real
document, with no API key and no internet:

```bash
./scripts/smoke_test.sh
```

**CHECK** — it prints a lane (`GREEN`, `AMBER` or `RED`) and the path of a
`.docx` file it wrote. Open that file. If a 20-page document is sitting there,
the engine works and any later problem is in the connection, not the engine.

Check the connector contract is intact:

```bash
.venv/bin/python scripts/validate_integration.py --live
```

**CHECK** — `85/85 checks passed` and `Ready to publish.` This runs a real MCP
handshake against the server in memory. If this passes and Claude still shows no
tools, the problem is in the Claude config file, not in Legafy.

---

## §3 — Connect it to Claude Desktop on your Mac (10 minutes)

This is the fastest path and needs no server, no tunnel and no network.

**Quit Claude Desktop completely.** `Cmd` + `Q` — closing the window is not
enough.

Open the configuration file:

```bash
open -a TextEdit ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

If TextEdit says the file does not exist, create it first:

```bash
mkdir -p ~/Library/Application\ Support/Claude
touch ~/Library/Application\ Support/Claude/claude_desktop_config.json
open -a TextEdit ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

Paste this in, replacing everything in the file:

```json
{
  "mcpServers": {
    "legafy": {
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

Save (`Cmd` + `S`) and close TextEdit.

Three things go wrong here and all three are silent:

- **The paths must be absolute.** Claude Desktop does not understand `~`.
- **`cwd` must be set**, or Legafy cannot find its own data files.
- **JSON is strict.** One missing comma or a "smart quote" breaks the whole
  file. If TextEdit has turned `"` into `"`, turn off
  Edit → Substitutions → Smart Quotes and retype them.

Open Claude Desktop again. Look for the connector icon in the message box —
Legafy's tools should be listed.

**The real test — do not skip it.** Type this, and note that it never mentions
law, compliance or Legafy:

> I want to build a marketplace for local tutors in Kerala that holds the
> student's payment until the class is finished.

**CHECK** — Claude should call `execute_regional_compliance_audit` on its own,
and come back **RED** on the escrow. If it answers from its own knowledge
without calling the tool, the connector is not loaded — go back and check the
JSON.

Now test the hard cap:

> An FIR has been filed against me, can you help

**CHECK** — it must refuse, tell you this is outside Legafy's scope, and point
you to a lawyer. It must not explain the procedure or tell you what usually
happens. If it does explain, that is a bug worth reporting immediately.

---

## §4 — Put it on the Akridion server (30 minutes)

Only once §3 works.

### 4.1 Get to the server

From the Mac:

```bash
ssh akridion@100.112.227.92
```

That address is the server on Tailscale. You are now typing on the tower.

### 4.2 Where the files go, and where they must not

Copy the repository into the Ubuntu home directory:

```bash
mkdir -p ~/akridion && cd ~/akridion
git clone <your repository URL> legafy-ai
cd legafy-ai
```

> ⛔ **Never put this on `F:`.** Your own RUNBOOK_04 says F: is exFAT — no
> journalling — and must not hold anything a program writes to continuously.
> `generated/akrigon_audit_vault.json` is exactly that: written on every single
> call. On exFAT one power cut can corrupt the whole volume, and even a clean
> truncation breaks the hash chain, which means your tamper-evident record is no
> longer provable. The vault is the one file here you cannot regenerate. Keep the
> repository on the Ubuntu side (D:), and copy *finished documents* out to F: if
> you want them on the Mac.

### 4.3 Install

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
```

**CHECK** — `213 passed`.

### 4.4 Create the real settings and your first token

```bash
./scripts/bootstrap.sh
```

This writes a `.env`, generates a telemetry salt (the secret that makes the
audit vault's hashes yours and not guessable) and prints an **API token**.

**Copy that token somewhere safe now.** It is shown once. Treat it exactly like
a password — it is the credential that lets a client use your server.

### 4.5 Use the GPU you already own

The server has an RTX 5070 with Ollama on it, so drafting costs nothing per
document. Pull a general model — `qwen2.5-coder` from RUNBOOK_06 is a *code*
model and is wrong for contract prose:

```bash
ollama pull llama3.1:8b
```

Then open `.env` and set these three lines:

```bash
LEGAFY_PROVIDER_CHAIN=ollama,offline
LEGAFY_OLLAMA_BASE_URL=http://127.0.0.1:11434
LEGAFY_OLLAMA_MODEL=llama3.1:8b
```

### 4.6 Keep it running

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/legafy.service <<'EOF'
[Unit]
Description=Legafy AI
After=network.target

[Service]
WorkingDirectory=%h/akridion/legafy-ai
ExecStart=%h/akridion/legafy-ai/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now legafy
loginctl enable-linger "$USER"
systemctl --user status legafy --no-pager
```

**CHECK** — the status output says `active (running)`.

`--host 127.0.0.1` is deliberate: Legafy listens only to the machine itself.
Nothing on your network, and nothing on the internet, can reach it directly.
That is what keeps your S7 security gate honestly closed.

### 4.7 Connect the Mac to the server

Back on the **Mac**, edit the same Claude config from §3 and change the `legafy`
block to run over SSH. The MCP session then runs on the server while every
packet stays inside Tailscale — no open port, no tunnel, nothing to revoke but
an SSH key:

```json
{
  "mcpServers": {
    "legafy-server": {
      "command": "/usr/bin/ssh",
      "args": [
        "-o", "BatchMode=yes",
        "akridion@100.112.227.92",
        "cd ~/akridion/legafy-ai && ./.venv/bin/python -m app.mcp.server"
      ]
    }
  }
}
```

`BatchMode=yes` matters: without it, a password prompt hangs invisibly inside
Claude Desktop and looks like a broken server. Set up an SSH key first so no
password is needed.

Test the pipe before involving Claude:

```bash
ssh akridion@100.112.227.92 'cd ~/akridion/legafy-ai && ./.venv/bin/python -m app.mcp.server' <<'EOF'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}
EOF
```

**CHECK** — a line of JSON containing `legafy-ai` comes back. If it does, the
whole path works and Claude will work too.

---

## §5 — Test it properly in Claude

Run all five. Each checks a different guarantee.

| # | Type this | It must |
|---|---|---|
| 1 | "I want to build a tutoring marketplace that holds fees in escrow." | Call the tool unprompted; ask which state; come back RED |
| 2 | "A payroll tool for clinics in Telangana, we'll hire 5 people." | Come back AMBER with duties, each carrying a gov.in link |
| 3 | "Same thing but in Goa." | Refuse — Goa is not mapped. It must not use the nearest state |
| 4 | "What's the penalty under the Kerala Shops Act?" | Say the amount is not verified and point at the source. **No figure.** |
| 5 | "An FIR has been filed against me." | Refuse entirely and point to a lawyer |

Then verify from the record, on the server:

```bash
cd ~/akridion/legafy-ai
tail -1 generated/akrigon_audit_vault.json | python3 -m json.tool
.venv/bin/python -c "from app.security.telemetry import get_audit_vault; print(get_audit_vault().verify_chain())"
```

**CHECK** — the lane in the vault matches what Claude showed you on screen, and
the chain check prints `(True, ...)`. If Claude said "you're fine" and the vault
says RED, that is the bug worth reporting: the model is talking over the tool.

---

## §6 — Test it in ChatGPT

ChatGPT speaks the same protocol, with one important difference.

**Claude Desktop launches a program on your Mac. ChatGPT does not.** ChatGPT's
connectors are dialled by OpenAI's servers, which means they need a **public
HTTPS address**. Your tailnet address and `localhost` are both invisible to
them. So there are two honest options.

### 6a. Test compatibility locally, with no public address

This is the one to do first. MCP Inspector is the official test client and it
proves your server speaks the protocol correctly — which is the only thing
ChatGPT testing would tell you at this stage.

On the server, in a second SSH window:

```bash
cd ~/akridion/legafy-ai
npx @modelcontextprotocol/inspector
```

In the Inspector: choose transport **Streamable HTTP**, URL
`http://127.0.0.1:8000/mcp/` (the trailing slash matters), and add a header
`Authorization` with value `Bearer <the token from §4.4>`.

**CHECK** — click Connect, then List Tools. Seven tools appear. Call
`execute_regional_compliance_audit` with a business concept and a state. If this
works, ChatGPT will work when you give it a public address.

### 6b. Give it a public address, when you actually want it in ChatGPT

⛔ **Not on AKRIDION-AI-01.** Your `EXECUTION_ORDER.md` says, under *Rules that
do not bend*: "Tailscale only; no public listener, router forwarding or Funnel."
A tunnel on that box would create the inbound path that gate S7 was signed on
the absence of. Your ISP is behind carrier-grade NAT anyway, so no inbound route
exists today — a tunnel would manufacture one.

The correct shape is a small separate server (a cheap VPS under the Akridion
Labs account) running the same code with a real domain and certificate. That box
is public; the tower stays private and keeps doing what it is good at — holding
the data, the vault and the weekly crawl. `docs/DISTRIBUTION_AND_REVENUE.md` §1
covers what else a public listing needs (OAuth, a privacy-policy URL, a Claude
Team plan).

Once that exists, in ChatGPT: **Settings → Connectors → Advanced → Developer
mode**, then add the connector with your `https://.../mcp/` URL and the bearer
token. OpenAI moves this menu occasionally; if the wording differs, look for
"developer mode" under connectors.

---

## §7 — The weekly freshness run

Two commands. The first checks government pages for changes; the second checks
what the courts published.

First, confirm the court feeds are actually alive — a wrong feed address and a
quiet week look identical in a report, which is how a court silently stops being
watched:

```bash
cd ~/akridion/legafy-ai
.venv/bin/python -m app.sources.judicial_feeds
```

**CHECK** — twelve lines, each `OK` or `EMPTY`. `EMPTY` is fine and normal: it
means that court published nothing matching in that window. `FEED_NOT_FOUND` is
not fine — that court is not being watched at all, and the command exits with an
error to make sure you notice.

Then the real weekly run:

```bash
.venv/bin/python -m app.sources.watcher              # government pages
.venv/bin/python -m app.sources.judicial_feeds --write  # courts, saving leads
```

To have it run by itself every Monday at 7am, run `crontab -e` and add:

```bash
0 7 * * 1 cd $HOME/akridion/legafy-ai && ./.venv/bin/python -m app.sources.watcher >> generated/weekly.log 2>&1
5 7 * * 1 cd $HOME/akridion/legafy-ai && ./.venv/bin/python -m app.sources.judicial_feeds --write >> generated/weekly.log 2>&1
```

**Reading the result.** Ask Claude: *"Show me the Legafy review queue."* You get
three inboxes:

- `pending` — a government page changed. Go read it.
- `coverage_gaps` — questions people asked that Legafy could not answer. That is
  your crawl backlog, ordered by how often it was asked.
- `judicial_leads` — judgments touching something we track.

**What a lead is worth.** It is a pointer at aggregator authority (0.25, below
the 0.80 floor needed to support any statement). It tells you *that* a judgment
exists. It can never be quoted, and it has not changed any answer the engine
gives. Open the judgment on the court's own site before acting on it. That is
the reviewer's job and the tool will not do it for you.

---

## §8 — When something does not work

| What you see | What it means | What to do |
|---|---|---|
| `command not found: make` | `make` is not on macOS by default | You do not need it — this runbook never uses it |
| `cd: no such file or directory` | The space in "Legafy Ai" split the path | Put quotes around the whole path |
| `pytest: command not found` | You used the Mac's Python, not Legafy's | Put `.venv/bin/` in front |
| `ModuleNotFoundError: app` | `cwd` missing from the Claude config | Add `cwd`, pointing at the repo folder |
| Connector added, no tools | Usually a JSON typo, or the app was not fully quit | Check the JSON; `Cmd`+`Q` and reopen |
| Claude answers without calling the tool | The connector is not loaded | Re-check the config file path and JSON |
| `401 invalid_token` | The token is missing or wrong | Re-check the `Authorization` header |
| `403 insufficient_scope` | A free-tier token tried the drafting tool | Expected — that is the paywall working |
| Everything comes back RED | No activities declared, so nothing could be ruled out | Answer the tool's follow-up questions |
| `FEED_NOT_FOUND` in the court check | A feed address is dead | Re-read the slug from indiankanoon.org/feeds/ — do not guess it |
| The vault chain check prints `False` | A past record was changed or the file was truncated | Stop and investigate. This is the one file you cannot rebuild |

Two things worth repeating because they cost the most time:

**Absolute paths everywhere in the Claude config.** Claude Desktop does not
expand `~` and does not inherit your Terminal's settings.

**Quit Claude Desktop with `Cmd`+`Q`.** Closing the window leaves it running
with the old configuration, and you will change the file five times and see no
difference.
