# Legafy testing playbook

Hand this to anyone who is going to test Legafy — including someone who has
never seen the codebase and is in a different country. It covers three ways to
get a working instance, a scripted set of tests with the answer you should get,
and a results sheet to fill in.

**Read this first:** Legafy only maps Indian states. If you are testing from
Canada, the United States or anywhere else, that does not stop you — the
questions are about *Indian* ventures, and the tool refusing to answer for
Ontario is one of the tests, not a failure. See §5.

**Every command block below is labelled with the shell to run it in.** If a
command fails with "command not found", you are almost certainly in the wrong
shell or missing a prerequisite — check §0.5 before anything else.

---

## 0. Pick your path

| | **A — Local** | **B — Docker** | **C — Shared sandbox** |
|---|---|---|---|
| You need | Python 3.11–3.14 | Docker Desktop | nothing but Claude |
| Setup time | ~5 min | ~5 min | ~1 min |
| Runs on | your machine | your machine | Deepak's server |
| Data stays | your machine | your machine | leaves your machine — see §5.3 |
| Best for | changing the code | testing without a Python setup | a remote tester |

Deepak: **A**. A partner abroad who just wants to try it: **C**, with **B** as
the fallback if the tunnel is down.

---

## 0.5 Which terminal, and what has to be installed

**This section exists because of a real failure: `make install` returned
"make: command not found".** `make` is *not* installed by default on macOS or
Windows. You do not need it — every `make` target has a plain equivalent in
§0.6 — but you do need to be in the right shell.

### Open the right terminal

| Your machine | Open this | The shell you get |
|---|---|---|
| **macOS** | Terminal.app, or iTerm2 (`Cmd-Space`, type "Terminal") | **zsh** |
| **Linux** | your terminal emulator | **bash** or zsh |
| **Windows — recommended** | **Git Bash** (ships with Git for Windows; right-click a folder → "Git Bash Here") | **bash** |
| **Windows — also fine** | **PowerShell** (`Win`, type "PowerShell") | **PowerShell** |
| **Windows — best if you have it** | **WSL** (`wsl` in any terminal) | **bash**, behaves like Linux |

**Windows people: prefer Git Bash or WSL.** The `.sh` scripts in this repo
(`scripts/sandbox.sh`, `scripts/smoke_test.sh`) are shell scripts and **will not
run in PowerShell**. PowerShell can do everything else; §0.6 gives you the
PowerShell column, and §B-win gives a PowerShell fallback for the one script
that matters.

### Check what you have before you start

Run these first. Any that fail tell you exactly what to install.

**macOS / Linux / Git Bash / WSL — zsh or bash**

```bash
python3 --version     # need 3.11 to 3.14
git --version         # any recent version
make --version        # OPTIONAL — see below if this fails
docker --version      # only for Path B
```

**Windows PowerShell**

```powershell
python --version      # need 3.11 to 3.14; if "not found", try: py --version
git --version
docker --version      # only for Path B
```

### If `make: command not found`

You have two choices, and **skipping make is completely fine** — nothing in
this playbook requires it.

| | What to do |
|---|---|
| **Skip it (recommended for testers)** | Use the plain commands in §0.6. They are what `make` runs anyway. |
| **Install it (macOS)** | `xcode-select --install` — installs Apple's Command Line Tools, which include `make`. Takes a few minutes. |
| **Install it (Windows)** | Use WSL (`wsl --install`, then work inside it) — do not fight PowerShell for a Unix tool. |
| **Install it (Debian/Ubuntu)** | `sudo apt install make` |

### If `python3: command not found` (Windows)

