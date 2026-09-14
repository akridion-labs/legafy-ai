"""Weekly court-feed tip-offs: what a reviewer should go and read.

This is the freshness channel for **case law**, alongside `watcher.py`, which
watches government pages for changes to the statutes themselves. The two are
deliberately separate and behave differently, because their inputs differ in
authority by a factor of three.

## The one rule

**A lead is a pointer, never a source.** Nothing this module produces can be
cited, can enter the grounding matrix, or can move a traffic-light lane. It
lands in a human's reading queue with a link. That is the entire contract, and
it is why this can safely read an aggregator: Indian Kanoon sits at authority
weight 0.25, well below the 0.80 citable floor, so the type system already
refuses to let a lead be quoted. The reviewer opens the judgment on the court's
own site, reads it, and decides.

## Three restraints worth naming

**It never fetches a judgment.** The feed carries a title, a link and a date,
and that is all this reads. Indian Kanoon's robots.txt disallows a large set of
`/doc/` paths, so following the link to pull the text would be both rude and
wrong. It also happens to be unnecessary: a reviewer needs to know *that* a
case exists, and then wants the court's own copy anyway.

**It stores no body text.** Titles and links only. That keeps the copyright
question uninteresting and the storage small.

**An empty feed is a normal outcome, not an error.** The Kerala High Court feed
returned zero items when this was written — a valid RSS document with no entries.
A watcher that treats emptiness as failure gets muted; one that treats it as "no
developments" goes blind when a URL rots. So emptiness is recorded as `EMPTY`,
a dead slug is recorded as `FEED_NOT_FOUND`, and the two never share a line in
the report — `python -m app.sources.judicial_feeds` exits non-zero on the second
so a court that stopped being watched cannot pass as a quiet one.

## News

News sites are not here. A newspaper's legal section is an aggregator reporting
on an aggregator's reading of a judgment, at which point the thing Legafy exists
to prevent — a confident restatement of law by someone who has not read the
primary source — has already happened twice. Court feeds carry the same
information one hop closer to the source, and carry a link to the judgment. If
a news channel is added later, it belongs here, under the same lead-only rule,
storing headline and link and never a paragraph of the article.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import httpx

log = logging.getLogger("legafy.sources.judicial")

FEEDS_FILE = Path(__file__).resolve().parents[2] / "data" / "judicial_feeds.json"
ALLOWED_HOST = "indiankanoon.org"
TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
USER_AGENT = (
    "LegafyAI-JudicialWatch/1.0 (+https://akridion.com; weekly compliance review; "
    "feeds only, no document fetching)"
)

# A lead is kept only if its title touches something Legafy actually tracks.
# Without this a weekly run returns every judgment a court published, which is
# not a review queue, it is a firehose with a queue's name on it.
RELEVANCE_TERMS = (
    "companies act", "limited liability", "partnership", "shareholder", "director",
    "insolvency", "winding up", "oppression and mismanagement",
    "employment", "employee", "workman", "industrial dispute", "gratuity",
    "provident fund", "esi", "shops and establishment", "contract labour",
    "profession tax", "professional tax", "labour welfare",
    "goods and services tax", "gst", "income tax", "tds",
    "trade mark", "trademark", "copyright", "patent", "passing off",
    "confidential", "trade secret", "non-compete", "restraint of trade",
    "data protection", "privacy", "information technology act", "intermediary",
    "consumer", "unfair trade practice", "e-commerce",
    "arbitration", "stamp duty", "unstamped", "specific relief",
    "payment", "escrow", "payment aggregator", "prepaid",
    "foreign exchange", "fema", "competition act",
)

_RELEVANCE = re.compile(
    r"\b(?:" + "|".join(sorted((re.escape(t) for t in RELEVANCE_TERMS), key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Lead:
    """One thing for a human to read. Deliberately anaemic."""

    feed_id: str
    court: str
    jurisdiction: str
    cabinet: str
    title: str
    url: str
    published: str | None
    matched_terms: list[str]
    seen_at: str
    # Repeated on every record rather than stated once in a header: a lead that
    # gets copied out of its context must carry its own limits with it.
    authority_tier: str = "aggregator"
    citable: bool = False
    status: str = "UNREAD"


class UnverifiedFeedHost(ValueError):
    """Raised when a feed URL points somewhere the module is not allowed to read."""


def load_feeds(path: Path | None = None) -> list[dict[str, Any]]:
    raw = json.loads((path or FEEDS_FILE).read_text(encoding="utf-8"))
    feeds = raw.get("feeds", [])
    for feed in feeds:
        host = httpx.URL(feed["url"]).host
        if host != ALLOWED_HOST and not host.endswith(f".{ALLOWED_HOST}"):
            # Same restraint as the source watcher: the crawler cannot be pointed
            # at an arbitrary host by editing a data file.
            raise UnverifiedFeedHost(
                f"{feed['feed_id']}: {host!r} is not an allowed judicial feed host. "
                f"Only {ALLOWED_HOST} is permitted; adding another is a code change "
                f"with a reviewer, not a config edit."
            )
    return feeds


def _text(element: ElementTree.Element | None) -> str:
    return (element.text or "").strip() if element is not None else ""


def parse_feed(xml: str) -> list[dict[str, str]]:
    """Pull title/link/date out of RSS 2.0. Returns [] for an empty feed."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise ValueError(f"not parseable as XML: {exc}") from exc

    items = []
    for item in root.iter("item"):
        title = _text(item.find("title"))
        link = _text(item.find("link"))
        if not title or not link:
            continue
        items.append({"title": title, "link": link, "published": _text(item.find("pubDate")) or None})
    return items


