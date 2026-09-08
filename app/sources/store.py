"""Primary-source index, change detection and review queue.

Why this is not a news feed
---------------------------
Legafy's value is *verified* law. A news ranker is the opposite: fast, noisy,
unverified. Piping legal news into a compliance answer would destroy the
anti-hallucination property that is the entire product.

So this module never answers a compliance question. It does three things:

1. **Indexes** documents fetched from whitelisted primary sources (gazette,
   ministry and state portals) into SQLite FTS5.
2. **Detects change** by content hash against the previous snapshot, and files
   a *review candidate* against the instruments a document covers.
3. **Ranks** those candidates so a human reviewer sees the highest-impact
   change first.

The ranking decides **what a human reads next**, never what a user is told. A
document only reaches a user through `search_legal_sources`, which returns it
as a citation with its authority tier attached — not as an assertion.

Storage is stdlib `sqlite3` with FTS5. No search server, no embedding model, no
new dependency. BM25 over official prose is a strong baseline, and the ranking
signal that actually matters here is source authority, not semantic nuance.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import REPO_ROOT, get_settings

# How much a source's word is worth. A gazette notification is the law; an
# aggregator repeating it is a pointer to go read the gazette.
AUTHORITY_WEIGHT: dict[str, float] = {
    "gazette": 1.00,
    "statute_repository": 0.95,
    "ministry": 0.90,
    "regulator": 0.90,
    "state_portal": 0.85,
    "court": 0.80,
    "aggregator": 0.25,
}

# Below this, a document may be indexed for orientation but can never be cited
# in an answer or trigger a verification claim on its own.
CITABLE_AUTHORITY_FLOOR = 0.80

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id           TEXT PRIMARY KEY,
    source_id        TEXT NOT NULL,
    url              TEXT NOT NULL,
    title            TEXT NOT NULL,
    authority_tier   TEXT NOT NULL,
    jurisdiction     TEXT NOT NULL,
    instrument_ids   TEXT NOT NULL DEFAULT '[]',
    content_hash     TEXT NOT NULL,
    first_seen       TEXT NOT NULL,
    last_seen        TEXT NOT NULL,
    last_changed     TEXT,
    revision         INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_docs_jur ON documents(jurisdiction);
CREATE INDEX IF NOT EXISTS idx_docs_src ON documents(source_id);

-- Content-carrying (not contentless): change detection needs the previous body
-- to diff against, and a contentless table cannot be DELETEd from on re-index.
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    title, body, tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS fts_map (
    rowid   INTEGER PRIMARY KEY,
    doc_id  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS change_queue (
    change_id        TEXT PRIMARY KEY,
    doc_id           TEXT NOT NULL,
    detected_at      TEXT NOT NULL,
    change_magnitude REAL NOT NULL,
    priority         REAL NOT NULL,
    status           TEXT NOT NULL DEFAULT 'PENDING',
    reviewer         TEXT,
    resolved_at      TEXT,
    note             TEXT
);
CREATE INDEX IF NOT EXISTS idx_queue_status ON change_queue(status, priority DESC);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _shingles(text: str, n: int = 3) -> set[str]:
    words = text.lower().split()
    return {" ".join(words[i : i + n]) for i in range(max(len(words) - n + 1, 1))}


def change_magnitude(old: str, new: str) -> float:
    """0.0 (identical) to 1.0 (nothing in common), by trigram Jaccard distance.

    Cheap, order-insensitive and stable against reflowed whitespace — which is
    what most portal "changes" actually are. A CMS re-render should not page a
    reviewer at the same priority as a substantive amendment.
    """
    a, b = _shingles(old), _shingles(new)
    if not a and not b:
        return 0.0
    return 1.0 - len(a & b) / len(a | b)


@dataclass(frozen=True)
class SourceDoc:
    doc_id: str
    source_id: str
    url: str
    title: str
    authority_tier: str
    jurisdiction: str
    instrument_ids: list[str]
    body: str

    @property
    def authority_weight(self) -> float:
        return AUTHORITY_WEIGHT.get(self.authority_tier, 0.1)

    @property
    def citable(self) -> bool:
        return self.authority_weight >= CITABLE_AUTHORITY_FLOOR


def review_priority(
    *,
    authority_weight: float,
    magnitude: float,
    instrument_hits: int,
    exposure: int,
    age_days: float,
) -> float:
    """Reviewer queue ordering. Documented because it is a product decision.

    priority = authority × magnitude × coverage × recency × exposure

    * **authority** — a gazette amendment outranks a portal FAQ edit.
    * **magnitude** — how much of the document actually changed.
    * **coverage** — does it touch an instrument we already serve? An untracked
      document still enters the queue (it may be a gap in our matrix) but at a
      lower weight than one that changes an answer we are already giving.
    * **recency** — halves every 30 days. Old unreviewed changes fade but never
      reach zero, so nothing is silently dropped.
    * **exposure** — how many recorded audits touched this jurisdiction. Change
      that affects answers we actually gave outranks change that affects none.
      This is the one signal that makes the queue *ours* rather than generic.
    """
    coverage = 1.0 if instrument_hits else 0.4
    recency = 0.5 ** (age_days / 30.0)
    exposure_factor = 1.0 + math.log1p(max(exposure, 0))
    return round(authority_weight * magnitude * coverage * recency * exposure_factor, 6)


class MalformedQuery(ValueError):
    """The caller's search text is not valid FTS5 syntax."""