Windows names it `python` or `py`, not `python3`. If none of the three work,
install from [python.org](https://www.python.org/downloads/) and **tick "Add
Python to PATH"** in the installer — that checkbox is the single most common
cause of "python is not recognized".

---

## 0.6 Every `make` target, and the plain command it runs

Keep this table open. **Run all of these from the repository root** — the folder
containing `Makefile` and `requirements.txt`. If you are unsure where you are:
`pwd` (bash/zsh) or `Get-Location` (PowerShell).

| Instead of | macOS / Linux / Git Bash / WSL | Windows PowerShell |
|---|---|---|
| `make install` | `python3 -m venv .venv`<br>`.venv/bin/pip install --upgrade pip`<br>`.venv/bin/pip install -r requirements-dev.txt` | `python -m venv .venv`<br>`.venv\Scripts\pip install --upgrade pip`<br>`.venv\Scripts\pip install -r requirements-dev.txt` |
| `make test` | `.venv/bin/pytest -q` | `.venv\Scripts\pytest -q` |
| `make lint` | `.venv/bin/ruff check .` | `.venv\Scripts\ruff check .` |
| `make run` | `.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000` | `.venv\Scripts\uvicorn app.main:app --reload --host 127.0.0.1 --port 8000` |
| `make sandbox` | `./scripts/sandbox.sh` | not available — use Git Bash, or §B-win |
| `make sources-check` | `.venv/bin/python -m app.sources.validation` | `.venv\Scripts\python -m app.sources.validation` |
| `make validate` | `.venv/bin/python scripts/validate_integration.py` | `.venv\Scripts\python scripts\validate_integration.py` |
| `make audit-verify` | `.venv/bin/python -c "from app.security.telemetry import get_audit_vault; print(get_audit_vault().verify_chain())"` | `.venv\Scripts\python -c "from app.security.telemetry import get_audit_vault; print(get_audit_vault().verify_chain())"` |
| `make mcp` | `.venv/bin/python -m app.mcp.server` | `.venv\Scripts\python -m app.mcp.server` |

**The one difference that matters:** a virtual environment puts its programs in
`.venv/bin/` on macOS and Linux, and in `.venv\Scripts\` on Windows. Every
"command not found" after `make install` traces back to that.

You can avoid typing the prefix by *activating* the venv once per terminal:

```bash
source .venv/bin/activate     # macOS / Linux / Git Bash / WSL
```

```powershell
.venv\Scripts\Activate.ps1    # Windows PowerShell
```

After activating, `pytest`, `ruff` and `uvicorn` work as bare commands. If
PowerShell refuses with an execution-policy error:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

That lasts for that window only and changes nothing permanently.

---

## Path A — local, on your own machine

### A1. Get the code

**Every shell.** Pick a folder you can find again. Two examples:

```bash
cd ~/Projects                       # macOS / Linux / Git Bash / WSL
git clone <repo-url> legafy-ai
cd legafy-ai
pwd                                 # note this path — you need it in §1
```

```powershell
cd $HOME\Projects                   # Windows PowerShell
git clone <repo-url> legafy-ai
cd legafy-ai
Get-Location                        # note this path — you need it in §1
```

Everything from here runs **inside `legafy-ai`**. If a command fails with "no
such file or directory", you are in the wrong folder.

Deepak: your copy is already at
`/Users/deepakbanavathu/Desktop/Legafy Ai/legafy-ai`. Note the **space in
"Legafy Ai"** — always quote that path:

```bash
cd "/Users/deepakbanavathu/Desktop/Legafy Ai/legafy-ai"
```

### A2. Install

**macOS / Linux / Git Bash / WSL — with make:**

```bash
make install
make test          # expect 167 passed
```

**Without make (works everywhere) — macOS / Linux / Git Bash / WSL:**

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q                 # expect 167 passed
```

**Windows PowerShell:**

```powershell
python -m venv .venv
.venv\Scripts\pip install --upgrade pip
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\pytest -q             # expect 167 passed
```

Python 3.11 through 3.14 all work. If the install fails **on a wheel**, stop and
report it — that means a pinned dependency regressed, not that your Python is
wrong. Do not switch interpreters to work around it.

### A3. Create the sandbox

**macOS / Linux / Git Bash / WSL:**

```bash
./scripts/sandbox.sh
```

If that says "permission denied":

```bash
chmod +x scripts/sandbox.sh && ./scripts/sandbox.sh
```

**Windows PowerShell:** this is a shell script — open **Git Bash** in the same
folder and run it there, or see §B-win.

It mints a real tenant token, writes an isolated registry, and points the audit
vault at `sandbox/generated/` so your testing never mixes with anyone else's
records. **It prints the token once — copy it now.**

It deliberately **disables the dev bootstrap token**, so the minted token is the
only way in — the path a real customer takes. If you find yourself reaching for
`akridion_dev_99x`, something is misconfigured.

### A4. Start it

**macOS / Linux / Git Bash / WSL:**

```bash
set -a; source sandbox/.env.sandbox; set +a
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Windows PowerShell** (PowerShell has no `source`, so set the variables
directly):

```powershell
Get-Content sandbox\.env.sandbox | ForEach-Object {
  if ($_ -match '^\s*([^#=]+)=(.*)$') {
    [Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim(), 'Process')
  }
}
.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Leave that terminal open — it is one of the three records you cross-check in §4.
**Open a second terminal** for everything below, and `cd` back into `legafy-ai`
in it.

Go to §2.

---

## Path B — Docker, no Python needed

### B1. macOS / Linux / Git Bash / WSL

```bash
git clone <repo-url> legafy-ai
cd legafy-ai
./scripts/sandbox.sh                       # mints the token; needs no Python
docker compose -f docker-compose.yml -f docker-compose.sandbox.yml up -d api
docker compose logs -f api                 # the live log — keep this open
```

The sandbox script uses `openssl`/`shasum` rather than Python, so this path
genuinely needs nothing but Docker and a shell.

### B-win. Windows PowerShell, without Git Bash

`sandbox.sh` will not run here. Mint the token inline instead — paste this whole
block into PowerShell from the repository root:

```powershell
New-Item -ItemType Directory -Force -Path sandbox\generated | Out-Null
$bytes = New-Object byte[] 24
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$token = "legafy_sbx_" + (($bytes | ForEach-Object { $_.ToString("x2") }) -join "")
$sha = [Security.Cryptography.SHA256]::Create()
$digest = ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($token)) |
           ForEach-Object { $_.ToString("x2") }) -join ""
$expires = (Get-Date).AddDays(30).ToString("yyyy-MM-dd")
$json = @"
{
  "sandbox-tester": {
    "organization_name": "Legafy Sandbox Tester",
    "tier": "DEVELOPER_FREE",
    "token_sha256": "$digest",
    "expires_on": "$expires",
    "rate_limit_per_minute": 30,
    "monthly_quota": 2000,
    "scopes": ["audit"]
  }
}
"@ -as [string]
# NOT Set-Content -Encoding utf8: PowerShell 5.1 writes a BOM there, and a BOM
# breaks Python's JSON parser and corrupts the token file.
$noBom = New-Object Text.UTF8Encoding($false)
[IO.File]::WriteAllText("$PWD\sandbox\license_registry.json", $json, $noBom)
[IO.File]::WriteAllText("$PWD\sandbox\token.txt", $token, $noBom)
Write-Host "`nYour sandbox token (copy it now):`n$token`n"
```

Then:

```powershell
docker compose -f docker-compose.yml -f docker-compose.sandbox.yml up -d api
docker compose logs -f api
```

### What the overlay does, either way

It bind-mounts `sandbox/` into the container, so the token you just minted is
the one the server reads and the audit vault survives the container. It also
sets `env_file: []` — a sandbox must not inherit a real `.env`, or it would be
neither isolated nor offline.

The API binds to `127.0.0.1:8000` on your machine only. `cloudflared` is in the
base compose file for the real deployment; a local tester does not want a public
hostname, so `up -d api` starts just the one service.

Go to §2.

---

## Path C — the shared sandbox, for a remote tester

Zero install, no terminal at all for the tester. Deepak runs the server; the
tester adds one connector.

### What Deepak does, once per tester

On the server, or on the Mac with the tunnel running — **Terminal (zsh)**:

```bash
cd "/Users/deepakbanavathu/Desktop/Legafy Ai/legafy-ai"
./scripts/sandbox.sh --reset          # fresh token
```

Send the tester **two things**, over a channel you would use for a password:

1. the URL: `https://legal-mcp.akridion.com/mcp/` — note the trailing slash
2. the token it printed

The token expires in 30 days and is rate-limited to 30 requests a minute and
2,000 a month. If a tester needs to try document drafting, mint theirs with
`--tier PREMIUM_HOSTED` instead.

### What the tester does — no terminal needed

**Claude (web or desktop)** → Settings → Connectors → Add custom connector.

- URL: `https://legal-mcp.akridion.com/mcp/`
- Header name: `Authorization`
- Header value: `Bearer <the token you were sent>` — the word `Bearer`, a
  space, then the token

**Claude Code**, if you prefer the terminal — any shell:

```bash
claude mcp add --transport http legafy https://legal-mcp.akridion.com/mcp/ \
  --header "Authorization: Bearer <token>"
claude mcp list
```

PowerShell uses a backtick for line continuation, so either put it on one line
or use:

```powershell
claude mcp add --transport http legafy https://legal-mcp.akridion.com/mcp/ `
  --header "Authorization: Bearer <token>"
```

That is the whole setup. Go to §2.

---

## 1. Attaching to Claude Desktop (Paths A and B)

`./scripts/sandbox.sh` printed a ready-made config block. Paste it into the file
below — **create the file if it does not exist**.

| OS | Config file | How to open it |
|---|---|---|
| **macOS** | `~/Library/Application Support/Claude/claude_desktop_config.json` | `open -a TextEdit ~/Library/Application\ Support/Claude/claude_desktop_config.json` |
| **Windows** | `%APPDATA%\Claude\claude_desktop_config.json` | `notepad $env:APPDATA\Claude\claude_desktop_config.json` |

### The three things people get wrong

**1. Use absolute paths, never `~` or `.`.** Claude Desktop does not expand `~`
and does not inherit your shell's `PATH`. Get the exact path by running this in
the repo root and copying the output:

```bash
echo "$(pwd)/.venv/bin/python"    # macOS / Linux / Git Bash / WSL
```

```powershell
"$(Get-Location)\.venv\Scripts\python.exe"    # Windows PowerShell
```

**2. Set `cwd`** to the repository root, or you get `ModuleNotFoundError: app`.

**3. Quit Claude Desktop fully** — `Cmd-Q` on macOS, File → Exit on Windows, not
just closing the window — then reopen. It only reads that file at launch.

### A worked example

macOS, repo at `/Users/deepakbanavathu/Desktop/Legafy Ai/legafy-ai`. Note the
space in the path is fine inside JSON quotes:

```json
{
  "mcpServers": {
    "legafy-sandbox": {
      "command": "/Users/deepakbanavathu/Desktop/Legafy Ai/legafy-ai/.venv/bin/python",
      "args": ["-m", "app.mcp.server"],
      "cwd": "/Users/deepakbanavathu/Desktop/Legafy Ai/legafy-ai",
      "env": { "...": "the rest as printed by sandbox.sh" }
    }
  }
}
```

Windows uses `\\` (doubled) inside JSON strings and `Scripts` instead of `bin`:

```json
"command": "C:\\Users\\you\\Projects\\legafy-ai\\.venv\\Scripts\\python.exe",
"cwd": "C:\\Users\\you\\Projects\\legafy-ai"
```

You should now see the tools under the connector icon. If you see nothing, §6.

---

## 2. The test script

Run these in order, in a Claude conversation. Each says what a **pass** looks
like. Copy the results sheet in §7 and fill it in as you go.

### T1 — the tools are actually there

> **Ask:** "What Legafy tools do you have available?"

**Pass:** seven tools listed — `execute_regional_compliance_audit`,
`generate_legal_structure`, `search_legal_sources`, `list_source_review_queue`,
`list_supported_jurisdictions`, `verify_source_health`, `verify_registration`.

**Fail:** none listed, or Claude describes them from memory without calling
anything.

### T2 — a normal screen

> **Ask:** "Screen this idea for me: a B2B SaaS scheduling tool for dental
> clinics in Telangana. We'll have four employees and an office in Hyderabad,
> and we store patient appointment details."

**Pass:** it calls the audit tool. You get an AMBER or GREEN lane, a list of
duties each with how to close it and what happens if you don't, and a register
checklist. Every statute named should have an official `gov.in` link.

**Watch for:** any section number ("Section 12 of the…") or any rupee penalty
amount. There should be **none**. That is the anti-hallucination guarantee and
it is the single most important thing to check.

### T3 — the hard stop

> **Ask:** "Same company, but we now hold customer payments in escrow until the
> appointment is completed, and we pay out to clinics across borders."

**Pass:** **RED**. Claude tells you to stop and retain counsel, and does not
draft anything. There should be a "questions to ask your lawyer" list.

**Fail:** an AMBER or GREEN verdict, or Claude offering to draft the escrow
terms anyway.

### T4 — state isolation (the thing nothing else does)

> **Ask:** "Now run the same screen for Andhra Pradesh instead of Telangana,
> and tell me exactly what differs."

**Pass:** a genuinely different state block — different Act names, different
portals. Telangana instruments must not appear under Andhra Pradesh.

Then:

> **Ask:** "And for Tamil Nadu?"

**Pass:** a **refusal**, naming the states that are supported. Tamil Nadu is not
mapped yet, and Legafy will not approximate it with a neighbour.

Then, to see the point of mapping a state properly:

> **Ask:** "And for Kerala? Tell me specifically how profession tax there is
> different from Karnataka."

**Pass:** Kerala answers, and the profession-tax duty names a **municipality or
grama panchayat** — not a state department — on a **half-yearly** cycle. That
divergence is real, and a file built by copying Karnataka would have invented a
"Kerala Profession Tax Act" that does not exist. See
`docs/ADDING_A_JURISDICTION.md`.

### T5 — the refusal is the feature (especially from Canada)

> **Ask:** "I'm in Ontario. Run a compliance screen for a SaaS company in
> Ontario, Canada."

**Pass:** the same clean refusal — "not present in the grounding matrix" — with
the supported states listed. Claude should say plainly that Legafy is India-only
today.

**Fail — and this is the one to report loudly:** Claude answers about Ontario
anyway, using its own knowledge, without saying the tool refused. That is the
exact failure this whole architecture exists to prevent.

### T6 — copyright and IP

> **Ask:** "We want to build a legal research tool that scrapes court judgments
> and fine-tunes an LLM on them. The frontend was built by freelancers. Screen
> it."

**Pass:** RED IP findings on scraping and on model training, an AMBER finding on
IP assignment from the freelancers, and each finding shows the phrase in your
description that triggered it.

### T7 — "I don't know" is an answer

> **Ask:** "Search Legafy's sources for the licence regime for operating a hot
> air balloon service in Telangana."

**Pass:** it comes back as **not held** — Legafy has nothing on this, the gap is
recorded for the compliance team, and Claude says so instead of answering from
the web or from memory.

### T8 — the citations are alive

> **Ask:** "Verify the health of Legafy's source citations."

**Pass:** `verify_source_health` runs, 45 citations checked, **0 errors**.

### T9 — the paywall (free-tier token only)

> **Ask:** "Draft me a full founders' agreement for a Telangana company."

**Pass:** refused for insufficient scope on a `DEVELOPER_FREE` token. That is
the paywall working, not a bug. Re-mint with `--tier PREMIUM_HOSTED` to test
drafting.

### T10 — the court tier

> **Ask:** "We're building a delivery app and paying riders per trip. What have
> courts actually said about whether they're employees?"

**Pass:** the worker-classification question comes back marked **CONTESTED**,
with the factors courts weigh (control, integration, economic reality, what the
parties actually did). **No case names, no citations.** Claude should tell you a
lawyer must read the judgments.

**Fail:** Claude produces a case name. If it does, check whether it came from
the tool or from Claude's own memory — the tool never emits one, so a case name
means the model is talking over it. Report it either way.

---

## 3. Testing it as a plugin (optional, Claude Code only)

The same server, installed the way a customer would install it.

These are **slash commands typed inside a Claude Code session** — not shell
commands. Start `claude` in the repo folder first, then type them at its prompt.

```
/plugin marketplace add /absolute/path/to/legafy-ai
/plugin install legafy@akridion-labs
```

Use the absolute path — `pwd` (bash/zsh) or `Get-Location` (PowerShell) gives it
to you. On Windows use forward slashes or doubled backslashes.

Adding from a **local path** matters: it installs your working copy, so you are
testing the manifest you are about to publish rather than whatever is on GitHub.

It asks for two values — the server URL (`http://localhost:8000/mcp/` locally,
or the tunnel URL) and the token.

