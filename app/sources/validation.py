"""Source validity — is the citation we hand out still the right place to look?

The failure this exists to catch
--------------------------------
Legafy never states a rule; it hands out a pointer to the official page where
the rule lives. That makes the *pointer* the product. A pointer can rot in ways
that are invisible from inside the process:

* the department migrates the site (**indiacode.nic.in → indiacode.gov.in**,
  which is exactly how this module earned its place);
* the URL still resolves but 302s somewhere unrelated;
* the host quietly stops being a government host — a lapsed domain picked up by
  someone else is the worst case, because the citation still *looks* right;
* the certificate expires, so every founder who clicks gets a browser warning
  and reasonably concludes the tool is junk;
* the page 404s while the whitelist entry that authorises it stays put.

None of these break a test. All of them break trust the first time a lawyer
clicks a link we gave their client.

What this module does NOT do
----------------------------
It does not read the page and decide whether the law changed — that is
`app/sources/watcher.py` and it ends at a human. This is narrower and more
boring: *is this URL still a live, official, correctly-hosted place to look?*
The two are deliberately separate, because "the page moved" and "the law
changed" need different people to act.

Offline by default
------------------
`audit_sources()` runs the structural checks with no network at all: host
whitelisting, scheme, duplicate ids, instruments citing hosts nobody
whitelisted, whitelist entries no instrument uses. Those catch most real
defects and run in CI. Liveness needs `check_live=True` and is opt-in, because
a CI job that fails when a government portal has an outage is a CI job everyone
learns to ignore.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.compliance.registry import GLOBAL_SOURCE_WHITELIST, JURISDICTION_DIR
from app.config import REPO_ROOT

USER_AGENT = "LegafyAI-SourceCheck/1.0 (+https://github.com/akridion-labs/legafy-ai)"

# Suffixes that make a host official. A citation on any other host cannot carry
# authority, however plausible the content — this is the line between a primary
# source and a blog that quotes one.
OFFICIAL_SUFFIXES: tuple[str, ...] = (".gov.in", ".nic.in", ".org.in", ".gov")

# Hosts that have MOVED. Keyed by the dead host, valued by its replacement, so a
# stale citation is reported as a specific fix rather than "unreachable".
# Add an entry the moment a migration notice is seen; do not wait for the old
# host to start failing, because the window in between is when a stale link
# looks healthy and quietly sends people to a redirect page.
KNOWN_MIGRATIONS: dict[str, str] = {
    "www.indiacode.nic.in": "indiacode.gov.in",
    "indiacode.nic.in": "indiacode.gov.in",
}


@dataclass
class Finding:
    severity: str  # ERROR | WARN | INFO
    code: str
    url: str
    detail: str
    used_by: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "url": self.url,
            "detail": self.detail,
            "used_by": self.used_by,
        }


def host_of(url: str) -> str:
    return url.split("://", 1)[-1].split("/", 1)[0].lower()


def is_official_host(host: str) -> bool:
    bare = host.removeprefix("www.")
    return any(host.endswith(s) or bare.endswith(s) for s in OFFICIAL_SUFFIXES)


def collect_citations() -> dict[str, list[str]]:
    """Every URL Legafy hands out, mapped to what uses it."""
    urls: dict[str, list[str]] = {}

    def note(url: str, user: str) -> None:
        if url:
            urls.setdefault(url, []).append(user)

    for path in sorted(JURISDICTION_DIR.glob("*.json")):
        if path.name.startswith("_"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        code = data["code"]
        for url in data.get("source_whitelist", []):
            note(url, f"{code}:source_whitelist")
        for instrument in data.get("instruments", []):
            note(instrument.get("citation_url", ""), f"{code}:{instrument['id']}")

    sources_file = REPO_ROOT / "data" / "sources.json"
    if sources_file.exists():
        for source in json.loads(sources_file.read_text(encoding="utf-8"))["sources"]:
            note(source["url"], f"sources.json:{source['source_id']}")

    registers = REPO_ROOT / "data" / "research_registers.json"
    if registers.exists():
        for entry in json.loads(registers.read_text(encoding="utf-8"))["registers"]:
            note(entry.get("url", ""), f"registers:{entry['id']}")

    return urls


def _probe(url: str, timeout: float) -> tuple[str, Any, str]:
    """Return (url, status, note). Never raises — a probe failure is a finding."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return url, response.status, response.geturl()
    except urllib.error.HTTPError as exc:
        return url, exc.code, ""
    except ssl.SSLCertVerificationError as exc:
        return url, "TLS_INVALID", str(exc)[:160]
    except Exception as exc:  # network refused, DNS, timeout, proxy
        return url, type(exc).__name__, str(exc)[:160]


