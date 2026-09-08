"""Query understanding: what the person is asking, and how they are asking it.

Two things get read off a question, and it matters that they stay separate:

**Intent** — what they want (screen an idea, find the official page, draft a
document, know a penalty, compare two states). Intent selects the tool and the
shape of the answer.

**Tone** — how they are asking (exploring, worried, under a deadline, arguing).
Tone changes *delivery* only: ordering, brevity, whether the counsel brief comes
first. It must never change what is true. A worried founder and a curious one
get the same RED verdict on the same facts; the worried one gets it in the first
sentence with the phone-a-lawyer step attached, the curious one gets the
reasoning first. Any code that lets tone move a lane is a bug, and
`tone_affects_verdict` is hard-coded False so the property is stated in the
response rather than merely promised in a comment.

Data structures
---------------
A **trie** over jurisdiction names, aliases and instrument titles gives
longest-match extraction in one pass over the question — so "andhra pradesh"
matches as one entity rather than colliding with "andhra" plus noise, and a
50-term vocabulary costs the same as a 50,000-term one later.

Everything else is a scored rule table, not a model. Rules are auditable, they
run in microseconds, and when they misfire you can see exactly which phrase did
it. The classifier we would eventually train (roadmap 5.3) has labels only
because this one is running first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


# ---------------------------------------------------------------------------
# Trie — longest-match entity extraction
# ---------------------------------------------------------------------------
class TrieNode:
    __slots__ = ("children", "payload")

    def __init__(self) -> None:
        self.children: dict[str, TrieNode] = {}
        self.payload: Any = None


class PhraseTrie:
    """Word-level trie. Insert phrases, extract the longest matches in a text."""

    def __init__(self) -> None:
        self.root = TrieNode()
        self._size = 0

    def __len__(self) -> int:
        return self._size

    def insert(self, phrase: str, payload: Any) -> None:
        node = self.root
        for word in WORD_RE.findall(phrase.lower()):
            node = node.children.setdefault(word, TrieNode())
        if node.payload is None:
            self._size += 1
        node.payload = payload

    def extract(self, text: str) -> list[tuple[str, Any]]:
        """Greedy longest-match scan. O(n × longest phrase), one pass."""
        words = WORD_RE.findall(text.lower())
        found: list[tuple[str, Any]] = []
        i = 0
        while i < len(words):
            node = self.root
            best_payload, best_end = None, i
            j = i
            while j < len(words) and words[j] in node.children:
                node = node.children[words[j]]
                j += 1
                if node.payload is not None:
                    best_payload, best_end = node.payload, j
            if best_payload is not None:
                found.append((" ".join(words[i:best_end]), best_payload))
                i = best_end
            else:
                i += 1
        return found


def build_jurisdiction_trie() -> PhraseTrie:
    from app.compliance.registry import JURISDICTION_REGISTRY

    JURISDICTION_REGISTRY.load()
    trie = PhraseTrie()
    for summary in JURISDICTION_REGISTRY.all_summaries():
        code = summary["code"]
        jur = JURISDICTION_REGISTRY.get(code)
        trie.insert(summary["display_name"], {"kind": "jurisdiction", "code": code})
        trie.insert(code, {"kind": "jurisdiction", "code": code})
        for alias in jur.raw.get("aliases", []):
            trie.insert(alias, {"kind": "jurisdiction", "code": code})
        for instrument in jur.instruments:
            trie.insert(
                instrument["title"],
                {"kind": "instrument", "id": instrument["id"], "jurisdiction": code},
            )
    return trie


_TRIE: PhraseTrie | None = None


def get_trie() -> PhraseTrie:
    global _TRIE
    if _TRIE is None:
        _TRIE = build_jurisdiction_trie()
    return _TRIE


def reset_trie_cache() -> None:
    global _TRIE
    _TRIE = None


# ---------------------------------------------------------------------------
# Intent and tone
# ---------------------------------------------------------------------------
INTENT_RULES: dict[str, tuple[tuple[str, float], ...]] = {
    "screen_idea": (
        (r"\b(can i|are we allowed|is it legal|do i need|what do i need)\b", 3.0),
        (r"\b(start|launch|build|planning to|thinking of|idea for)\b", 2.0),
        (r"\b(licen[cs]e|registration|register|permission|approval)\b", 2.0),
        (r"\b(compliance|compliant|legal requirements)\b", 1.5),
    ),
    "find_source": (
        (r"\b(where (can|do) i (find|read|download)|official (page|site|link)|source)\b", 3.5),
        (r"\b(notification|gazette|circular|gu[id]+elines?|portal|form)\b", 2.0),
        (r"\b(link|url|website)\b", 1.0),
    ),
    "draft_document": (
        (r"\b(draft|write|prepare|generate|create) (me )?(an?|the)? ?"
         r"(agreement|contract|nda|policy|terms|deed)\b", 4.0),
        (r"\b(founders? agreement|employment (agreement|contract)|nda|privacy policy|terms of service)\b", 2.5),
        (r"\b(template|clause|boilerplate)\b", 1.5),
    ),
    "penalty_or_threshold": (
        (r"\b(penalt|fine|punishment|imprison|how much (is|will)|threshold|limit|slab)\b", 3.0),
        (r"\b(what happens if|consequence|non.?compliance)\b", 2.0),
    ),
    "deadline_or_timeline": (
        (r"\b(deadline|due date|by when|how long|timeline|within \d+ days|renewal)\b", 3.0),
        (r"\b(file|filing|return|annual)\b", 1.0),
    ),
    "compare_jurisdictions": (
        (r"\b(vs\.?|versus|compare|comparison|better|difference between|which state)\b", 3.0),
        (r"\b(cheaper|easier|faster) (to|for)\b", 1.5),
    ),
}

TONE_RULES: dict[str, tuple[tuple[str, float], ...]] = {
    "urgent": (
        (r"\b(urgent|asap|immediately|today|tomorrow|deadline (is|was)|running out|tonight)\b", 3.0),
        (r"\b(already (started|launched|signed|hired))\b", 2.0),
    ),
    "worried": (
        (r"\b(worried|scared|afraid|risk|trouble|in breach|violat|notice from|penalt)\b", 2.5),
        (r"\b(did i|have we|are we in) .{0,20}(wrong|trouble|breach)\b", 3.0),
        (r"\b(help|please)\b", 0.5),
    ),
    "exploratory": (
        (r"\b(thinking|considering|exploring|curious|what if|planning|someday|maybe)\b", 2.5),
        (r"\b(idea|concept|early stage|pre.?launch)\b", 1.5),
    ),
    "adversarial": (
        (r"\b(loophole|avoid|get around|without (registering|paying|declaring)|"
         r"bypass|do i really have to|no one checks)\b", 4.0),
    ),
}

# What each tone changes about delivery. Never about the verdict.
TONE_DELIVERY: dict[str, str] = {
    "urgent": (
        "Lead with the single blocking item and the immediate next step. Keep context short. "
        "If something is already done and cannot be undone, say so plainly and move to remedy."
    ),
    "worried": (
        "Open by naming what is and is not actually a problem, in that order — most fears here "
        "are about the wrong thing. Then the concrete next step. Do not amplify the worry, and "
        "do not minimise a real RED lane to be reassuring."
    ),
    "exploratory": (
        "Reasoning first, then the verdict. This person is deciding, not reacting, so the "
        "trade-offs between paths are the valuable part."
    ),
    "adversarial": (
        "Answer the actual legal position without moralising, and without helping structure "
        "avoidance. State what triggers the obligation, and that the assessment is what it is. "
        "Do not soften a RED lane because the user pushed back on it."
    ),
    "neutral": "Verdict, then obligations by block, then the counsel brief.",
}


def _score(text: str, rules: dict[str, tuple[tuple[str, float], ...]]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for label, patterns in rules.items():
        total = sum(weight for pattern, weight in patterns if re.search(pattern, text))
        if total:
            scores[label] = round(total, 3)
    return scores


@dataclass
class QueryAnalysis:
    question: str
    intent: str
    intent_scores: dict[str, float]
    tone: str
    tone_scores: dict[str, float]
    jurisdictions: list[str]
    instruments: list[str]
    entities: list[dict[str, Any]] = field(default_factory=list)
    expanded_terms: list[str] = field(default_factory=list)
    delivery_guidance: str = ""
    tone_affects_verdict: bool = False
    needs_jurisdiction: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "intent_scores": self.intent_scores,
            "tone": self.tone,
            "tone_scores": self.tone_scores,
            "jurisdictions": self.jurisdictions,
            "instruments": self.instruments,
            "entities": self.entities,
            "expanded_terms": self.expanded_terms,
            "delivery_guidance": self.delivery_guidance,
            "tone_affects_verdict": self.tone_affects_verdict,
            "needs_jurisdiction": self.needs_jurisdiction,
            "contract": (
                "Tone changes how the answer is delivered, never what it says. The same facts "
                "produce the same lane regardless of how the question was phrased."
            ),
        }


# Query expansion: the words a founder uses vs the words a government page uses.
# This is the gap that makes plain keyword search fail on official sources.
EXPANSIONS: dict[str, tuple[str, ...]] = {
    "hiring": ("employment", "employees", "establishment", "labour"),
    "hire": ("employment", "employees", "establishment"),
    "staff": ("employees", "establishment"),
    "office": ("establishment", "shops and establishments"),
    "shop": ("establishment", "shops and establishments"),
    "salary": ("wages", "remuneration"),
    "payroll": ("wages", "professional tax", "provident fund"),
    "pf": ("provident fund", "epf"),
    "esi": ("employees state insurance",),
    "pt": ("professional tax",),
    "data": ("personal data", "data protection"),
    "privacy": ("personal data", "data protection"),
    "gdpr": ("data protection", "personal data"),
    "payments": ("payment aggregator", "escrow", "nodal account"),
    "wallet": ("prepaid payment instrument", "payment aggregator"),
    "loan": ("lending", "credit", "nbfc"),
    "incorporate": ("incorporation", "registrar of companies", "company"),
    "register": ("registration", "registrar"),
    "gst": ("goods and services tax", "registration"),
    "trademark": ("trade mark", "intellectual property"),
    "layoff": ("retrenchment", "termination"),
    "fire": ("termination", "retrenchment"),
    "wfh": ("work from home", "conditions of service"),
    "night shift": ("night working", "conditions of service"),
}


def expand_terms(question: str) -> list[str]:
    words = set(WORD_RE.findall(question.lower()))
    lowered = question.lower()
    out: set[str] = set()
    for key, additions in EXPANSIONS.items():
        if (" " in key and key in lowered) or key in words:
            out.update(additions)
    return sorted(out)


def analyse(question: str) -> QueryAnalysis:
    text = question.lower().strip()
    intent_scores = _score(text, INTENT_RULES)
    tone_scores = _score(text, TONE_RULES)

    intent = max(intent_scores, key=lambda k: intent_scores[k]) if intent_scores else "general"
    tone = max(tone_scores, key=lambda k: tone_scores[k]) if tone_scores else "neutral"

    entities = [{"text": phrase, **payload} for phrase, payload in get_trie().extract(question)]
    jurisdictions = sorted({e["code"] for e in entities if e["kind"] == "jurisdiction"})
    instruments = sorted({e["id"] for e in entities if e["kind"] == "instrument"})

    # Intents whose answer is meaningless without a state. Asking is the correct
    # move here; guessing a state is the failure this whole system prevents.
    jurisdiction_bound = {"screen_idea", "penalty_or_threshold", "deadline_or_timeline", "find_source"}

    return QueryAnalysis(
        question=question,
        intent=intent,
        intent_scores=intent_scores,
        tone=tone,
        tone_scores=tone_scores,
        jurisdictions=jurisdictions,
        instruments=instruments,
        entities=entities,
        expanded_terms=expand_terms(question),
        delivery_guidance=TONE_DELIVERY.get(tone, TONE_DELIVERY["neutral"]),
        tone_affects_verdict=False,
        needs_jurisdiction=intent in jurisdiction_bound and not jurisdictions,
    )


def build_fts_query(question: str, analysis: QueryAnalysis | None = None) -> str:
    """Turn a natural question into an FTS5 query.

    Stopwords out, expansions in, entity phrases quoted so a multi-word statute
    title matches as a phrase rather than as loose words.
    """
    analysis = analysis or analyse(question)
    stop = {
        "the", "a", "an", "and", "or", "of", "to", "in", "for", "is", "are", "do", "does",
        "i", "we", "my", "our", "can", "what", "how", "when", "where", "need", "want",
        "should", "would", "if", "it", "this", "that", "with", "on", "at", "be", "have",
    }
    words = [w for w in WORD_RE.findall(question.lower()) if w not in stop and len(w) > 2]
    phrases = [f'"{e["text"]}"' for e in analysis.entities if " " in e["text"]]
    terms = phrases + [f'"{t}"' if " " in t else t for t in analysis.expanded_terms] + words
    seen: set[str] = set()
    unique = [t for t in terms if not (t in seen or seen.add(t))]
    return " OR ".join(unique[:24]) or question
