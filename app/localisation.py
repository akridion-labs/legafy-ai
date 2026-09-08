"""Regional-language output, with a hard line around what may be translated.

The line
--------
A mistranslated obligation is worse than no translation: it reads as authority
and it is wrong. So this layer splits every response in two.

**Never translated** — instrument titles, statutory references, party names,
defined terms, and the operative text of any generated agreement. A statute's
title is its identifier; translating "Telangana Shops and Establishments Act,
1988" produces a name that matches nothing on any portal and cannot be looked
up. Contract operative text stays in English because English is the language
the document is enforceable in, and a bilingual contract needs an explicit
controlling-language clause to be safe.

**Translated** — the explanation layer a founder actually reads: what the
obligation means, why the traffic light says what it says, and the questions to
put to a lawyer. That is where language access genuinely changes who can use
this, and where a wording slip is recoverable rather than dangerous.

Every translated payload carries `machine_translated: true` and the English
source alongside it. Nothing here is presented as an authoritative rendering
until a native-speaker reviewer signs off the glossary.

Model-agnostic: translation goes through the same provider router as everything
else. With no provider configured it degrades to glossary-annotated English and
says so, rather than guessing.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.config import REPO_ROOT

log = logging.getLogger("legafy.localisation")

GLOSSARY_DIR = REPO_ROOT / "data" / "glossary"

# `language` arrives from the request body, and it is used to build a file path.
# Without this, `language="../license_registry.example"` reads a file outside the
# glossary directory, and the difference between "parsed but wrong shape" and
# "no such file" is an enumeration oracle for what exists on disk. A language tag
# is a short alphanumeric code; anything else is refused before it touches a path.
LANGUAGE_CODE_RE = re.compile(r"^[a-z]{2,3}(?:-[a-z]{2,8})?$", re.IGNORECASE)

# Keys whose values are explanation and may be translated. Anything not listed
# is left alone — an allow-list, so a new field is untranslated until someone
# decides it is safe, rather than translated by default.
TRANSLATABLE_KEYS: frozenset[str] = frozenset(
    {
        "summary",
        "rationale",
        "headline",
        "mandatory_counsel_notice",
        "counsel_brief",
        "verification_note",
        "provenance_warning",
        "isolation_contract",
        "disclaimer",
        "escalation_triggers",
        "title",  # signal titles, not instrument titles — see _walk
    }
)

# Inside these blocks nothing is translated at all, whatever the key.
PROTECTED_BLOCKS: frozenset[str] = frozenset({"instruments", "union", "states", "chunk_plan"})

SYSTEM_PROMPT = """You are translating explanatory text for a legal compliance tool into {language_name} ({native_name}).

RULES:
1. Translate meaning, not word by word. The reader is a startup founder, not a lawyer.
2. Use the glossary below for every listed term. Consistency matters more than elegance.
3. NEVER translate: statute names, Act titles with years, party names, defined terms in Capitals, URLs, or anything in `backticks`. Leave them in English exactly as written.
4. Do not add, soften or strengthen any obligation. If the English hedges, hedge.
5. Output ONLY the translation. No preamble, no notes, no transliteration.