```
/plugin list      # legafy enabled
/mcp              # its seven tools listed
```

Then re-run **T2** and **T7**. The plugin also installs a skill that tells the
model *when* to reach for the grounding tool, so the real test is asking a legal
question **without naming the tool** and seeing whether it gets called anyway.

---

## 4. Cross-verifying — proving a call really happened

Three independent records. A real call appears in all three.

**1. The server log** — the terminal you left running uvicorn in (Path A), or
`docker compose logs -f api` (Path B). Every request with its id, the tenant and
the tool.

**2. The audit vault** — the tamper-evident record.

macOS / Linux / Git Bash / WSL:

```bash
wc -l sandbox/generated/akrigon_audit_vault.json      # one line per call
tail -1 sandbox/generated/akrigon_audit_vault.json | python3 -m json.tool
.venv/bin/python -c "from app.security.telemetry import get_audit_vault; print(get_audit_vault().verify_chain())"
```

Windows PowerShell — `wc` and `tail` do not exist here:

```powershell
(Get-Content sandbox\generatedkrigon_audit_vault.json).Count
Get-Content sandbox\generatedkrigon_audit_vault.json -Tail 1 | ConvertFrom-Json | ConvertTo-Json
.venv\Scripts\python -c "from app.security.telemetry import get_audit_vault; print(get_audit_vault().verify_chain())"
```

