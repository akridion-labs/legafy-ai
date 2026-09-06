"""Anti-truncation pipeline tests. Offline provider only — no network."""

from __future__ import annotations

import re

import pytest

from app.compliance.citation_guard import CitationGuard
from app.config import Settings
from app.models.schemas import DocumentGenerationRequest, FrameworkType
from app.pipeline.assembler import ChunkAssembler
from app.pipeline.chunks import MODULE_SEQUENCE, build_chunk_plan, build_table_of_contents
from app.pipeline.renderers import render_docx
from app.providers.base import CompletionRequest, ProviderError
from app.providers.offline import OfflineProvider
from app.providers.router import ProviderRouter


def _settings(**over) -> Settings:
    base = {
        "LEGAFY_PROVIDER_CHAIN": "offline",
        "LEGAFY_CHUNK_MAX_TOKENS": 900,
        "LEGAFY_CHUNK_CONTINUATIONS": 4,
        "LEGAFY_MIN_DOCUMENT_WORDS": 1200,
        "LEGAFY_TELEMETRY_SALT": "test-salt",
    }
    base.update(over)
    return Settings(**base)


def _plan(min_words: int = 1200):
    request = DocumentGenerationRequest(
        project_name="Test Venture",
        target_state="Telangana",
        framework_type=FrameworkType.MUTUAL_NDA,
    )
    return build_chunk_plan(
        framework_type=FrameworkType.MUTUAL_NDA,
        jurisdiction_display="Telangana",
        request=request,
        min_words=min_words,
    )


def test_mandatory_modules_present_and_ordered():
    modules = [c.module for c in _plan()]
    assert modules[: len(MODULE_SEQUENCE)] == list(MODULE_SEQUENCE)


def test_toc_lists_every_clause():
    plan = _plan()
    toc = build_table_of_contents(plan)
    for chunk in plan:
        for clause in chunk.clauses:
            assert clause.id in toc


async def test_offline_provider_never_emits_law():
    provider = OfflineProvider()
    result = await provider.complete(
        CompletionRequest(system="s", prompt="- 1.1 Definitions\n- 1.2 Recitals", max_tokens=800)
    )
    assert not re.search(r"\b(Section|Rule|Article)\s+\d", result.text)
    assert not re.search(r"[₹$]|\bRs\.?\s?\d|\bINR\b", result.text)


async def test_router_fails_over_to_next_provider():
    class Broken(OfflineProvider):
        name = "broken"

        async def complete(self, request):
            raise ProviderError("broken", "boom")

    settings = _settings(LEGAFY_PROVIDER_CHAIN="offline")
    router = ProviderRouter(settings, sleep=lambda _: __import__("asyncio").sleep(0))
    router._providers = [Broken(), OfflineProvider()]
    result = await router.complete(CompletionRequest(system="s", prompt="- 1.1 X", max_tokens=200))
    assert result.provider == "offline"


async def test_truncation_is_detected_and_recovered():
    """The core invariant: a truncated generation still yields every clause."""
    settings = _settings(LEGAFY_CHUNK_MAX_TOKENS=260)  # forces mid-sentence cut-offs
    router = ProviderRouter(settings)
    document = await ChunkAssembler(router, settings).assemble(
        plan=_plan(), system_prompt="test system"
    )

    assert any(c.report.truncation_recovered for c in document.chunks), "no truncation exercised"
    assert document.missing_clauses == []
    for chunk in document.chunks:
        for clause_id in chunk.spec.clause_ids:
            assert f"### {clause_id}" in chunk.markdown


async def test_word_floor_is_met():
    settings = _settings(LEGAFY_MIN_DOCUMENT_WORDS=1200)
    document = await ChunkAssembler(ProviderRouter(settings), settings).assemble(
        plan=_plan(), system_prompt="test system"
    )
    assert document.total_words >= 1200
    assert document.estimated_pages > 0


async def test_citation_guard_runs_over_every_chunk():
    settings = _settings()
    guard = CitationGuard(allowed_titles=set(), allowed_hosts={"indiacode.nic.in"})
    document = await ChunkAssembler(ProviderRouter(settings), settings, guard).assemble(
        plan=_plan(), system_prompt="test system"
    )
    assert "violation_count" in document.guard_report


def test_render_docx_produces_a_real_document(tmp_path):
    pytest.importorskip("docx")
    from docx import Document

    markdown = "# Title\n\n## 1. Preamble\n\n### 1.1 Definitions\n\nText.\n\n- bullet\n\n1. numbered\n"
    path = render_docx(
        markdown_text=markdown * 30,
        path=tmp_path / "out.docx",
        title="Test",
        meta={"Jurisdiction": "Telangana"},
        disclaimer="Not legal advice.",
    )
    assert path.exists()
    assert len(Document(str(path)).paragraphs) > 50
