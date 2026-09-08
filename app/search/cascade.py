"""The Legafy Grounded Retrieval Cascade — local first, net last, never guess.

The rule this implements
------------------------
A question is answered from what we already hold. The network is not a search
path; it is a *restocking* path that runs behind a human. So a lookup walks four
tiers, cheapest and most authoritative first, and stops at the first tier that
answers:

    L0  Instrument resolution   O(1) dict + O(n) phrase trie over the question.
                                Deterministic. This is the tier that answers
                                "which law is this?" and it needs no index at
                                all — the grounding matrix is already in memory.

    L1  Local primary-source index  BM25 over FTS5, partitioned by jurisdiction
                                *before* ranking. This is the tier that answers
                                "show me the official page behind that duty."

    L2  Semantic recall (seam)  For a question whose words do not appear in any
                                document — "can I hold my customers' money" vs
                                "payment aggregator" — lexical search returns
                                nothing and is *right* to. See VECTOR_SEAM below.

    L3  Miss                    Nothing local answers it. We do not fall through
                                to the open web and paraphrase whatever comes
                                back. The gap is recorded, ranked, and handed to
                                the legal team; the caller is told plainly that
                                Legafy does not hold this yet.

Why the miss tier is the important one
--------------------------------------
Every legal-AI failure that has made the news is the same failure: no local
answer, so the model produced one. Making "we don't have this" a first-class,
recorded outcome is what stops that, and it doubles as the product's roadmap —
the miss log *is* the crawl backlog, ordered by how many people hit it.

Why there is no embedding model in this file yet
------------------------------------------------
``VECTOR_SEAM``: L2 is a named, empty seam rather than a built layer. At the
current corpus size, approximate nearest-neighbour recall over a few hundred
documents is slower and less accurate than BM25 and adds a model dependency to
a system whose entire value is that it does not guess. The trigger to build it
is stated in ``docs/SEARCH_DESIGN.md``: >5,000 indexed documents *and* a
sustained L3 miss rate above 15% whose misses are paraphrase misses rather than
coverage gaps. Building it before then is a model dependency bought with no
recall to show for it.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.compliance.registry import JURISDICTION_REGISTRY
from app.config import get_settings
from app.search.intent import analyse, build_fts_query
from app.sources.store import MalformedQuery, SourceStore, get_store

MISS_SCHEMA = """
CREATE TABLE IF NOT EXISTS misses (
    miss_id      TEXT PRIMARY KEY,
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL,
    hits         INTEGER NOT NULL DEFAULT 1,
    query        TEXT NOT NULL,
    intent       TEXT NOT NULL DEFAULT '',
    jurisdiction TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'OPEN'
);
CREATE INDEX IF NOT EXISTS idx_miss_hits ON misses(status, hits DESC);
"""


@dataclass
class CascadeResult:
    tier: str
    query: str
    jurisdiction: str | None
    instruments: list[dict[str, Any]] = field(default_factory=list)
    documents: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "query": self.query,
            "jurisdiction": self.jurisdiction,
            "instruments": self.instruments,
            "documents": self.documents,
            "note": self.note,
        }


class MissLog:
    """The crawl backlog, written by users and read by the legal team.

    Deliberately identical in privacy posture to the question corpus: the query
    text and nothing about who asked it. There is no tenant parameter here for
    the same reason there is none there.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (get_settings().generated_path / "retrieval_misses.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        create = not self.path.exists()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        if create:
            os.chmod(self.path, 0o600)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(MISS_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def record(self, query: str, *, intent: str = "", jurisdiction: str = "") -> None:
        import hashlib

        normalised = " ".join(query.lower().split())[:400]
        if len(normalised) < 8:
            return
        miss_id = hashlib.sha256(f"{normalised}|{jurisdiction}".encode()).hexdigest()[:32]
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """INSERT INTO misses (miss_id, first_seen, last_seen, query, intent, jurisdiction)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(miss_id) DO UPDATE SET hits = hits + 1, last_seen = excluded.last_seen""",
            (miss_id, now, now, normalised, intent, jurisdiction),
        )
        self._conn.commit()

    def backlog(self, limit: int = 25) -> list[dict[str, Any]]:
        """What to crawl next, ordered by how many people have hit the gap."""
        return [
            dict(row)
            for row in self._conn.execute(
                "SELECT * FROM misses WHERE status='OPEN' ORDER BY hits DESC, last_seen DESC "
                "LIMIT ?",
                (limit,),
            )
        ]

    def close_gap(self, miss_id: str, *, note: str = "") -> bool:
        cur = self._conn.execute(
            "UPDATE misses SET status='CLOSED' WHERE miss_id=?", (miss_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def stats(self) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(hits),0) h FROM misses WHERE status='OPEN'"
        ).fetchone()
        return {"open_gaps": row["c"], "total_miss_hits": row["h"], "db": str(self.path)}


_MISS_LOG: MissLog | None = None


def get_miss_log() -> MissLog:
    global _MISS_LOG
    if _MISS_LOG is None:
        _MISS_LOG = MissLog()
    return _MISS_LOG


def reset_miss_log_cache() -> None:
    global _MISS_LOG
    if _MISS_LOG is not None:
        _MISS_LOG.close()
    _MISS_LOG = None


# Tokens that appear in instrument titles but carry no topical signal. Without
# this, "hot air balloon licence in telangana" matches the Telangana Shops and
# Establishments Act on the word "telangana" — a confident answer to a question
# we cannot answer, which is the exact failure the miss tier exists to catch.
NOISE_TOKENS: frozenset[str] = frozenset(
    {
        "act", "acts", "rules", "rule", "code", "codes", "india", "indian", "state",
        "central", "union", "framework", "regulation", "regulations", "under", "with",
        "from", "that", "this", "what", "when", "does", "need", "should", "must",
        "andhra", "pradesh", "telangana", "maharashtra", "karnataka", "delhi",
        # three-letter fillers, kept out because the length floor is 3 — an
        # acronym like GST or EPF is exactly the token we most want to keep.
        "the", "and", "for", "are", "can", "you", "who", "how", "why", "its",
        "our", "not", "but", "was", "any", "get", "out", "has", "may",
    }
)


L0_SCORE_FLOOR = 0.3


def _match_instruments(query: str, jurisdiction: str | None) -> list[dict[str, Any]]:
    """L0 — resolve the question against instruments already in the matrix.

    Scored on title-token overlap and domain match. No index: the matrix is a
    few hundred instruments held in memory, so a linear pass is faster than any
    structure that would have to be kept in sync with it.
    """
    words = {w for w in query.lower().replace(",", " ").split() if len(w) >= 3} - NOISE_TOKENS
    if not words:
        return []
    # The union block is not addressable through resolve() — that refusal is the
    # state-isolation contract doing its job — so it is fetched explicitly.
    # Without this the entire union catalogue is invisible to L0, and a
    # copyright question misses while the Copyright Act sits in memory.
    jurisdictions = [JURISDICTION_REGISTRY.union()]
    if jurisdiction and jurisdiction != JURISDICTION_REGISTRY.union().code:
        jurisdictions.append(JURISDICTION_REGISTRY.resolve(jurisdiction))
    elif not jurisdiction:
        jurisdictions.extend(
            JURISDICTION_REGISTRY.resolve(j["code"])
            for j in JURISDICTION_REGISTRY.all_summaries()
            if j["code"] != JURISDICTION_REGISTRY.union().code
        )

    out: list[dict[str, Any]] = []
    for jur in jurisdictions:
        for instrument in jur.instruments:
            title_words = set(instrument["title"].lower().replace(",", " ").split())
            domain_words = set(instrument.get("domain", "").split("_"))
            # The instrument id carries the acronym the user actually types
            # ("IN-GST-2017" -> gst), which the formal title never contains.
            id_words = set(instrument["id"].lower().split("-"))
            overlap = words & (title_words | domain_words | id_words)
            if not overlap:
                continue
            # An acronym hit is a much stronger signal than a generic title word
            # ("registration" matches half the catalogue; "epf" matches one Act).
            weight = len(overlap) + 0.5 * len(overlap & id_words)
            out.append(
                {
                    "id": instrument["id"],
                    "title": instrument["title"],
                    "jurisdiction": jur.code,
                    "domain": instrument.get("domain", "general"),
                    "citation_url": instrument.get("citation_url", ""),
                    "matched_on": sorted(overlap),
                    "score": round(weight / len(words), 4),
                }
            )
    # A single generic word ("registration", "clearance") matching one instrument
    # out of a catalogue is noise, not an answer. Below the floor it is better to
    # miss and record the gap than to hand back a confident near-miss.
    out = [i for i in out if i["score"] >= L0_SCORE_FLOOR]
    out.sort(key=lambda i: i["score"], reverse=True)
    return out[:8]


def resolve(
    query: str,
    *,
    jurisdiction: str | None = None,
    limit: int = 10,
    store: SourceStore | None = None,
    record_miss: bool = True,
) -> CascadeResult:
    """Walk the cascade and return the first tier that answers.

    Jurisdiction stays a hard partition at every tier. A cascade that widened
    the filter on the way down would answer a Telangana question with an Andhra
    Pradesh document — which is the one failure this product exists to prevent,
    and it would look like helpfulness on the way there.
    """
    store = store or get_store()
    analysis = analyse(query)
    if jurisdiction is None and len(analysis.jurisdictions) == 1:
        jurisdiction = analysis.jurisdictions[0]

    instruments = _match_instruments(query, jurisdiction)

    try:
        documents = store.search(
            build_fts_query(query, analysis), jurisdiction=jurisdiction, limit=limit
        )
    except MalformedQuery:
        documents = []

    if instruments and documents:
        tier = "L0+L1"
        note = "Answered from the grounding matrix, with the official page behind it."
    elif instruments:
        tier = "L0"
        note = (
            "Answered from the grounding matrix. No indexed copy of the source page yet — "
            "follow citation_url to the primary source."
        )
    elif documents:
        tier = "L1"
        note = "Answered from the local primary-source index."
    else:
        tier = "L3_MISS"
        note = (
            "Legafy does not hold anything for this question in this jurisdiction. It has not "
            "been answered from the open web instead: the gap is recorded for the compliance "
            "team to source, and until they do, treat this as unanswered."
        )
        if record_miss:
            get_miss_log().record(
                query, intent=analysis.intent, jurisdiction=jurisdiction or ""
            )

    return CascadeResult(
        tier=tier,
        query=query,
        jurisdiction=jurisdiction,
        instruments=instruments,
        documents=documents,
        note=note,
    )


def backlog_report(limit: int = 25) -> dict[str, Any]:
    log = get_miss_log()
    return {"gaps": log.backlog(limit=limit), "stats": log.stats()}


__all__ = [
    "CascadeResult",
    "MissLog",
    "backlog_report",
    "get_miss_log",
    "reset_miss_log_cache",
    "resolve",
]
