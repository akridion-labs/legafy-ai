# Deploying on the Akridion server (the actual machine)

`docs/DEPLOYMENT.md` describes a generic Linux box. This one is written against your
build, from the RUNBOOK series in *Server Setup Documents*, and it corrects three
assumptions that would have bitten you.

## What the machine actually is

| | |
|---|---|
| CPU / board | Ryzen 5 9600X · Gigabyte B650 AORUS ELITE AX V2 (BIOS F42c) |
| GPU | RTX 5070, 12 GB VRAM |
| OS | Windows 11, UEFI, CSM disabled |
| Linux | WSL 2, Ubuntu-24.04, installed to `D:\WSL\Ubuntu-24.04`, user `akridion` |
| Containers | Docker Desktop, WSL 2 engine, Ubuntu-24.04 integration on |
| Local models | Ollama **inside WSL**, GPU-backed (RUNBOOK 06 §3.0) |
| Remote access | Tailscale, run unattended |
| Drives | C: Windows · D: WSL_SERVER · E: AI_MODELS · **F: EXCHANGE_HUB (exFAT)** |

### Three corrections to the generic guide

1. **It is not a CPU-only server.** There is a 12 GB GPU with Ollama already on it, so
   Legafy can draft documents locally at zero marginal cost. Set the provider chain
   accordingly instead of paying per token.
2. **`make up-host` will not work here.** `network_mode: host` is a Linux-engine feature;
   under Docker Desktop it does not do what it does on a bare-metal Linux server. Use the
   default bridge stack (`make up`), or skip Docker entirely — see below.
3. **`host.docker.internal` does not reach your Ollama by default.** Ollama runs inside
   WSL, and on Docker Desktop that name points at the *Windows* host. Fixed below.

---

## ⛔ The F: drive rule applies to Legafy, hard

Your own RUNBOOK 04 says F: is exFAT — no journaling, no permissions — and must not hold
"anything a program writes to continuously."

**`generated/akrigon_audit_vault.json` is exactly that file.** It is append-only,
hash-chained, and `fsync`ed on every write. On exFAT a power cut mid-write can corrupt the
volume outright, and even a clean truncation breaks the hash chain — which means
`make audit-verify` returns `false` and your liability-defence record is no longer
provable. The vault is the one artefact in this system you cannot regenerate.

**Put the repo and `generated/` inside the Ubuntu filesystem on D:.** Never on F:, and
avoid `/mnt/f` and `/mnt/c` for the working tree — cross-filesystem I/O from WSL is both
slow and permission-lossy. Copy *documents* to F: for the Mac; never point the app there.

```bash
# in Ubuntu — native ext4, not a Windows mount
mkdir -p ~/akridion && cd ~/akridion
git clone git@github.com:akridion-labs/legafy-ai.git
cd legafy-ai
```

---

## Port map

Ports already spoken for on this machine:

| Port | Owner |
|---|---|
| 8765 | Vyom command centre |
| 11434 | Ollama |
| 4000, 3000 | dev servers |
| 3389 | Remote Desktop |

Legafy defaults to **8000**, which is free — but 8000 is a popular default, so check
before you start:

```bash
ss -ltnp | grep -E ':(8000|8765|11434)\b' || echo "8000 is free"
```

Change `LEGAFY_PORT` in `.env` if you ever need to move it.

---

## Path A — native in WSL (recommended for this box)

Docker buys you isolation you do not need here, and costs you the Ollama networking
problem. Ollama and Python are already in this Ubuntu; running Legafy beside them is
fewer moving parts, and it binds loopback only — which is what the access rules below
depend on.

```bash
cd ~/akridion/legafy-ai
sudo apt update && sudo apt install -y python3-venv python3-pip openssl
make install                    # Python 3.11–3.14 all work (see README)
make test                       # 181 tests, offline
./scripts/bootstrap.sh          # .env, telemetry salt, first ENTERPRISE token
```

Point it at your local GPU:

