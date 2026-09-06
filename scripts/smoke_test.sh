#!/usr/bin/env bash
# =============================================================================
# Legafy AI — end-to-end smoke test against a running instance
#
# Exercises the core guardrails over HTTP: health, tool discovery, state
# isolation (a valid Telangana audit succeeds, an unmapped jurisdiction is
# refused), the RED-lane trip for high-risk concepts, and a dry-run of the
# document-generation chunk plan. Exits non-zero if any check fails.
#
# Does not assume `jq` — response bodies are parsed with python3.
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"
ENV_FILE="${REPO_ROOT}/.env"

if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'; C_GREEN=$'\033[32m'; C_RED=$'\033[31m'
else
  C_RESET=""; C_GREEN=""; C_RED=""
fi

BASE_URL="http://localhost:8000"
TOKEN=""

usage() {
  cat <<'EOF'
Usage: smoke_test.sh [--base-url URL] [--token TOKEN]

  --base-url URL   API base URL (default: http://localhost:8000)
  --token TOKEN    Bearer token to authenticate with (default: read
                    LEGAFY_SMOKE_TOKEN or LEGAFY_DEV_TOKEN from .env, else
                    the literal string "dev-token")
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url) BASE_URL="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "${TOKEN}" ]]; then
  if [[ -f "${ENV_FILE}" ]]; then
    TOKEN="$(grep -E '^(LEGAFY_SMOKE_TOKEN|LEGAFY_DEV_TOKEN)=' "${ENV_FILE}" | head -n1 | cut -d'=' -f2-)"
  fi
  TOKEN="${TOKEN:-dev-token}"
fi

PASS_COUNT=0
FAIL_COUNT=0

pass() { printf '%s[PASS]%s %s\n' "${C_GREEN}" "${C_RESET}" "$*"; PASS_COUNT=$((PASS_COUNT + 1)); }
fail() { printf '%s[FAIL]%s %s\n' "${C_RED}" "${C_RESET}" "$*" >&2; FAIL_COUNT=$((FAIL_COUNT + 1)); }

# Performs a request, splits body/status via the trailing status-code line
# curl -w appends, and leaves them in the globals RESP_BODY / RESP_STATUS.
request() {
  local method="$1" path="$2" data="${3:-}"
  local raw
  if [[ -n "${data}" ]]; then
    raw="$(curl -sS -w '\n%{http_code}' -X "${method}" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Content-Type: application/json" \
      --data "${data}" \
      "${BASE_URL}${path}" || true)"
  else
    raw="$(curl -sS -w '\n%{http_code}' -X "${method}" \
      -H "Authorization: Bearer ${TOKEN}" \
      "${BASE_URL}${path}" || true)"
  fi
  RESP_STATUS="${raw##*$'\n'}"
  RESP_BODY="${raw%$'\n'"${RESP_STATUS}"}"
}

json_contains() {
  # Usage: json_contains '<json>' '<needle>' -> exit 0 if needle appears
  # anywhere in the raw JSON text (case-sensitive substring), else exit 1.
  python3 -c '
import sys
body, needle = sys.argv[1], sys.argv[2]
sys.exit(0 if needle in body else 1)
' "$1" "$2"
}

echo "Target: ${BASE_URL}"
echo

# --- 1. /healthz --------------------------------------------------------------
request GET "/healthz"
if [[ "${RESP_STATUS}" == "200" ]] && json_contains "${RESP_BODY}" '"ok"'; then
  pass "/healthz reports ok (200)"
else
  fail "/healthz did not report ok (status=${RESP_STATUS}, body=${RESP_BODY})"
fi

# --- 2. /mcp/tools lists execute_regional_compliance_audit --------------------
request GET "/mcp/tools"
if [[ "${RESP_STATUS}" == "200" ]] && json_contains "${RESP_BODY}" 'execute_regional_compliance_audit'; then
  pass "/mcp/tools includes execute_regional_compliance_audit"
else
  fail "/mcp/tools missing execute_regional_compliance_audit (status=${RESP_STATUS})"
fi

# --- 3. Telangana audit succeeds and names IN-TG ------------------------------
TG_PAYLOAD='{"concept_summary": "A SaaS payroll tool for retail staff", "state_location": "Telangana", "activity_tags": ["payroll", "saas"]}'
request POST "/api/v1/audit" "${TG_PAYLOAD}"
if [[ "${RESP_STATUS}" == "200" ]] && json_contains "${RESP_BODY}" 'IN-TG'; then
  pass "Telangana audit succeeds (200) and cites IN-TG"
else
  fail "Telangana audit did not succeed with IN-TG (status=${RESP_STATUS}, body=${RESP_BODY})"
fi

# --- 4. Unmapped jurisdiction ("Atlantis") is refused with 422 ----------------
ATLANTIS_PAYLOAD='{"concept_summary": "A SaaS payroll tool for retail staff", "state_location": "Atlantis", "activity_tags": ["payroll", "saas"]}'
request POST "/api/v1/audit" "${ATLANTIS_PAYLOAD}"
if [[ "${RESP_STATUS}" == "422" ]]; then
  pass "Unmapped jurisdiction 'Atlantis' refused with 422 (state isolation holds)"
else
  fail "Expected 422 for unmapped jurisdiction 'Atlantis', got ${RESP_STATUS} (body=${RESP_BODY})"
fi

# --- 5. Escrow / cross-border payment concept trips RED -----------------------
ESCROW_PAYLOAD='{"concept_summary": "A cross-border payment escrow platform routing customer funds between India and the US", "state_location": "Telangana", "activity_tags": ["escrow", "payments", "cross-border"]}'
request POST "/api/v1/audit" "${ESCROW_PAYLOAD}"
if [[ "${RESP_STATUS}" == "200" ]] && json_contains "${RESP_BODY}" 'RED'; then
  pass "Escrow/cross-border concept trips RED (halt & retain counsel)"
else
  fail "Expected RED traffic light for escrow concept (status=${RESP_STATUS}, body=${RESP_BODY})"
fi

# --- 6. dry_run structure generation returns a chunk plan ---------------------
DRYRUN_PAYLOAD='{"concept_summary": "A SaaS payroll tool for retail staff", "state_location": "Telangana", "activity_tags": ["payroll", "saas"], "dry_run": true}'
request POST "/api/v1/legal/generate-structure" "${DRYRUN_PAYLOAD}"
if [[ "${RESP_STATUS}" == "200" ]] && json_contains "${RESP_BODY}" 'chunk'; then
  pass "dry_run generate-structure returns a chunk plan"
else
  fail "dry_run generate-structure did not return a chunk plan (status=${RESP_STATUS}, body=${RESP_BODY})"
fi

echo
echo "----------------------------------------"
echo "Passed: ${PASS_COUNT}  Failed: ${FAIL_COUNT}"

if [[ "${FAIL_COUNT}" -gt 0 ]]; then
  exit 1
fi
exit 0
