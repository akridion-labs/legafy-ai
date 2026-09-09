#!/usr/bin/env bash
# =============================================================================
# Legafy AI — Cloudflare Tunnel setup automation
#
# Idempotent end-to-end bring-up of a named Cloudflare Tunnel for the
# Legafy AI API: install check -> login -> create tunnel -> write config ->
# route DNS -> mint token -> wire it into .env -> verify.
#
# Every mutating step is guarded so re-running this script is safe.
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

# --- Paths -------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
ENV_EXAMPLE="${SCRIPT_DIR}/.env.example"
CONFIG_DIR="${SCRIPT_DIR}/cloudflared"
CONFIG_TEMPLATE="${CONFIG_DIR}/config.yml.example"
CONFIG_FILE="${CONFIG_DIR}/config.yml"
CRED_DIR="${HOME}/.cloudflared"

# --- Colourised logging helpers ----------------------------------------------
if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'; C_BLUE=$'\033[34m'
else
  C_RESET=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_BLUE=""
fi

log()  { printf '%s[+]%s %s\n' "${C_GREEN}" "${C_RESET}" "$*"; }
info() { printf '%s[*]%s %s\n' "${C_BLUE}"  "${C_RESET}" "$*"; }
warn() { printf '%s[!]%s %s\n' "${C_YELLOW}" "${C_RESET}" "$*" >&2; }
die()  { printf '%s[x]%s %s\n' "${C_RED}"   "${C_RESET}" "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage: setup_tunnel.sh [options]

Automates the Cloudflare Tunnel bring-up for the Legafy AI API:
cloudflared install check, login, tunnel create, config.yml generation,
DNS route, token mint, and .env wiring. Every step is idempotent.

Options:
  --name <name>          Tunnel name (default: $CLOUDFLARE_TUNNEL_NAME or
                          akridion-legal-tunnel)
  --hostname <fqdn>      Public hostname to route to the tunnel (default:
                          $CLOUDFLARE_HOSTNAME or legal-mcp.akridion.com)
  --port <port>          Local port the API listens on (default: 8000)
  --non-interactive      Never prompt; fail instead of waiting on input
                          (e.g. `cloudflared tunnel login` still opens a
                          browser flow it cannot skip — this flag only
                          controls prompts this script itself would issue)
  --force                Overwrite an existing cloudflared/config.yml, and
                          allow the "install cloudflared" step to actually
                          fetch/install a binary automatically for the
                          direct-download (non-apt, non-brew) Linux path
                          instead of just printing the command and exiting
  -h, --help             Show this help and exit
EOF
}

# --- Arg parsing ---------------------------------------------------------------
TUNNEL_NAME="${CLOUDFLARE_TUNNEL_NAME:-akridion-legal-tunnel}"
TUNNEL_HOSTNAME="${CLOUDFLARE_HOSTNAME:-legal-mcp.akridion.com}"
LOCAL_PORT="8000"
NON_INTERACTIVE=0
FORCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) TUNNEL_NAME="$2"; shift 2 ;;
    --hostname) TUNNEL_HOSTNAME="$2"; shift 2 ;;
    --port) LOCAL_PORT="$2"; shift 2 ;;
    --non-interactive) NON_INTERACTIVE=1; shift ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1 (see --help)" ;;
  esac
done