```bash
# .env
LEGAFY_PROVIDER_CHAIN=ollama,offline
LEGAFY_OLLAMA_BASE_URL=http://127.0.0.1:11434
LEGAFY_OLLAMA_MODEL=llama3.1:8b
```

**On model choice.** `qwen2.5-coder:7b` from RUNBOOK 06 is a code model — good for the
dev agent, wrong for drafting contract prose. Pull a general instruct model; your own
12 GB VRAM table says 7B/8B 4-bit is comfortable and 13B/14B is tight but works:

```bash
ollama pull llama3.1:8b        # comfortable, start here
# ollama pull qwen2.5:14b      # better prose, tighter fit — check `ollama ps` says 100% GPU
```

Run it, and keep it running:

```bash
make run                        # foreground, for the first check
```

Once it looks right, install it as a user service so it survives a WSL restart:

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
systemctl --user daemon-reload && systemctl --user enable --now legafy
loginctl enable-linger "$USER"     # keeps it up when no shell is open
systemctl --user status legafy --no-pager
```

WSL 2 on Windows 11 runs systemd if `/etc/wsl.conf` has `[boot]\nsystemd=true`. If
`systemctl` errors out, add that, run `wsl --shutdown` from PowerShell, reopen Ubuntu, and
retry. Failing that, the `.bashrc` autostart trick RUNBOOK 06 uses for Ollama works here
too.

---

## Path B — Docker, if you want the isolation

```bash
make build && make up            # bridge networking; NOT make up-host
make ps && make logs
```

For the container to reach Ollama running in WSL, Ollama must listen on more than
loopback:

```bash
# replace the autostart line from RUNBOOK 06 §3.0 with this
pkill ollama
OLLAMA_HOST=0.0.0.0:11434 ollama serve > ~/ollama.log 2>&1 &
```

and in `.env`:

```bash
LEGAFY_OLLAMA_BASE_URL=http://host.docker.internal:11434
```

`docker-compose.yml` now maps `host.docker.internal` to the host gateway, so this resolves
to the WSL host where Ollama listens. Verify from inside the container before blaming the
model:

```bash
docker compose exec api python -c "import httpx;print(httpx.get('http://host.docker.internal:11434/api/tags').status_code)"
```

Container data stays on `D:\Containers` or in the Ubuntu filesystem, per RUNBOOK 04
Stage 7. Never F:.

---

## Reaching it — and the rule that decides how

> ⛔ **Correction to an earlier draft of this document.** It told you to put a Cloudflare
> Tunnel on this machine and hand out `legal-mcp.akridion.com`. **Do not.** Your own
> `EXECUTION_ORDER.md`, under *Rules that do not bend*, says:
>
> > Tailscale only; no public listener, router forwarding or Funnel.
>
> and the Phase 4 boundary adds that *"raw port 8765 and public Funnel remain prohibited."*
> A Cloudflare Tunnel opens no router port, so it clears the letter of the rule — and
> breaks its point exactly, because it creates a public inbound path to `AKRIDION-AI-01`,
> which is the single thing security gate **S7** was signed on the absence of. Your S2B
> evidence (hop 2 = `10.130.128.1`, RFC1918 — the ISP is carrier-grade NAT, so the router
> holds no routable public address) says an inbound path **cannot exist today**. A tunnel
> would manufacture one. That is a decision to take deliberately, in daylight, not a
> deployment step to follow.
>
> Nothing below needs it.

### Who needs to reach it, and how each one does

| Who | Route | Public exposure |
|---|---|---|
| You, from the Mac, in Claude Desktop | **stdio over SSH** (§A below) | none |
| You, from the Mac, in Claude Code | stdio over SSH, or Tailscale Serve | none |
| Your partner in Canada | same, once he is on the tailnet | none |
| claude.ai in a browser · ChatGPT connectors | **not this machine** — see §C | n/a |

### §A — Claude Desktop on the Mac, over SSH (the one that just works)

Claude Desktop launches a *local* command and speaks stdio to it. Make that command an
`ssh` into the server, and the MCP session runs on `AKRIDION-AI-01` while every packet
stays inside the tailnet. No listener, no certificate, no tunnel, nothing to revoke but an
SSH key.

On the Mac, in `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

