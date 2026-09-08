"""Fetch watched sources, extract text, hand them to the store.

Deliberately boring: an HTTP GET, an HTML-to-text pass with the standard
library's parser, and a hash comparison. No headless browser, no scraping
framework, no ML extraction. Portals that need JavaScript to render are a real
limitation — they are recorded as `FETCH_UNSUPPORTED` rather than silently
skipped, so the gap is visible instead of looking like "no change".

Fetching is refused for any host not already on a jurisdiction file's
whitelist. That check is the same programmatic restraint the blueprint asks
for: the crawler cannot wander onto a blog and bring back something that looks
authoritative.
"""

from __future__ import annotations

import asyncio
import logging
import re
from html.parser import HTMLParser
from typing import Any

import httpx

from app.compliance.registry import GLOBAL_SOURCE_WHITELIST
from app.sources.store import SourceDoc, SourceStore, get_store, load_source_registry

log = logging.getLogger("legafy.sources.watcher")

TIMEOUT = httpx.Timeout(connect=10.0, read=45.0, write=15.0, pool=10.0)
USER_AGENT = "LegafyAI-SourceWatcher/1.0 (+https://akridion.com; compliance monitoring)"
SKIP_TAGS = {"script", "style", "noscript", "svg", "head"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self._parts.append(data.strip())

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._parts)).strip()


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:  # malformed markup is normal on government portals
        log.debug("HTML parse degraded; using partial text")
    return parser.text


def host_of(url: str) -> str:
    return url.split("://", 1)[-1].split("/", 1)[0].lower()


def is_whitelisted(url: str) -> bool:
    host = host_of(url)
    return any(host == w or host.endswith(f".{w}") for w in GLOBAL_SOURCE_WHITELIST)


def matched_instruments(text: str, declared: list[str], titles: dict[str, str]) -> list[str]:
    """Which tracked instruments this document plausibly concerns.

    Declared coverage from the registry always counts. On top of that, an
    instrument whose exact title appears in the text is added — that is a
    string match, not an inference, and it is only used to order a reviewer's
    queue, never to assert anything.
    """
    hits = set(declared)
    lowered = text.lower()
    for instrument_id, title in titles.items():
        if title.lower() in lowered:
            hits.add(instrument_id)
    return sorted(hits)


def _instrument_titles() -> dict[str, str]:
    from app.compliance.registry import JURISDICTION_REGISTRY

    JURISDICTION_REGISTRY.load()
    titles: dict[str, str] = {}
    for summary in JURISDICTION_REGISTRY.all_summaries():
        jur = JURISDICTION_REGISTRY.get(summary["code"])
        for instrument in jur.instruments:
            titles[instrument["id"]] = instrument["title"]
    return titles


def exposure_for(jurisdiction: str) -> int:
    """How many recorded audits touched this jurisdiction.

    Read from the audit vault, which stores jurisdiction codes in clear (only
    the concept text is hashed). Change affecting answers we actually gave
    should reach a reviewer before change affecting none.
    """
    try:
        from app.security.telemetry import get_audit_vault

        return sum(
            1
            for record in get_audit_vault().read_records()
            if jurisdiction in (record.get("jurisdiction_codes") or [])
        )
    except Exception:  # the vault is best-effort; never block a crawl on it
        return 0


async def fetch_source(client: httpx.AsyncClient, source: dict[str, Any]) -> dict[str, Any]:
    url = source["url"]
    if not is_whitelisted(url):
        return {"source_id": source["source_id"], "status": "REFUSED_NOT_WHITELISTED", "url": url}
    try:
        response = await client.get(url, follow_redirects=True)
    except httpx.HTTPError as exc:
        return {"source_id": source["source_id"], "status": "FETCH_ERROR", "error": str(exc)}
    if response.status_code >= 400:
        return {
            "source_id": source["source_id"],
            "status": "FETCH_ERROR",
            "error": f"HTTP {response.status_code}",
        }

    text = html_to_text(response.text)
    if len(text) < 200:
        # Almost certainly a JavaScript-rendered shell. Record it as a gap.
        return {
            "source_id": source["source_id"],
            "status": "FETCH_UNSUPPORTED",
            "chars": len(text),
            "note": "Page yielded almost no text — likely client-rendered. Needs a manual check.",
        }
    return {"source_id": source["source_id"], "status": "OK", "text": text, "url": str(response.url)}


async def run_once(store: SourceStore | None = None, *, sources: list[dict] | None = None) -> dict:
    """One crawl pass over the registry. Returns a per-source report."""
    store = store or get_store()
    sources = sources if sources is not None else load_source_registry()
    titles = _instrument_titles()
    report: list[dict[str, Any]] = []

    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers) as client:
        for source in sources:
            fetched = await fetch_source(client, source)
            if fetched["status"] != "OK":
                report.append(fetched)
                continue
            doc = SourceDoc(
                doc_id=source["source_id"],
                source_id=source["source_id"],
                url=fetched["url"],
                title=source["title"],
                authority_tier=source["authority_tier"],
                jurisdiction=source["jurisdiction"],
                instrument_ids=matched_instruments(
                    fetched["text"], source.get("instrument_ids", []), titles
                ),
                body=fetched["text"],
            )
            outcome = store.upsert(doc, exposure=exposure_for(source["jurisdiction"]))
            report.append({**outcome, "source_id": source["source_id"]})
            await asyncio.sleep(1.0)  # be a polite guest on government infrastructure

    changed = [r for r in report if r.get("status") in {"NEW", "CHANGED"}]
    return {
        "checked": len(report),
        "changed": len(changed),
        "report": report,
        "queue": store.stats()["pending_reviews"],
    }


def main() -> None:  # pragma: no cover - operator entrypoint
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = asyncio.run(run_once())
    log.info(
        "checked=%d changed=%d pending_reviews=%d",
        result["checked"],
        result["changed"],
        result["queue"],
    )
    for row in result["report"]:
        if row.get("status") not in {"OK", "UNCHANGED"}:
            log.info("  %s -> %s", row.get("source_id"), row.get("status"))


if __name__ == "__main__":  # pragma: no cover
    main()
