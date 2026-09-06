"""Tests for the traffic-light safety matrix."""

from __future__ import annotations

from app.compliance.traffic_light import TRAFFIC_LIGHT
from app.models.schemas import Lane


def test_escrow_payments_concept_yields_red_and_blocks_automation():
    verdict = TRAFFIC_LIGHT.evaluate(
        business_concept=(
            "A B2B SaaS platform for freelancers where we hold customer funds in escrow "
            "and release them once a milestone is approved."
        ),
        industry_vertical="fintech",
        activity_flags={"operates_escrow", "holds_customer_funds"},
        jurisdiction_codes=["IN-TG"],
    )
    assert verdict.lane == Lane.RED
    assert verdict.automation_permitted is False
    assert verdict.mandatory_counsel_notice is not None
    assert any(signal.id == "payment_escrow" for signal in verdict.red)


def test_plain_mutual_nda_with_no_risky_flags_yields_green():
    verdict = TRAFFIC_LIGHT.evaluate(
        business_concept=(
            "A mutual non-disclosure agreement between two startups exploring a "
            "potential product partnership before any commercial terms are discussed."
        ),
        industry_vertical="B2B SaaS",
        activity_flags=set(),
        jurisdiction_codes=["IN-TG"],
        framework_type="mutual_nda",
    )
    assert verdict.lane == Lane.GREEN
    assert verdict.automation_permitted is True
    assert verdict.red == []
    assert verdict.amber == []
    assert verdict.green


def test_two_states_trigger_red_via_multi_state_gateway():
    verdict = TRAFFIC_LIGHT.evaluate(
        business_concept="A plain consulting agreement for software delivery services.",
        industry_vertical="B2B SaaS",
        activity_flags=set(),
        jurisdiction_codes=["IN-TG", "IN-AP"],
    )
    assert verdict.lane == Lane.RED
    assert verdict.automation_permitted is False
    assert any(signal.id == "multi_state_gateway" for signal in verdict.red)


def test_keyword_only_hit_without_declared_flag_still_escalates_to_red():
    verdict = TRAFFIC_LIGHT.evaluate(
        business_concept=(
            "A marketplace app where we hold customer funds in escrow until delivery "
            "is confirmed by both sides."
        ),
        industry_vertical="marketplace",
        activity_flags=set(),  # deliberately NOT declared
        jurisdiction_codes=["IN-TG"],
    )
    assert verdict.lane == Lane.RED
    assert verdict.automation_permitted is False
    matching = [signal for signal in verdict.red if signal.id == "payment_escrow"]
    assert matching, "expected a payment_escrow signal inferred purely from the keyword hit"
    signal = matching[0]
    assert "inferred from the description" in signal.rationale
    assert "escrow" in signal.matched_on


def test_render_markdown_contains_traffic_light_header():
    verdict = TRAFFIC_LIGHT.evaluate(
        business_concept="A plain consulting agreement for software delivery services.",
        industry_vertical="B2B SaaS",
        activity_flags=set(),
        jurisdiction_codes=["IN-TG"],
    )
    markdown = verdict.render_markdown()
    assert "Traffic-Light" in markdown


def test_red_lane_always_sets_automation_permitted_false_and_names_signals():
    verdict = TRAFFIC_LIGHT.evaluate(
        business_concept="A lending product offering short-term credit lines to gig workers.",
        industry_vertical="fintech",
        activity_flags={"lending_or_credit"},
        jurisdiction_codes=["IN-TG"],
    )
    assert verdict.lane == Lane.RED
    assert verdict.automation_permitted is False
    assert verdict.mandatory_counsel_notice is not None
    assert "Lending or credit" in verdict.mandatory_counsel_notice
    assert verdict.counsel_brief, "expected at least one counsel-brief question"


def test_amber_lane_permits_automation_with_recorded_caveat():
    verdict = TRAFFIC_LIGHT.evaluate(
        business_concept=(
            "A staffing platform that employs full-time employees and also engages "
            "contract labour for seasonal peaks."
        ),
        industry_vertical="staffing",
        activity_flags={"employs_persons", "engages_contract_labour"},
        jurisdiction_codes=["IN-TG"],
    )
    assert verdict.lane == Lane.AMBER
    assert verdict.automation_permitted is True
    assert verdict.mandatory_counsel_notice is None
    assert verdict.amber


def test_under_specified_concept_fails_closed_to_amber_or_worse():
    verdict = TRAFFIC_LIGHT.evaluate(
        business_concept="   ",
        industry_vertical="unknown",
        activity_flags=set(),
        jurisdiction_codes=["IN-TG"],
    )
    assert verdict.lane in (Lane.AMBER, Lane.RED)
    assert any(signal.id == "under_specified_assessment" for signal in verdict.amber + verdict.red)