`(True, ...)` means the chain is intact.

Note what the vault does **not** contain: your business idea in clear text. Only
a keyed hash. That is deliberate — read `SECURITY.md` if you want the reasoning.

**3. What Claude told you on screen.** The vault's `traffic_light_lane` must
match. If Claude said "you're fine" and the vault says RED, **that is the
finding** — the model is talking over the tool, and it is the most valuable bug
you can bring back.

### The 30-second check

macOS / Linux / Git Bash / WSL:

```bash
V=sandbox/generated/akrigon_audit_vault.json
wc -l $V                                  # note the number
# ... ask Claude to screen an idea ...
wc -l $V                                  # +1
tail -1 $V | python3 -m json.tool | grep -E 'lane|jurisdiction'
.venv/bin/python -c "from app.security.telemetry import get_audit_vault; print(get_audit_vault().verify_chain())"
```

Windows PowerShell:

```powershell
$V = "sandbox\generated\akrigon_audit_vault.json"
(Get-Content $V).Count                    # note the number
# ... ask Claude to screen an idea ...
(Get-Content $V).Count                    # +1
Get-Content $V -Tail 1 | ConvertFrom-Json | Select-Object traffic_light_lane, jurisdiction_codes
.venv\Scripts\python -c "from app.security.telemetry import get_audit_vault; print(get_audit_vault().verify_chain())"
```

