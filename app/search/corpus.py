"""Opt-in question corpus — the training data the audit vault deliberately cannot be.

Why a second store
------------------
The audit vault stores an HMAC digest of every business concept and never the
text. That was the right call for liability, and it means the vault can never
train anything. This module is the separate, explicitly opted-in path the
roadmap calls for.

What is stored: the question (scrubbed), what we classified it as, which
jurisdictions it touched, and which lane we returned.

What is never stored: tenant, token id, organisation, IP, session, or any
identifier that could link two questions to one person. There is no join key
back to the vault by design — so this corpus cannot be de-anonymised by
correlating it with billing records, because there is nothing to correlate on.

The residual risk, stated plainly
---------------------------------
Founders describe unlaunched ideas. Mechanical identifiers (email, phone, PAN,
Aadhaar, GST, URLs, money) are scrubbed reliably. A *description* — "an app that
matches retired cricket coaches with schools in Warangal" — is not PII by any
regex and is still commercially sensitive. Scrubbing cannot fix that; only
consent can. Hence:

* opt-in per request, defaulting to off;
* a cooling-off window before a row is exportable, so a contributor has time to
  change their mind;
* `purge()` to drop everything, and a documented retention decision.

Do not turn this on by default to grow the corpus faster. A legal-tech company
that quietly harvests unlaunched startup ideas has a much bigger problem than a
small corpus.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import get_settings

# Rows younger than this are stored but not exported for training. A
# contributor who has second thoughts has a window to ask for a purge.
COOLING_OFF_DAYS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    corpus_id      TEXT PRIMARY KEY,
    recorded_at    TEXT NOT NULL,
    question       TEXT NOT NULL,
    question_hash  TEXT NOT NULL,
    intent         TEXT NOT NULL,
    tone           TEXT NOT NULL,
    jurisdictions  TEXT NOT NULL DEFAULT '[]',
    activity_flags TEXT NOT NULL DEFAULT '[]',
    lane           TEXT,
    scrub_hits     TEXT NOT NULL DEFAULT '[]',
    schema_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_q_intent ON questions(intent);
CREATE INDEX IF NOT EXISTS idx_q_recorded ON questions(recorded_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_q_hash ON questions(question_hash);
"""

# Mechanical identifiers. Ordered so the greedy ones run first.
SCRUBBERS: tuple[tuple[str, str, str], ...] = (
    ("url", r"https?://\S+|www\.\S+", "[URL]"),
    ("email", r"[\w.+-]+@[\w-]+\.[\w.]+", "[EMAIL]"),
    ("aadhaar", r"\b\d{4}\s?\d{4}\s?\d{4}\b", "[ID]"),
    ("pan", r"\b[A-Z]{5}\d{4}[A-Z]\b", "[ID]"),
    ("gstin", r"\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z\d]{2}\b", "[ID]"),
    ("cin", r"\b[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}\b", "[ID]"),
    ("phone", r"(?:\+91[\s-]?)?\b[6-9]\d{9}\b", "[PHONE]"),
    ("account", r"\b\d{9,18}\b", "[NUMBER]"),
    ("money", r"(?:₹|Rs\.?|INR)\s?[\d,]+(?:\.\d+)?\s?(?:lakh|lakhs|crore|crores)?", "[AMOUNT]"),
    ("handle", r"@[A-Za-z0-9_]{3,}", "[HANDLE]"),
)


def scrub(text: str) -> tuple[str, list[str]]:
    """Remove mechanical identifiers. Returns the cleaned text and what was hit."""
    hits: list[str] = []
    cleaned = text
    for name, pattern, placeholder in SCRUBBERS:
        cleaned, count = re.subn(pattern, placeholder, cleaned)
        if count:
            hits.append(f"{name}:{count}")
    return re.sub(r"\s+", " ", cleaned).strip(), hits


@dataclass(frozen=True)
class CorpusEntry:
    corpus_id: str
    question: str
    intent: str
    tone: str
    jurisdictions: list[str]
    activity_flags: list[str]
    lane: str | None
    scrub_hits: list[str]


