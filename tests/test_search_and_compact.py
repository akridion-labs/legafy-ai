"""Query understanding, source index, corpus privacy and compact mode."""

from __future__ import annotations

import pytest

from app.compact import compact_audit, savings
from app.compliance.obligations import build_obligation_ledger
from app.search.corpus import QuestionCorpus, scrub
from app.search.intent import PhraseTrie, analyse, build_fts_query, expand_terms
from app.sources.store import (
    SourceDoc,
    SourceStore,
    change_magnitude,
    review_priority,
)


# --- trie ------------------------------------------------------------------
def test_trie_takes_the_longest_match():
    trie = PhraseTrie()
    trie.insert("andhra", {"code": "WRONG"})
    trie.insert("andhra pradesh", {"code": "IN-AP"})
    found = trie.extract("we are hiring in andhra pradesh next month")
    assert found == [("andhra pradesh", {"code": "IN-AP"})]


def test_trie_finds_nothing_in_unrelated_text():
    trie = PhraseTrie()
    trie.insert("telangana", {"code": "IN-TG"})
    assert trie.extract("a recipe for lemon rice") == []


# --- intent and tone -------------------------------------------------------
def test_intent_and_jurisdiction_extraction():
    a = analyse("Can I hire 12 people in Hyderabad without registering anything?")
    assert a.intent == "screen_idea"
    assert a.jurisdictions == ["IN-TG"]


def test_tone_is_detected_but_never_moves_the_verdict():
    worried = analyse("I'm really worried, we already hired staff in Telangana, are we in trouble?")
    calm = analyse("Considering hiring staff in Telangana at some point")
    assert worried.tone == "worried"
    assert calm.tone == "exploratory"
    # The contract that matters: tone is delivery only.
    assert worried.tone_affects_verdict is False
    assert calm.tone_affects_verdict is False
    assert worried.delivery_guidance != calm.delivery_guidance


def test_adversarial_phrasing_is_flagged_not_refused():
    a = analyse("is there a loophole to avoid professional tax in Telangana")
    assert a.tone == "adversarial"
    assert "do not soften" in a.delivery_guidance.lower()


def test_missing_jurisdiction_is_surfaced_not_guessed():
    a = analyse("what licences do I need to open an office?")
    assert a.needs_jurisdiction is True
    assert a.jurisdictions == []


def test_query_expansion_bridges_founder_and_government_vocabulary():
    assert "professional tax" in expand_terms("what payroll taxes apply")
    assert "establishment" in expand_terms("opening a shop")


def test_fts_query_quotes_multiword_entities():
    a = analyse("Telangana Shops and Establishments Act, 1988 registration")
    assert '"telangana shops and establishments act 1988"' in build_fts_query("x", a)


# --- source store ----------------------------------------------------------
def _doc(body: str, tier: str = "state_portal", jur: str = "IN-TG") -> SourceDoc:
    return SourceDoc(
        doc_id="tg-labour", source_id="tg-labour", url="https://labour.telangana.gov.in",
        title="Telangana Labour", authority_tier=tier, jurisdiction=jur,
        instrument_ids=["TG-SE-1988"], body=body,
    )


def test_unchanged_document_is_not_requeued(tmp_path):
    store = SourceStore(tmp_path / "s.db")
    body = "registration of shops and establishments in telangana " * 20
    assert store.upsert(_doc(body))["status"] == "NEW"
    assert store.upsert(_doc(body))["status"] == "UNCHANGED"
    assert len(store.pending_reviews()) == 1


def test_change_is_detected_and_magnitude_reflects_size(tmp_path):
    store = SourceStore(tmp_path / "s.db")
    store.upsert(_doc("registration of shops in telangana " * 20))
    small = store.upsert(_doc("registration of shops in telangana " * 20 + "minor addition here"))
    assert small["status"] == "CHANGED"
    assert 0 < small["change_magnitude"] < 0.5


def test_jurisdiction_is_a_hard_filter_in_search(tmp_path):
    store = SourceStore(tmp_path / "s.db")
    store.upsert(_doc("professional tax registration slabs", jur="IN-TG"))
    ap = SourceDoc(
        doc_id="ap-ct", source_id="ap-ct", url="https://apct.gov.in", title="AP CT",
        authority_tier="state_portal", jurisdiction="IN-AP",
        instrument_ids=["AP-PT-1987"], body="professional tax registration slabs",
    )
    store.upsert(ap)
    hits = store.search("professional tax", jurisdiction="IN-TG")
    assert {h["jurisdiction"] for h in hits} == {"IN-TG"}, "AP leaked into a TG search"


