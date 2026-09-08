#!/usr/bin/env python3
"""Validate everything an AI platform needs before it will talk to Legafy.

Run this before publishing, before a demo, and in CI. It catches the class of
failure that is invisible until someone tries to install the thing: a manifest
that parses but names a directory that does not exist, a tool whose JSON Schema
a strict validator rejects, an MCP handshake that 401s because the token header
was spelled differently in the plugin than in the server.

Two modes:

    python scripts/validate_integration.py            # static checks only
    python scripts/validate_integration.py --live     # + boot the app in-process
                                                      #   and run a real MCP
                                                      #   initialize / tools/list
                                                      #   / tools/call
    python scripts/validate_integration.py --live --url https://host/mcp --token T
                                                      # + probe a DEPLOYED server

Exit code is 0 only when every check passes. Nothing here mutates a file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent

GREEN, RED, YELLOW, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

_results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    _results.append((ok, name, detail))
    mark = f"{GREEN}PASS{RESET}" if ok else f"{RED}FAIL{RESET}"
    print(f"  [{mark}] {name}" + (f"  — {detail}" if detail and not ok else ""))
    return ok


def warn(name: str, detail: str = "") -> None:
    print(f"  [{YELLOW}WARN{RESET}] {name}" + (f"  — {detail}" if detail else ""))


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        check(False, f"{path.relative_to(REPO)} exists")
    except json.JSONDecodeError as exc:
        check(False, f"{path.relative_to(REPO)} is valid JSON", str(exc))
    return None


# --------------------------------------------------------------------------
# 1. Plugin marketplace (install path B for Claude Code)
# --------------------------------------------------------------------------
def validate_marketplace() -> None:
    print("\nPlugin marketplace")
    market = load_json(REPO / ".claude-plugin" / "marketplace.json")
    if not market:
        return
    check(bool(market.get("name")), "marketplace has a name")
    check(bool(market.get("owner", {}).get("name")), "marketplace names an owner")
    plugins = market.get("plugins") or []
    check(bool(plugins), "marketplace lists at least one plugin")

    for entry in plugins:
        name = entry.get("name", "<unnamed>")
        source = entry.get("source", "")
        check(bool(source), f"plugin '{name}' declares a source")
        if source.startswith("./"):
            plugin_dir = REPO / source[2:]
            if not check(plugin_dir.is_dir(), f"plugin '{name}' source directory exists", str(plugin_dir)):
                continue
            manifest = load_json(plugin_dir / ".claude-plugin" / "plugin.json")
            if not manifest:
                continue
            check(
                manifest.get("name") == name,
                f"plugin '{name}' manifest name matches the marketplace entry",
                f"{manifest.get('name')!r} != {name!r}",
            )
            check(
                manifest.get("version") == entry.get("version"),
                f"plugin '{name}' version matches the marketplace entry",
                f"{manifest.get('version')!r} != {entry.get('version')!r}",
            )
            validate_plugin_manifest(name, manifest, plugin_dir)


def validate_plugin_manifest(name: str, manifest: dict, plugin_dir: Path) -> None:
    servers = manifest.get("mcpServers") or {}
    check(bool(servers), f"plugin '{name}' declares an mcpServers block")
    user_config = manifest.get("userConfig") or {}

    for server_name, server in servers.items():
        transport = server.get("type", "stdio")
        check(
            transport in {"http", "sse", "stdio"},
            f"plugin '{name}' server '{server_name}' uses a known transport",
            transport,
        )
        blob = json.dumps(server)
        # Every ${user_config.X} the server template uses must be declared, or
        # the install prompts for nothing and the connection silently has no
        # token in the header.
        for token in _placeholders(blob):
            check(
                token in user_config,
                f"plugin '{name}' declares userConfig '{token}'",
                f"referenced by server '{server_name}' but never declared",
            )
        if transport == "http":
            url = server.get("url", "")
            check(
                "${user_config." in url or url.startswith("https://"),
                f"plugin '{name}' server '{server_name}' URL is https or configurable",
                url,
            )
            check(
                "authorization" in {k.lower() for k in (server.get("headers") or {})},
                f"plugin '{name}' server '{server_name}' sends an Authorization header",
            )

    for key, spec in user_config.items():
        if "token" in key or "key" in key or "secret" in key:
            check(
                bool(spec.get("sensitive")),
                f"plugin '{name}' marks userConfig '{key}' as sensitive",
                "a credential shown in plain text in the settings UI",
            )

    skills = list((plugin_dir / "skills").glob("*/SKILL.md")) if (plugin_dir / "skills").is_dir() else []
    if skills:
        for skill in skills:
            head = skill.read_text(encoding="utf-8")[:400]
            check(
                head.startswith("---") and "description:" in head,
                f"skill '{skill.parent.name}' has frontmatter with a description",
            )
    else:
        warn(f"plugin '{name}' ships no skills", "the MCP tools still work; a skill adds the how-to")


def _placeholders(blob: str) -> set[str]:
    import re

    return set(re.findall(r"\$\{user_config\.([A-Za-z0-9_]+)\}", blob))


# --------------------------------------------------------------------------
# 2. Config-file examples (install path A for every stdio/HTTP client)
# --------------------------------------------------------------------------
def validate_examples() -> None:
    print("\nClient config examples")
    for filename in ("mcp.json", "claude_desktop_config.json"):
        cfg = load_json(REPO / "examples" / filename)
        if not cfg:
            continue
        servers = cfg.get("mcpServers") or {}
        check(bool(servers), f"examples/{filename} declares mcpServers")
        for server_name, server in servers.items():
            has_command = bool(server.get("command"))
            has_url = bool(server.get("url"))
            check(
                has_command or has_url,
                f"examples/{filename}:{server_name} has a command or a url",
            )
            if has_command:
                check(
                    server.get("args") is not None,
                    f"examples/{filename}:{server_name} passes args to the command",
                )


# --------------------------------------------------------------------------
# 3. The tool contract itself — what every platform actually consumes
# --------------------------------------------------------------------------
def validate_tools() -> None:
    print("\nTool contract")
    sys.path.insert(0, str(REPO))
    from app.tools import TOOLS, manifest  # noqa: PLC0415

    man = manifest()
    check(bool(man.get("tools")), "tool manifest is non-empty")
    seen: set[str] = set()

    for spec in TOOLS:
        name = spec.name
        check(name not in seen, f"tool '{name}' name is unique")
        seen.add(name)
        # Platforms differ on the allowed character set; this is the strict
        # intersection (OpenAI function names, MCP tool names, Gemini
        # declarations all accept it).
        check(
            name.replace("_", "").isalnum() and name[0].isalpha() and len(name) <= 64,
            f"tool '{name}' name is portable across platforms",
            "use [a-z0-9_], start with a letter, max 64 chars",
        )
        check(
            len(spec.description) >= 40,
            f"tool '{name}' description is substantive",
            "a thin description is why a model calls the wrong tool",
        )
        schema = spec.json_schema()
        check(schema.get("type") == "object", f"tool '{name}' schema is an object")
        check(
            "properties" in schema,
            f"tool '{name}' schema declares properties",
        )
        # $defs / $ref are legal JSON Schema but several function-calling
        # implementations flatten badly. Warn rather than fail — MCP is fine.
        if "$defs" in json.dumps(schema):
            warn(
                f"tool '{name}' schema uses $defs/$ref",
                "fine over MCP; some function-calling runtimes need it inlined",
            )
        check(bool(spec.required_scope), f"tool '{name}' declares a required scope")


# --------------------------------------------------------------------------
# 4. Live handshake
# --------------------------------------------------------------------------
def validate_live(url: str | None, token: str) -> None:
    print("\nLive MCP handshake" + (f" against {url}" if url else " (in-process)"))
    sys.path.insert(0, str(REPO))
    import httpx  # noqa: PLC0415

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }

    def rpc(client: httpx.Client, path: str, method: str, params: dict | None = None) -> dict:
        body = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params is not None:
            body["params"] = params
        response = client.post(path, headers=headers, json=body, timeout=30)
        response.raise_for_status()
        text = response.text
        if text.startswith("event:"):  # SSE framing
            text = next(
                line[6:] for line in text.splitlines() if line.startswith("data: ")
            )
        return json.loads(text)

    if url:
        base, path = url.rsplit("/", 1)
        client = httpx.Client(base_url=base)
        path = "/" + path
        ctx = None
    else:
        from fastapi.testclient import TestClient  # noqa: PLC0415

        from app.main import app  # noqa: PLC0415

        ctx = TestClient(app)
        client = ctx.__enter__()
        path = "/mcp/"

    try:
        init = rpc(
            client,
            path,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "legafy-validator", "version": "1"},
            },
        )
        check("result" in init, "initialize returns a result", json.dumps(init)[:200])
        listed = rpc(client, path, "tools/list")
        names = [t["name"] for t in listed.get("result", {}).get("tools", [])]
        check(bool(names), "tools/list returns tools", json.dumps(listed)[:200])
        check(
            "execute_regional_compliance_audit" in names,
            "the mandatory grounding tool is exposed",
            str(names),
        )
        called = rpc(
            client,
            path,
            "tools/call",
            {
                "name": "execute_regional_compliance_audit",
                "arguments": {
                    "business_concept": "A validator probe for the Legafy integration check",
                    "industry_vertical": "B2B SaaS",
                    "state_location": "Telangana",
                    "activity_flags": ["employs_persons"],
                },
            },
        )
        content = called.get("result", {}).get("content", [])
        check(bool(content), "tools/call returns content", json.dumps(called)[:200])
        if content:
            payload = json.loads(content[0]["text"])
            check("lane" in payload, "audit result carries a traffic-light lane")
            check("obligations" in payload, "audit result carries the obligation ledger")
            check(
                "research_checklist" in payload,
                "audit result carries the register-search checklist",
            )
    finally:
        if ctx is not None:
            ctx.__exit__(None, None, None)
        else:
            client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="run a real MCP handshake")
    parser.add_argument("--url", default=None, help="deployed /mcp endpoint to probe")
    parser.add_argument(
        "--token", default="akridion_dev_99x", help="bearer token for the live probe"
    )
    args = parser.parse_args()

    print("Legafy integration validation")
    validate_marketplace()
    validate_examples()
    validate_tools()
    if args.live:
        validate_live(args.url, args.token)

    failed = [name for ok, name, _ in _results if not ok]
    print(f"\n{len(_results) - len(failed)}/{len(_results)} checks passed")
    if failed:
        print(f"{RED}FAILED:{RESET}")
        for name in failed:
            print(f"  - {name}")
        return 1
    print(f"{GREEN}Ready to publish.{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
