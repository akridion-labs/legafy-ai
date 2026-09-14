"""The hard cap, and the weekly court-feed tip-off channel.

These two tests guard the boundary of the product. The first says what Legafy
refuses to do at all; the second says that what it learns from an aggregator
can never be quoted as law.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.compliance.scope import check_scope
from app.mcp.server import LOCAL_TENANT
from app.sources import judicial_feeds as jf
from app.tools import TOOLS_BY_NAME


def call(name: str, payload: dict) -> dict:
    return asyncio.run(
        TOOLS_BY_NAME[name].handler(payload, request_id="t", tenant=LOCAL_TENANT)
    )


# -- the hard cap ------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "An FIR has been filed against me, what should I do",
        "I need help with an anticipatory bail application",
        "how do I get the case quashed",
        "a POCSO complaint was made and it is a false case",
        "my chargesheet says I was present at the scene",
    ],
)
def test_criminal_matters_are_refused(text):
    refusal = check_scope(text)
    assert refusal is not None, f"criminal matter slipped through: {text!r}"
    assert refusal.category == "criminal"


@pytest.mark.parametrize(
    "text",
    [
        "my wife filed a 498a case",
        "dowry harassment allegations in my divorce",
        "I want child custody after the separation",
        "she filed a maintenance petition",
        "domestic violence proceedings against me",
    ],
)
def test_family_matters_are_refused(text):
    refusal = check_scope(text)
    assert refusal is not None, f"family matter slipped through: {text!r}"
    assert refusal.category == "family"


@pytest.mark.parametrize(
    "text",
    [
        # The whole reason the carve-outs are checked first: every one of these
        # is a real employer duty, and refusing them would refuse the product.
        "We need a POSH Act policy and an Internal Committee for our 40 staff",
        "background verification process for new engineering hires",
        "a fraud detection feature for our payments product",
        "KYC onboarding for merchants on our marketplace",
        # And the false positives that a naive word list would produce.
        "our firm is confirming the firmware release",
        "a marketplace for local tutors holding fees in escrow",
        "penalty clauses in our vendor contracts",
        "we want to prosecute our trademark registration faster",
    ],
)
def test_corporate_questions_are_not_refused(text):
    assert check_scope(text) is None, f"false refusal on a corporate question: {text!r}"


def test_the_refusal_leaks_no_substance():
    payload = check_scope("my wife filed a 498a dowry case against me").as_dict()
    assert payload["status"] == "OUT_OF_SCOPE"
    assert payload["success"] is False
    # None of the things a real answer would carry.
    for leaked in ("lane", "obligations", "proofs", "traffic_light", "playbooks"):
        assert leaked not in payload, f"a refusal must not carry {leaked!r}"
    assert "STOP" in payload["instruction"]
    assert "draft anything" in payload["instruction"].lower()
    # It must still point somewhere useful rather than just closing the door.
    assert "Legal Services Authorit" in payload["where_to_get_help"]


def test_every_free_text_tool_enforces_the_cap():
    """Not just the audit. A refused question gets asked again another way."""
    criminal = "help me respond to the FIR filed against me"

    audit = call(
        "execute_regional_compliance_audit",
        {
            "business_concept": criminal,
            "industry_vertical": "Personal",
            "state_location": "Telangana",
        },
    )
    assert audit["status"] == "OUT_OF_SCOPE"

    search = call("search_legal_sources", {"query": criminal})
    assert search["status"] == "OUT_OF_SCOPE"

    draft = call(
        "generate_legal_structure",
        {
            "project_name": "Reply",
            "target_state": "Telangana",
            "framework_type": "founders_agreement",
            "business_concept": criminal,
            "industry_vertical": "Personal",
        },
    )
    assert draft["status"] == "OUT_OF_SCOPE"


# -- the judicial feed channel ----------------------------------------------


SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Kerala High Court</title>
  <item>
    <title>ACME Pvt Ltd vs State — profession tax assessment by the municipality</title>
    <link>https://indiankanoon.org/doc/123456/</link>
    <pubDate>Mon, 08 Sep 2026 10:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Some unrelated land dispute between two neighbours</title>
    <link>https://indiankanoon.org/doc/999999/</link>
    <pubDate>Mon, 08 Sep 2026 11:00:00 GMT</pubDate>
  </item>
</channel></rss>"""