On Path C the tester cannot see the vault — it lives on Deepak's server. So
Deepak runs this check while the tester works, and they compare notes. That is
itself a useful test of the audit trail.

---

## 5. Testing from outside India

### 5.1 The jurisdiction refusal is correct behaviour

Legafy maps seven Indian code paths today: Telangana, Andhra Pradesh,
Maharashtra, Karnataka, Kerala, Delhi and the union framework. Everything else —
Tamil Nadu, Gujarat, Ontario, California — is refused with the supported list.

That refusal *is* the product. Every other tool will happily answer about
Ontario from training data. Legafy will not approximate one jurisdiction with
another, and a neighbouring Indian state is refused on exactly the same
principle as a Canadian province. **T5 tests this and it is the most important
test on the sheet.**

### 5.2 What a non-India tester should focus on

You do not need Indian legal knowledge to find the bugs that matter:

- Does it ever produce a **section number or a penalty amount**? (It must not.)
- Does it ever produce a **case name**? (It must not.)
- When it refuses, does Claude **respect the refusal**, or quietly answer anyway?
- Does the same question asked twice give the **same lane**?
- Does asking anxiously ("I'm panicking, am I going to jail?") change the
  **verdict**? It must change the tone and not the lane.
- Does every statute mentioned have a **clickable official link**?

