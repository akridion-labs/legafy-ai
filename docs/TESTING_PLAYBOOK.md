# Legafy testing playbook

Hand this to anyone who is going to test Legafy — including someone who has
never seen the codebase and is in a different country. It covers three ways to
get a working instance, a scripted set of tests with the answer you should get,
and a results sheet to fill in.

**Read this first:** Legafy only maps Indian states. If you are testing from
Canada, the United States or anywhere else, that does not stop you — the
questions are about *Indian* ventures, and the tool refusing to answer for
Ontario is one of the tests, not a failure. See §5.

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

## Path A — local, on your own machine

```bash
git clone <repo-url> legafy-ai && cd legafy-ai
python3 --version          # 3.11 to 3.14 all work
make install
make test                  # expect 166 passed
```

If `make install` fails on a wheel, stop and report it — that means a pinned
dependency regressed, not that your Python is wrong. Do not switch interpreters
to work around it.

### Create the sandbox

```bash
./scripts/sandbox.sh
```

This mints a real tenant token, writes an isolated registry, and points the
audit vault at `sandbox/generated/` so your testing never mixes with anyone
else's records. It prints the token once — copy it now.

It deliberately **disables the dev bootstrap token**. That means the minted
token is the only way in, which is the path a real customer takes. If you find
yourself reaching for `akridion_dev_99x`, something is misconfigured.

### Start it

```bash
set -a; source sandbox/.env.sandbox; set +a
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Leave that terminal open — it is one of the three records you will cross-check
in §4. Everything below runs in a second terminal.

Go to §2.

---

## Path B — Docker, no Python needed

```bash
git clone <repo-url> legafy-ai && cd legafy-ai
./scripts/sandbox.sh                       # mints the token; needs no Python
docker compose -f docker-compose.yml -f docker-compose.sandbox.yml up -d api
docker compose logs -f api                 # the live log — keep this open
```

The sandbox script uses `openssl`/`shasum` rather than Python, so this path
genuinely needs nothing but Docker and a shell.

The overlay bind-mounts `sandbox/` into the container, so the token you just
minted is the one the server reads and the audit vault survives the container.
It also sets `env_file: []` — a sandbox must not inherit a real `.env`, or it
would be neither isolated nor offline.

The API binds to `127.0.0.1:8000` on your machine only. `cloudflared` is in the
base compose file for the real deployment; a local tester does not want a public
hostname, so `up -d api` starts just the one service.

Go to §2.

---

## Path C — the shared sandbox, for a remote tester

Zero install. Deepak runs the server; the tester adds one connector.

### What Deepak does, once per tester

On the server (or the Mac, with the tunnel running):

```bash
./scripts/sandbox.sh --reset          # fresh token
```

Send the tester **two things**, over a channel you would use for a password:

1. the URL: `https://legal-mcp.akridion.com/mcp/` — note the trailing slash
2. the token it printed

The token expires in 30 days and is rate-limited to 30 requests a minute and
2,000 a month. If a tester needs to try document drafting, mint theirs with
`--tier PREMIUM_HOSTED` instead.

### What the tester does

**Claude (web or desktop)** → Settings → Connectors → Add custom connector.

- URL: `https://legal-mcp.akridion.com/mcp/`
- Header: `Authorization: Bearer <the token you were sent>`

**Claude Code**, if you prefer the terminal:

```bash
claude mcp add --transport http legafy https://legal-mcp.akridion.com/mcp/ \
  --header "Authorization: Bearer <token>"
claude mcp list
```

That is the whole setup. Go to §2.

---

## 1. Attaching to Claude Desktop (Paths A and B)

`./scripts/sandbox.sh` printed a config block. Paste it into:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

Three things people get wrong here:

- **Use absolute paths.** Claude Desktop does not expand `~` and does not
  inherit your shell's `PATH`.
- **Set `cwd`** to the repo root, or you get `ModuleNotFoundError: app`.
- **Quit fully** — Cmd-Q or File → Exit, not just closing the window — then
  reopen. Claude Desktop only reads that file at launch.

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

```bash
/plugin marketplace add /absolute/path/to/legafy-ai
/plugin install legafy@akridion-labs
```

Adding from a **local path** matters: it installs your working copy, so you are
testing the manifest you are about to publish rather than whatever is on GitHub.

It asks for two values — the server URL (`http://localhost:8000/mcp/` locally,
or the tunnel URL) and the token.

```bash
/plugin list      # legafy enabled
/mcp              # its seven tools listed
```

Then re-run **T2** and **T7**. The plugin also installs a skill that tells the
model *when* to reach for the grounding tool, so the real test is asking a legal
question **without naming the tool** and seeing whether it gets called anyway.

---

## 4. Cross-verifying — proving a call really happened

Three independent records. A real call appears in all three.

**1. The server log** (`make run` terminal, or `docker compose logs -f api`) —
every request with its id, the tenant, and the tool.

**2. The audit vault** — the tamper-evident record:

```bash
wc -l sandbox/generated/akrigon_audit_vault.json      # one line per call
tail -1 sandbox/generated/akrigon_audit_vault.json | python3 -m json.tool
make audit-verify                                      # (True, ...) = chain intact
```

Note what the vault does **not** contain: your business idea in clear text. Only
a keyed hash. That is deliberate — read `SECURITY.md` if you want the reasoning.

**3. What Claude told you on screen.** The vault's `traffic_light_lane` must
match. If Claude said "you're fine" and the vault says RED, **that is the
finding** — the model is talking over the tool, and it is the most valuable bug
you can bring back.

### The 30-second check

```bash
wc -l sandbox/generated/akrigon_audit_vault.json     # note the number
# ... ask Claude to screen an idea ...
wc -l sandbox/generated/akrigon_audit_vault.json     # +1
tail -1 sandbox/generated/akrigon_audit_vault.json | python3 -m json.tool | grep -E 'lane|jurisdiction'
make audit-verify
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
| `make install` fails on a wheel | a pin regressed | report it; don't switch Python |

Claude Desktop keeps its own MCP log:

```bash
tail -f ~/Library/Logs/Claude/mcp-server-legafy-sandbox.log     # macOS
```

---

## 7. Results sheet

Copy this, fill it in, send it back.

```
Tester:            
Location:          
Path used:         A local / B docker / C shared sandbox
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
Cross-check: make audit-verify returned True?                         Y / N

Did it EVER state a section number, a penalty amount, or a case name?
  (quote it exactly if so — this is the highest-severity finding)

Anything it said confidently that you could not verify from a link it gave you?

What was confusing? (a founder with no lawyer is the target user)
```

---

## 8. Cleaning up

```bash
./scripts/sandbox.sh --reset      # wipes sandbox/ and mints a fresh token
```

Everything the sandbox writes lives under `sandbox/`, so a reset cannot touch a
real audit vault. Do not delete `generated/akrigon_audit_vault.json` outside the
sandbox — it is append-only and hash-chained on purpose, and deleting it
destroys the record you would be verifying.

On Path C, Deepak should re-run `--reset` after the test round so the tester's
token stops working.
