"""The pre-counsel research checklist — the searches, not the answers.

What an advocate actually does first
------------------------------------
A lawyer briefed on a new venture does not begin by reciting statutes. They
begin by running searches: is the name free on the company register *and* the
trade-mark register (different registers, different tests); is the co-founder a
disqualified director; is the vendor's GSTIN live; is the activity one only an
RBI-authorised entity may carry on. Those searches are cheap before launch and
ruinously expensive afterwards.

Legafy's grounding matrix answers "which law applies". This module answers the
question that comes before it: **"what should I have looked up by now?"** —
each entry naming the official register, what a search there proves, and what
skipping it costs.

Why it is a checklist and not a lookup
--------------------------------------
Legafy does not run these searches for the user, and deliberately does not
cache their results. A register's contents change daily, several require a
captcha or a login, and a stale answer about whether a mark is free is worse
than no answer. So this returns *where to look and why*, which is stable, and
never *what you will find*, which is not.

Filtering uses the same declared activity flags as the instrument matrix, so a
venture that employs nobody is not told to check the PF register.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from app.config import REPO_ROOT

REGISTER_FILE = REPO_ROOT / "data" / "research_registers.json"

# Order the checklist the way the work actually happens, not alphabetically.
PHASE_ORDER: tuple[str, ...] = (
    "name_and_identity",
    "entity_formation",
    "premises",
    "sector_licence",
    "counterparty_diligence",
    "ip",
    "rule_currency",
)

PHASE_LABEL: dict[str, str] = {
    "name_and_identity": "Before you print the name on anything",
    "entity_formation": "While incorporating",
    "premises": "Once you have an address and a first hire",
    "sector_licence": "Before you build the regulated feature",
    "counterparty_diligence": "Before you sign with them",
    "ip": "Before the feature ships",
    "rule_currency": "Every time you rely on a rule",
}


@lru_cache(maxsize=1)
def _load() -> list[dict[str, Any]]:
    raw = json.loads(REGISTER_FILE.read_text(encoding="utf-8"))
    return raw.get("registers", [])


def build_research_checklist(activity_flags: set[str]) -> dict[str, Any]:
    """Return the register searches this venture should have run, by phase."""
    flags = set(activity_flags) | {"any_entity"}
    selected = [
        entry
        for entry in _load()
        if not entry.get("applies_when") or (set(entry["applies_when"]) & flags)
    ]

    by_phase: dict[str, list[dict[str, Any]]] = {}
    for entry in selected:
        by_phase.setdefault(entry.get("phase", "counterparty_diligence"), []).append(
            {
                "id": entry["id"],
                "search": entry["name"],
                "where": entry["url"] or "state portal — see the state block in this response",
                "authority": entry["authority"],
                "proves": entry["proves"],
                "if_skipped": entry["if_skipped"],
            }
        )

    phases = [
        {"phase": phase, "when": PHASE_LABEL.get(phase, phase), "searches": by_phase[phase]}
        for phase in PHASE_ORDER
        if phase in by_phase
    ]
    return {
        "count": len(selected),
        "phases": phases,
        "note": (
            "These are searches to run, not results. Legafy does not query these registers "
            "and holds no view on what they contain today — a register's answer changes daily "
            "and a stale one is worse than none. Run them yourself, keep the dated screenshot, "
            "and put anything surprising to a lawyer before you build around it."
        ),
    }
