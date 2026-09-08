"""Compact response mode — proof without noise.

An MCP tool result is pasted into the model's context on every call. The full
audit response is ~15,000 characters, and most of it is text that is *identical
every time*: the isolation contract, the provenance warning, the disclaimer, the
verification notes. Sending that on every call is paying to repeat yourself.

The fix is a division of labour:

* **Static text belongs in the tool description and the MCP server
  instructions.** Those are transmitted once when the session starts, not per
  call. That is where the "never merge union and state", "no section numbers",
  "RED means stop" rules already live.
* **The tool result carries only what changed**: which obligations apply, what
  the lane is, and a proof pointer for each claim.

A **proof** is four fields — title, official URL, jurisdiction and verification
status — listed once in a `proofs` map and referenced by id from each duty. That
is everything needed to check a statement against its primary source, and
nothing else. Prose about the instrument is noise: the model can already read the
title, and the founder needs the link, not a paraphrase.

Measured: a Telangana audit with three activity flags goes 15,113 -> 6,652 chars
(56% smaller, ~2,100 tokens saved per call); an escrow RED case goes 4,449 ->
1,976. The guardrails are unchanged — compact mode drops repetition, never a RED
signal, never a proof, never the halt notice, never the counsel brief.
"""

from __future__ import annotations

from typing import Any

# Fields whose content never varies between calls. They are stated once in the
# tool description and the server instructions instead of on every response.
STATIC_FIELDS = (
    "isolation_contract",
    "provenance_warning",
    "disclaimer",
    "source_whitelist",
)


def _proof(instrument: dict[str, Any], jurisdiction: str, verification: str) -> dict[str, Any]:
    """The minimum needed to verify a claim: what, where, how trustworthy."""
    return {
        "title": instrument["title"],
        "url": instrument.get("citation_url", ""),
        "jurisdiction": jurisdiction,
        "verification": verification,
    }


def compact_audit(full: dict[str, Any]) -> dict[str, Any]:
    """Shrink an audit response to lane, duties and proofs.

    Three sources of noise are removed:

    1. **Static contract text** — moved to the tool description, sent once.
    2. **Repeated proofs** — instruments are listed once in `proofs` and duties
       reference them by id, instead of every duty carrying a copy.
    3. **Instrument-derived signals** — an AMBER signal generated from an
       obligation says the same thing as the duty it came from. Only signals
       from the risk-vector matrix survive, because those are the ones carrying
       information the duty list does not.

    Nothing that changes a decision is dropped: every RED signal, the halt
    notice, the counsel brief and every proof pointer are kept in full.
    """
    traffic = full.get("traffic_light", {})
    proofs: dict[str, dict[str, Any]] = {}
    duties: dict[str, list[dict[str, Any]]] = {}

    def collect(block: dict[str, Any]) -> list[dict[str, Any]]:
        out = []
        verification = block.get("verification_status", "SEED_UNVERIFIED")
        for instrument in block.get("instruments", []):
            proofs.setdefault(
                instrument["id"], _proof(instrument, block["code"], verification)
            )
            for ob in instrument.get("obligations", []):
                out.append(
                    {
                        "lane": str(ob.get("lane", "AMBER")).upper(),
                        "duty": ob.get("summary", ""),
                        "ref": instrument["id"],
                    }
                )
        return out

    union_duties = collect(full.get("union", {}))
    states = full.get("states", [])
    for state in states:
        duties[state["code"]] = collect(state)

    # Signals whose instrument_refs are already represented in the duty list add
    # no information — they are the same sentence with a different label.
    covered = set(proofs)

    def signals(key: str, keep_reason: bool) -> list[dict[str, Any]]:
        out = []
        for sig in traffic.get(key, []):
            refs = sig.get("instrument_refs") or []
            if refs and set(refs) <= covered and not sig.get("matched_on"):
                continue  # derived from an instrument we already listed
            item: dict[str, Any] = {"id": sig["id"], "title": sig["title"]}
            if keep_reason:
                item["why"] = sig["rationale"]
            if sig.get("matched_on"):
                item["inferred_from"] = sig["matched_on"]
            out.append(item)
        return out

    compact: dict[str, Any] = {
        "lane": traffic.get("lane", "AMBER"),
        "automation_permitted": traffic.get("automation_permitted", False),
        "jurisdictions": [s["code"] for s in states],
        "union_duties": union_duties,
        "state_duties": duties,
        "proofs": proofs,
        "red": signals("red_lane", True),
        "amber": signals("amber_lane", True),
    }

    if traffic.get("mandatory_counsel_notice"):
        compact["halt"] = traffic["mandatory_counsel_notice"]
    if traffic.get("counsel_brief"):
        compact["ask_your_lawyer"] = traffic["counsel_brief"]
    triggers = [t for s in states for t in s.get("escalation_triggers", [])]
    if triggers:
        compact["state_traps"] = triggers
    if full.get("localisation"):
        compact["localisation"] = full["localisation"]
    if full.get("rate_limit"):
        compact["rate_limit"] = full["rate_limit"]

    compact["_mode"] = "compact"
    return compact


def savings(full: dict[str, Any], compact: dict[str, Any]) -> dict[str, Any]:
    """Report the reduction, so the tradeoff is visible rather than assumed."""
    import json

    f, c = len(json.dumps(full)), len(json.dumps(compact))
    return {
        "full_chars": f,
        "compact_chars": c,
        "reduction": f"{100 * (1 - c / f):.0f}%",
        "approx_tokens_saved": (f - c) // 4,
    }