GLOSSARY:
{glossary}
"""


@dataclass(frozen=True)
class Glossary:
    code: str
    language_name: str
    native_name: str
    verified: bool
    terms: dict[str, str]
    ui: dict[str, str]

    def as_prompt_block(self) -> str:
        return "\n".join(f"- {en} → {native}" for en, native in self.terms.items())


@lru_cache(maxsize=8)
def load_glossary(code: str) -> Glossary | None:
    if not code or not LANGUAGE_CODE_RE.match(code):
        log.warning("refused malformed language code %r", code[:32])
        return None
    path = (GLOSSARY_DIR / f"{code.lower()}.json").resolve()
    # Belt and braces: even with the regex, never read outside the directory.
    if path.parent != GLOSSARY_DIR.resolve() or not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Glossary(
        code=raw["language"],
        language_name=raw["language_name"],
        native_name=raw.get("native_name", raw["language_name"]),
        verified=raw.get("verification_status") == "VERIFIED",
        terms=raw.get("terms", {}),
        ui=raw.get("ui", {}),
    )


def supported_languages() -> list[dict[str, Any]]:
    out = []
    for path in sorted(GLOSSARY_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        out.append(
            {
                "code": raw["language"],
                "language_name": raw["language_name"],
                "native_name": raw.get("native_name"),
                "glossary_verified": raw.get("verification_status") == "VERIFIED",
            }
        )
    return out


def _collect(node: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], str]]:
    """Find every translatable string, skipping protected blocks."""
    found: list[tuple[tuple[str, ...], str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in PROTECTED_BLOCKS:
                continue
            if isinstance(value, str) and key in TRANSLATABLE_KEYS and value.strip():
                found.append(((*path, key), value))
            else:
                found.extend(_collect(value, (*path, key)))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            if isinstance(value, str) and path and path[-1] in TRANSLATABLE_KEYS:
                found.append(((*path, str(i)), value))
            else:
                found.extend(_collect(value, (*path, str(i))))
    return found


def _assign(node: Any, path: tuple[str, ...], value: str) -> None:
    for key in path[:-1]:
        node = node[int(key)] if isinstance(node, list) else node[key]
    last = path[-1]
    if isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value


async def translate_payload(
    payload: dict[str, Any], language: str, *, router=None
) -> dict[str, Any]:
    """Return the payload with its explanation layer translated.

    The original English is preserved under `source_en` for every field that was
    translated, so a reader — or a lawyer — can always check the rendering.
    """
    glossary = load_glossary(language)
    if glossary is None:
        return {
            **payload,
            "localisation": {
                "requested": language,
                "status": "UNSUPPORTED_LANGUAGE",
                "supported": [entry["code"] for entry in supported_languages()],
            },
        }

    targets = _collect(payload)
    if not targets:
        return payload

    if router is None:
        from app.providers.router import get_router

        router = get_router()

    from app.providers.base import CompletionRequest

    numbered = "\n".join(f"[{i}] {text}" for i, (_, text) in enumerate(targets))
    system = SYSTEM_PROMPT.format(
        language_name=glossary.language_name,
        native_name=glossary.native_name,
        glossary=glossary.as_prompt_block(),
    )
    prompt = (
        "Translate each numbered line. Return exactly one line per input, in the same order, "
        f"each prefixed with its number in square brackets.\n\n{numbered}"
    )

    try:
        result = await router.complete(
            CompletionRequest(system=system, prompt=prompt, max_tokens=4000, temperature=0.1)
        )
        translations = _parse_numbered(result.text, len(targets))
        provider = result.provider
    except Exception as exc:
        log.warning("translation failed (%s); returning English", exc)
        return {
            **payload,
            "localisation": {
                "requested": language,
                "status": "TRANSLATION_UNAVAILABLE",
                "detail": str(exc),
                "note": "Returned in English. A failed translation must not be guessed at.",
            },
        }

    localised = json.loads(json.dumps(payload))  # deep copy, payload is plain JSON
    source_en: dict[str, str] = {}
    translated_count = 0
    for (path, original), rendered in zip(targets, translations, strict=False):
        if not rendered:
            continue
        _assign(localised, path, rendered)
        source_en[".".join(path)] = original
        translated_count += 1

    localised["localisation"] = {
        "requested": language,
        "language_name": glossary.language_name,
        "native_name": glossary.native_name,
        "status": "TRANSLATED",
        "machine_translated": True,
        "glossary_verified": glossary.verified,
        "provider": provider,
        "fields_translated": translated_count,
        "controlling_language": "en",
        "banner": glossary.ui.get(
            "machine_translation_banner",
            "Machine translation. The English text is the controlling version.",
        ),
        "source_en": source_en,
    }
    return localised


def _parse_numbered(text: str, expected: int) -> list[str]:
    """Pull `[n] translation` lines back into order, tolerating stray output."""
    out: list[str] = [""] * expected
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("["):
            continue
        marker, _, body = line.partition("]")
        try:
            index = int(marker[1:])
        except ValueError:
            continue
        if 0 <= index < expected:
            out[index] = body.strip()
    return out
