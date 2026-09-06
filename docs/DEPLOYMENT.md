# Deploying Legafy AI to the Akridion CPU server

Target: a Linux box you control, reachable from the internet **only** through a
Cloudflare Tunnel. No inbound router port is ever opened.

```
Internet → Cloudflare edge → outbound-only tunnel → cloudflared container
                                                        → api container :8000 (loopback-bound)
```

---

## 0. Prerequisites on the server

```bash
# Docker Engine + compose v2
curl -fsSL https://get.docker.com | sh          # or your distro's package
sudo usermod -aG docker "$USER" && newgrp docker
docker --version && docker compose version

# git, openssl
sudo apt-get install -y git openssl
```

A Cloudflare account with `akridion.com` (or your domain) on it, nameservers
already pointed at Cloudflare.

---

## 1. Get the code onto the server

```bash
sudo mkdir -p /opt/akridion && sudo chown "$USER":"$USER" /opt/akridion
cd /opt/akridion
git clone git@github.com:akridion-labs/legafy-ai.git
cd legafy-ai
```

No git remote yet? See §7 — create the repo first, then come back.

---

## 2. Bootstrap the host

```bash
./scripts/bootstrap.sh
```

This creates `generated/` at mode 0750, copies `.env.example` → `.env`,
generates a real `LEGAFY_TELEMETRY_SALT` with `openssl rand -hex 32`, mints one
ENTERPRISE token and writes **its SHA-256** into `data/license_registry.json`,
then sets `LEGAFY_ENV=production` and `LEGAFY_BOOTSTRAP_TOKENS_ENABLED=false`.

**The token is printed exactly once.** Copy it into your password manager now.
It is not recoverable — the server only ever stores the hash.

Two things about the salt: it is what makes vault telemetry pseudonymous, and
rotating it permanently breaks correlation with older records. Back up `.env`
somewhere encrypted before you ever touch it.

Then choose your model backend in `.env`:

```bash
LEGAFY_PROVIDER_CHAIN=anthropic,openai,ollama,offline   # first healthy wins, rest are failover
ANTHROPIC_API_KEY=sk-ant-…
# …or keep everything on-box:
LEGAFY_PROVIDER_CHAIN=ollama,offline
LEGAFY_OLLAMA_BASE_URL=http://host.docker.internal:11434
```

---

## 3. Bring the stack up

```bash
make build
make up            # api + cloudflared, bridge networking
make ps
make logs
```

Or bring up the redis-backed rate limiter when you run multiple workers:

```bash
make up-full       # adds redis; also set LEGAFY_RATELIMIT_BACKEND=redis in .env
```

The memory rate-limiter counts **per process**. With `LEGAFY_WORKERS=2` and the
memory backend, a tenant's effective limit is doubled. Use redis for anything
past a single worker.

Verify locally before exposing anything:

```bash
curl -s localhost:8000/healthz | python3 -m json.tool
```

`"status": "ok"` and a non-zero `jurisdictions_loaded` means you are good.
`"degraded"` means the telemetry salt is missing — fix `.env` before going public.

If the container refuses to start with *"Refusing to start in production with an
unsafe posture"*, that is the production posture check doing its job: it is
telling you the salt is still the template value, or bootstrap tokens are still
enabled, or the licence registry is missing.

---

## 4. Cloudflare Tunnel

```bash
./setup_tunnel.sh --hostname legal-mcp.akridion.com --port 8000
```

The script is idempotent and will:

1. detect the OS and print the exact `cloudflared` install command if it is missing
   (it prints it rather than piping a remote script into your shell);
2. run `cloudflared tunnel login` only if `~/.cloudflared/cert.pem` is absent;
3. create the tunnel only if a tunnel of that name does not already exist;
4. write `cloudflared/config.yml` from the template with the real UUID;
5. route the DNS record (`cloudflared tunnel route dns`), treating "already
   exists" as success;
6. mint a tunnel token and write it into `.env` as `CLOUDFLARE_TUNNEL_TOKEN`,
   backing up the old `.env` first and printing only the token's length;
7. curl `/healthz` and warn if the API is not up yet.