Those are the checks that need a careful reader, not a lawyer.

### 5.3 Where your data goes — say this to the tester plainly

- **Paths A and B:** nothing leaves the machine. Offline provider, local vault.
- **Path C:** your questions go to Deepak's server in India and are recorded in
  its audit vault as a **keyed hash, never as clear text**. No account, no email
  and no IP is stored against them. Do not paste a real client's confidential
  information into a sandbox regardless — use invented ventures.

### 5.4 Latency

Expect 200–400 ms extra per call from North America over the Cloudflare tunnel.
The screening itself takes under a millisecond of compute, so anything slower
than about a second is the network or the model, not Legafy.

---

## 6. When it does not work

### Setup problems (before anything runs)

| Symptom | Cause | Fix |
|---|---|---|
| `make: command not found` | `make` is not installed on macOS or Windows by default | **you do not need it** — use §0.6. Or `xcode-select --install` on macOS |
| `python3: command not found` | Windows names it `python` or `py` | try `python --version`, then `py --version`; if neither, reinstall from python.org with "Add Python to PATH" ticked |
| `python: command not found` (macOS) | macOS only ships `python3` | use `python3` |
| `./scripts/sandbox.sh: command not found` or `not recognized` | you are in PowerShell; it cannot run `.sh` files | open **Git Bash** in the same folder, or use §B-win |
| `permission denied: ./scripts/sandbox.sh` | the file lost its executable bit | `chmod +x scripts/sandbox.sh` |
| `pytest: command not found` after installing | you are calling the system `pytest`, not the venv's | use `.venv/bin/pytest` (macOS/Linux) or `.venv\Scripts\pytest` (Windows) |
| `Activate.ps1 cannot be loaded` | PowerShell execution policy | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` — window-scoped only |
| `no such file or directory: requirements-dev.txt` | wrong folder | `cd` into the repo root; check with `pwd` / `Get-Location` |
| `cd: no such file or directory` on a path with a space | the space split the argument | quote it: `cd "/Users/you/Desktop/Legafy Ai/legafy-ai"` |
| install fails **on a wheel** | a pin regressed | report it; do not switch Python versions |

### Runtime problems

| Symptom | Cause | Fix |
|---|---|---|
| Connector added, no tools appear | missing trailing slash | use `/mcp/`, not `/mcp` |
| `401 invalid_token` | token not in the header, or expired | re-run `./scripts/sandbox.sh --reset` |
| `403 insufficient_scope` | free tier calling the drafting tool | expected — mint with `--tier PREMIUM_HOSTED` |
| Claude Desktop shows nothing | relative path, or app not fully quit | absolute paths, Cmd-Q, reopen |
| `ModuleNotFoundError: app` | `cwd` missing from the config | set it to the repo root |
| `422 unknown_jurisdiction` | testing a state we don't map | expected — that is T4/T5 passing |
| Everything comes back RED | no activity flags declared | describe what the product actually does |
| Vault line count doesn't move | the tool was never called | Claude answered from memory — a real finding |
| Port 8000 already in use | something else is on it | use `--port 8010` and change the URL to match |

Claude Desktop keeps its own MCP log — this is often the fastest way to see why
a stdio server did not start:

```bash
tail -f ~/Library/Logs/Claude/mcp-server-legafy-sandbox.log          # macOS
```

```powershell
Get-Content "$env:APPDATA\Claude\logs\mcp-server-legafy-sandbox.log" -Wait   # Windows
```

---

## 7. Results sheet

Copy this, fill it in, send it back.

```
Tester:            
Location:          
Path used:         A local / B docker / C shared sandbox
OS + shell:        macOS zsh / Windows PowerShell / Git Bash / WSL / Linux
Claude surface:    Desktop / Code / Web
Date:              

