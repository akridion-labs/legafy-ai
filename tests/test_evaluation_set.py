"""The evaluation set in evals/ must stay true, not just well-formed.

An eval file whose answers have quietly drifted is worse than no eval file: it
scores a regression as a pass. So each answer is re-derived from the live tools
here. If Kerala's profession-tax instrument is ever renamed, or a seventh state
is added, this fails and the eval file gets updated deliberately.
"""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from app.mcp.server import LOCAL_TENANT
from app.sources.store import CITABLE_AUTHORITY_FLOOR
from app.tools import TOOLS_BY_NAME

EVAL_FILE = Path(__file__).resolve().parents[1] / "evals" / "legafy_mcp_eval.xml"


def call(name: str, payload: dict) -> dict:
    return asyncio.run(
        TOOLS_BY_NAME[name].handler(payload, request_id="eval", tenant=LOCAL_TENANT)
    )


@pytest.fixture(scope="module")
def answers() -> list[str]:
    pairs = ET.parse(EVAL_FILE).getroot().findall("qa_pair")
    assert len(pairs) == 10, "the mcp-builder guidance asks for ten questions"
    for pair in pairs:
        assert (pair.findtext("question") or "").strip()
        assert (pair.findtext("answer") or "").strip()
    return [(p.findtext("answer") or "").strip() for p in pairs]


def test_escrow_marketplace_in_kerala_is_red(answers):
    result = call(
        "execute_regional_compliance_audit",
        {
            "business_concept": (
                "A marketplace for local tutors that holds student payments in escrow "
                "until a session finishes."
            ),
            "industry_vertical": "Marketplace",
            "state_location": "Kerala",
            "activity_flags": [
                "employs_persons",
                "has_workplace_in_state",
                "holds_customer_funds",
            ],
        },
    )
    assert result["lane"] == answers[0]


def test_kerala_profession_tax_instrument_id(answers):
    result = call(
        "execute_regional_compliance_audit",
        {
            "business_concept": "A payroll tool for small clinics with staff rostering.",
            "industry_vertical": "B2B SaaS",
            "state_location": "Kerala",
            "activity_flags": ["employs_persons", "has_workplace_in_state"],
        },
    )
    # Compact is the default shape a real client sees: instruments appear as
    # keys in `proofs`, each pointing at the official page behind it.
    ids = set(result["proofs"])
    assert answers[1] in ids
    # The whole point of the answer: no dedicated state Act was invented for it.
    assert not any(i.startswith("KL-PT-ACT") for i in ids)


def test_the_welfare_fund_title_still_carries_no_year(answers):
    result = call(
        "execute_regional_compliance_audit",
        {
            "business_concept": "A payroll tool for small clinics with staff rostering.",
            "industry_vertical": "B2B SaaS",
            "state_location": "Kerala",
            "activity_flags": ["employs_persons", "has_workplace_in_state"],
        },
    )
    titles = {p["title"] for p in result["proofs"].values()}
    assert answers[2] in titles
    assert not any(char.isdigit() for char in answers[2])


def test_state_count(answers):
    codes = {
        j["code"]
        for j in call("list_supported_jurisdictions", {})["jurisdictions"]
        if j["code"] != "IN-CENTRAL"
    }
    assert len(codes) == int(answers[3])


def test_unmapped_state_refuses(answers):
    from app.compliance.registry import UnknownJurisdictionError

    with pytest.raises(UnknownJurisdictionError):
        call(
            "execute_regional_compliance_audit",
            {
                "business_concept": "A bakery chain.",
                "industry_vertical": "Retail",
                "state_location": "Goa",
                "activity_flags": ["has_workplace_in_state"],
            },
        )
    assert "refuses to approximate" in answers[4]


def test_citable_floor(answers):
    assert float(answers[5]) == CITABLE_AUTHORITY_FLOOR
    result = call("search_legal_sources", {"query": "shops and establishments"})
    assert str(CITABLE_AUTHORITY_FLOOR) in result["usage_note"]


def test_court_tier_settled_statuses(answers):
    result = call(
        "execute_regional_compliance_audit",
        {
            "business_concept": "A SaaS product that stores customer personal data.",
            "industry_vertical": "B2B SaaS",
            "state_location": "Telangana",
            "activity_flags": ["processes_personal_data"],
        },
    )
    questions = result["judicial"]
    by_status: dict[str, list[str]] = {}
    for q in questions:
        by_status.setdefault(q["settled"], []).append(q["question"].lower())

    assert any("data-protection" in q for q in by_status.get(answers[6], []))
    assert any("non-compete" in q for q in by_status.get(answers[7], []))
    # No authority is ever asserted — the reason the court tier is safe to ship.
    assert all(not q.get("authorities") for q in questions)


def test_penalties_are_never_shipped_verified(answers):
    result = call(
        "execute_regional_compliance_audit",
        {
            "business_concept": "A payroll tool for small clinics.",
            "industry_vertical": "B2B SaaS",
            "state_location": "Telangana",
            "activity_flags": ["employs_persons", "has_workplace_in_state"],
            "detail": "full",
        },
    )
    statuses = {
        i["penalty_status"]
        for block in (result["states"][0]["instruments"], result["union"]["instruments"])
        for i in block
    }
    assert statuses == {answers[8]}


def test_available_checks_tool(answers):
    result = call(answers[9], {})
    assert result["success"] is True
    assert "available_checks" in result