Then restart so the tunnel container picks up the token:

```bash
make down && make up
```

**Bridge vs host networking.** The default `docker-compose.yml` puts cloudflared
on the compose network, so the tunnel's public hostname must map to
`http://api:8000` in the Cloudflare dashboard. If you prefer host networking (the
blueprint's layout, Linux only):

```bash
make up-host       # docker compose -f docker-compose.yml -f docker-compose.host.yml up -d
```

In host mode cloudflared targets `http://localhost:8000` directly. Host mode does
not behave the same way on Docker Desktop for macOS or Windows — use bridge mode
there.

Confirm from anywhere:

```bash
curl -s https://legal-mcp.akridion.com/healthz
curl -s https://legal-mcp.akridion.com/mcp/tools | python3 -m json.tool | head -30
```

---

## 5. Smoke test the live deployment

```bash
./scripts/smoke_test.sh --base-url https://legal-mcp.akridion.com --token "$LEGAFY_TOKEN"
```

It asserts: health is ok; the tool manifest contains
`execute_regional_compliance_audit`; a Telangana audit returns `IN-TG`; an
**unmapped** state returns HTTP 422 (state isolation refuses to approximate);
an escrow concept comes back RED; and a `dry_run` generation returns a chunk plan.
Any failure exits non-zero, so it drops straight into CI or a cron check.

---

## 6. Operations

```bash
make audit-verify            # verify the vault hash chain is unbroken
make logs                    # tail everything
./scripts/healthcheck.sh     # exit 0/1, for cron or systemd
```

**Back up `generated/`.** It holds the append-only audit vault — your liability
defence record. It is bind-mounted, so it survives container replacement, and
`make clean` never touches it. Back it up off-box:

```bash
0 2 * * * tar czf /backup/legafy-vault-$(date +\%F).tgz -C /opt/akridion/legafy-ai generated
```

Verify the chain after any restore: a `false` from `make audit-verify` means the
file was altered or truncated after the fact.

**Upgrades:**

```bash
cd /opt/akridion/legafy-ai && git pull && make build && make down && make up
```

**Adding a state** — the whole point of the isolation design is that this is a
data change, not a code change:

```bash
cp data/jurisdictions/_TEMPLATE.json data/jurisdictions/IN-GJ.json
# fill it in from that state's own official portals, then:
make test && make down && make up
```

Every instrument you add starts at `penalty_schedule: null` and
`penalty_status: "NOT_VERIFIED"`. Leave it that way until a human has read the
primary source. `tests/test_registry.py` asserts this across every file, so a
fabricated penalty fails CI.

---

## 7. Creating the GitHub repository

From your Mac, in the project folder:

```bash
git init -b main
git add .
git commit -m "Legafy AI v1.0.0 — compliance engine, MCP server, deployment stack"

gh repo create akridion-labs/legafy-ai --private --source=. --remote=origin --push
# or, without the gh CLI:
#   git remote add origin git@github.com:akridion-labs/legafy-ai.git && git push -u origin main
```

Before the first push, confirm nothing secret is staged:

```bash
git status --porcelain            # .env, generated/*, cloudflared/*.json must NOT appear
git check-ignore -v .env generated/akrigon_audit_vault.json
```

`.gitignore` already excludes `.env`, `generated/*`, `cloudflared/cert.pem` and
`cloudflared/*.json`. If a secret ever does land in a commit, rotate it — do not
just amend the commit.

Recommended repo settings: branch protection on `main` requiring the CI workflow
(`.github/workflows/ci.yml` runs ruff, pytest on 3.11/3.12, a Docker build with a
live `/healthz` probe, and shellcheck), and a deploy key on the server if you
pull directly onto it.

**Open-core split.** The blueprint's Tier-1 play is to publish the thin MCP
bridge publicly while the grounding engine stays private. The cut line is clean:
publish `app/mcp/`, `app/models/`, `app/tools.py` and the client configs; keep
`data/jurisdictions/`, `app/compliance/` and `app/pipeline/` in the private repo.
A public client running `LEGAFY_MCP_MODE=remote` needs nothing else.
