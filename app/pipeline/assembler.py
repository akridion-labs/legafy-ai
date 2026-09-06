"""Anti-truncation chunk assembly — the core of the product.

Standard LLM output windows truncate a 20-page agreement mid-sentence. This
loop generates one module at a time, detects a truncated stop, resumes from the
trailing text, repairs any clause that never appeared, and only then stitches.
A short document is a bug here, not a degraded mode.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from app.compliance.citation_guard import CitationGuard
from app.config import Settings
from app.models.schemas import ChunkReport
from app.pipeline.chunks import ChunkSpec
from app.pipeline.prompts import (
    build_chunk_prompt,
    build_continuation_prompt,
    build_repair_prompt,
)
from app.providers.base import CompletionRequest
from app.providers.router import ProviderRouter

log = logging.getLogger("legafy.assembler")

SENTENCE_END = re.compile(r"(?s)^.*[.;:!?]\s")


@dataclass
class AssembledChunk:
    spec: ChunkSpec
    markdown: str
    report: ChunkReport


@dataclass
class AssembledDocument:
    session_id: str
    markdown: str
    chunks: list[AssembledChunk]
    total_words: int
    estimated_pages: float
    guard_report: dict = field(default_factory=dict)
    missing_clauses: list[str] = field(default_factory=list)


def _words(text: str) -> int:
    return len(text.split())


def _trim_partial_sentence(text: str) -> str:
    """Drop a dangling half-sentence so the continuation joins cleanly."""
    match = SENTENCE_END.match(text)
    return match.group(0) if match else text


def _present_clause_ids(text: str, spec: ChunkSpec) -> set[str]:
    return {s.id for s in spec.clauses if re.search(rf"^###\s+{re.escape(s.id)}\b", text, re.M)}


class ChunkAssembler:
    def __init__(
        self,
        router: ProviderRouter,
        settings: Settings,
        guard: CitationGuard | None = None,
    ) -> None:
        self.router = router
        self.settings = settings
        self.guard = guard

    async def _generate_chunk(
        self, spec: ChunkSpec, system: str, previous_tail: str
    ) -> tuple[str, ChunkReport]:
        started = time.perf_counter()
        result = await self.router.complete(
            CompletionRequest(
                system=system,
                prompt=build_chunk_prompt(spec, previous_tail),
                max_tokens=self.settings.chunk_max_tokens,
            )
        )
        text = result.text
        continuations = 0
        recovered = False

        # 1. Truncation recovery. Continue only while something is actually
        #    missing — a truncated stop on a chunk that already carries every
        #    clause and meets its word budget is done, and looping past that
        #    point is how a 20-page target turns into 240 pages.
        while result.truncated and continuations < self.settings.chunk_continuations:
            missing = sorted(set(spec.clause_ids) - _present_clause_ids(text, spec))
            if not missing and _words(text) >= spec.min_words:
                break
            text = _trim_partial_sentence(text)
            result = await self.router.complete(
                CompletionRequest(
                    system=system,
                    prompt=build_continuation_prompt(text, missing),
                    max_tokens=self.settings.chunk_max_tokens,
                )
            )
            text = f"{text.rstrip()}\n{result.text.lstrip()}"
            continuations += 1
            recovered = True

        # 2. Targeted repair for any clause that never appeared.
        missing = sorted(set(spec.clause_ids) - _present_clause_ids(text, spec))
        if missing:
            log.warning("module %s missing clauses %s — repairing", spec.index, missing)
            repair = await self.router.complete(
                CompletionRequest(
                    system=system,
                    prompt=build_repair_prompt(spec, missing),
                    max_tokens=self.settings.chunk_max_tokens,
                )
            )
            text = f"{text.rstrip()}\n\n{repair.text.lstrip()}"

        return text, ChunkReport(
            index=spec.index,
            module=spec.module,
            heading=spec.heading,
            clause_ids=spec.clause_ids,
            words=_words(text),
            continuations=continuations,
            truncation_recovered=recovered,
            provider=result.provider,
            model=result.model,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    async def assemble(
        self,
        *,
        plan: list[ChunkSpec],
        system_prompt: str,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> AssembledDocument:
        chunks: list[AssembledChunk] = []
        violations: list = []
        previous_tail = ""

        # ponytail: strictly sequential. Concurrency here costs clause-numbering
        # and defined-term continuity; the wall-clock win is not worth it.
        for spec in plan:
            if progress:
                progress(spec.index, len(plan), spec.heading)
            text, report = await self._generate_chunk(spec, system_prompt, previous_tail)
            if self.guard:
                text, found = self.guard.sanitize(text)
                violations.extend(found)
                report = report.model_copy(update={"words": _words(text)})
            body = f"## {spec.index}. {spec.heading}\n\n{text.strip()}\n"
            chunks.append(AssembledChunk(spec=spec, markdown=body, report=report))
            previous_tail = text[-400:]

        # 3. Word-floor top-up: expand the biggest shortfalls rather than padding.
        floor = self.settings.min_document_words
        for _ in range(2):
            total = sum(_words(c.markdown) for c in chunks)
            if total >= floor:
                break
            deficits = sorted(
                chunks, key=lambda c: _words(c.markdown) - c.spec.min_words
            )[:3]
            for chunk in deficits:
                extra = await self.router.complete(
                    CompletionRequest(
                        system=system_prompt,
                        prompt=(
                            f"Expand module {chunk.spec.index} ({chunk.spec.heading}) with "
                            "additional sub-paragraphs under its existing clause headings. "
                            "Output only the new sub-paragraphs, each prefixed with its "
                            "clause id. Same constraints as before."
                        ),
                        max_tokens=self.settings.chunk_max_tokens,
                    )
                )
                text = extra.text
                if self.guard:
                    text, found = self.guard.sanitize(text)
                    violations.extend(found)
                chunk.markdown = f"{chunk.markdown.rstrip()}\n\n{text.strip()}\n"

        body = "\n".join(c.markdown for c in chunks)
        total_words = _words(body)
        missing = [
            cid
            for c in chunks
            for cid in sorted(set(c.spec.clause_ids) - _present_clause_ids(c.markdown, c.spec))
        ]
        guard_report = (
            self.guard.report(violations)
            if self.guard
            else {"clean": True, "violation_count": 0}
        )
        guard_report["missing_clauses"] = missing

        return AssembledDocument(
            session_id=str(uuid.uuid4()),
            markdown=body,
            chunks=chunks,
            total_words=total_words,
            estimated_pages=round(total_words / 500, 1),
            guard_report=guard_report,
            missing_clauses=missing,
        )
