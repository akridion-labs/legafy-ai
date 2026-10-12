"""Which AI client is calling — recorded as evidence, never trusted as identity.

An MCP client announces itself exactly once, in the ``initialize`` handshake, as
``clientInfo: {name, version}``. Everything in this module hangs off that string,
so the first thing to be clear about is what it is worth.

**It is self-reported and unverified.** Any client can send any name. Nothing
here may therefore influence authorisation, tier, rate limit, scope, or — most
importantly — what a tool says about the law. Those decisions belong to the
bearer token (``app/security/tenancy.py``) and to the compliance engine. This
module answers one question only: *who appears to be using Legafy, and how
much?* That is a product question, not a security one.

**Why it exists.** Legafy is distributed as a connector. Without this, the
business has no idea whether anyone outside Claude Desktop has ever run a single
audit — which client to support next, which one to test against before a
release, and whether the ChatGPT and Codex work paid for itself are all
unanswerable. The audit vault already records every call; this adds the one
dimension that was missing from it.

**The family map is deliberately small and deliberately incomplete.** It holds
only clients whose identifier has actually been observed, and every record keeps
the raw ``client_name`` alongside the family. An unrecognised client is recorded
as ``unknown`` *with its raw name intact*, so the fix is reading the breakdown
and adding a row — never a guess made in advance. A wrong mapping is worse than
no mapping: it silently merges two clients' usage and nobody notices.
"""

from __future__ import annotations

from contextvars import ContextVar

__all__ = [
    "CLIENT_FAMILIES",
    "CURRENT_CLIENT",
    "client_context",
    "get_client",
    "normalise_client",
    "set_client",
]

# (substring, family). Matched case-insensitively, in order, against the
# client's self-reported name.
#
# ORDER IS THE WHOLE CORRECTNESS ARGUMENT. Many clients embed another client's
# identifier in their own: Cursor reports "cursor-vscode", Claude Code contains
# "claude". If the generic row is reached first, the specific client silently
# disappears into the generic bucket and the breakdown looks plausible while
# being wrong — the worst failure mode for a usage report, because nobody goes
# looking for a number that seems fine.
#
# The rule, enforced by a test: **if one needle is a substring of another, the
# longer one must come first.** Groups below run specific → generic.
#
# Only add a row once the identifier has actually appeared in `unmapped_names`.
# A guessed mapping that is wrong merges two clients' usage invisibly; an
# unmapped one is loudly visible and harmless.
CLIENT_FAMILIES: tuple[tuple[str, str], ...] = (
    # Anthropic surfaces — "claude-code" and "cowork" before bare "claude"
    ("claude-code", "claude-code"),
    ("claude code", "claude-code"),
    ("cowork", "claude-cowork"),
    ("claude", "claude"),
    # OpenAI surfaces
    ("codex", "codex"),
    ("chatgpt", "chatgpt"),
    ("openai", "chatgpt"),
    # Editors that embed "vscode" in their own identifier — all before it
    ("cursor", "cursor"),
    ("windsurf", "windsurf"),
    ("cline", "cline"),
    ("continue", "continue"),
    ("zed", "zed"),
    ("copilot", "copilot"),
    ("visual studio code", "vscode"),
    ("vscode", "vscode"),
    # Everything else
    ("groq", "groq"),
    ("gemini", "gemini"),
    ("librechat", "librechat"),
    ("goose", "goose"),
    ("inspector", "mcp-inspector"),
)

# Ambient for the duration of one tool call. A ContextVar rather than a
# parameter because this is cross-cutting telemetry on a path that already
# threads request_id and tenant: adding a fourth argument to every handler to
# carry something no handler reads would be worse.
CURRENT_CLIENT: ContextVar[dict[str, str] | None] = ContextVar(
    "legafy_mcp_client", default=None
)


def normalise_client(name: str | None) -> str:
    """Map a self-reported client name onto a family slug.

    Returns ``"unknown"`` for anything unrecognised — which is a signal to read
    the raw names in the breakdown and extend ``CLIENT_FAMILIES``, not a reason
    to drop the record.
    """
    if not name:
        return "unknown"
    lowered = name.strip().lower()
    for needle, family in CLIENT_FAMILIES:
        if needle in lowered:
            return family
    return "unknown"


def set_client(name: str | None, version: str | None = None) -> None:
    """Record the calling client for the remainder of this context."""
    if not name:
        CURRENT_CLIENT.set(None)
        return
    CURRENT_CLIENT.set(
        {
            # Bounded: this string reaches the audit vault, and the vault is
            # append-only. A client sending a megabyte of "name" must not be
            # able to bloat a file we promise to keep forever.
            "client_name": name.strip()[:120],
            "client_version": (version or "").strip()[:60] or None,
            "client_family": normalise_client(name),
        }
    )


def get_client() -> dict[str, str | None]:
    """The current client, as vault fields. All None when nothing identified."""
    current = CURRENT_CLIENT.get()
    if not current:
        return {"client_name": None, "client_version": None, "client_family": None}
    return dict(current)


class client_context:  # noqa: N801 - used as a context manager, not a class
    """Scope a client identity to a block, restoring the previous one after.

    Used by the HTTP API, where one process serves many callers and a leaked
    ContextVar would attribute the next request to the previous caller.
    """

    def __init__(self, name: str | None, version: str | None = None) -> None:
        self._name = name
        self._version = version
        self._token = None

    def __enter__(self) -> None:
        self._token = CURRENT_CLIENT.set(None)
        set_client(self._name, self._version)

    def __exit__(self, *exc) -> None:
        if self._token is not None:
            CURRENT_CLIENT.reset(self._token)
        return None
