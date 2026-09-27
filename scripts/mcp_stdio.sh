#!/usr/bin/env bash
# mcp_stdio.sh — the launcher to point Claude Desktop (or any stdio MCP client) at.
#
# Put THIS in claude_desktop_config.json, not the interpreter:
#
#     {
#       "mcpServers": {
#         "legafy": {
#           "command": "/absolute/path/to/legafy-ai/scripts/mcp_stdio.sh"
#         }
#       }
#     }
#
# No "args", no "cwd", no "env" needed. That is the entire point.
#
# WHY THIS EXISTS
#
# The obvious config — command: .venv/bin/python, args: ["-m","app.mcp.server"],
# cwd: <repo> — has three separate ways to fail silently, and every one of them
# produces the same useless symptom: the process dies before the handshake and
# the client reports "Server disconnected" / "Connection closed" with no log.
#
#   1. `python -m app.mcp.server` finds the `app` package ONLY because `-m` puts
#      the working directory on sys.path. If the client does not apply `cwd` —
#      and some launch paths do not — you get
#      `ModuleNotFoundError: No module named 'app'` and an instant exit.
#   2. A relative interpreter path resolves against whatever cwd the client
#      happened to use.
#   3. A spawned server does not inherit your shell's environment, so anything
#      that depended on it is gone.
#
# This script resolves its own location, so all three stop mattering: it works
# from any working directory, with any environment, called by any client.
#
# It is deliberately a few lines of shell. A launcher that can itself fail in
# interesting ways defeats the purpose.

set -eu

# Resolve this script's real directory even when reached through a symlink, so
# the repo root is found from the script's own location rather than from cwd.
SELF="$0"
while [ -L "$SELF" ]; do
  LINK="$(readlink "$SELF")"
  case "$LINK" in
    /*) SELF="$LINK" ;;
    *)  SELF="$(dirname "$SELF")/$LINK" ;;
  esac
done
REPO="$(cd "$(dirname "$SELF")/.." && pwd)"

PY="$REPO/.venv/bin/python"
if [ ! -x "$PY" ]; then
  # stderr, never stdout: stdout belongs to the JSON-RPC protocol and one stray
  # byte on it corrupts the stream for good.
  echo "legafy: no interpreter at $PY" >&2
  echo "legafy: build it with:  cd '$REPO' && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt" >&2
  exit 1
fi

# Defaults for a local run. Anything already set in the environment — by the
# client's "env" block, or by a shell — wins, so this configures without
# overriding.
: "${LEGAFY_MCP_MODE:=local}"
: "${LEGAFY_ENV:=development}"
: "${LEGAFY_PROVIDER_CHAIN:=offline}"
: "${LEGAFY_TELEMETRY_SALT:=local-dev-salt-change-before-production}"
export LEGAFY_MCP_MODE LEGAFY_ENV LEGAFY_PROVIDER_CHAIN LEGAFY_TELEMETRY_SALT

# `cd` so `-m` can find the package, and `exec` so the Python process replaces
# this shell — the client's signals and stdin/stdout reach it directly, with no
# shell sitting in the middle of the protocol stream.
cd "$REPO"
exec "$PY" -m app.mcp.server "$@"