def sanitise_fts_query(query: str) -> str:
    """Make an arbitrary user string safe to hand to FTS5 MATCH.

    FTS5 has its own query language, so raw user text can be a syntax error
    ("a OR"), an unterminated string, or a column filter that reaches for a
    column that does not exist. None of those are SQL injection — parameters are
    bound — but each one is an unhandled OperationalError, which is a 500 and a
    leaked internal message. Quoting each token as a literal removes the whole
    class: the query still works, and no user input is ever parsed as syntax.
    """
    tokens = re.findall(r'"[^"]*"|\S+', query or "")
    cleaned: list[str] = []
    for token in tokens:
        bare = token.strip('"').replace('"', "")
        bare = re.sub(r"[^\w\s.\-/]", " ", bare, flags=re.UNICODE).strip()
        if not bare:
            continue
        # Every token is quoted, not just multi-word ones. A bare token that
        # happens to be an FTS5 operator ("a OR" -> "a OR OR") is still a syntax
        # error; quoting turns it into the literal word the user typed.
        cleaned.append(f'"{bare}"')
    if not cleaned:
        raise MalformedQuery("Query contained no searchable terms.")
    return " OR ".join(cleaned[:32])


# ponytail: one sqlite3 connection, shared, check_same_thread=False. Safe today
# because every caller runs on the event loop (all handlers are async, none are
# offloaded). If a caller is ever moved to a worker thread, give each thread its
# own connection and enable WAL — do NOT just add a lock and call it fixed.
class SourceStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (get_settings().generated_path / "legal_sources.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # The index holds government text and the change queue; the corpus holds
        # user questions. Neither is world-readable on a shared box.
        create = not self.path.exists()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        if create:
            os.chmod(self.path, 0o600)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- ingest -------------------------------------------------------------
    def upsert(self, doc: SourceDoc, *, exposure: int = 0) -> dict[str, Any]:
        """Index a document. Returns what happened and any queued change."""
        new_hash = _hash(doc.body)
        row = self._conn.execute(
            "SELECT content_hash, revision FROM documents WHERE doc_id = ?", (doc.doc_id,)
        ).fetchone()
        previous_body = self._body_of(doc.doc_id) if row else ""

        if row and row["content_hash"] == new_hash:
            self._conn.execute(
                "UPDATE documents SET last_seen = ? WHERE doc_id = ?", (_now(), doc.doc_id)
            )
            self._conn.commit()
            return {"doc_id": doc.doc_id, "status": "UNCHANGED"}

        magnitude = change_magnitude(previous_body, doc.body) if row else 1.0
        revision = (row["revision"] + 1) if row else 1
        now = _now()

        self._conn.execute(
            """INSERT INTO documents
                 (doc_id, source_id, url, title, authority_tier, jurisdiction,
                  instrument_ids, content_hash, first_seen, last_seen, last_changed, revision)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(doc_id) DO UPDATE SET
                 title=excluded.title, url=excluded.url,
                 instrument_ids=excluded.instrument_ids,
                 content_hash=excluded.content_hash, last_seen=excluded.last_seen,
                 last_changed=excluded.last_changed, revision=excluded.revision""",
            (
                doc.doc_id, doc.source_id, doc.url, doc.title, doc.authority_tier,
                doc.jurisdiction, json.dumps(doc.instrument_ids), new_hash,
                now, now, now, revision,
            ),
        )
        self._index_body(doc)

        priority = review_priority(
            authority_weight=doc.authority_weight,
            magnitude=magnitude,
            instrument_hits=len(doc.instrument_ids),
            exposure=exposure,
            age_days=0.0,
        )
        change_id = _hash(f"{doc.doc_id}:{new_hash}")[:24]
        self._conn.execute(
            """INSERT OR IGNORE INTO change_queue
                 (change_id, doc_id, detected_at, change_magnitude, priority)
               VALUES (?,?,?,?,?)""",
            (change_id, doc.doc_id, now, round(magnitude, 4), priority),
        )
        self._conn.commit()
        return {
            "doc_id": doc.doc_id,
            "status": "NEW" if revision == 1 else "CHANGED",
            "revision": revision,
            "change_magnitude": round(magnitude, 4),
            "review_priority": priority,
            "change_id": change_id,
        }

    def _index_body(self, doc: SourceDoc) -> None:
        row = self._conn.execute(
            "SELECT rowid FROM fts_map WHERE doc_id = ?", (doc.doc_id,)
        ).fetchone()
        if row:
            self._conn.execute("DELETE FROM documents_fts WHERE rowid = ?", (row["rowid"],))
            rowid = row["rowid"]
        else:
            cur = self._conn.execute("INSERT INTO fts_map (doc_id) VALUES (?)", (doc.doc_id,))
            rowid = cur.lastrowid
        self._conn.execute(
            "INSERT INTO documents_fts (rowid, title, body) VALUES (?,?,?)",
            (rowid, doc.title, doc.body),
        )

    def _body_of(self, doc_id: str) -> str:
        row = self._conn.execute(
            """SELECT f.body FROM documents_fts f
                 JOIN fts_map m ON m.rowid = f.rowid WHERE m.doc_id = ?""",
            (doc_id,),
        ).fetchone()
        return row["body"] if row else ""

    # -- search -------------------------------------------------------------
    def search(
        self,
        query: str,
        *,
        jurisdiction: str | None = None,
        limit: int = 10,
        citable_only: bool = True,
    ) -> list[dict[str, Any]]:
        """Full-text search over indexed primary sources.

        **Jurisdiction is a hard filter, never a ranking signal.** A Telangana
        search must not surface an Andhra Pradesh notification as a lower-ranked
        result — the state isolation contract applies to search exactly as it
        applies to the grounding matrix. Softening this into a boost is the one
        change that would quietly break the product.
        """
        query = sanitise_fts_query(query)
        sql = [
            """SELECT d.doc_id, d.title, d.url, d.authority_tier, d.jurisdiction,
                      d.instrument_ids, d.last_changed, d.revision, bm25(documents_fts) AS bm25
                 FROM documents_fts
                 JOIN fts_map m ON m.rowid = documents_fts.rowid
                 JOIN documents d ON d.doc_id = m.doc_id
                WHERE documents_fts MATCH ?"""
        ]
        params: list[Any] = [query]
        if jurisdiction:
            sql.append("AND d.jurisdiction = ?")
            params.append(jurisdiction)
        sql.append("ORDER BY bm25 LIMIT ?")
        params.append(limit * 3)

        results = []
        for row in self._conn.execute(" ".join(sql), params):
            weight = AUTHORITY_WEIGHT.get(row["authority_tier"], 0.1)
            if citable_only and weight < CITABLE_AUTHORITY_FLOOR:
                continue
            # bm25() is negative-better; flip it into a positive relevance.
            relevance = 1.0 / (1.0 + abs(row["bm25"]))
            results.append(
                {
                    "doc_id": row["doc_id"],
                    "title": row["title"],
                    "url": row["url"],
                    "authority_tier": row["authority_tier"],
                    "authority_weight": weight,
                    "jurisdiction": row["jurisdiction"],
                    "instrument_ids": json.loads(row["instrument_ids"]),
                    "last_changed": row["last_changed"],
                    "revision": row["revision"],
                    "score": round(relevance * weight, 6),
                    "citable": weight >= CITABLE_AUTHORITY_FLOOR,
                }
            )
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]

    # -- review queue -------------------------------------------------------
    def pending_reviews(self, limit: int = 25, jurisdiction: str | None = None) -> list[dict]:
        sql = """SELECT q.*, d.title, d.url, d.jurisdiction, d.authority_tier, d.instrument_ids
                   FROM change_queue q JOIN documents d ON d.doc_id = q.doc_id
                  WHERE q.status = 'PENDING'"""
        params: list[Any] = []
        if jurisdiction:
            sql += " AND d.jurisdiction = ?"
            params.append(jurisdiction)
        sql += " ORDER BY q.priority DESC LIMIT ?"
        params.append(limit)
        out = []
        for row in self._conn.execute(sql, params):
            item = dict(row)
            item["instrument_ids"] = json.loads(item["instrument_ids"])
            out.append(item)
        return out

    def resolve(self, change_id: str, *, reviewer: str, status: str, note: str = "") -> bool:
        if status not in {"VERIFIED", "NO_CHANGE_NEEDED", "REJECTED"}:
            raise ValueError(f"invalid review status {status!r}")
        cur = self._conn.execute(
            "UPDATE change_queue SET status=?, reviewer=?, resolved_at=?, note=? WHERE change_id=?",
            (status, reviewer, _now(), note, change_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def stats(self) -> dict[str, Any]:
        d = self._conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]
        p = self._conn.execute(
            "SELECT COUNT(*) c FROM change_queue WHERE status='PENDING'"
        ).fetchone()["c"]
        return {"documents": d, "pending_reviews": p, "db": str(self.path)}


_STORE: SourceStore | None = None


def get_store() -> SourceStore:
    global _STORE
    if _STORE is None:
        _STORE = SourceStore()
    return _STORE


def reset_store_cache() -> None:
    global _STORE
    if _STORE is not None:
        _STORE.close()
    _STORE = None


def load_source_registry() -> list[dict[str, Any]]:
    path = REPO_ROOT / "data" / "sources.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["sources"]