# --- Load .env without clobbering already-exported vars ----------------------
# CLOUDFLARE_TUNNEL_NAME / CLOUDFLARE_HOSTNAME above already prefer a live
# export over the default; this second pass additionally picks up values
# from .env for anything not already set in the environment, without
# overwriting what the shell already had exported.
if [[ -f "${ENV_FILE}" ]]; then
  while IFS='=' read -r key value; do
    [[ -z "${key}" || "${key}" == \#* ]] && continue
    key="${key%"${key##*[![:space:]]}"}"
    [[ -z "${key}" ]] && continue
    if [[ -z "${!key:-}" ]]; then
      value="${value%\"}"; value="${value#\"}"
      export "${key}=${value}"
    fi
  done < "${ENV_FILE}"
  # Re-apply CLI-overridable defaults now that .env may have set them.
  TUNNEL_NAME="${CLOUDFLARE_TUNNEL_NAME:-${TUNNEL_NAME}}"
  TUNNEL_HOSTNAME="${CLOUDFLARE_HOSTNAME:-${TUNNEL_HOSTNAME}}"
fi

info "Tunnel name:     ${TUNNEL_NAME}"
info "Public hostname: ${TUNNEL_HOSTNAME}"
info "Local port:      ${LOCAL_PORT}"

# --- OS/arch detection & cloudflared install check ----------------------------
OS_NAME="$(uname -s)"
ARCH_NAME="$(uname -m)"

install_hint_and_exit() {
  local cmd="$1"
  warn "cloudflared is not installed."
  echo
  echo "  ${cmd}"
  echo
  if [[ "${FORCE}" -eq 1 ]]; then
    info "--force given: attempting to run the install command now."
    eval "${cmd}"
    return 0
  fi
  die "Run the command above, then re-run this script. (Pass --force to attempt it automatically for direct-download installs.)"
}

ensure_cloudflared() {
  if command -v cloudflared >/dev/null 2>&1; then
    log "cloudflared found: $(cloudflared --version 2>&1 | head -n1)"
    return 0
  fi

  case "${OS_NAME}" in
    Darwin)
      install_hint_and_exit "brew install cloudflared"
      ;;
    Linux)
      if [[ -f /etc/debian_version ]]; then
        install_hint_and_exit "sudo mkdir -p --mode=0755 /usr/share/keyrings && curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null && echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs 2>/dev/null || echo bookworm) main' | sudo tee /etc/apt/sources.list.d/cloudflared.list && sudo apt-get update && sudo apt-get install -y cloudflared"
      else
        local dl_arch bin_url
        case "${ARCH_NAME}" in
          x86_64|amd64) dl_arch="amd64" ;;
          aarch64|arm64) dl_arch="arm64" ;;
          armv7l) dl_arch="arm" ;;
          *) die "Unsupported architecture for direct download: ${ARCH_NAME}. See https://github.com/cloudflare/cloudflared/releases" ;;
        esac
        bin_url="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${dl_arch}"
        install_hint_and_exit "curl -fsSL -o /tmp/cloudflared '${bin_url}' && sudo install -m 0755 /tmp/cloudflared /usr/local/bin/cloudflared && rm -f /tmp/cloudflared"
      fi
      ;;
    *)
      die "Unsupported OS: ${OS_NAME}. Install cloudflared manually: https://github.com/cloudflare/cloudflared"
      ;;
  esac

  command -v cloudflared >/dev/null 2>&1 || die "cloudflared still not on PATH after install attempt."
  log "cloudflared installed: $(cloudflared --version 2>&1 | head -n1)"
}

ensure_cloudflared

# --- cloudflared tunnel login (idempotent: only if no cert.pem yet) ----------
if [[ -f "${CRED_DIR}/cert.pem" ]]; then
  log "Already authenticated (${CRED_DIR}/cert.pem present) — skipping login."
else
  if [[ "${NON_INTERACTIVE}" -eq 1 ]]; then
    die "Not authenticated with Cloudflare and --non-interactive was given. Run 'cloudflared tunnel login' manually first."
  fi
  info "Not authenticated — launching 'cloudflared tunnel login' (opens a browser)."
  cloudflared tunnel login
  [[ -f "${CRED_DIR}/cert.pem" ]] || die "Login did not produce ${CRED_DIR}/cert.pem — aborting."
  log "Authenticated."
fi

# --- Create the tunnel only if it does not already exist ---------------------
TUNNEL_LIST_OUTPUT="$(cloudflared tunnel list 2>/dev/null || true)"

if grep -qF "${TUNNEL_NAME}" <<<"${TUNNEL_LIST_OUTPUT}"; then
  log "Tunnel '${TUNNEL_NAME}' already exists — skipping creation."
else
  info "Creating tunnel '${TUNNEL_NAME}'."
  cloudflared tunnel create "${TUNNEL_NAME}"
  TUNNEL_LIST_OUTPUT="$(cloudflared tunnel list 2>/dev/null || true)"
fi

# Parse the UUID out of `cloudflared tunnel list` output. The default table
# format is "<ID> <NAME> <CREATED> <CONNECTIONS>" — take the first
# UUID-shaped token on the line that mentions our tunnel name.
TUNNEL_UUID="$(
  grep -F "${TUNNEL_NAME}" <<<"${TUNNEL_LIST_OUTPUT}" \
    | grep -oE '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}' \
    | head -n1
)"

[[ -n "${TUNNEL_UUID}" ]] || die "Could not determine tunnel UUID for '${TUNNEL_NAME}' from 'cloudflared tunnel list' output."
log "Tunnel UUID: ${TUNNEL_UUID}"

CRED_FILE="${CRED_DIR}/${TUNNEL_UUID}.json"

# --- Write cloudflared/config.yml from the template ---------------------------
if [[ -f "${CONFIG_FILE}" && "${FORCE}" -ne 1 ]]; then
  warn "cloudflared/config.yml already exists — leaving it untouched (pass --force to regenerate)."
else
  [[ -f "${CONFIG_TEMPLATE}" ]] || die "Missing template: ${CONFIG_TEMPLATE}"
  info "Writing ${CONFIG_FILE} from template."
  sed \
    -e "s#<TUNNEL-UUID>#${TUNNEL_UUID}#g" \
    -e "s#credentials-file:.*#credentials-file: ${CRED_FILE}#" \
    -e "s#hostname: .*#hostname: ${TUNNEL_HOSTNAME}#" \
    -e "s#service: http://localhost:8000#service: http://localhost:${LOCAL_PORT}#" \
    "${CONFIG_TEMPLATE}" > "${CONFIG_FILE}"
  log "Wrote ${CONFIG_FILE}."
fi

