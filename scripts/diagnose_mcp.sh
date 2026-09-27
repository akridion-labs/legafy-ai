#!/usr/bin/env bash
# diagnose_mcp.sh — why did Claude Desktop say "Server disconnected"?
#
# "Server disconnected" means Claude Desktop DID launch the server and the
# process then went away. That is a different problem from "no tools appeared",
# which means the config was never read. So the config is almost certainly fine
# and something is failing at startup — this finds out what, in one command.
#
# Run it from the repository root:
#
#     ./scripts/diagnose_mcp.sh
#
# It changes nothing. Every check is read-only.

set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1

PY="$REPO/.venv/bin/python"
LOG_DIR="$HOME/Library/Logs/Claude"
PASS=0
FAIL=0

say()  { printf '%s\n' "$*"; }
ok()   { printf '  \033[32mOK\033[0m    %s\n' "$*"; PASS=$((PASS + 1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; FAIL=$((FAIL + 1)); }
warn() { printf '  \033[33mNOTE\033[0m  %s\n' "$*"; }
hdr()  { printf '\n\033[1m%s\033[0m\n' "$*"; }

say "Legafy MCP diagnostic"
say "repository: $REPO"

# ---------------------------------------------------------------- 1. interpreter
hdr "1. The interpreter Claude Desktop is told to launch"
if [ -x "$PY" ]; then
  ok ".venv/bin/python exists and is executable"
  if VER="$("$PY" --version 2>&1)"; then
    ok "it runs: $VER"
  else
    bad "it exists but will not run — this alone explains a disconnect"
    say "        $VER"
  fi
else
  bad ".venv/bin/python is missing. Build it: python3 -m venv .venv"
  say ""
  say "Nothing below can pass until that exists. Stop here."
  exit 1
fi

# A venv built against a Homebrew Python that was later upgraded or removed is
# the most common way a working setup breaks on a Mac without anyone touching it.
if [ -f "$REPO/.venv/pyvenv.cfg" ]; then
  HOME_DIR="$(sed -n 's/^home = //p' "$REPO/.venv/pyvenv.cfg")"
  if [ -n "$HOME_DIR" ] && [ ! -d "$HOME_DIR" ]; then
    bad "the venv was built against $HOME_DIR, which no longer exists"
    warn "Homebrew probably upgraded or removed that Python. Rebuild: rm -rf .venv && python3 -m venv .venv"
  else
    ok "the Python the venv was built against is still present"
  fi
fi

# ---------------------------------------------------------------- 2. imports
hdr "2. Can the server's dependencies be imported?"
if IMPORT_ERR="$("$PY" - <<'PY' 2>&1
import sys
failed = []
for mod in ("mcp", "pydantic", "pydantic_core", "httpx", "anyio", "docx"):
    try:
        __import__(mod)
    except Exception as exc:
        failed.append(f"{mod}: {type(exc).__name__}: {exc}")
if failed:
    print("\n".join(failed))
    sys.exit(1)
import pydantic
from importlib.metadata import version
print(f"mcp {version('mcp')} | pydantic {pydantic.VERSION} | python {sys.version.split()[0]}")
PY
)"; then
  ok "$IMPORT_ERR"
else
  bad "a dependency will not import — this is very likely your answer"
  say "$IMPORT_ERR" | sed 's/^/        /'
  warn "fix: .venv/bin/pip install -r requirements-dev.txt"
fi

# ---------------------------------------------------------------- 3. handshake
hdr "3. A real MCP handshake, exactly as Claude Desktop performs it"
OUT="$(mktemp)"; ERR="$(mktemp)"
REQ='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"diagnostic","version":"0"}}}'

LEGAFY_MCP_MODE=local \
LEGAFY_ENV=development \
LEGAFY_PROVIDER_CHAIN=offline \
LEGAFY_TELEMETRY_SALT=diagnostic-salt \
  printf '%s\n' "$REQ" | LEGAFY_MCP_MODE=local LEGAFY_ENV=development \
  LEGAFY_PROVIDER_CHAIN=offline LEGAFY_TELEMETRY_SALT=diagnostic-salt \
  "$PY" -m app.mcp.server >"$OUT" 2>"$ERR"
RC=$?

if [ $RC -ne 0 ]; then
  bad "the server exited with code $RC — Claude Desktop would report exactly your error"
  say ""
  say "  --- the reason, from stderr ---"
  tail -30 "$ERR" | sed 's/^/        /'
else
  ok "the server started, answered and exited cleanly"
fi

# stdout MUST carry only JSON-RPC. One stray print corrupts the stream and the
# client hangs up — the single most common cause of a disconnect in a stdio server.
if [ -s "$OUT" ]; then
  FIRST_CHAR="$(head -c 1 "$OUT")"
  if [ "$FIRST_CHAR" = "{" ]; then
    ok "stdout is clean JSON-RPC (nothing is polluting the protocol stream)"
    if grep -q '"serverInfo"' "$OUT"; then
      ok "the server identified itself: $(sed -n 's/.*"name":"\([^"]*\)".*/\1/p' "$OUT" | head -1)"
    fi
  else
    bad "stdout does NOT start with '{' — something is printing over the protocol"
    say "  --- first 200 bytes of stdout ---"
    head -c 200 "$OUT" | sed 's/^/        /'
  fi
else
  bad "the server produced no output at all"
fi

if [ -s "$ERR" ]; then
  warn "stderr said (this is normal — logs belong on stderr):"
  tail -5 "$ERR" | sed 's/^/        /'
fi
rm -f "$OUT" "$ERR"

# ---------------------------------------------------------------- 4. stripped env
hdr "4. The same launch with a stripped environment"
say "  Claude Desktop does not hand a spawned server your Terminal's environment."
say "  If check 3 passed and this one fails, that difference is your answer."
SOUT="$(mktemp)"; SERR="$(mktemp)"
if printf '%s\n' "$REQ" | env -i HOME="$HOME" PATH=/usr/bin:/bin \
  LEGAFY_MCP_MODE=local LEGAFY_ENV=development \
  LEGAFY_PROVIDER_CHAIN=offline LEGAFY_TELEMETRY_SALT=diagnostic-salt \
  "$PY" -m app.mcp.server >"$SOUT" 2>"$SERR" &&
   [ "$(head -c 1 "$SOUT")" = "{" ]; then
  ok "works with no inherited environment too"
else
  bad "fails without your Terminal's environment — that is the difference"
  tail -20 "$SERR" | sed 's/^/        /'
fi
rm -f "$SOUT" "$SERR"

# ---------------------------------------------------------------- 5. claude's log
hdr "5. What Claude Desktop itself recorded"
if [ -d "$LOG_DIR" ]; then
  FOUND=0
  for f in "$LOG_DIR"/mcp-server-legafy*.log "$LOG_DIR"/mcp.log; do
    [ -f "$f" ] || continue
    FOUND=1
    say "  --- $(basename "$f") (last 25 lines) ---"
    tail -25 "$f" | sed 's/^/        /'
    say ""
  done
  [ $FOUND -eq 0 ] && warn "no legafy log yet — Claude Desktop has not tried to start it since the last config change"
else
  warn "$LOG_DIR does not exist (is this a Mac with Claude Desktop installed?)"
fi

# ---------------------------------------------------------------- verdict
hdr "Verdict"
if [ $FAIL -eq 0 ]; then
  say "  $PASS checks passed, 0 failed."
  say ""
  say "  The server is healthy when launched by hand. If Claude Desktop still"
  say "  says \"Server disconnected\", the remaining difference is Claude Desktop"
  say "  itself — quit it completely with Cmd-Q (closing the window is not"
  say "  enough), reopen, and send me section 5 above."
else
  say "  $PASS passed, $FAIL FAILED."
  say ""
  say "  Send me everything above. The first FAIL is the cause; the ones after"
  say "  it are usually consequences."
fi
say ""