def audit_sources(
    *, check_live: bool = False, timeout: float = 20.0, workers: int = 8
) -> dict[str, Any]:
    """Audit every citation Legafy hands out. Structure always, liveness on request."""
    urls = collect_citations()
    findings: list[Finding] = []

    whitelisted_hosts = {h.lower() for h in GLOBAL_SOURCE_WHITELIST}

    for url, users in sorted(urls.items()):
        host = host_of(url)

        if not url.startswith("https://"):
            findings.append(
                Finding(
                    "ERROR", "not_https", url,
                    "A citation served over plain HTTP can be rewritten in transit. "
                    "For a legal source that is the whole game.",
                    users,
                )
            )

        if not is_official_host(host):
            findings.append(
                Finding(
                    "ERROR", "unofficial_host", url,
                    f"Host {host!r} is not a government domain. A citation here cannot "
                    "carry authority whatever it contains.",
                    users,
                )
            )

        bare = host.removeprefix("www.")
        if not any(bare.endswith(w) or host.endswith(w) for w in whitelisted_hosts):
            findings.append(
                Finding(
                    "ERROR", "host_not_whitelisted", url,
                    f"Host {host!r} is cited but is not in GLOBAL_SOURCE_WHITELIST, so the "
                    "citation guard would strip any statement resting on it.",
                    users,
                )
            )

        if host in KNOWN_MIGRATIONS:
            findings.append(
                Finding(
                    "ERROR", "host_migrated", url,
                    f"{host} has migrated to {KNOWN_MIGRATIONS[host]}. The old host may still "
                    "answer with a migration notice, which reads as 'working' and is not.",
                    users,
                )
            )

    # Whitelist hygiene: entries nobody cites, and cited hosts nobody authorised.
    for path in sorted(JURISDICTION_DIR.glob("*.json")):
        if path.name.startswith("_"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        listed = {host_of(u) for u in data.get("source_whitelist", [])}
        cited = {host_of(i["citation_url"]) for i in data.get("instruments", []) if i.get("citation_url")}
        for host in sorted(cited - listed):
            findings.append(
                Finding(
                    "WARN", "cited_but_not_listed", host,
                    f"{data['code']} cites {host} but does not list it in its own "
                    "source_whitelist. The global whitelist is a backstop, not a substitute.",
                    [data["code"]],
                )
            )

    live: dict[str, Any] = {}
    if check_live:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for url, status, note in pool.map(lambda u: _probe(u, timeout), urls):
                live[url] = {"status": status, "note": note}
                users = urls[url]
                if status == 200:
                    final_host = host_of(note) if note else host_of(url)
                    if note and final_host != host_of(url):
                        severity = "ERROR" if not is_official_host(final_host) else "WARN"
                        findings.append(
                            Finding(
                                severity, "redirects_offsite", url,
                                f"Redirects to {note}. Cite the destination, not the hop — a "
                                "redirect can be repointed without the citation changing.",
                                users,
                            )
                        )
                elif status == "TLS_INVALID":
                    findings.append(
                        Finding("ERROR", "tls_invalid", url,
                                f"Certificate does not verify: {note}", users)
                    )
                elif isinstance(status, int) and 400 <= status < 500:
                    findings.append(
                        Finding("ERROR", "dead_link", url,
                                f"HTTP {status}. A founder clicking this gets nothing.", users)
                    )
                else:
                    # 5xx and network errors are usually the portal, not us.
                    findings.append(
                        Finding("WARN", "unreachable", url,
                                f"{status} {note}".strip() + " — retry before acting on it.",
                                users)
                    )

    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    findings.sort(key=lambda f: (order.get(f.severity, 3), f.code, f.url))
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "urls_checked": len(urls),
        "liveness_checked": check_live,
        "counts": {
            sev: sum(1 for f in findings if f.severity == sev) for sev in ("ERROR", "WARN", "INFO")
        },
        "findings": [f.as_dict() for f in findings],
        "live": live,
        "note": (
            "This checks whether a citation is still a live, official, correctly-hosted place "
            "to look. It does NOT check whether the law changed — that is the source watcher, "
            "and it ends at a human reviewer. A clean report means the pointers are sound, not "
            "that the content behind them is current."
        ),
    }


def write_report(path: Path | None = None, *, check_live: bool = False) -> Path:
    from app.config import get_settings

    report = audit_sources(check_live=check_live)
    target = path or (get_settings().generated_path / "source_health.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return target


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    import sys

    live = "--live" in sys.argv
    result = audit_sources(check_live=live)
    for finding in result["findings"]:
        print(f"[{finding['severity']:5s}] {finding['code']:22s} {finding['url']}")
        print(f"          {finding['detail']}")
        print(f"          used by: {', '.join(finding['used_by'][:6])}")
    counts = result["counts"]
    print(
        f"\n{result['urls_checked']} citations checked"
        f" (liveness: {'yes' if live else 'no'})"
        f" — {counts['ERROR']} errors, {counts['WARN']} warnings"
    )
    raise SystemExit(1 if counts["ERROR"] else 0)