EMPTY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Kerala High Court</title></channel></rss>"""


def test_an_empty_feed_parses_to_no_items_rather_than_failing():
    """Observed live: the Kerala HC feed is valid RSS with zero items."""
    assert jf.parse_feed(EMPTY_FEED) == []


def test_only_titles_touching_a_tracked_instrument_become_leads():
    items = jf.parse_feed(SAMPLE_FEED)
    assert len(items) == 2
    kept = [i for i in items if jf.relevant_terms(i["title"])]
    assert len(kept) == 1
    assert "profession tax" in kept[0]["title"].lower()


def test_every_configured_feed_host_is_the_allowed_one():
    feeds = jf.load_feeds()
    assert feeds, "the feed list is empty"
    for feed in feeds:
        assert feed["url"].startswith("https://indiankanoon.org/feeds/latest/")
        assert feed["url"].endswith("/"), f"{feed['feed_id']}: missing trailing slash"


def test_a_feed_pointed_at_another_host_is_refused(tmp_path):
    """A data-file edit must not be able to aim the crawler somewhere new."""
    path = tmp_path / "feeds.json"
    path.write_text(
        json.dumps(
            {
                "feeds": [
                    {
                        "feed_id": "rogue",
                        "court": "Somewhere",
                        "url": "https://example.com/feeds/latest/x/",
                        "jurisdiction": "IN-KL",
                        "cabinet": "corporate",
                    }
                ]
            }
        )
    )
    with pytest.raises(jf.UnverifiedFeedHost):
        jf.load_feeds(path)


def test_a_lead_carries_its_own_uncitability():
    lead = jf.Lead(
        feed_id="ik-kerala",
        court="Kerala High Court",
        jurisdiction="IN-KL",
        cabinet="corporate",
        title="x vs y",
        url="https://indiankanoon.org/doc/1/",
        published=None,
        matched_terms=["gst"],
        seen_at="2026-09-14T00:00:00+00:00",
    )
    # The point: copy this record anywhere and it still says it cannot be quoted.
    assert lead.citable is False
    assert lead.authority_tier == "aggregator"


def test_leads_reach_the_reviewer_inbox(tmp_path, monkeypatch):
    leads_file = tmp_path / "judicial_leads.jsonl"
    report = {
        "leads": [
            {
                "feed_id": "ik-kerala",
                "court": "Kerala High Court",
                "jurisdiction": "IN-KL",
                "cabinet": "corporate",
                "title": "profession tax assessment",
                "url": "https://indiankanoon.org/doc/1/",
                "published": None,
                "matched_terms": ["profession tax"],
                "seen_at": "2026-09-14T00:00:00+00:00",
                "authority_tier": "aggregator",
                "citable": False,
                "status": "UNREAD",
            }
        ]
    }
    assert jf.write_leads(report, leads_file) == 1
    monkeypatch.setattr("app.tools.LEADS_FILE", leads_file)

    queue = call("list_source_review_queue", {"limit": 5})
    assert queue["judicial_leads"][0]["court"] == "Kerala High Court"
    assert queue["judicial_leads"][0]["citable"] is False
    # And the note must tell a reader what tier they are looking at.
    assert "below the 0.80 citable floor" in queue["note"]


def test_jurisdiction_filter_holds_for_leads(tmp_path, monkeypatch):
    leads_file = tmp_path / "leads.jsonl"
    rows = [
        {"jurisdiction": "IN-KL", "court": "Kerala High Court", "seen_at": "2026-09-14"},
        {"jurisdiction": "IN-TG", "court": "Telangana High Court", "seen_at": "2026-09-13"},
    ]
    leads_file.write_text("\n".join(json.dumps(r) for r in rows))
    kerala = jf.read_leads(leads_file, jurisdiction="IN-KL")
    assert [r["jurisdiction"] for r in kerala] == ["IN-KL"]
