"""Anti-truncation document assembly pipeline."""

from app.pipeline.assembler import AssembledChunk, AssembledDocument, ChunkAssembler
from app.pipeline.chunks import (
    MODULE_SEQUENCE,
    ChunkSpec,
    ClauseSpec,
    build_chunk_plan,
    build_table_of_contents,
    plan_to_dicts,
)
from app.pipeline.prompts import build_system_prompt
from app.pipeline.renderers import (
    estimate_pages,
    render_document_markdown,
    render_docx,
    slugify,
    write_markdown,
)

__all__ = [
    "MODULE_SEQUENCE",
    "AssembledChunk",
    "AssembledDocument",
    "ChunkAssembler",
    "ChunkSpec",
    "ClauseSpec",
    "build_chunk_plan",
    "build_system_prompt",
    "build_table_of_contents",
    "estimate_pages",
    "plan_to_dicts",
    "render_docx",
    "render_document_markdown",
    "slugify",
    "write_markdown",
]
