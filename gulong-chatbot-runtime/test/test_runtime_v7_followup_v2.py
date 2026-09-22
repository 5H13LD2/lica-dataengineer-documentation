"""Safety regressions for the Runtime V7 follow-up v2 contract."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.routers import gulong as gulong_router
from runtime_v7.api_runtime import (
    _delivery_result_means_customer_visible,
    _followup_attempt_status,
    _remember_product_delivery_result,
)
from runtime_v7.channel_renderer import RuntimeV7ChannelRender, _product_presentation_metadata
from runtime_v7.followup_v2 import (
    RuntimeV7FollowupPlanModel,
    build_attempt_record,
    build_followup_case,
    build_followup_plan_messages,
    build_followup_plan_response_model,
    customer_recovery_gate,
    followup_stop_reason,
    load_current_promo_brands,
    parse_followup_plan,
    proactive_followup_gate,
    upsert_attempt,
    validate_and_render_followup,
)


def test_discovery_config_alerts_requires_live_router(monkeypatch):
    monkeypatch.setenv("SERVICE_ENVIRONMENT", "production")
    monkeypatch.delenv("PRICE_CATEGORY_LIVE_ROUTER_FLOW_NAMESPACE", raising=False)
    monkeypatch.delenv("PROMO_LIVE_ROUTER_FLOW_NAMESPACE", raising=False)

    assert gulong_router._discovery_config_alerts() == [
        "interactive_choice_router_not_configured"
    ]

    monkeypatch.setenv("PROMO_LIVE_ROUTER_FLOW_NAMESPACE", "content-live-router")
    assert gulong_router._discovery_config_alerts() == []


def test_discovery_config_alerts_uses_staging_router(monkeypatch):
    monkeypatch.setenv("SERVICE_ENVIRONMENT", "staging")
    monkeypatch.delenv("PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE", raising=False)
    monkeypatch.delenv("PROMO_STAGING_ROUTER_FLOW_NAMESPACE", raising=False)
    monkeypatch.setenv("PROMO_LIVE_ROUTER_FLOW_NAMESPACE", "content-live-router")

    assert gulong_router._discovery_config_alerts() == [
        "interactive_choice_router_not_configured"
    ]

    monkeypatch.setenv("PROMO_STAGING_ROUTER_FLOW_NAMESPACE", "content-stage-router")
    assert gulong_router._discovery_config_alerts() == []


REQUEST_TIME_FIRST = "2026-07-15 10:00:00"
REQUEST_TIME_SECOND = "2026-07-15 21:00:00"


def _messages(*, customer_text: str = "Need 185/65R15 tires po", assistant_text: str = "May options po tayo."):
    return [
        {
            "role": "user",
            "content": customer_text,
            "datetime": "2026-07-15 08:58:00",
            "message_id": "mc_customer_1",
        },
        {
            "role": "assistant",
            "content": assistant_text,
            "datetime": "2026-07-15 09:00:00",
            "message_id": "mc_assistant_1",
        },
    ]


def _delivered_presentation():
    return {
        "presentation_ref": "presentation_1",
        "observation_ref": "obs_1",
        "delivery_status": "success",
        "delivered_at": "2026-07-15 09:00:00",
        "cards": [
            {
                "card_ref": "card_michelin",
                "item_ref": "item_michelin",
                "brand": "MICHELIN",
                "tire_size": "185/65R15",
                "promo_savings_line": "Buy 3 Get 1 FREE",
                "installment_text": "BPI 6mo 0% interest",
                "tire_protection_plan": "Tire Protection Plan (1 Year)",
            },
            {
                "card_ref": "card_apollo",
                "item_ref": "item_apollo",
                "brand": "APOLLO",
                "tire_size": "185/65R15",
                "promo_savings_line": "Buy 3 Get 1 FREE",
            },
            {
                "card_ref": "card_fronway",
                "item_ref": "item_fronway",
                "brand": "FRONWAY",
                "tire_size": "185/65R15",
            },
            {
                "card_ref": "card_bfg",
                "item_ref": "item_bfg",
                "brand": "BFGOODRICH",
                "tire_size": "185/65R15",
                "promo_savings_line": "Buy 3 Get 1 FREE",
            },
        ],
    }


def _state(*, facts=None, followup=None, presentation=True):
    payload = {
        "background_signals": list(
            facts
            or [
                {
                    "key": "tire_size",
                    "value": "185/65R15",
                    "source": "latest_user_message",
                    "message_id": "mc_customer_1",
                }
            ]
        ),
        "product_presentation_history": [_delivered_presentation()] if presentation else [],
    }
    if followup is not None:
        payload["followup"] = followup
    return payload


def _case(*, request_time=REQUEST_TIME_FIRST, state=None, messages=None, cadence="first"):
    return build_followup_case(
        request_time=request_time,
        recent_messages=messages or _messages(),
        v7_state=state or _state(),
        profile_fields={"tags": [], "profile_loaded_at": request_time},
        cadence=cadence,
        promo_brand_result={"status": "ok", "brands": ["MICHELIN", "APOLLO", "VREDESTEIN"]},
    )


def _send_plan(
    *,
    focus="tire_brand",
    benefit_refs=None,
    visible_text="Naka-ready akong tumulong—alin sa mga brand na ito ang gusto mong pag-usapan?",
):
    return {
        "action": "send",
        "customer_stance": "active",
        "focus_field": focus,
        "visible_text": visible_text,
        "benefit_refs": list(benefit_refs or []),
        "reason": "continue the open qualification field",
    }


def test_brand_followup_preserves_every_shown_brand_and_one_cta():
    case = _case()
    benefit = next(item for item in case["allowed_benefits"] if item["kind"] == "buy3get1" and item["brand"] == "MICHELIN")
    visible_text = "May gusto ka bang unahin sa mga naipakita kong brands?"

    result = validate_and_render_followup(
        case,
        _send_plan(benefit_refs=[benefit["benefit_ref"]], visible_text=visible_text),
    )

    assert result["status"] == "valid"
    assert result["message"].split("\n\n")[0] == visible_text
    assert result["message"].count("?") == 1
    assert "Buy 3 Get 1 FREE" in result["message"]


def test_bfg_buy3get1_is_not_allowed_without_promo_authority():
    case = _case()

    buy3_brands = {
        item["brand"] for item in case["allowed_benefits"] if item.get("kind") == "buy3get1"
    }

    assert "MICHELIN" in buy3_brands
    assert "APOLLO" in buy3_brands
    assert "BFGOODRICH" not in buy3_brands


def test_explicit_presentation_expiry_blocks_product_and_benefit_evidence():
    presentation = _delivered_presentation()
    presentation["expires_at"] = "2026-07-15 09:30:00"
    state = _state()
    state["product_presentation_history"] = [presentation]

    case = _case(state=state)

    assert case["product_presentations"] == []
    assert case["presented_brands"] == []
    assert case["allowed_benefits"] == []


def test_cumulative_benefits_are_not_rendered_as_choices():
    case = _case()
    refs = [
        item["benefit_ref"]
        for item in case["allowed_benefits"]
        if item["brand"] == "MICHELIN" and item["kind"] in {"buy3get1", "tire_protection_plan"}
    ]

    result = validate_and_render_followup(case, _send_plan(benefit_refs=refs[:2]))

    assert result["status"] == "valid"
    assert "Buy 3 Get 1 FREE" in result["message"]
    assert "Tire Protection Plan" in result["message"]
    assert "or Tire Protection Plan" not in result["message"]
    assert "pili" not in result["message"].casefold()


def test_visible_text_is_delivered_verbatim_with_varied_natural_wording():
    case = _case(state=_state(presentation=False))
    variants = (
        "Para mas maitugma natin sa area ninyo, anong city o barangay po kayo?",
        "Saan po kayo banda para ma-guide ko kayo sa susunod na step?",
    )

    for visible_text in variants:
        result = validate_and_render_followup(case, _send_plan(focus="location", visible_text=visible_text))

        assert result["status"] == "valid"
        assert result["message"] == visible_text


def test_visible_text_is_not_phrase_classified_or_rewritten():
    case = _case(state=_state(presentation=False))
    visible_text = "Naiintindihan ko ang pagtatanong ninyo—pa-send ng city o barangay para ma-check natin."

    result = validate_and_render_followup(case, _send_plan(focus="location", visible_text=visible_text))

    assert result["status"] == "valid"
    assert result["message"] == visible_text


def test_visible_text_requires_nonempty_bounded_content():
    case = _case(state=_state(presentation=False))

    empty = validate_and_render_followup(case, _send_plan(focus="location", visible_text="  "))
    too_long = validate_and_render_followup(case, _send_plan(focus="location", visible_text="a" * 361))

    assert empty["validation_reasons"] == ["visible_text_empty"]
    assert too_long["validation_reasons"] == ["visible_text_too_long"]


def test_send_conflicting_with_deferred_stance_fails_closed():
    case = _case(state=_state(presentation=False))
    plan = _send_plan(focus="location")
    plan["customer_stance"] = "deferred"

    result = validate_and_render_followup(case, plan)

    assert result["status"] == "invalid"
    assert "send_conflicts_with_deferred_stance" in result["validation_reasons"]


def test_present_typed_field_is_not_a_valid_next_step_candidate():
    case = _case()

    result = validate_and_render_followup(
        case,
        _send_plan(focus="tire_size", visible_text="Pwede mo bang i-confirm ulit ang tire size?"),
    )

    assert result["status"] == "invalid"
    assert "focus_field_not_candidate" in result["validation_reasons"]


def test_exact_allowed_benefit_lines_are_appended_without_synthesized_cta():
    case = _case()
    benefit = next(item for item in case["allowed_benefits"] if item["kind"] == "buy3get1" and item["brand"] == "MICHELIN")
    visible_text = "May gusto ka bang unahin sa mga naipakita kong brands?"

    result = validate_and_render_followup(
        case,
        _send_plan(benefit_refs=[benefit["benefit_ref"]], visible_text=visible_text),
    )

    assert result["status"] == "valid"
    assert result["message"] == f"{visible_text}\n\n{benefit['customer_text']}"


def test_customer_brand_preference_removes_brand_as_followup_focus():
    state = _state(
        facts=[
            {"key": "tire_size", "value": "185/65R15", "source": "latest_user_message", "message_id": "mc_customer_1"},
            {"key": "required_brands", "value": ["YOKOHAMA"], "source": "latest_user_message", "message_id": "mc_customer_1"},
        ]
    )
    case = _case(state=state, messages=_messages(customer_text="Yokohama lang preferred ko po"))

    assert case["customer_brand_preference"] == "YOKOHAMA"
    assert "tire_brand" not in case["next_step_candidates"]
    assert {
        item["brand"]
        for item in case["allowed_benefits"]
        if item.get("brand")
    } <= {"YOKOHAMA"}
    result = validate_and_render_followup(case, _send_plan(focus="tire_brand"))
    assert result["status"] == "invalid"


def test_raw_customer_transcript_does_not_recover_lead_facts_without_typed_signals():
    state = {"background_signals": [], "product_presentation_history": [_delivered_presentation()]}
    messages = _messages(customer_text="Michelin 175 65 R14 po, contact ko 0917 123 4567")

    case = _case(state=state, messages=messages)

    assert case["customer_facts"] == {}
    assert "0917" not in build_followup_plan_messages(case)[1]["content"]
    assert {"tire_size", "tire_brand", "contact_number"}.issubset(case["lead_qualification"]["missing"])


def test_raw_customer_brand_text_is_not_promoted_to_preference():
    state = {"background_signals": [], "product_presentation_history": [_delivered_presentation()]}

    case = _case(state=state, messages=_messages(customer_text="Ayoko ng Michelin, ibang option po"))

    assert "tire_brand" not in case["customer_facts"]
    assert "tire_brand" in case["lead_qualification"]["missing"]


def test_raw_customer_brand_text_does_not_override_missing_typed_signal():
    state = {"background_signals": [], "product_presentation_history": [_delivered_presentation()]}

    case = _case(state=state, messages=_messages(customer_text="Fronway po ang gusto ko"))

    assert "tire_brand" not in case["customer_facts"]
    assert "tire_brand" in case["lead_qualification"]["missing"]


def test_typed_signal_is_not_text_matched_against_raw_customer_message():
    state = _state(
        facts=[
            {
                "key": "location",
                "value": "Cebu City",
                "source": "latest_user_message",
                "message_id": "mc_customer_1",
            }
        ],
        presentation=False,
    )

    case = _case(state=state, messages=_messages(customer_text="Need tires po"))

    assert case["customer_facts"]["location"]["value"] == "Cebu City"
    assert "location" not in case["lead_qualification"]["missing"]


def test_typed_signal_without_transcript_link_prevents_reasking():
    state = _state(
        facts=[
            {"key": "location", "value": "Cebu City", "source": "latest_user_message"},
        ],
        presentation=False,
    )
    case = _case(state=state, messages=_messages(customer_text="Need tires po"))

    assert case["customer_facts"]["location"]["value"] == "Cebu City"
    assert "location" not in case["lead_qualification"]["missing"]


def test_typed_signal_preserves_its_message_reference_without_text_matching():
    state = _state(
        facts=[
            {
                "key": "location",
                "value": "Quezon City",
                "source": "latest_user_message",
                "metadata": {"evidence": "QC po"},
            },
        ],
        presentation=False,
    )
    case = _case(state=state, messages=_messages(customer_text="QC po"))

    assert case["customer_facts"]["location"]["value"] == "Quezon City"
    assert case["customer_facts"]["location"]["evidence_message_id"] == ""


def test_typed_signal_ignores_punctuation_only_raw_evidence_text():
    state = _state(
        facts=[
            {
                "key": "location",
                "value": "Quezon City",
                "source": "latest_user_message",
                "metadata": {"evidence": "..."},
            },
        ],
        presentation=False,
    )
    case = _case(state=state, messages=_messages(customer_text="Need tires po"))

    assert case["customer_facts"]["location"]["value"] == "Quezon City"


def test_human_agent_signal_is_not_treated_as_customer_stated_fact():
    state = _state(
        facts=[
            {
                "key": "required_brands",
                "value": ["MICHELIN"],
                "source": "human_agent_history",
                "message_id": "mc_customer_1",
            },
        ],
        presentation=False,
    )
    case = _case(state=state, messages=_messages(customer_text="Need tires po"))

    assert "tire_brand" not in case["customer_facts"]


def test_successful_brand_send_rotates_second_cadence_to_location():
    first = _case()
    assert first["next_step_candidates"] == ["location", "tire_brand", "contact_number"]
    validation = validate_and_render_followup(first, _send_plan())
    attempt = build_attempt_record(
        case=first,
        plan=_send_plan(),
        validation=validation,
        status="sent",
        request_id="req_first",
        delivery_result={"status": "success"},
    )
    followup = upsert_attempt({}, attempt)
    second_state = _state(followup=followup)

    second = _case(request_time=REQUEST_TIME_SECOND, state=second_state, cadence="second")

    assert "tire_brand" not in second["next_step_candidates"]
    assert second["next_step_candidates"] == ["location", "contact_number"]
    assert proactive_followup_gate(second)["status"] == "allow"


def test_non_lead_focus_requires_selected_product_from_active_delivered_presentation():
    customer_text = "Proceed po sa 185/65R15 Michelin, Quezon City, 09171234567."
    facts = [
        {"key": "tire_size", "value": "185/65R15", "source": "latest_user_message", "message_id": "mc_customer_1"},
        {"key": "location", "value": "Quezon City", "source": "latest_user_message", "message_id": "mc_customer_1"},
        {"key": "required_brands", "value": ["MICHELIN"], "source": "latest_user_message", "message_id": "mc_customer_1"},
        {"key": "contact_number", "value": "09171234567", "source": "latest_user_message", "message_id": "mc_customer_1"},
    ]
    grounded_state = _state(facts=facts)
    grounded_state["latest_selected_product_context"] = {
        "product_presentation_ref": "presentation_1",
        "product_card_ref": "card_michelin",
    }
    stale_state = _state(facts=facts)
    stale_state["latest_selected_product_context"] = {
        "product_presentation_ref": "old_presentation",
        "product_card_ref": "old_card",
    }

    grounded = _case(state=grounded_state, messages=_messages(customer_text=customer_text))
    stale = _case(state=stale_state, messages=_messages(customer_text=customer_text))

    assert grounded["selected_product_ref"] == "presentation_1"
    assert grounded["next_step_candidates"] == ["installation_partner", "payment_option"]
    assert stale["selected_product_ref"] == ""
    assert stale["next_step_candidates"] == []


def test_failed_brand_attempt_does_not_consume_focus_after_cooldown(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_FOLLOWUP_RETRY_COOLDOWN_MINUTES", "15")
    first = _case()
    validation = validate_and_render_followup(first, _send_plan())
    attempt = build_attempt_record(
        case=first,
        plan=_send_plan(),
        validation=validation,
        status="delivery_failed",
        request_id="req_failed",
        delivery_result={"status": "error"},
    )
    attempt["updated_at"] = "2026-07-15 09:10:00"
    followup = upsert_attempt({}, attempt)

    retried = _case(state=_state(followup=followup))

    assert "tire_brand" in retried["next_step_candidates"]
    assert proactive_followup_gate(retried)["status"] == "allow"


def test_validation_failure_uses_retry_cooldown_without_consuming_focus(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_FOLLOWUP_RETRY_COOLDOWN_MINUTES", "15")
    first = _case()
    validation = {"status": "invalid", "message": "", "focus_field": "tire_brand", "validation_reasons": ["test"]}
    attempt = build_attempt_record(
        case=first,
        plan=_send_plan(),
        validation=validation,
        status="validation_failed",
        request_id="req_invalid",
    )
    attempt["updated_at"] = "2026-07-15 09:10:00"
    followup = upsert_attempt({}, attempt)

    retried = _case(state=_state(followup=followup))

    assert "tire_brand" in retried["next_step_candidates"]
    assert proactive_followup_gate(retried)["status"] == "allow"


def test_early_trigger_does_not_consume_first_cadence():
    early = _case(request_time="2026-07-15 09:10:00")
    gate = proactive_followup_gate(early)
    decision = {"action": "suppress", "customer_stance": "unclear", "reason": gate["reason"]}
    delivery = {"status": "suppressed", "reason": gate["reason"]}
    status = _followup_attempt_status(
        sent=False,
        decision=decision,
        validation={},
        delivery_result=delivery,
    )
    attempt = build_attempt_record(
        case=early,
        plan=decision,
        validation={},
        status=status,
        request_id="req_early",
        delivery_result=delivery,
    )
    state = _state(followup=upsert_attempt({}, attempt))

    eligible = _case(request_time=REQUEST_TIME_FIRST, state=state)

    assert gate["reason"] == "outside_first_followup_window"
    assert status == "evaluated"
    assert attempt["reason"] == "outside_first_followup_window"
    assert proactive_followup_gate(eligible)["status"] == "allow"


def test_legacy_transient_suppression_does_not_consume_first_cadence():
    early = _case(request_time="2026-07-15 09:10:00")
    gate = proactive_followup_gate(early)
    decision = {"action": "suppress", "customer_stance": "unclear", "reason": gate["reason"]}
    delivery = {"status": "suppressed", "reason": gate["reason"]}
    attempt = build_attempt_record(
        case=early,
        plan=decision,
        validation={},
        status="suppressed",
        request_id="req_legacy_early",
        delivery_result=delivery,
    )
    state = _state(followup=upsert_attempt({}, attempt))

    eligible = _case(request_time=REQUEST_TIME_FIRST, state=state)

    assert proactive_followup_gate(eligible)["status"] == "allow"


def test_unknown_delivery_reconciles_from_refreshed_transcript_hash():
    first = _case()
    plan = _send_plan(benefit_refs=[first["allowed_benefits"][0]["benefit_ref"]])
    validation = validate_and_render_followup(first, plan)
    attempt = build_attempt_record(
        case=first,
        plan=plan,
        validation=validation,
        status="delivery_unknown",
        request_id="req_unknown",
        delivery_result={"status": "unknown"},
    )
    followup = upsert_attempt({}, attempt)
    messages = [
        *_messages(),
        {
            "role": "assistant",
            "content": validation["message"],
            "datetime": "2026-07-15 09:00:00",
            "message_id": "mc_assistant_reconciled",
        },
    ]

    reconciled = _case(state=_state(followup=followup), messages=messages)

    assert reconciled["prior_attempts"][-1]["status"] == "sent"
    assert reconciled["prior_attempts"][-1]["reconciled_from_transcript"] is True
    assert "tire_brand" not in reconciled["next_step_candidates"]
    assert proactive_followup_gate(reconciled)["reason"] == "cadence_already_sent"


def test_interrupted_sending_attempt_becomes_unknown_until_transcript_reconciliation():
    first = _case()
    plan = _send_plan(benefit_refs=[first["allowed_benefits"][0]["benefit_ref"]])
    validation = validate_and_render_followup(first, plan)
    attempt = build_attempt_record(
        case=first,
        plan=plan,
        validation=validation,
        status="sending",
        request_id="req_interrupted",
    )
    followup = upsert_attempt({}, attempt)

    interrupted = _case(state=_state(followup=followup))

    prior = interrupted["prior_attempts"][-1]
    assert prior["status"] == "delivery_unknown"
    assert prior["reclassified_from_interrupted_sending"] is True
    assert prior["reconciliation_pending_persist"] is True
    assert proactive_followup_gate(interrupted)["reason"] == "cadence_delivery_unresolved"


def test_deferred_stance_blocks_first_and_second_but_not_nurture_window():
    first = _case()
    validation = validate_and_render_followup(
        first,
        {
            "action": "defer",
            "customer_stance": "deferred",
            "focus_field": None,
            "visible_text": "",
            "benefit_refs": [],
            "reason": "customer said just inquiry and matagal pa",
        },
    )
    attempt = build_attempt_record(
        case=first,
        plan={"action": "defer", "customer_stance": "deferred"},
        validation=validation,
        status="deferred",
        request_id="req_defer",
    )
    state = _state(followup=upsert_attempt({}, attempt))

    second = _case(request_time=REQUEST_TIME_SECOND, state=state, cadence="second")
    nurture = _case(request_time="2026-07-17 10:00:00", state=state, cadence="nurture")

    assert proactive_followup_gate(second)["reason"] == "customer_stance_deferred"
    assert proactive_followup_gate(nurture)["status"] == "allow"


def test_stop_tags_and_human_takeover_suppress_before_model():
    assert followup_stop_reason(
        profile_fields={"tags": [{"name": "Stop Followup"}]},
        recent_messages=_messages(),
    ) == "stop_tag:stop_followup"
    assert followup_stop_reason(
        profile_fields={"tags": [{"name": "Stop Chatbot"}]},
        recent_messages=_messages(),
    ) == "stop_tag:stop_chatbot"
    assert followup_stop_reason(
        profile_fields={"tags": []},
        recent_messages=[*_messages(), {"role": "human_agent", "content": "Ako na po mag-assist.", "datetime": "2026-07-15 09:30:00"}],
    ) == "human_agent_message_after_latest_customer"


def test_dynamic_prompt_contains_only_case_evidence_and_one_system_message():
    messages = build_followup_plan_messages(_case())

    assert [item["role"] for item in messages] == ["system", "user"]
    assert "Typed next-step candidates" in messages[1]["content"]
    assert "Recent conversation" in messages[1]["content"]
    assert "active_working_memory" not in messages[1]["content"]
    assert "background_signals" not in messages[1]["content"]


def test_structured_response_schema_is_stable_across_case_candidate_sets():
    case = _case()
    model = build_followup_plan_response_model(case)
    schema = model.model_json_schema()

    focus_schema = schema["properties"]["focus_field"]
    allowed_values = next(item["enum"] for item in focus_schema["anyOf"] if "enum" in item)
    assert set(allowed_values) == {
        "tire_size",
        "location",
        "tire_brand",
        "contact_number",
        "installation_partner",
        "schedule",
        "payment_option",
    }


def test_structured_response_schema_does_not_encode_case_specific_candidates():
    brand_case = _case()
    location_case = dict(brand_case)
    location_case["next_step_candidates"] = ["location", "contact_number"]

    brand_model = build_followup_plan_response_model(brand_case)
    location_model = build_followup_plan_response_model(location_case)

    assert brand_model is location_model
    assert brand_model is RuntimeV7FollowupPlanModel


def test_none_benefit_sentinel_is_normalized_to_empty_list():
    plan = parse_followup_plan(
        '{"action":"send","customer_stance":"active","focus_field":"tire_size",'
        '"visible_text":"Pwede mo bang i-share ang tire size?","benefit_refs":["none"],"reason":"open"}'
    )

    assert plan["parse_status"] == "valid"
    assert plan["benefit_refs"] == []


def test_raw_motorcycle_wording_does_not_suppress_before_model():
    case = _case(messages=_messages(customer_text="Dunlop Roadsmart IV motorcycle tire po"))

    assert case["domain_status"] == "unknown"
    assert proactive_followup_gate(case)["status"] == "allow"


def test_evidenced_typed_domain_assessment_suppresses_before_model():
    state = _state()
    state["domain_assessment"] = {
        "status": "unsupported_or_unresolved",
        "evidence_ref": "domain_assessment_1",
    }
    case = _case(state=state, messages=_messages(customer_text="Need tires po"))

    assert case["domain_status"] == "unsupported_or_unresolved"
    assert proactive_followup_gate(case)["reason"] == "unsupported_or_unresolved_domain"


def test_raw_progression_words_do_not_create_secondary_next_step_candidates():
    facts = [
        {"key": "tire_size", "value": "185/65R15", "source": "latest_user_message"},
        {"key": "location", "value": "Quezon City", "source": "latest_user_message"},
        {"key": "required_brands", "value": ["MICHELIN"], "source": "latest_user_message"},
        {"key": "contact_number", "value": "09171234567", "source": "latest_user_message"},
    ]
    case = _case(
        state=_state(facts=facts, presentation=False),
        messages=_messages(customer_text="Proceed na tayo, gusto ko mag-book at magpa-install."),
    )

    assert case["next_step_candidates"] == []
    assert proactive_followup_gate(case)["reason"] == "no_typed_next_step_candidates"


def test_customer_last_recovery_is_limited_to_24_hours():
    messages = [
        {
            "role": "user",
            "content": "Available pa po?",
            "datetime": "2026-07-15 08:00:00",
            "message_id": "mc_customer_recovery",
        }
    ]
    fresh = build_followup_case(
        request_time="2026-07-16 07:00:00",
        recent_messages=messages,
        v7_state=_state(presentation=False),
        profile_fields={"tags": []},
        cadence="first",
    )
    stale = build_followup_case(
        request_time="2026-07-16 09:00:01",
        recent_messages=messages,
        v7_state=_state(presentation=False),
        profile_fields={"tags": []},
        cadence="first",
    )

    assert customer_recovery_gate(fresh)["status"] == "allow"
    assert customer_recovery_gate(stale)["reason"] == "customer_message_recovery_stale"


def test_validated_submitted_order_suppresses_proactive_qualification_followup():
    state = _state()
    state["latest_submitted_order_context"] = {
        "order_id": "order_redacted",
        "order_payload_ref": "order_payload_1",
        "submitted_at": "2026-07-15 08:59:00",
    }

    case = _case(state=state)

    assert case["completion"]["is_complete"] is True
    assert proactive_followup_gate(case)["reason"] == "conversation_already_converted"


def test_old_submitted_order_does_not_suppress_a_new_active_segment():
    state = _state()
    state["latest_submitted_order_context"] = {
        "order_id": "old_order_redacted",
        "order_payload_ref": "old_order_payload",
        "submitted_at": "2026-07-01 08:00:00",
    }

    case = _case(state=state)

    assert case["completion"]["is_complete"] is False
    assert proactive_followup_gate(case)["status"] == "allow"


def test_product_presentation_ledger_records_exact_cards_only_on_success():
    surfaces = [
        (
            "product",
            {
                "tool": "product_search",
                "full_result": {"presentation_ref": "presentation_1", "observation_ref": "obs_1"},
                "cards": deepcopy(_delivered_presentation()["cards"]),
            },
        )
    ]
    presentations = _product_presentation_metadata(surfaces)
    harness = SimpleNamespace(latest_product_presentation={}, product_presentation_history=[])
    rendered = RuntimeV7ChannelRender(
        response={},
        content_messages=[
            {
                "type": "cards",
                "elements": [
                    {
                        "title": "MICHELIN 185/65R15",
                        "buttons": [
                            {
                                "actions": [
                                    {
                                        "value": "ps1|presentation_1|card_michelin"
                                    }
                                ]
                            }
                        ],
                    }
                ],
            }
        ],
        product_presentations=presentations,
    )

    _remember_product_delivery_result(harness, rendered, {"status": "success", "status_code": 200})

    assert harness.product_presentation_history[-1]["delivery_status"] == "success"
    assert harness.product_presentation_history[-1]["observation_ref"] == "obs_1"
    assert [card["brand"] for card in harness.product_presentation_history[-1]["cards"]] == [
        "MICHELIN",
        "APOLLO",
        "FRONWAY",
        "BFGOODRICH",
    ]


def test_product_presentation_ledger_ignores_metadata_not_rendered_to_customer():
    surfaces = [
        (
            "product",
            {
                "tool": "product_search",
                "full_result": {
                    "presentation_ref": "presentation_hidden",
                    "observation_ref": "obs_hidden",
                },
                "cards": deepcopy(_delivered_presentation()["cards"]),
            },
        )
    ]
    harness = SimpleNamespace(
        latest_product_presentation={},
        product_presentation_history=[],
    )
    rendered = RuntimeV7ChannelRender(
        response={"bubble1": "Choose your city below."},
        content_messages=[
            {
                "type": "cards",
                "elements": [
                    {
                        "title": "Cainta",
                        "buttons": [
                            {
                                "actions": [
                                    {
                                        "value": "lc1|loc_1|city|PH-RIZ|PH-RIZ-005"
                                    }
                                ]
                            }
                        ],
                    }
                ],
            }
        ],
        product_presentations=_product_presentation_metadata(surfaces),
    )

    _remember_product_delivery_result(
        harness,
        rendered,
        {"status": "success", "status_code": 200},
    )

    assert harness.product_presentation_history == []
    assert harness.latest_product_presentation == {}


def test_product_presentation_ledger_records_only_rendered_inclusions():
    surfaces = [
        (
            "product",
            {
                "tool": "product_search",
                "full_result": {"presentation_ref": "presentation_1", "observation_ref": "obs_1"},
                "cards": deepcopy(_delivered_presentation()["cards"]),
            },
        )
    ]

    with_inclusions = _product_presentation_metadata(surfaces, include_product_inclusions=True)
    without_inclusions = _product_presentation_metadata(surfaces, include_product_inclusions=False)

    assert "Install with our authorized Installation Partners" in with_inclusions[0]["inclusions_text"]
    assert "inclusions_text" not in without_inclusions[0]


def test_followup_can_render_delivered_installation_inclusions_as_cumulative_benefit():
    presentation = _delivered_presentation()
    presentation["inclusions_text"] = (
        "Warranty and inclusions:\n"
        "- Install with our authorized Installation Partners and get:\n"
        "  - FREE installation\n"
        "  - FREE mounting & balancing\n"
        "  - FREE weights & tire valves"
    )
    state = _state()
    state["product_presentation_history"] = [presentation]
    case = _case(state=state)
    promo_ref = next(item["benefit_ref"] for item in case["allowed_benefits"] if item["kind"] == "buy3get1")
    inclusions_ref = next(
        item["benefit_ref"] for item in case["allowed_benefits"] if item["kind"] == "installation_inclusions"
    )

    result = validate_and_render_followup(case, _send_plan(benefit_refs=[promo_ref, inclusions_ref]))

    assert result["status"] == "valid"
    assert "Buy 3 Get 1 FREE" in result["message"]
    assert "FREE installation" in result["message"]
    assert "or FREE installation" not in result["message"]
    assert result["message"].count("?") == 1


def test_return_only_is_never_customer_visible():
    assert _delivery_result_means_customer_visible({"status": "skipped", "reason": "return_only"}) is False
    assert _delivery_result_means_customer_visible({"status": "suppressed"}) is False
    assert _delivery_result_means_customer_visible({"status": "success"}) is True


def test_promo_brand_authority_fails_closed_when_api_raises():
    class RaisingHTTPClient:
        def get_json(self, _path):
            raise TimeoutError("promo endpoint timed out")

    result = load_current_promo_brands(http_client=RaisingHTTPClient())

    assert result["status"] == "unavailable"
    assert result["brands"] == []
    assert result["reason"] == "promo_brand_lookup_failed"
    assert result["error_type"] == "TimeoutError"


def test_followup_endpoint_rejects_missing_and_wrong_bearer_token(monkeypatch):
    monkeypatch.setenv("FOLLOWUP_WEBHOOK_TOKEN", "correct-secret")
    client = TestClient(create_app())
    body = {"user_id": "trial-user", "idempotency_key": "trigger-1", "cadence": "first"}

    missing = client.post("/gulong/v7/followup", json=body)
    wrong = client.post("/gulong/v7/followup", json=body, headers={"Authorization": "Bearer wrong"})

    assert missing.status_code == 401
    assert wrong.status_code == 401


def test_followup_endpoint_fails_closed_when_server_token_missing(monkeypatch):
    monkeypatch.delenv("FOLLOWUP_WEBHOOK_TOKEN", raising=False)
    client = TestClient(create_app())

    result = client.post(
        "/gulong/v7/followup/tester",
        json={"user_id": "trial-user", "idempotency_key": "trigger-2", "cadence": "first"},
    )

    assert result.status_code == 503


def test_followup_send_admission_is_server_side_and_allowlisted(monkeypatch):
    monkeypatch.setenv("FOLLOWUP_SEND_ENABLED", "1")
    monkeypatch.setenv("FOLLOWUP_SEND_USER_ALLOWLIST", "trial-user")
    monkeypatch.setenv("FOLLOWUP_SEND_CANARY_PERCENT", "100")

    assert gulong_router._followup_send_enabled_for_user("trial-user") is True
    assert gulong_router._followup_send_enabled_for_user("other-user") is False

    monkeypatch.setenv("FOLLOWUP_SEND_USER_ALLOWLIST", "")
    monkeypatch.setenv("FOLLOWUP_SEND_CANARY_PERCENT", "100")
    assert gulong_router._followup_send_enabled_for_user("trial-user") is True
    assert gulong_router._followup_send_enabled_for_user("other-user") is True

    monkeypatch.setenv("FOLLOWUP_SEND_ENABLED", "0")
    assert gulong_router._followup_send_enabled_for_user("trial-user") is False


def test_followup_auto_cadence_resolves_shared_manychat_timer():
    current = "2026-07-26T12:00:00+08:00"

    first, first_error = gulong_router._resolve_followup_cadence(
        "auto",
        "2026-07-26T11:00:00+08:00",
        current_time=current,
    )
    second, second_error = gulong_router._resolve_followup_cadence(
        "auto",
        "2026-07-26T00:00:00+08:00",
        current_time=current,
    )

    assert (first, first_error) == ("first", None)
    assert (second, second_error) == ("second", None)


def test_followup_auto_cadence_rejects_invalid_event_timestamp():
    cadence, error = gulong_router._resolve_followup_cadence(
        "auto",
        "not-a-timestamp",
        current_time="2026-07-26T12:00:00+08:00",
    )

    assert cadence is None
    assert error == "invalid_channel_event_ts_for_auto_cadence"


def test_followup_auto_cadence_namespaces_idempotency_by_resolved_layer(monkeypatch):
    captured = {}

    class InProgressDecision:
        action = "in_progress"
        request_id = "req_existing"
        replay_payload = None

    class Gateway:
        def begin(self, **kwargs):
            captured.update(kwargs)
            return InProgressDecision()

    monkeypatch.setattr(
        gulong_router,
        "build_idempotency_gateway",
        lambda bu: Gateway(),
    )
    event_time = datetime.now().astimezone() - timedelta(hours=1)
    payload = gulong_router.FollowupV7RequestPayload(
        user_id="trial-user",
        channel_event_id="last-interaction-event",
        channel_event_ts=event_time.isoformat(),
        idempotency_key="last-interaction-event",
        cadence="auto",
    )

    result = asyncio.run(gulong_router._handle_followup(payload, tester=False))

    assert result["status"] == "in_progress"
    assert captured["idempotency_key"] == "last-interaction-event:first"
    assert captured["payload"]["cadence"] == "first"


def test_followup_route_replays_completed_http_retry_without_runtime_call(monkeypatch):
    captured = {}

    class ReplayDecision:
        action = "replay"
        request_id = "req_original"
        replay_payload = {"status": "evaluated", "request_id": "req_original"}

    class ReplayGateway:
        def begin(self, **kwargs):
            captured.update(kwargs)
            return ReplayDecision()

    class UnexpectedService:
        def __init__(self, **_kwargs):
            raise AssertionError("runtime must not run for an idempotent replay")

    monkeypatch.setattr(gulong_router, "build_idempotency_gateway", lambda bu: ReplayGateway())
    monkeypatch.setattr(gulong_router, "RuntimeV7APIService", UnexpectedService)

    payload = gulong_router.FollowupV7RequestPayload(
        user_id="trial-user",
        idempotency_key="same-trigger",
        cadence="first",
    )
    result = asyncio.run(gulong_router._handle_followup(payload, tester=True))

    assert result["status"] == "evaluated"
    assert result["request_id"] == "req_original"
    assert captured["message_id"] == "followup_tester:same-trigger"
    assert captured["idempotency_key"] == "followup_tester:same-trigger"


def test_followup_route_blocks_concurrent_duplicate_while_first_is_running(monkeypatch):
    class InProgressDecision:
        action = "in_progress"
        request_id = "req_first"
        replay_payload = None

    class InProgressGateway:
        def begin(self, **_kwargs):
            return InProgressDecision()

    class UnexpectedService:
        def __init__(self, **_kwargs):
            raise AssertionError("runtime must not run for an in-progress duplicate")

    monkeypatch.setattr(gulong_router, "build_idempotency_gateway", lambda bu: InProgressGateway())
    monkeypatch.setattr(gulong_router, "RuntimeV7APIService", UnexpectedService)

    payload = gulong_router.FollowupV7RequestPayload(
        user_id="trial-user",
        idempotency_key="concurrent-trigger",
        channel_event_id="event-concurrent",
        channel_event_ts="2026-07-20T09:00:00+08:00",
        cadence="second",
    )
    result = asyncio.run(gulong_router._handle_followup(payload, tester=False))

    assert result["status"] == "in_progress"
    assert result["message"] == "duplicate_request_processing"


def test_production_followup_requires_external_event_identity_before_runtime_io(monkeypatch):
    def unexpected_idempotency_gateway(*_args, **_kwargs):
        raise AssertionError("idempotency I/O must not run")

    monkeypatch.setattr(gulong_router, "build_idempotency_gateway", unexpected_idempotency_gateway)

    payload = gulong_router.FollowupV7RequestPayload(user_id="trial-user")
    result = asyncio.run(gulong_router._handle_followup(payload, tester=False))

    assert result["status"] == "error"
    assert result["message"] == "missing_required_followup_fields"
    assert result["missing_fields"] == ["channel_event_id", "channel_event_ts", "idempotency_key", "cadence"]


def test_production_followup_requires_user_id_not_legacy_channel_user_id(monkeypatch):
    monkeypatch.setenv("FOLLOWUP_WEBHOOK_TOKEN", "correct-secret")

    def unexpected_idempotency_gateway(*_args, **_kwargs):
        raise AssertionError("idempotency I/O must not run")

    monkeypatch.setattr(gulong_router, "build_idempotency_gateway", unexpected_idempotency_gateway)
    client = TestClient(create_app())
    result = client.post(
        "/gulong/v7/followup",
        headers={"Authorization": "Bearer correct-secret"},
        json={
            "channel_user_id": "legacy-user",
            "channel_event_id": "event-legacy",
            "channel_event_ts": "2026-07-20T09:00:00+08:00",
            "idempotency_key": "trigger-legacy",
            "cadence": "first",
        },
    ).json()

    assert result == {"status": "error", "message": "user_id is required."}


def test_july_regression_corpus_has_required_size_and_rollback_cases():
    fixture = Path(__file__).parent / "fixtures" / "runtime_v7_followup_july_corpus.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))

    assert payload["case_count"] >= 95
    cases = payload["cases"]
    assert len(cases) == payload["case_count"]
    assert sum("rolled_back_release" in case["scenario_tags"] for case in cases) == 9
    assert sum("safety_matrix" in case["scenario_tags"] for case in cases) >= 15
    assert sum("july_live_transcript" in case["scenario_tags"] for case in cases) >= 71
    assert all(len(case["messages"]) >= 2 for case in cases)
    assert all("expected_invariants" in case for case in cases)