def test_low_authority_sources_are_not_citable(tmp_path):
    store = SourceStore(tmp_path / "s.db")
    store.upsert(_doc("shops and establishments registration guide", tier="aggregator"))
    assert store.search("establishments") == []
    assert len(store.search("establishments", citable_only=False)) == 1


def test_review_priority_orders_by_impact():
    gazette = review_priority(authority_weight=1.0, magnitude=0.8, instrument_hits=2,
                              exposure=50, age_days=0)
    portal_typo = review_priority(authority_weight=0.85, magnitude=0.02, instrument_hits=0,
                                  exposure=0, age_days=0)
    assert gazette > portal_typo * 10


def test_change_magnitude_ignores_whitespace_reflow():
    assert change_magnitude("the rules apply here", "the   rules\napply    here") == 0.0


# --- corpus privacy --------------------------------------------------------
def test_scrub_removes_mechanical_identifiers():
    dirty = "Email me at deepak@example.com or 9876543210, PAN ABCDE1234F, https://x.com, ₹5,00,000"
    clean, hits = scrub(dirty)
    for leaked in ("deepak@example.com", "9876543210", "ABCDE1234F", "https://x.com", "5,00,000"):
        assert leaked not in clean
    assert len(hits) >= 4


def test_corpus_stores_no_identity(tmp_path):
    corpus = QuestionCorpus(tmp_path / "c.db")
    corpus.record(
        question="A payroll tool for clinics in Hyderabad, contact me at a@b.com",
        intent="screen_idea", tone="neutral", jurisdictions=["IN-TG"], lane="AMBER",
    )
    row = corpus.export_training_rows()  # inside cooling-off, so empty
    assert row == []
    columns = {r[1] for r in corpus._conn.execute("PRAGMA table_info(questions)")}
    for forbidden in ("tenant", "token", "token_id", "ip", "organization", "user"):
        assert forbidden not in columns, f"corpus schema grew an identity column: {forbidden}"
    raw = (tmp_path / "c.db").read_bytes()
    assert b"a@b.com" not in raw


def test_corpus_deduplicates_identical_questions(tmp_path):
    corpus = QuestionCorpus(tmp_path / "c.db")
    q = "Do I need to register an establishment in Telangana for eight staff"
    assert corpus.record(question=q, intent="screen_idea", tone="neutral") is not None
    assert corpus.record(question=q, intent="screen_idea", tone="neutral") is None
    assert corpus.taxonomy()["total"] == 1


# --- compact mode ----------------------------------------------------------
FULL = {
    "traffic_light": {
        "lane": "RED",
        "automation_permitted": False,
        "headline": "Halt",
        "red_lane": [{"id": "payment_escrow", "title": "Escrow", "rationale": "Because funds.",
                      "matched_on": ["escrow"], "instrument_refs": []}],
        "amber_lane": [{"id": "TG-SE-1988:reg", "title": "Registration", "rationale": "Dup.",
                        "matched_on": [], "instrument_refs": ["TG-SE-1988"]}],
        "green_lane": [],
        "mandatory_counsel_notice": "Stop and retain counsel.",
        "counsel_brief": ["Ask about payment aggregator authorisation."],
    },
    "union": {"code": "IN-CENTRAL", "verification_status": "SEED_UNVERIFIED", "instruments": []},
    "states": [{
        "code": "IN-TG", "verification_status": "SEED_UNVERIFIED",
        "escalation_triggers": ["Cross-border payroll"],
        "instruments": [{"id": "TG-SE-1988", "title": "Telangana Shops and Establishments Act, 1988",
                         "citation_url": "https://labour.telangana.gov.in",
                         "obligations": [{"key": "reg", "summary": "Register.", "lane": "GREEN"}]}],
    }],
    "isolation_contract": "x" * 400,
    "provenance_warning": "y" * 400,
    "disclaimer": "z" * 400,
    "source_whitelist": ["https://labour.telangana.gov.in"] * 10,
}
# The audit always attaches the ledger; the fixture is the same shape it is built from.
FULL["legal_obligations"] = build_obligation_ledger(FULL)


