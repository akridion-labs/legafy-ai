#!/usr/bin/env bash
# =============================================================================
# Legafy AI — operational healthcheck (cron / systemd friendly)
#
# Exit 0 if the API reports healthy, exit 1 otherwise. Prints nothing on
# success unless --verbose is given, so it's quiet in a crontab by default.
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

BASE_URL="${LEGAFY_HEALTHCHECK_URL:-http://localhost:8000}"
VERBOSE=0

usage() {
  cat <<'EOF'
Usage: healthcheck.sh [--base-url URL] [--verbose]

  --base-url URL   API base URL (default: http://localhost:8000, or
                    $LEGAFY_HEALTHCHECK_URL if set)
  --verbose        Print the /healthz JSON body on success too
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url) BASE_URL="$2"; shift 2 ;;
    --verbose) VERBOSE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

BODY="$(curl -fsS --max-time 5 "${BASE_URL}/healthz" 2>/dev/null)" || {
  echo "healthcheck: FAIL — ${BASE_URL}/healthz did not respond" >&2
  exit 1
}

if [[ "${VERBOSE}" -eq 1 ]]; then
  echo "${BODY}"
fi

exit 0