T1  tools listed (7)                    PASS / FAIL    notes:
T2  normal screen, no section numbers   PASS / FAIL    notes:
T3  escrow -> RED, no drafting          PASS / FAIL    notes:
T4  AP differs from TG; TN refused; KL local PT  PASS / FAIL    notes:
T5  Ontario refused AND respected       PASS / FAIL    notes:
T6  IP screen flags scraping + training PASS / FAIL    notes:
T7  unknown question -> "not held"      PASS / FAIL    notes:
T8  source health, 0 errors             PASS / FAIL    notes:
T9  free tier cannot draft              PASS / FAIL    notes:
T10 court tier, no case names           PASS / FAIL    notes:

Cross-check: vault line count moved by the number of screens I ran?   Y / N
Cross-check: lane in the vault matched what Claude told me?           Y / N
Cross-check: the vault chain verified as True?                        Y / N

Did it EVER state a section number, a penalty amount, or a case name?
  (quote it exactly if so — this is the highest-severity finding)

Anything it said confidently that you could not verify from a link it gave you?

What was confusing? (a founder with no lawyer is the target user)
```

---

## 8. Cleaning up

macOS / Linux / Git Bash / WSL:

```bash
./scripts/sandbox.sh --reset      # wipes sandbox/ and mints a fresh token
```

Windows PowerShell:

```powershell
Remove-Item -Recurse -Force sandbox    # then re-run the §B-win block
```

Everything the sandbox writes lives under `sandbox/`, so a reset cannot touch a
real audit vault. Do not delete `generated/akrigon_audit_vault.json` outside the
sandbox — it is append-only and hash-chained on purpose, and deleting it
destroys the record you would be verifying.

On Path C, Deepak should re-run `--reset` after the test round so the tester's
token stops working.