class QuestionCorpus:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (get_settings().generated_path / "question_corpus.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # This file holds user questions. It must not be group- or world-readable.
        create = not self.path.exists()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        if create:
            os.chmod(self.path, 0o600)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def record(
        self,
        *,
        question: str,
        intent: str,
        tone: str,
        jurisdictions: list[str] | None = None,
        activity_flags: list[str] | None = None,
        lane: str | None = None,
    ) -> CorpusEntry | None:
        """Store one question. Returns None if it was a duplicate.

        Note the signature: there is no tenant parameter. It is not omitted by
        oversight — there is nowhere to put one, so no future edit can casually
        start linking rows to a customer.
        """
        cleaned, hits = scrub(question)
        if len(cleaned) < 12:
            return None
        digest = hashlib.sha256(cleaned.lower().encode()).hexdigest()
        entry = CorpusEntry(
            corpus_id=str(uuid.uuid4()),
            question=cleaned,
            intent=intent,
            tone=tone,
            jurisdictions=sorted(jurisdictions or []),
            activity_flags=sorted(activity_flags or []),
            lane=lane,
            scrub_hits=hits,
        )
        try:
            self._conn.execute(
                """INSERT INTO questions
                     (corpus_id, recorded_at, question, question_hash, intent, tone,
                      jurisdictions, activity_flags, lane, scrub_hits)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    entry.corpus_id, datetime.now(UTC).isoformat(), entry.question, digest,
                    entry.intent, entry.tone, json.dumps(entry.jurisdictions),
                    json.dumps(entry.activity_flags), entry.lane, json.dumps(entry.scrub_hits),
                ),
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            return None  # already have this exact question
        return entry

    def taxonomy(self) -> dict[str, Any]:
        """What people actually ask. Available without any corpus opt-in caveat.

        This is the analytics the roadmap puts first: it tells you which
        instruments to verify next and which risk vectors are under-detected.
        """
        def counts(column: str) -> dict[str, int]:
            return {
                row[0]: row[1]
                for row in self._conn.execute(
                    f"SELECT {column}, COUNT(*) FROM questions GROUP BY {column} "
                    f"ORDER BY COUNT(*) DESC"  # noqa: S608 - column is a literal above
                )
            }

        jur: dict[str, int] = {}
        for row in self._conn.execute("SELECT jurisdictions FROM questions"):
            for code in json.loads(row[0]):
                jur[code] = jur.get(code, 0) + 1
        return {
            "total": self._conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0],
            "by_intent": counts("intent"),
            "by_tone": counts("tone"),
            "by_lane": counts("lane"),
            "by_jurisdiction": dict(sorted(jur.items(), key=lambda kv: -kv[1])),
        }

    def export_training_rows(self, *, limit: int = 1000) -> list[dict[str, Any]]:
        """Rows past the cooling-off window, for classifier training only."""
        cutoff = (datetime.now(UTC) - timedelta(days=COOLING_OFF_DAYS)).isoformat()
        return [
            {
                "question": row["question"],
                "intent": row["intent"],
                "tone": row["tone"],
                "jurisdictions": json.loads(row["jurisdictions"]),
                "activity_flags": json.loads(row["activity_flags"]),
                "lane": row["lane"],
            }
            for row in self._conn.execute(
                "SELECT * FROM questions WHERE recorded_at < ? ORDER BY recorded_at LIMIT ?",
                (cutoff, limit),
            )
        ]

    def purge(self, *, before: datetime | None = None) -> int:
        sql = "DELETE FROM questions"
        params: tuple = ()
        if before:
            sql += " WHERE recorded_at < ?"
            params = (before.isoformat(),)
        cur = self._conn.execute(sql, params)
        self._conn.commit()
        return cur.rowcount

    def stats(self) -> dict[str, Any]:
        return {
            "questions": self._conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0],
            "exportable": len(self.export_training_rows(limit=10_000)),
            "cooling_off_days": COOLING_OFF_DAYS,
            "db": str(self.path),
            "contains_identifiers": False,
        }


_CORPUS: QuestionCorpus | None = None


def get_corpus() -> QuestionCorpus:
    global _CORPUS
    if _CORPUS is None:
        _CORPUS = QuestionCorpus()
    return _CORPUS


def reset_corpus_cache() -> None:
    global _CORPUS
    if _CORPUS is not None:
        _CORPUS.close()
    _CORPUS = None
