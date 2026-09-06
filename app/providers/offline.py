"""Deterministic, no-network provider.

Used for CI, air-gapped runs and `make smoke`. It drafts generic contract
prose from the clause list in the prompt, seeded by the prompt hash so output
is reproducible. It never emits a section number, penalty or Act title — the
anti-hallucination invariant holds even for the stub.
"""

from __future__ import annotations

import hashlib
import random
import re
import time

from app.providers.base import CompletionRequest, CompletionResult, LLMProvider

CLAUSE_RE = re.compile(r"^\s*[-*]?\s*([0-9]+\.[0-9]+)\s+(.+?)\s*$", re.MULTILINE)

OPENERS = (
    "The Parties acknowledge and agree that",
    "For the purposes of this Agreement, the Parties record that",
    "Subject to the remaining provisions of this Agreement,",
    "Each Party undertakes to the other that",
    "It is expressly agreed between the Parties that",
)
BODIES = (
    "the obligations set out in this clause are continuing obligations and survive any change in the composition, ownership or control of either Party",
    "no waiver of any right under this clause is effective unless recorded in writing and signed by an authorised signatory of the waiving Party",
    "the arrangements described in this clause are to be performed in good faith and with reasonable commercial diligence",
    "any notice required under this clause is validly given when delivered to the address recorded in the schedule to this Agreement",
    "the Parties will keep complete and accurate records sufficient to evidence performance of this clause",
    "where a conflict arises between this clause and a schedule, the operative provisions of this clause prevail",
    "each Party bears its own costs of complying with this clause unless the Agreement expressly provides otherwise",
    "the rights conferred by this clause are cumulative and do not exclude any other right available to the Parties",
)
TAILS = (
    "This provision is drafting scaffolding and requires review by qualified counsel before execution.",
    "The commercial thresholds referenced here are left for the Parties to settle with their advisers.",
    "Defined terms used in this clause carry the meanings given in the Definitions clause.",
    "The Parties will review this clause upon any material change to the operating model it describes.",
)


class OfflineProvider(LLMProvider):
    name = "offline"

    def is_configured(self) -> bool:
        return True

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        started = time.perf_counter()
        rng = random.Random(hashlib.sha256(request.prompt.encode()).hexdigest())
        clauses = CLAUSE_RE.findall(request.prompt) or [("1.1", "General Provisions")]

        # ponytail: 0.75 words/token is close enough to budget prose; exactness buys nothing.
        word_budget = int(request.max_tokens * 0.75)
        # Honour an explicit word target in the prompt, the way a real model would —
        # otherwise the stub always drafts to its ceiling and a 20-page target
        # comes back at 40+.
        if target := re.search(r"approximately (\d+) words", request.prompt):
            word_budget = min(word_budget, int(target.group(1)))
        per_clause = max(60, word_budget // len(clauses))

        parts: list[str] = []
        words = 0
        truncated = False
        for cid, heading in clauses:
            parts.append(f"### {cid} {heading}\n")
            n = 0
            i = 1
            while n < per_clause:
                sentence = (
                    f"{cid}.{i} {rng.choice(OPENERS)} {rng.choice(BODIES)}. "
                    f"{rng.choice(TAILS)}\n"
                )
                if words + len(sentence.split()) > word_budget:
                    parts.append(sentence.split(".")[0])  # deliberate mid-sentence cut
                    truncated = True
                    break
                parts.append(sentence)
                n += len(sentence.split())
                words += len(sentence.split())
                i += 1
            if truncated:
                break
            parts.append("\n")

        text = "".join(parts)
        return CompletionResult(
            text=text,
            provider=self.name,
            model="legafy-offline-drafter",
            finish_reason="max_tokens" if truncated else "stop",
            output_tokens=int(words / 0.75),
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