# --- Route DNS (tolerate "already exists") ------------------------------------
info "Routing DNS: ${TUNNEL_HOSTNAME} -> ${TUNNEL_NAME}"
ROUTE_OUTPUT="$(cloudflared tunnel route dns "${TUNNEL_NAME}" "${TUNNEL_HOSTNAME}" 2>&1)" && ROUTE_STATUS=0 || ROUTE_STATUS=$?
echo "${ROUTE_OUTPUT}"
if [[ "${ROUTE_STATUS}" -ne 0 ]]; then
  if grep -qiE 'already exists|already configured' <<<"${ROUTE_OUTPUT}"; then
    log "DNS route already exists — treating as success."
  else
    die "Failed to create DNS route (see output above)."
  fi
else
  log "DNS route created."
fi

# --- Mint a tunnel token and wire it into .env --------------------------------
info "Minting tunnel token."
TUNNEL_TOKEN="$(cloudflared tunnel token "${TUNNEL_NAME}" 2>/dev/null | tr -d '\n')"
[[ -n "${TUNNEL_TOKEN}" ]] || die "Failed to obtain a tunnel token from 'cloudflared tunnel token'."
log "Token obtained (never printed — length: ${#TUNNEL_TOKEN} chars)."

if [[ ! -f "${ENV_FILE}" ]]; then
  [[ -f "${ENV_EXAMPLE}" ]] || die "Neither .env nor .env.example exists — cannot create .env."
  info "No .env found — creating from .env.example."
  cp "${ENV_EXAMPLE}" "${ENV_FILE}"
else
  BACKUP_FILE="${ENV_FILE}.bak.$(date +%Y%m%d%H%M%S)"
  cp "${ENV_FILE}" "${BACKUP_FILE}"
  log "Backed up existing .env to $(basename "${BACKUP_FILE}")."
fi

if grep -q '^CLOUDFLARE_TUNNEL_TOKEN=' "${ENV_FILE}"; then
  # Portable in-place edit: write to a temp file then move, so we never
  # depend on `sed -i` GNU/BSD flag differences.
  TMP_ENV="$(mktemp)"
  awk -v tok="${TUNNEL_TOKEN}" '
    BEGIN { done = 0 }
    /^CLOUDFLARE_TUNNEL_TOKEN=/ { print "CLOUDFLARE_TUNNEL_TOKEN=" tok; done = 1; next }
    { print }
    END { if (!done) print "CLOUDFLARE_TUNNEL_TOKEN=" tok }
  ' "${ENV_FILE}" > "${TMP_ENV}"
  mv "${TMP_ENV}" "${ENV_FILE}"
else
  printf 'CLOUDFLARE_TUNNEL_TOKEN=%s\n' "${TUNNEL_TOKEN}" >> "${ENV_FILE}"
fi
# Keep the name/hostname in sync too, since they may have been overridden on
# the CLI for this run.
if grep -q '^CLOUDFLARE_TUNNEL_NAME=' "${ENV_FILE}"; then
  TMP_ENV="$(mktemp)"
  awk -v name="${TUNNEL_NAME}" '
    /^CLOUDFLARE_TUNNEL_NAME=/ { print "CLOUDFLARE_TUNNEL_NAME=" name; next }
    { print }
  ' "${ENV_FILE}" > "${TMP_ENV}"
  mv "${TMP_ENV}" "${ENV_FILE}"
fi
if grep -q '^CLOUDFLARE_HOSTNAME=' "${ENV_FILE}"; then
  TMP_ENV="$(mktemp)"
  awk -v host="${TUNNEL_HOSTNAME}" '
    /^CLOUDFLARE_HOSTNAME=/ { print "CLOUDFLARE_HOSTNAME=" host; next }
    { print }
  ' "${ENV_FILE}" > "${TMP_ENV}"
  mv "${TMP_ENV}" "${ENV_FILE}"
fi
log "CLOUDFLARE_TUNNEL_TOKEN (and name/hostname) written to .env."

# --- Verify: is the API already up? (warn, don't fail) -----------------------
if curl -fsS --max-time 3 "http://localhost:${LOCAL_PORT}/healthz" >/dev/null 2>&1; then
  log "API is already responding on http://localhost:${LOCAL_PORT}/healthz."
else
  warn "API is not responding on http://localhost:${LOCAL_PORT}/healthz yet — start it before traffic hits the tunnel (this is not a failure of tunnel setup)."
fi

# --- Final instructions -------------------------------------------------------
cat <<EOF

${C_GREEN}Tunnel setup complete.${C_RESET}

Next steps:
  1. Start (or restart) the stack so the new CLOUDFLARE_TUNNEL_TOKEN is picked up:
       docker compose up -d --build
     (on the CPU server, using host networking for cloudflared:)
       docker compose -f docker-compose.yml -f docker-compose.host.yml up -d --build

  2. Confirm the public hostname routes correctly:
       curl -I https://${TUNNEL_HOSTNAME}/healthz

  3. If you regenerate the token later, just re-run this script — it is
     idempotent and will refresh .env and cloudflared/config.yml as needed.

EOF