Prove the pipe before you involve Claude — this is the whole test:

```bash
# from the Mac
ssh akridion@100.112.227.92 'cd ~/akridion/legafy-ai && ./.venv/bin/python -m app.mcp.server' <<'EOF'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}
EOF
```

A JSON line naming `legafy-ai` means the whole path works. `BatchMode=yes` matters: without
it a passphrase prompt hangs invisibly inside Claude Desktop and looks like a broken server.
Use a key, not a password.

### §B — Tailscale Serve, when you want an HTTPS URL on the tailnet

Serve is not Funnel. Serve publishes to your tailnet only; Funnel publishes to the
internet. Your own Phase 4 boundary names *private Tailscale Serve* as the sanctioned way
to reach a Deck session, so this is in-policy — **`tailscale funnel` is not, ever.**

```bash
# on the server, with Legafy listening on 127.0.0.1:8000
tailscale serve --bg --https=443 http://127.0.0.1:8000
tailscale serve status          # confirm it says tailnet-only, not Funnel
```

That gives `https://akridion-ai-01.<your-tailnet>.ts.net/mcp/` with a real certificate.
It works from **Claude Code** on the Mac, which dials MCP endpoints from your own machine:

```bash
claude mcp add --transport http legafy-server \
  https://akridion-ai-01.<your-tailnet>.ts.net/mcp/ \
  --header "Authorization: Bearer <token from scripts/bootstrap.sh>"
```

It will **not** work for a connector added in claude.ai or Claude Desktop's connector
pane: those are dialled by Anthropic's servers, which are not on your tailnet, and the
symptom is a connector that saves and then shows no tools. That is the expected result,
not a bug to chase — use §A for Desktop.

Keep the bearer token even inside the tailnet. Anything on your tailnet can reach port 443
on this host, and Legafy's tiering is what stops a `DEVELOPER_FREE` token from drafting.

### §C — The public endpoint, when there is one, is not this box

A hosted connector for customers needs a public HTTPS origin. Put it on a small VPS or a
managed host under the Akridion Labs account, and leave `AKRIDION-AI-01` as what it is:
the private box where the data is compiled, the vault lives and releases are verified.
That separation is not caution for its own sake — it is what lets you keep the S7 answer
("no inbound path to the server") true while still shipping a product. See
`docs/DISTRIBUTION_AND_REVENUE.md`.

---

## Windows-side housekeeping

- **Docker Desktop and WSL do not start at boot by themselves.** Set Docker Desktop to
  "Start when you log in", and remember that WSL starts on first use — a rebooted machine
  with nobody logged in serves nothing. If Legafy is to be reachable unattended, either
  keep the machine logged in with `loginctl enable-linger`, or run the tunnel and app as
  Windows services. Decide this before you hand the URL to anyone.
- **Power settings** (RUNBOOK 04 §2.2) matter more now: sleep drops the tunnel. Set the
  machine to never sleep on AC.
- **Back the vault up onto F: or the Mac** — copying *out* to exFAT is fine, it is only
  continuous writes that are dangerous:

```bash
# nightly, in Ubuntu
0 2 * * * tar czf "/mnt/f/legafy-vault-$(date +\%F).tgz" -C ~/akridion/legafy-ai generated
```

---

## Where this sits next to Vyom

Vyom and Legafy are separate services on the same box: different ports, different repos,
different data. Two things they should eventually share:

- **Ollama.** One model server, both consumers. That is already how it is set up.
- **The GPU.** A large Vyom retrieval run and a 30-page Legafy draft at the same time will
  contend for 12 GB. If both become routine, either queue them or accept that one waits.

They should **not** share the audit vault, the token registry or the `.env`. Legafy's vault
is a legal record with its own integrity guarantee; keep it isolated.