def test_compact_keeps_every_decision_critical_field():
    c = compact_audit(FULL)
    assert c["lane"] == "RED"
    assert c["automation_permitted"] is False
    assert c["halt"] == "Stop and retain counsel."
    assert c["ask_your_lawyer"] == ["Ask about payment aggregator authorisation."]
    assert c["red"][0]["id"] == "payment_escrow"
    assert c["red"][0]["why"]           # RED reasoning is never dropped
    assert c["state_traps"] == ["Cross-border payroll"]


def test_compact_dedupes_proofs_and_instrument_derived_signals():
    c = compact_audit(FULL)
    # The instrument appears once in proofs, referenced by id from the duty.
    assert list(c["proofs"]) == ["TG-SE-1988"]
    assert c["obligations"][0]["ref"] == "TG-SE-1988"
    # The AMBER signal restating that duty is gone.
    assert c["amber"] == []


def test_compact_is_materially_smaller():
    c = compact_audit(FULL)
    s = savings(FULL, c)
    assert s["compact_chars"] < s["full_chars"] * 0.6


@pytest.mark.parametrize("field", ["isolation_contract", "provenance_warning", "disclaimer"])
def test_static_text_is_not_repeated_per_call(field):
    assert field not in compact_audit(FULL)


# -- progressive disclosure: index -> expand one branch ----------------------


def _audit(**kw):
    import asyncio

    from app.mcp.server import LOCAL_TENANT
    from app.tools import TOOLS_BY_NAME

    payload = {
        "business_concept": (
            "A marketplace for local tutors that holds student payments in escrow "
            "until the session finishes."
        ),
        "industry_vertical": "Marketplace",
        "state_location": "Kerala",
    }
    payload.update(kw)
    return asyncio.run(
        TOOLS_BY_NAME["execute_regional_compliance_audit"].handler(
            payload, request_id="t", tenant=LOCAL_TENANT
        )
    )


def test_an_index_never_hides_a_red_light():
    """The whole safety question for progressive disclosure.

    An index is allowed to withhold duties. It is never allowed to withhold the
    verdict, a RED signal, the halt notice or the counsel brief — invariant 8:
    a token budget is not a safety dial.
    """
    index = _audit(detail="index")
    compact = _audit()

    assert index["lane"] == compact["lane"] == "RED"
    assert index["automation_permitted"] is False
    assert index["red"] == compact["red"], "a RED signal was dropped by indexing"
    assert index["halt"] == compact["halt"]
    assert index["ask_your_lawyer"] == compact["ask_your_lawyer"]
    assert index["amber"] == compact["amber"]


def test_an_index_withholds_the_bodies_and_says_how_to_get_them():
    index = _audit(detail="index")
    assert index["_mode"] == "index"
    for heavy in ("obligations", "playbooks", "judicial", "research_checklist"):
        assert heavy not in index, f"{heavy} should not be in an index"
    assert index["index"]["domains"], "the index must say which domains exist"
    # Self-describing: the model must not need the docs to expand.
    assert "domains=['<name>']" in index["index"]["expand"]
    assert "NEVER hides a red light" in index["index"]["expand"]


def test_the_index_counts_match_what_expansion_returns():
    """Progressive disclosure must not lose a duty between the two calls."""
    index = _audit(detail="index")
    counted = index["index"]["domains"]
    everything = _audit()

    from collections import Counter

    actual = Counter(ob.get("playbook") or "general" for ob in everything["obligations"])
    assert {k: v["obligations"] for k, v in counted.items()} == dict(actual)

    # And expanding every domain returns every duty the unfiltered call does.
    expanded = _audit(domains=sorted(counted))
    assert len(expanded["obligations"]) == len(everything["obligations"])


def test_a_narrowed_answer_announces_that_it_is_narrowed():
    """A caller who forgot the filter must not read this as the whole picture."""
    one = _audit(domains=["labour"])
    assert one["expanded_domains"] == ["labour"]
    assert "not sent" in one["partial"]
    assert all(ob["playbook"] == "labour" for ob in one["obligations"])
    assert set(one["playbooks"]) == {"labour"}
    # Proofs follow the narrowing, or the saving is spent carrying all 25.
    assert set(one["proofs"]) <= {ob["ref"] for ob in one["obligations"]}
    # The lane still cannot be softened by asking for less.
    assert one["lane"] == "RED"
    assert one["halt"]


def test_indexing_is_worth_doing():
    """If the saving ever stops being large, the added parameter is not earning."""
    import json

    index = len(json.dumps(_audit(detail="index")))
    compact = len(json.dumps(_audit()))
    assert index < compact * 0.4, f"index {index} vs compact {compact} — saving too small"
