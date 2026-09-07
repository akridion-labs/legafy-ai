#!/usr/bin/env bash
# =============================================================================
# Legafy AI — one-shot host preparation for the custom CPU server
#
# Verifies docker/compose are present, creates the runtime directories,
# seeds .env with a real telemetry salt, mints a starter enterprise license
# token, and locks the environment down to production posture.
#
# Safe to re-run: every step checks before it writes.
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"
cd "${REPO_ROOT}"

if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'; C_BLUE=$'\033[34m'
else
  C_RESET=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_BLUE=""
fi
log()  { printf '%s[+]%s %s\n' "${C_GREEN}" "${C_RESET}" "$*"; }
info() { printf '%s[*]%s %s\n' "${C_BLUE}"  "${C_RESET}" "$*"; }
warn() { printf '%s[!]%s %s\n' "${C_YELLOW}" "${C_RESET}" "$*" >&2; }
die()  { printf '%s[x]%s %s\n' "${C_RED}"   "${C_RESET}" "$*" >&2; exit 1; }

ENV_FILE="${REPO_ROOT}/.env"
ENV_EXAMPLE="${REPO_ROOT}/.env.example"
LICENSE_REGISTRY="${REPO_ROOT}/data/license_registry.json"
LICENSE_REGISTRY_EXAMPLE="${REPO_ROOT}/data/license_registry.example.json"

# --- 1. Verify docker + compose v2 -------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  die "docker is not installed. Install it first: https://docs.docker.com/engine/install/"
fi

if ! docker compose version >/dev/null 2>&1; then
  die "docker compose (v2, the 'docker compose' subcommand) is not available. Install/upgrade Docker Desktop, or the docker-compose-plugin package on Linux: https://docs.docker.com/compose/install/"
fi

log "docker: $(docker --version)"
log "docker compose: $(docker compose version --short 2>/dev/null || docker compose version)"

# --- 2. Create generated/ with mode 0750 -------------------------------------
mkdir -p "${REPO_ROOT}/generated"
chmod 0750 "${REPO_ROOT}/generated"
log "generated/ ready (mode 0750)."

# --- 3. .env.example -> .env if absent ----------------------------------------
if [[ -f "${ENV_FILE}" ]]; then
  log ".env already exists — leaving it in place."
else
  [[ -f "${ENV_EXAMPLE}" ]] || die "Missing ${ENV_EXAMPLE} — cannot bootstrap .env."
  cp "${ENV_EXAMPLE}" "${ENV_FILE}"
  log "Created .env from .env.example."
fi

# Portable "set or replace a KEY=value line" helper.
set_env_var() {
  local key="$1" value="$2"
  local tmp
  tmp="$(mktemp)"
  if grep -q "^${key}=" "${ENV_FILE}"; then
    awk -v k="${key}" -v v="${value}" '
      BEGIN { done = 0 }
      $0 ~ "^" k "=" { print k "=" v; done = 1; next }
      { print }
      END { if (!done) print k "=" v }
    ' "${ENV_FILE}" > "${tmp}"
  else
    cp "${ENV_FILE}" "${tmp}"
    printf '%s=%s\n' "${key}" "${value}" >> "${tmp}"
  fi
  mv "${tmp}" "${ENV_FILE}"
}

get_env_var() {
  local key="$1"
  grep "^${key}=" "${ENV_FILE}" | head -n1 | cut -d'=' -f2-
}

command -v openssl >/dev/null 2>&1 || die "openssl is required (for LEGAFY_TELEMETRY_SALT and license token generation) but was not found."

# --- 4. LEGAFY_TELEMETRY_SALT: generate only if still the placeholder --------
CURRENT_SALT="$(get_env_var LEGAFY_TELEMETRY_SALT || true)"
if [[ -z "${CURRENT_SALT}" || "${CURRENT_SALT}" == "CHANGE_ME_openssl_rand_hex_32" ]]; then
  NEW_SALT="$(openssl rand -hex 32)"
  set_env_var LEGAFY_TELEMETRY_SALT "${NEW_SALT}"
  log "Generated a fresh LEGAFY_TELEMETRY_SALT."
  warn "This salt pseudonymises business-concept strings at rest. Back it up — rotating it later permanently breaks correlation with older audit-vault records."
else
  log "LEGAFY_TELEMETRY_SALT already set — leaving it untouched."
fi

# --- 5. Mint a starter ENTERPRISE token, print once, store only its hash ----
mkdir -p "${REPO_ROOT}/data"
if [[ -f "${LICENSE_REGISTRY}" ]]; then
  log "data/license_registry.json already exists — not overwriting; skipping starter token mint."
else
  STARTER_TOKEN="$(openssl rand -hex 24)"
  TOKEN_SHA256="$(printf '%s' "${STARTER_TOKEN}" | openssl dgst -sha256 -r | awk '{print $1}')"
  EXPIRES_ON="$(date -u -d '+365 days' +%Y-%m-%d 2>/dev/null || date -u -v+365d +%Y-%m-%d 2>/dev/null || echo "")"

  # The registry is a flat JSON object keyed by an arbitrary tenant label
  # (any key not starting with "_", e.g. "_README" is a documentation-only
  # entry app/security/tenancy.py skips); each value is one tenant record
  # with organization_name / tier / token_sha256 / expires_on (+ optional
  # per-tenant scope/limit overrides) — see data/license_registry.example.json
  # and app/security/tenancy.py:TenantRegistry._load_file for the exact
  # contract this must satisfy.
  if [[ -f "${LICENSE_REGISTRY_EXAMPLE}" ]]; then
    info "Seeding data/license_registry.json from data/license_registry.example.json."
    cp "${LICENSE_REGISTRY_EXAMPLE}" "${LICENSE_REGISTRY}"
    # Add our freshly minted starter tenant alongside whatever sample
    # tenants the example file ships, without disturbing them.
    python3 - "${LICENSE_REGISTRY}" "${TOKEN_SHA256}" "${EXPIRES_ON}" <<'PYEOF'
import json, sys
path, token_sha256, expires_on = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as f:
    data = json.load(f)

if not isinstance(data, dict):
    # Unknown shape from the example file — do not guess further, leave the
    # example content as-is rather than corrupt it.
    sys.exit(0)

key = "bootstrap-enterprise"
suffix = 2
while key in data:
    key = f"bootstrap-enterprise-{suffix}"
    suffix += 1

data[key] = {
    "organization_name": "Akridion Labs LLP (bootstrap)",
    "tier": "ENTERPRISE_B2B",
    "token_sha256": token_sha256,
    "expires_on": expires_on,
}

with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PYEOF
  else
    info "No data/license_registry.example.json found — writing a minimal starter registry."
    cat > "${LICENSE_REGISTRY}" <<EOF
{
  "bootstrap-enterprise": {
    "organization_name": "Akridion Labs LLP (bootstrap)",
    "tier": "ENTERPRISE_B2B",
    "token_sha256": "${TOKEN_SHA256}",
    "expires_on": "${EXPIRES_ON}"
  }
}
EOF
  fi

  echo
  echo "${C_YELLOW}=============================================================================${C_RESET}"
  echo "${C_YELLOW}  STARTER ENTERPRISE TOKEN — shown ONLY this once. Store it in a password${C_RESET}"
  echo "${C_YELLOW}  manager or secrets vault now. Only its SHA-256 hash is kept on disk.${C_RESET}"
  echo "${C_YELLOW}=============================================================================${C_RESET}"
  echo
  echo "  ${STARTER_TOKEN}"
  echo
  log "Wrote SHA-256 of the starter token to data/license_registry.json."
fi

# --- 6. Lock down bootstrap tokens + production posture ----------------------
set_env_var LEGAFY_BOOTSTRAP_TOKENS_ENABLED "false"
set_env_var LEGAFY_ENV "production"
log "Set LEGAFY_BOOTSTRAP_TOKENS_ENABLED=false and LEGAFY_ENV=production in .env."

# --- Next steps ---------------------------------------------------------------
cat <<EOF

${C_GREEN}Bootstrap complete.${C_RESET}

Next steps:
  1. Review .env — fill in provider API keys / Ollama URL as needed.
  2. Set up the Cloudflare Tunnel:
       ./setup_tunnel.sh
  3. Bring the stack up:
       make up            # bridge networking (default)
       make up-host        # host networking on the CPU server
  4. Verify:
       make smoke

EOF
