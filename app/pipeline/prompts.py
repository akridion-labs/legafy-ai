"""Prompt templates.

Kept in one small reviewable file because these strings are the actual
instruction that decides whether a generated clause is safe. Treat edits here
as product changes, not copy tweaks.
"""

from __future__ import annotations

import json

from app.pipeline.chunks import ChunkSpec

SYSTEM_TEMPLATE = """You are a contract drafting engine for Legafy AI (Akridion Labs).
You produce PRE-COUNSEL STRUCTURAL SCAFFOLDING. You are not a lawyer and you do not give legal advice.

FRAMEWORK: {framework}
JURISDICTION IN SCOPE: {jurisdiction} (India). This is the ONLY state in scope.

HARD CONSTRAINTS — violating any of these invalidates the output:
1. NEVER write a statutory section number, sub-section, rule number, article, schedule reference, penalty amount, fine, monetary threshold, percentage of turnover, or commencement date. Not one. If a clause would normally cite an authority, describe the obligation in plain terms instead and leave the citation to counsel.
2. Refer to a statute ONLY by an exact title from the grounding block below. If a title is not in that list, do not name it at all.
3. Do not generalise a union-level rule over the state, or one state's rule over another. {jurisdiction} only.
4. Output Markdown. One `### <id> <heading>` per requested clause, using the exact ids given. Numbered sub-paragraphs beneath each.
5. Output the clauses only. No preamble, no commentary, no restating the table of contents, no closing summary.

GROUNDING BLOCK (the only instruments you may name):
{titles}

The obligations below are context for your drafting. They are seed metadata: the titles are usable, everything else is unverified.
{obligations}
"""

CHUNK_TEMPLATE = """Draft module {index}: **{heading}**.

Clauses to produce, in order:
{clauses}

Target length: approximately {min_words} words for this module.

{tail_block}
Begin at `### {first_id}`."""

CONTINUATION_TEMPLATE = """Your previous output was cut off mid-clause. Continue it seamlessly.

The last text you produced ended with:
---
{tail}
---

Resume exactly from that point. Do not repeat any text above. Do not re-emit a heading you have already written.
Clauses still to produce: {missing}"""

REPAIR_TEMPLATE = """These clauses from module {index} ({heading}) are missing from your output. Produce ONLY them, nothing else:
{clauses}"""


def build_system_prompt(grounding: dict, framework_type: str, jurisdiction_display: str) -> str:
    titles = grounding.get("citable_instrument_titles", [])
    obligations = []
    for block in [grounding.get("union", {})] + list(grounding.get("states", [])):
        for instrument in block.get("instruments", []):
            for ob in instrument.get("obligations", []):
                obligations.append(
                    {"instrument": instrument["title"], "duty": ob.get("summary", "")}
                )
    return SYSTEM_TEMPLATE.format(
        framework=framework_type,
        jurisdiction=jurisdiction_display,
        titles="\n".join(f"- {t}" for t in titles) or "- (none supplied)",
        obligations=json.dumps(obligations[:40], indent=1),
    )


def build_chunk_prompt(chunk: ChunkSpec, previous_tail: str) -> str:
    clauses = "\n".join(f"- {s.id} {s.heading} — {s.guidance}" for s in chunk.clauses)
    tail_block = (
        f"For continuity, the previous module ended with:\n---\n{previous_tail}\n---\n"
        if previous_tail
        else ""
    )
    return CHUNK_TEMPLATE.format(
        index=chunk.index,
        heading=chunk.heading,
        clauses=clauses,
        min_words=chunk.min_words,
        tail_block=tail_block,
        first_id=chunk.clauses[0].id,
    )


def build_continuation_prompt(tail: str, missing: list[str]) -> str:
    return CONTINUATION_TEMPLATE.format(
        tail=tail[-600:], missing=", ".join(missing) or "(finish the current clause)"
    )


def build_repair_prompt(chunk: ChunkSpec, missing_ids: list[str]) -> str:
    clauses = "\n".join(
        f"- {s.id} {s.heading} — {s.guidance}" for s in chunk.clauses if s.id in missing_ids
    )
    return REPAIR_TEMPLATE.format(index=chunk.index, heading=chunk.heading, clauses=clauses)