def relevant_terms(title: str) -> list[str]:
    seen: list[str] = []
    for match in _RELEVANCE.finditer(title):
        hit = match.group(0).lower()
        if hit not in seen:
            seen.append(hit)
    return seen


async def fetch_feed(client: httpx.AsyncClient, feed: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    try:
        response = await client.get(feed["url"], follow_redirects=True)
    except httpx.HTTPError as exc:
        return {"feed_id": feed["feed_id"], "status": "FETCH_ERROR", "error": str(exc), "at": now}
    if response.status_code == 404:
        # The specific failure this module was built to make loud: a slug that
        # does not exist returns 404, and looks exactly like a quiet court.
        return {
            "feed_id": feed["feed_id"],
            "status": "FEED_NOT_FOUND",
            "error": "HTTP 404 — the slug is wrong or was retired. This court is NOT being watched.",
            "at": now,
        }
    if response.status_code >= 400:
        return {
            "feed_id": feed["feed_id"],
            "status": "FETCH_ERROR",
            "error": f"HTTP {response.status_code}",
            "at": now,
        }

    try:
        items = parse_feed(response.text)
    except ValueError as exc:
        return {"feed_id": feed["feed_id"], "status": "UNPARSEABLE", "error": str(exc), "at": now}

    leads = []
    for item in items:
        matched = relevant_terms(item["title"])
        if not matched:
            continue
        leads.append(
            Lead(
                feed_id=feed["feed_id"],
                court=feed["court"],
                jurisdiction=feed["jurisdiction"],
                cabinet=feed.get("cabinet", "corporate"),
                title=item["title"],
                url=item["link"],
                published=item["published"],
                matched_terms=matched,
                seen_at=now,
            )
        )

    return {
        "feed_id": feed["feed_id"],
        "court": feed["court"],
        "status": "EMPTY" if not items else "OK",
        "items_in_feed": len(items),
        "leads": leads,
        "at": now,
    }


async def run_once(
    feeds: list[dict[str, Any]] | None = None, *, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """One weekly pass. Returns a per-feed report plus the leads worth reading."""
    feeds = feeds if feeds is not None else load_feeds()
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    try:
        reports = [await fetch_feed(client, feed) for feed in feeds]
    finally:
        if owns_client:
            await client.aclose()

    leads: list[Lead] = []
    for report in reports:
        leads.extend(report.pop("leads", []))

    broken = [r["feed_id"] for r in reports if r["status"] in {"FEED_NOT_FOUND", "UNPARSEABLE"}]
    return {
        "ran_at": datetime.now(UTC).isoformat(),
        "feeds_checked": len(reports),
        "reports": reports,
        "leads": [asdict(lead) for lead in leads],
        "lead_count": len(leads),
        "broken_feeds": broken,
        "note": (
            "Leads are pointers for a human to read, at aggregator authority (0.25, "
            "below the 0.80 citable floor). None of this has changed any answer the "
            "engine gives, and none of it may be quoted. Open each judgment on the "
            "court's own site before acting on it."
            + (
                f" WARNING: {len(broken)} feed(s) are not returning a usable document, "
                "so those courts are not being watched at all: " + ", ".join(broken)
                if broken
                else ""
            )
        ),
    }


def write_leads(report: dict[str, Any], path: Path) -> int:
    """Append the run's leads to a JSON Lines file. Returns how many were written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for lead in report.get("leads", []):
            handle.write(json.dumps(lead, ensure_ascii=False) + "\n")
    return len(report.get("leads", []))


def read_leads(path: Path, limit: int = 25, jurisdiction: str | None = None) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if jurisdiction and row.get("jurisdiction") != jurisdiction:
            continue
        rows.append(row)
    rows.sort(key=lambda r: r.get("seen_at", ""), reverse=True)
    return rows[:limit]


def _cli() -> int:
    """`python -m app.sources.judicial_feeds` — check every feed, write leads.

    This is the acceptance test for the whole channel and the one command worth
    running by hand after editing the feed list. It prints one line per court so
    a wrong slug is visible as FEED_NOT_FOUND rather than hiding inside a quiet
    week, and exits non-zero if any feed is broken.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Check the weekly judicial feeds.")
    parser.add_argument(
        "--write",
        action="store_true",
        help="append this run's leads to generated/judicial_leads.jsonl",
    )
    args = parser.parse_args()

    report = asyncio.run(run_once())
    for row in report["reports"]:
        detail = row.get("error", "")
        print(
            f"{row['feed_id']:24} {row['status']:16} "
            f"items={row.get('items_in_feed', '-'):>4}  {detail[:70]}"
        )
    print(
        f"\n{report['feeds_checked']} feeds checked, {report['lead_count']} lead(s) worth reading."
    )
    if args.write:
        written = write_leads(report, LEADS_FILE)
        print(f"{written} lead(s) appended to {LEADS_FILE}")
    if report["broken_feeds"]:
        print(
            "\nBROKEN — these courts are NOT being watched: "
            + ", ".join(report["broken_feeds"])
        )
        return 1
    return 0


LEADS_FILE = Path(__file__).resolve().parents[2] / "generated" / "judicial_leads.jsonl"

if __name__ == "__main__":  # pragma: no cover - CLI
    import sys

    logging.basicConfig(level=logging.INFO)
    sys.exit(_cli())
