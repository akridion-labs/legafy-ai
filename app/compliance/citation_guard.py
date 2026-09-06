"""The anti-hallucination barrier applied to every model-generated string.

Legafy's grounding matrix deliberately stores no section numbers, sub-clauses,
penalty amounts or commencement dates — those fields are ``null`` by
construction until a human verifies them (see ``data/jurisdictions/*.json``
and ``app/compliance/registry.py``). This module is the enforcement point: it
scans model output for exactly the kind of confident-but-unverifiable legal
detail that field intentionally omits, and refuses to let it reach a user
unless it can be traced back to a verified citation supplied by the caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

PLACEHOLDER = "[UNVERIFIED CITATION REMOVED — confirm against the primary source before relying on this]"

# ---------------------------------------------------------------------------
# Detection patterns — compiled once at import time.
# ---------------------------------------------------------------------------

_SECTION_KEYWORDS = (
    r"Sections?|Secs?\.|u/s|Rules?|Articles?|Clauses?|Schedules?|Regulations?"
)
SECTION_REFERENCE_RE = re.compile(
    rf"\b(?:{_SECTION_KEYWORDS})\s+"
    # Digits, or an UPPERCASE Roman numeral. The case-sensitive group matters:
    # under IGNORECASE a bare [IVXLCDM]+ matches ordinary words, so "clause is"
    # and "clause can" were being flagged as pinpoint citations.
    r"(?:[0-9]+[A-Za-z]?|(?-i:[IVXLCDM]{1,7})(?![a-z]))(?:\s*\([0-9A-Za-z]+\))*"
    r"(?:\s+of\s+the\s+(?:[A-Z][^,.;\n]{0,80}?\s)?Act\b)?",
    re.IGNORECASE,
)

# \b anchors matter: without them "yea(rs.)\n1.1" reads as a rupee amount.
_CURRENCY_AMOUNT = r"(?:₹|\bRs\.?|\bINR\b)\s?[0-9][0-9,]*(?:\.[0-9]+)?\s?(?:lakh|lakhs|crore|crores)?"
_PERCENT_FINE = r"fine\s+of\s+up\s+to\s+[0-9]+(?:\.[0-9]+)?%\s+of\s+turnover"
_IMPRISONMENT = r"imprisonment\s+(?:of\s+up\s+to|up\s+to|for\s+up\s+to)\s+[a-z0-9\- ]+?\s+years?\b"
PENALTY_AMOUNT_RE = re.compile(
    rf"(?:{_CURRENCY_AMOUNT}|{_PERCENT_FINE}|{_IMPRISONMENT})",
    re.IGNORECASE,
)

INSTRUMENT_TITLE_RE = re.compile(
    r"\b[A-Z][A-Za-z0-9&,\-'/ ]{2,100}?\s(?:Act|Rules|Regulations|Ordinance|Bill)\s*,?\s*\d{4}\b"
)

URL_RE = re.compile(r"https?://[^\s)\]}>\"']+", re.IGNORECASE)

COMMENCEMENT_RE = re.compile(
    r"\b(?:came into force on|with effect from|notified on)\s+[A-Za-z0-9,\- ]{3,40}?(?=[.,;\n]|$)",
    re.IGNORECASE,
)


def _host_of(url: str) -> str:
    return (urlparse(url).netloc or "").split("@")[-1].split(":")[0].lower()


@dataclass(frozen=True)
class CitationViolation:
    kind: str
    excerpt: str
    start: int
    end: int
    reason: str


class CitationGuard:
    """Scans and sanitizes text against a per-request citation whitelist."""

    def __init__(
        self,
        allowed_titles: set[str],
        allowed_hosts: set[str],
        verified_citations: set[str] | None = None,
    ) -> None:
        self.allowed_titles = set(allowed_titles or ())
        self.allowed_hosts = {h.lower() for h in (allowed_hosts or ())}
        self.verified_citations = set(verified_citations or ())

    @classmethod
    def from_grounding(cls, grounding: dict) -> CitationGuard:
        """Build a guard straight from a grounding bundle's own whitelists."""
        allowed_titles = set(grounding.get("citable_instrument_titles", []) or [])
        allowed_hosts = set(grounding.get("citable_hosts", []) or [])
        verified: set[str] = set()

        def _collect(block: dict | None) -> None:
            for instrument in (block or {}).get("instruments", []) or []:
                for vc in instrument.get("verified_citations", []) or []:
                    verified.add(vc)

        _collect(grounding.get("union"))
        _collect(grounding.get("state"))
        for state in grounding.get("states", []) or []:
            _collect(state)

        return cls(allowed_titles=allowed_titles, allowed_hosts=allowed_hosts, verified_citations=verified)

    def _is_verified(self, excerpt: str) -> bool:
        return excerpt in self.verified_citations

    def _title_is_allowed(self, excerpt: str) -> bool:
        return any(excerpt == title or excerpt in title or title in excerpt for title in self.allowed_titles)

    def _host_is_allowed(self, host: str) -> bool:
        if not host:
            return False
        return any(host == allowed or host.endswith(f".{allowed}") for allowed in self.allowed_hosts)

    def scan(self, text: str) -> list[CitationViolation]:
        violations: list[CitationViolation] = []

        for m in SECTION_REFERENCE_RE.finditer(text):
            excerpt = m.group(0).strip()
            if self._is_verified(excerpt):
                continue
            violations.append(
                CitationViolation(
                    kind="section_reference",
                    excerpt=excerpt,
                    start=m.start(),
                    end=m.end(),
                    reason="Pinpoint statutory citations are refused unless verified against a primary source.",
                )
            )

        for m in PENALTY_AMOUNT_RE.finditer(text):
            excerpt = m.group(0).strip()
            if self._is_verified(excerpt):
                continue
            violations.append(
                CitationViolation(
                    kind="penalty_amount",
                    excerpt=excerpt,
                    start=m.start(),
                    end=m.end(),
                    reason="Penalty amounts and thresholds are not stored data and must not be asserted.",
                )
            )

        for m in INSTRUMENT_TITLE_RE.finditer(text):
            excerpt = m.group(0).strip()
            if self._is_verified(excerpt) or self._title_is_allowed(excerpt):
                continue
            violations.append(
                CitationViolation(
                    kind="unverified_instrument",
                    excerpt=excerpt,
                    start=m.start(),
                    end=m.end(),
                    reason="Instrument title is not on the verified allow-list for this jurisdiction.",
                )
            )

        for m in URL_RE.finditer(text):
            url = m.group(0)
            if self._is_verified(url):
                continue
            host = _host_of(url)
            if self._host_is_allowed(host):
                continue
            violations.append(
                CitationViolation(
                    kind="offwhitelist_url",
                    excerpt=url,
                    start=m.start(),
                    end=m.end(),
                    reason=f"Host '{host}' is not on the citation whitelist.",
                )
            )

        for m in COMMENCEMENT_RE.finditer(text):
            excerpt = m.group(0).strip()
            if self._is_verified(excerpt):
                continue
            violations.append(
                CitationViolation(
                    kind="commencement_claim",
                    excerpt=excerpt,
                    start=m.start(),
                    end=m.end(),
                    reason="Commencement/effective dates must be confirmed against the Gazette, not asserted.",
                )
            )

        violations.sort(key=lambda v: v.start)
        return violations

    def sanitize(self, text: str) -> tuple[str, list[CitationViolation]]:
        violations = self.scan(text)
        if not violations:
            return text, []

        spans = sorted({(v.start, v.end) for v in violations})
        merged: list[list[int]] = []
        for start, end in spans:
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])

        parts: list[str] = []
        cursor = 0
        for start, end in merged:
            parts.append(text[cursor:start])
            parts.append(PLACEHOLDER)
            cursor = end
        parts.append(text[cursor:])
        return "".join(parts), violations

    def report(self, violations: list[CitationViolation]) -> dict:
        by_kind: dict[str, int] = {}
        for v in violations:
            by_kind[v.kind] = by_kind.get(v.kind, 0) + 1
        samples = [
            {"kind": v.kind, "excerpt": v.excerpt, "start": v.start, "end": v.end, "reason": v.reason}
            for v in violations[:5]
        ]
        return {
            "clean": len(violations) == 0,
            "violation_count": len(violations),
            "by_kind": by_kind,
            "samples": samples,
        }
