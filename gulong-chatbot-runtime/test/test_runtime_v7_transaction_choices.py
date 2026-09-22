from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

from runtime_v7 import api_runtime
from runtime_v7.api_runtime import (
    RuntimeV7APIRequest,
    _attach_checkout_choice_surface,
    _apply_payment_policy_truth_guard,
    _apply_promo_provider_truth_guard,
    _apply_submit_authorization_truth_guard,
    _customer_payment_method_label,
    _remember_choice_action_attempt,
    _remember_choice_delivery_result,
    _remember_promo_action_attempt,
    _record_commercial_payment_claims,
    _semantic_customer_payment_query_plans,
)
from runtime_v7.channel_renderer import render_turn_for_channel
from runtime_v7.commercial_claim_contract import (
    dedupe_payment_policies,
    payment_claim,
    payment_claim_contract_violations,
    payment_policies_from_tool_results,
)
from runtime_v7.choice_actions import (
    build_payment_method_choice_token,
    build_payment_option_choice_token,
    build_schedule_choice_token,
    parse_payment_method_choice_token,
    parse_payment_option_choice_token,
    parse_schedule_choice_token,
)
from runtime_v7.fulfillment_aliases import resolve_fulfillment_alias
from runtime_v7.product_observations import ProductToolHarness
from runtime_v7.order_state import _signal_has_validated_checkout_choice_ref
from runtime_v7.order_canonicalization import local_canonical_payment_method
from runtime_v7.runtime_harness import (
    FINAL_COMPOSER_SYSTEM_PROMPT,
    RuntimeV7Harness,
    _apply_validated_choice_signal_boundaries,
    _build_final_composer_messages,
    _complete_model_client,
    _final_composer_commercial_answer_contract,
    _final_composer_draft_text,
    _final_composer_required_commercial_claims,
    _final_composer_temperature,
    _final_composer_tool_result_payload,
    _final_composer_voice_contract_violations,
    _no_tool_order_progression_requires_composer,
    _ready_payment_request_retry_context,
)
from runtime_v7.service_tools import RuntimeV7ServiceTools
from runtime_v7.transaction_choices import (
    _payment_method_choice_description,
    build_payment_method_surface,
    build_payment_option_surface,
    build_schedule_choice_surface,
)


class EmptyModel:
    def complete(self, **_kwargs):
        return {}


def test_tracked_promo_action_keeps_presentation_card_surface_and_choice_refs():
    harness = RuntimeV7Harness(
        model_client=EmptyModel(),
        tools=ProductToolHarness(),
    )
    harness.latest_promo_presentation = {
        "catalog_version_id": "catalog-20260811",
        "presentation_ref": "promo_gallery_visible_1",
        "card_refs": ["promo-card-1"],
        "delivery_status": "success",
    }
    request = RuntimeV7APIRequest(
        user_id="tracked-promo-user",
        user_text="promo action",
        message_id="promo-event-1",
        channel_event_id="promo-event-1",
        idempotency_key="promo-idem-1",
        channel_event_ts="2026-08-11T11:00:00+08:00",
        flow_context={
            "promo_action_context": {
                "status": "valid",
                "catalog_version_id": "catalog-20260811",
                "card_id": "promo-card-1",
                "action": "check_price",
                "promo": {
                    "promo_id": "promo-1",
                    "promo_ref": "promo:promo-1",
                },
            }
        },
    )

    _remember_promo_action_attempt(harness, request)

    action = harness.latest_promo_action
    assert action["presentation_ref"] == "promo_gallery_visible_1"
    assert action["card_ref"] == "promo-card-1"
    assert action["surface_type"] == "promo_gallery"
    assert action["surface_ref"] == "promo_gallery_visible_1"
    assert action["choice_type"] == "promo_action"
    assert action["choice_ref"] == "promo_action:promo:promo-1:check_price"
    assert request.flow_context["promo_action_tracking_context"] == {
        key: action[key]
        for key in (
            "surface_type",
            "surface_ref",
            "presentation_ref",
            "presentation_ref_source",
            "card_ref",
            "choice_type",
            "choice_ref",
            "promo_id",
            "promo_ref",
            "action",
            "validation_status",
        )
    }


def _slot_result(*, include_afternoon: bool = True) -> dict:
    slots = [
        {
            "slot_ref": "slot_20260729_0830",
            "date": "2026-07-29",
            "time_text": "8:30 AM",
            "start": "2026-07-29T08:30:00+08:00",
        },
        {
            "slot_ref": "slot_20260729_0900",
            "date": "2026-07-29",
            "time_text": "9:00 AM",
            "start": "2026-07-29T09:00:00+08:00",
        },
        {
            "slot_ref": "slot_20260729_1100",
            "date": "2026-07-29",
            "time_text": "11:00 AM",
            "start": "2026-07-29T11:00:00+08:00",
        },
    ]
    if include_afternoon:
        slots.extend(
            [
                {
                    "slot_ref": "slot_20260729_1400",
                    "date": "2026-07-29",
                    "time_text": "2:00 PM",
                    "start": "2026-07-29T14:00:00+08:00",
                },
                {
                    "slot_ref": "slot_20260729_1700",
                    "date": "2026-07-29",
                    "time_text": "5:00 PM",
                    "start": "2026-07-29T17:00:00+08:00",
                },
            ]
        )
    return {
        "status": "ok",
        "presentation_ref": "pres_slots_20260729",
        "observation_ref": "svc_slots_20260729",
        "query_basis": {"customer_location_label": "San Pedro, Laguna"},
        "slot_groups": [
            {
                "installation_partner_ref": "partner_san_pedro",
                "service_location_ref": "location_san_pedro",
                "branch_id": "17",
                "name": "SLICK FERN TIRES AND SERVICES OPC",
                "address": "Binan, Laguna",
                "municipality_city": "San Pedro, Laguna",
                "slots": slots,
            }
        ],
        "installation_partner_cards": [
            {
                "card_ref": "partner_card_17",
                "card_text": "Installation slots near San Pedro, Laguna",
            }
        ],
        "service_policy_notes": [
            {"id": "no_walkin_setup", "text": "No walk-in setup."}
        ],
        "card_runtime_insert": True,
    }


def _slot_turn(*, include_afternoon: bool = True) -> dict:
    result = _slot_result(include_afternoon=include_afternoon)
    return {
        "assistant_text": "Choose the schedule that works for you.",
        "tool_results": [
            {
                "name": "find_installation_slots",
                "result": {
                    "status": "ok",
                    "presentation_ref": result["presentation_ref"],
                },
                "full_result": result,
            }
        ],
    }


def test_transaction_choice_tokens_round_trip() -> None:
    builders_and_parsers = (
        (build_schedule_choice_token, parse_schedule_choice_token, "ss1"),
        (
            build_payment_option_choice_token,
            parse_payment_option_choice_token,
            "po1",
        ),
        (
            build_payment_method_choice_token,
            parse_payment_method_choice_token,
            "pm1",
        ),
    )
    for builder, parser, prefix in builders_and_parsers:
        token = builder(presentation_ref="pres_1", choice_ref="choice_1")
        assert token.startswith(f"{prefix}|")
        assert parser(token) == {
            "presentation_ref": "pres_1",
            "choice_ref": "choice_1",
        }


def test_schedule_surface_always_has_flexible_afternoon_choice() -> None:
    surface = build_schedule_choice_surface(_slot_result(include_afternoon=False))
    choices = surface["days"][0]["choices"]

    assert [choice["time_text"] for choice in choices[:-1]] == [
        "8:30 AM",
        "11:00 AM",
    ]
    assert choices[-1]["label"] == "Anytime in the afternoon"
    assert choices[-1]["time_text"] == "12:00 PM"
    assert choices[-1]["slot_ref"] == ""
    assert choices[-1]["slot_refs"] == []
    assert (
        choices[-1]["availability_status"]
        == "preference_only_no_current_afternoon_slot"
    )


def test_schedule_surface_hides_individual_afternoon_times() -> None:
    surface = build_schedule_choice_surface(_slot_result(include_afternoon=True))
    choices = surface["days"][0]["choices"]

    exact_button_times = {
        choice.get("time_text")
        for choice in choices
        if choice.get("selection_kind") == "exact_slot"
    }
    assert "2:00 PM" not in exact_button_times
    assert "5:00 PM" not in exact_button_times
    assert choices[-1]["slot_refs"] == [
        "slot_20260729_1400",
        "slot_20260729_1700",
    ]
    assert choices[-1]["time_text"] == "2:00 PM"
    assert choices[-1]["slot_ref"] == "slot_20260729_1400"


def test_schedule_renderer_outputs_one_day_card_with_three_buttons(
    monkeypatch,
) -> None:
    monkeypatch.setenv("PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE", "flow_test")
    rendered = render_turn_for_channel(
        _slot_turn(),
        service_environment="staging",
    )
    cards = [
        item for item in rendered.content_messages if item.get("type") == "cards"
    ]

    assert len(cards) == 1
    assert len(cards[0]["elements"]) == 1
    assert [button["caption"] for button in cards[0]["elements"][0]["buttons"]] == [
        "8:30 AM",
        "11:00 AM",
        "Anytime in afternoon",
    ]
    assert len(rendered.choice_presentations) == 1
    assert rendered.choice_presentations[0]["choice_type"] == "schedule_selection"


def test_model_composed_turn_can_render_product_without_schedule(monkeypatch) -> None:
    monkeypatch.setenv("PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE", "flow_test")
    slot_result = _slot_result()
    product_result = {
        "status": "ok",
        "presentation_ref": "pres_products",
        "observation_ref": "obs_products",
        "product_cards": [
            {
                "card_ref": "card_apollo",
                    "sku_model": "APOLLO ALNAC 4G",
                    "brand": "APOLLO",
                    "image_url": "https://storage.googleapis.com/catalog/apollo.webp",
                    "card_text": "APOLLO ALNAC 4G",
            },
            {
                "card_ref": "card_michelin",
                    "sku_model": "MICHELIN XM2+",
                    "brand": "MICHELIN",
                    "image_url": "https://storage.googleapis.com/catalog/michelin.webp",
                    "card_text": "MICHELIN XM2+",
            },
        ],
    }
    turn = {
        "assistant_text": json.dumps(
            {
                "response_units": [
                    {
                        "type": "render_surface",
                        "content": {"surface_ref": "pres_products"},
                    }
                ]
            }
        ),
        "final_composer": {"status": "used"},
        "tool_results": [
            {
                "name": "product_search",
                "full_result": product_result,
                "result": {"status": "ok"},
            },
            {
                "name": "find_installation_slots",
                "full_result": slot_result,
                "result": {"status": "ok"},
            },
        ],
    }

    rendered = render_turn_for_channel(turn, service_environment="staging")
    tokens = [
        action["value"]
        for message in rendered.content_messages
        if message.get("type") == "cards"
        for element in message.get("elements") or []
        for button in element.get("buttons") or []
        for action in button.get("actions") or []
    ]

    assert any(token.startswith("ps1|") for token in tokens)
    assert not any(token.startswith("ss1|") for token in tokens)


def test_renderer_preserves_model_owned_cta_after_product_buttons(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE",
        "flow_test",
    )
    product_result = {
        "status": "ok",
        "presentation_ref": "pres_products",
        "observation_ref": "obs_products",
        "product_cards": [
            {
                "card_ref": "card_michelin",
                    "sku_model": "MICHELIN PRIMACY 4",
                    "brand": "MICHELIN",
                    "image_url": "https://storage.googleapis.com/catalog/michelin.webp",
                    "card_text": "MICHELIN PRIMACY 4",
            },
            {
                "card_ref": "card_fronway",
                    "sku_model": "FRONWAY ECOGREEN ONE",
                    "brand": "FRONWAY",
                    "image_url": "https://storage.googleapis.com/catalog/fronway.webp",
                    "card_text": "FRONWAY ECOGREEN ONE",
            },
            {
                "card_ref": "card_black_arrow",
                    "sku_model": "BLACK ARROW DART P09",
                    "brand": "BLACK ARROW",
                    "image_url": "https://storage.googleapis.com/catalog/black-arrow.webp",
                    "card_text": "BLACK ARROW DART P09",
            },
        ],
    }
    turn = {
        "assistant_text": json.dumps(
            {
                "response_units": [
                    {
                        "type": "render_surface",
                        "content": {"surface_ref": "pres_products"},
                    },
                    {
                        "type": "text",
                        "content": {
                            "text": (
                                "Para ma-check po ang availability at kung "
                                "saan pwede magpa-install, anong city or "
                                "barangay po kayo?"
                            )
                        },
                    },
                ]
            }
        ),
        "tool_results": [
            {
                "name": "product_search",
                "full_result": product_result,
                "result": {"status": "ok"},
            }
        ],
    }

    rendered = render_turn_for_channel(
        turn,
        service_environment="staging",
    )
    texts = [
        str(message.get("text") or "")
        for message in rendered.content_messages
        if message.get("type") == "text"
    ]

    assert texts[-1] == (
        "Para ma-check po ang availability at kung saan pwede magpa-install, "
        "anong city or barangay po kayo?"
    )
    assert sum(
        token.startswith("ps1|")
        for message in rendered.content_messages
        if message.get("type") == "cards"
        for element in message.get("elements") or []
        for button in element.get("buttons") or []
        for action in button.get("actions") or []
        for token in [str(action.get("value") or "")]
    ) == 3


def test_final_composer_receives_product_and_schedule_as_available_surfaces() -> None:
    slot_result = _slot_result()
    product_result = {
        "status": "ok",
        "presentation_ref": "pres_products",
        "observation_ref": "obs_products",
        "product_cards": [
            {
                "card_ref": "card_apollo",
                "sku_model": "APOLLO ALNAC 4G",
                "brand": "APOLLO",
            },
            {
                "card_ref": "card_michelin",
                "sku_model": "MICHELIN XM2+",
                "brand": "MICHELIN",
            },
        ],
    }
    messages = _build_final_composer_messages(
        current_user_message="Apollo or Michelin, then what schedules are open?",
        request_time="2026-07-24 15:00:00",
        active_working_memory="",
        background_signals=[],
        lead_qualification={},
        order_readiness={},
        capability_profile={"selected_domains": ["product", "service"]},
        tool_results=[
            {
                "name": "product_search",
                "full_result": product_result,
                "result": {"status": "ok"},
            },
            {
                "name": "find_installation_slots",
                "full_result": slot_result,
                "result": {"status": "ok"},
            },
        ],
        draft_assistant_text="Choose a tire and a schedule.",
    )
    payload = json.loads(messages[-1]["content"])

    assert "decision_contract" not in payload
    assert {
        item["surface_ref"]
        for item in payload["surface_authorization"]["available_surfaces"]
    } == {
        "pres_products",
        "pres_slots_20260729",
    }
    assert {
        item["decision_layer"]
        for item in payload["surface_authorization"]["available_surfaces"]
    } == {"product", "schedule"}


def test_final_composer_receives_product_surface_without_stage_instruction() -> None:
    messages = _build_final_composer_messages(
        current_user_message="Show Apollo options first.",
        request_time="2026-07-24 15:00:00",
        active_working_memory="",
        background_signals=[],
        lead_qualification={},
        order_readiness={},
        capability_profile={"selected_domains": ["product"]},
        tool_results=[
            {
                "name": "product_search",
                "full_result": {
                    "status": "ok",
                    "presentation_ref": "pres_products",
                    "product_cards": [
                        {"card_ref": "card_1", "sku_model": "APOLLO A"},
                        {"card_ref": "card_2", "sku_model": "APOLLO B"},
                    ],
                },
                "result": {"status": "ok"},
            }
        ],
        draft_assistant_text="Which tire and schedule do you prefer?",
    )

    payload = json.loads(messages[-1]["content"])

    assert "decision_contract" not in payload
    assert [
        item["surface_ref"]
        for item in payload["surface_authorization"]["available_surfaces"]
    ] == ["pres_products"]
    assert "The model owns conversational sequencing" in (
        payload["surface_authorization"]["authority"]
    )


def test_schedule_surface_drops_unparseable_exact_time() -> None:
    result = _slot_result(include_afternoon=False)
    result["slot_groups"][0]["slots"] = [
        {
            "slot_ref": "slot_bad",
            "date": "2026-07-29",
            "time_text": "when available",
            "start": "",
        }
    ]

    surface = build_schedule_choice_surface(result)

    assert len(surface["choices"]) == 1
    assert surface["choices"][0]["selection_kind"] == "afternoon_preference"
    assert surface["choices"][0]["slot_refs"] == []


def test_exact_schedule_click_is_validated_against_delivered_observation() -> None:
    result = _slot_result()
    service_tools = RuntimeV7ServiceTools()
    service_tools.store.save_installation_slots_result(result)
    harness = RuntimeV7Harness(
        model_client=EmptyModel(),
        tools=ProductToolHarness(),
        service_tools=service_tools,
    )
    schedule = build_schedule_choice_surface(result)
    harness.choice_presentation_history = [
        {
            **schedule,
            "delivery_status": "success",
        }
    ]
    exact = schedule["days"][0]["choices"][0]
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="generic click",
        idempotency_key="schedule_click_1",
        flow_context={
            "choice_action_context": {
                "presentation_ref": schedule["presentation_ref"],
                "choice_ref": exact["choice_ref"],
                "choice_type": "schedule_selection",
            }
        },
    )

    _remember_choice_action_attempt(harness, request)

    assert (
        request.flow_context["choice_action_runtime_context"]["validation_status"]
        == "valid"
    )
    assert service_tools.store.latest_validated_slot_context()["selected_slot"][
        "slot_ref"
    ] == exact["slot_ref"]
    assert "not booked or reserved" in request.user_text
    assert resolve_fulfillment_alias(request.user_text) is None


def test_stale_product_click_does_not_emit_location_choice_ref() -> None:
    harness = RuntimeV7Harness(
        model_client=EmptyModel(),
        tools=ProductToolHarness(),
        service_tools=RuntimeV7ServiceTools(),
    )
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="generic click",
        idempotency_key="stale_product_click",
        flow_context={
            "choice_action_context": {
                "presentation_ref": "pres_missing",
                "card_ref": "card_1",
                "choice_type": "product_selection",
            }
        },
    )

    _remember_choice_action_attempt(harness, request)

    context = request.flow_context["choice_action_runtime_context"]
    assert context["validation_status"] == "stale"
    assert context["choice_ref"] == ""


def test_other_province_choice_clears_installation_state_and_steers_to_delivery() -> None:
    harness = RuntimeV7Harness(
        model_client=EmptyModel(),
        tools=ProductToolHarness(),
        service_tools=RuntimeV7ServiceTools(),
    )
    harness.signal_ledger.save(
        harness.session_id,
        [
            {"key": "tire_size", "value": "205/60R16", "source": "latest_user_message"},
            {"key": "location", "value": "Cavite", "source": "validated_choice_action"},
            {"key": "service_type", "value": "installation", "source": "validated_choice_action"},
            {
                "key": "selected_installation_partner",
                "value": "prior partner",
                "source": "validated_choice_action",
            },
        ],
    )
    harness.choice_presentation_history = [
        {
            "presentation_ref": "serviceable_provinces_1",
            "choice_type": "serviceable_province",
            "delivery_status": "success",
            "choices": [
                {
                    "choice_ref": "location:province:other",
                    "code": "other",
                    "label": "Other",
                    "position": 9,
                }
            ],
        }
    ]
    request = RuntimeV7APIRequest(
        user_id="trial-other-province",
        user_text="generic click",
        idempotency_key="other_province_click",
        flow_context={
            "choice_action_context": {
                "presentation_ref": "serviceable_provinces_1",
                "choice_ref": "location:province:other",
                "choice_code": "other",
                "choice_type": "serviceable_province",
            }
        },
    )

    _remember_choice_action_attempt(harness, request)

    runtime_context = request.flow_context["choice_action_runtime_context"]
    signals = {
        row["key"]: row["value"]
        for row in harness.signal_ledger.load(harness.session_id)
    }
    assert runtime_context["validation_status"] == "valid"
    assert runtime_context["recommended_service_path"] == "delivery"
    assert runtime_context["service_path_selected"] is False
    assert "delivery as the likely alternative" in request.user_text
    assert "delivery is already selected or confirmed" in request.user_text
    assert signals == {"tire_size": "205/60R16"}


def test_other_province_navigation_preserves_trusted_delivery_but_clears_synthetic_candidates() -> None:
    state_context = {
        "background_signals": [
            {"key": "tire_size", "value": "225/50R17"},
            {
                "key": "service_type",
                "value": "delivery",
                "source": "validated_choice_action",
            },
            {
                "key": "delivery_address",
                "value": "123 Example Street, Quezon City",
                "source": "validated_choice_action",
            },
            {
                "key": "location",
                "value": "Others",
                "source": "latest_user_message",
            },
        ]
    }

    _apply_validated_choice_signal_boundaries(
        state_context,
        validated_choice_context={
            "validation_status": "valid",
            "choice_type": "serviceable_province",
            "choice_code": "other",
            "recommended_service_path": "delivery",
            "service_path_selected": False,
        },
    )

    assert state_context["background_signals"] == [
        {"key": "tire_size", "value": "225/50R17"},
        {
            "key": "service_type",
            "value": "delivery",
            "source": "validated_choice_action",
        },
        {
            "key": "delivery_address",
            "value": "123 Example Street, Quezon City",
            "source": "validated_choice_action",
        },
    ]
    assert state_context["validated_choice_signal_boundary"] == {
        "status": "applied",
        "reason": "guided_other_area_synthetic_prose_is_not_customer_consent",
        "removed_keys": ["location"],
        "recommended_service_path": "delivery",
        "service_path_selected": False,
    }


def test_other_province_navigation_drops_synthetic_delivery_candidates() -> None:
    state_context = {
        "background_signals": [
            {"key": "tire_size", "value": "225/50R17"},
            {
                "key": "service_type",
                "value": "delivery",
                "source": "latest_user_message",
            },
            {
                "key": "delivery_address",
                "value": "123 Example Street, Quezon City",
                "source": "latest_user_message",
            },
            {
                "key": "location",
                "value": "Others",
                "source": "latest_user_message",
            },
        ]
    }

    _apply_validated_choice_signal_boundaries(
        state_context,
        validated_choice_context={
            "validation_status": "valid",
            "choice_type": "serviceable_province",
            "choice_code": "other",
            "recommended_service_path": "delivery",
            "service_path_selected": False,
        },
    )

    assert state_context["background_signals"] == [
        {"key": "tire_size", "value": "225/50R17"}
    ]
    assert state_context["validated_choice_signal_boundary"]["removed_keys"] == [
        "delivery_address",
        "location",
        "service_type",
    ]


def test_afternoon_click_remains_preference_when_no_slot_exists() -> None:
    result = _slot_result(include_afternoon=False)
    service_tools = RuntimeV7ServiceTools()
    service_tools.store.save_installation_slots_result(result)
    harness = RuntimeV7Harness(
        model_client=EmptyModel(),
        tools=ProductToolHarness(),
        service_tools=service_tools,
    )
    schedule = build_schedule_choice_surface(result)
    harness.choice_presentation_history = [
        {
            **schedule,
            "delivery_status": "success",
        }
    ]
    afternoon = schedule["days"][0]["choices"][-1]
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="generic click",
        idempotency_key="schedule_click_2",
        flow_context={
            "choice_action_context": {
                "presentation_ref": schedule["presentation_ref"],
                "choice_ref": afternoon["choice_ref"],
                "choice_type": "schedule_selection",
            }
        },
    )

    _remember_choice_action_attempt(harness, request)

    assert (
        request.flow_context["choice_action_runtime_context"]["validation_status"]
        == "valid"
    )
    assert (
        request.flow_context["choice_action_runtime_context"][
            "afternoon_resolution_status"
        ]
        == "default_noon_preference_unvalidated"
    )
    assert (
        request.flow_context["choice_action_runtime_context"]["time_text"]
        == "12:00 PM"
    )
    assert service_tools.store.latest_validated_slot_context() == {}
    assert "12:00 PM" in request.user_text
    assert "not an availability or booking claim" in request.user_text


def test_afternoon_click_resolves_to_earliest_available_exact_slot() -> None:
    result = _slot_result(include_afternoon=True)
    service_tools = RuntimeV7ServiceTools()
    service_tools.store.save_installation_slots_result(result)
    harness = RuntimeV7Harness(
        model_client=EmptyModel(),
        tools=ProductToolHarness(),
        service_tools=service_tools,
    )
    schedule = build_schedule_choice_surface(result)
    harness.choice_presentation_history = [
        {
            **schedule,
            "delivery_status": "success",
        }
    ]
    afternoon = schedule["days"][0]["choices"][-1]
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="generic click",
        idempotency_key="schedule_click_afternoon_available",
        flow_context={
            "choice_action_context": {
                "presentation_ref": schedule["presentation_ref"],
                "choice_ref": afternoon["choice_ref"],
                "choice_type": "schedule_selection",
            }
        },
    )

    _remember_choice_action_attempt(harness, request)

    context = request.flow_context["choice_action_runtime_context"]
    validated = service_tools.store.latest_validated_slot_context()
    assert context["validation_status"] == "valid"
    assert context["afternoon_resolution_status"] == (
        "earliest_available_slot_validated"
    )
    assert context["resolved_time_text"] == "2:00 PM"
    assert validated["selected_slot"]["slot_ref"] == "slot_20260729_1400"
    assert "earliest validated afternoon slot" in request.user_text
    assert "not booked or reserved" in request.user_text


def test_payment_surfaces_use_quote_and_checkout_compatibility() -> None:
    metadata = {
        "source": "gulong_api_checkout_metadata",
        "payment_options": [
            {"id": 1, "name": "Pay Later"},
            {"id": 2, "name": "Pay Now"},
        ],
        "transaction_types": [{"id": 1, "trans_type": "Installation"}],
        "payment_types": [
            {
                "id": 10,
                "name": "BPI 6 mos 0% interest",
                "label": "Installment",
                "description": (
                    "Pay after the service and pay a reservation fee."
                ),
                "main_payment_type_id": 2,
                "available_brands": "YOKOHAMA,APOLLO",
                "is_installment": True,
            },
            {
                "id": 11,
                "name": "Home Credit",
                "label": "Home Credit",
                "main_payment_type_id": 2,
                "available_brands": "TOYO",
            },
        ],
    }
    quote = {
        "quote_ref": "quote_1",
        "quote_breakdown": {
            "payment_options_preview": {
                "pay_now": {
                    "discount_text": "PHP 100.00",
                    "amount_due_now_text": "PHP 17,029.60",
                },
                "pay_later": {
                    "reservation_fee_text": "PHP 500.00",
                    "balance_due_text": "PHP 16,629.60",
                },
            }
        },
    }

    options = build_payment_option_surface(
        quote=quote,
        metadata=metadata,
        turn_id="turn_1",
    )
    methods = build_payment_method_surface(
        metadata=metadata,
        payment_option="Pay Now",
        product_brand="YOKOHAMA",
        service_path="installation",
        turn_id="turn_2",
    )

    assert {choice["label"] for choice in options["choices"]} == {
        "Pay Now",
        "Pay Later",
    }
    assert any(
        "Save PHP 100.00" in choice["subtitle"]
        for choice in options["choices"]
        if choice["label"] == "Pay Now"
    )
    assert [choice["label"] for choice in methods["choices"]] == [
        "BPI 6 mos 0% interest"
    ]
    assert methods["choices"][0]["installment_months"] == "6"
    assert methods["choices"][0]["payment_stage"] == "full_payment"
    assert methods["choices"][0]["description"].startswith("Use for Pay Now.")
    assert "after the service" not in methods["choices"][0]["description"]
    assert len(methods["choices"][0]["description"]) <= 80
    assert len(_payment_method_choice_description(payment_option="Pay Later")) <= 80


def test_payment_method_click_retains_its_delivered_payment_option() -> None:
    surface = build_payment_method_surface(
        metadata={
            "source": "gulong_api_checkout_metadata",
            "payment_options": [{"id": 1, "name": "Pay Later"}],
            "transaction_types": [{"id": 1, "trans_type": "Install"}],
            "payment_types": [
                {
                    "id": 10,
                    "main_payment_type_id": 1,
                    "name": "BPI 6-mos Installment (0% interest)",
                    "value": "BPI-INSTALLMENT",
                    "is_installment": True,
                }
            ],
        },
        payment_option="Pay Later",
        product_brand="MICHELIN",
        service_path="installation",
        turn_id="turn_method_context",
    )
    harness = RuntimeV7Harness(
        model_client=EmptyModel(),
        tools=ProductToolHarness(),
        service_tools=RuntimeV7ServiceTools(),
    )
    harness.choice_presentation_history = [
        {
            **surface,
            "delivery_status": "success",
        }
    ]
    choice = surface["choices"][0]
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="generic click",
        idempotency_key="method_click_1",
        flow_context={
            "choice_action_context": {
                "presentation_ref": surface["presentation_ref"],
                "choice_ref": choice["choice_ref"],
                "choice_type": "payment_method_selection",
            }
        },
    )

    _remember_choice_action_attempt(harness, request)

    context = request.flow_context["choice_action_runtime_context"]
    assert context["validation_status"] == "valid"
    assert context["payment_option"] == "Pay Later"
    assert context["payment_stage"] == "balance_payment"
    assert context["installment_months"] == "6"
    assert "BPI 6-mos Installment" in request.user_text
    assert "6 months" in request.user_text
    commercial_signals = {
        row["key"]: row["value"]
        for row in harness.signal_ledger.load(harness.session_id)
        if row.get("source") == "validated_choice_action"
    }
    assert commercial_signals == {
        "payment_option": "Pay Later",
        "balance_payment_method": "BPI 6-mos Installment (0% interest)",
        "installment_months": "6",
    }


def test_pay_later_method_roles_come_from_checkout_row_type() -> None:
    metadata = {
        "source": "gulong_api_checkout_metadata",
        "payment_options": [{"id": 1, "name": "Pay Later"}],
        "transaction_types": [{"id": 1, "trans_type": "Install"}],
        "payment_types": [
            {
                "id": 18,
                "main_payment_type_id": 1,
                "name": "Gcash / PayMaya / Grab Pay",
                "value": "EWALLET",
                "is_installment": False,
            },
            {
                "id": 9,
                "main_payment_type_id": 1,
                "name": "3-mos Installment (0% interest)",
                "value": "INSTALLMENT LATER",
                "is_installment": True,
            },
        ],
    }

    surface = build_payment_method_surface(
        metadata=metadata,
        payment_option="Pay Later",
        product_brand="YOKOHAMA",
        service_path="installation",
        turn_id="turn_pay_later_roles",
    )
    choices = {choice["payment_type_id"]: choice for choice in surface["choices"]}

    assert choices["18"]["payment_stage"] == "reservation_fee"
    assert "reservation fee" in choices["18"]["description"]
    assert choices["9"]["payment_stage"] == "balance_payment"
    assert "balance after service" in choices["9"]["description"]

    reservation_only = build_payment_method_surface(
        metadata=metadata,
        payment_option="Pay Later",
        product_brand="YOKOHAMA",
        service_path="installation",
        turn_id="turn_reservation_only",
        payment_stage="reservation_fee",
    )
    assert [choice["payment_type_id"] for choice in reservation_only["choices"]] == [
        "18"
    ]


def test_pay_later_reservation_click_keeps_timing_and_role_in_model_input() -> None:
    surface = build_payment_method_surface(
        metadata={
            "source": "gulong_api_checkout_metadata",
            "payment_options": [{"id": 1, "name": "Pay Later"}],
            "transaction_types": [{"id": 1, "trans_type": "Install"}],
            "payment_types": [
                {
                    "id": 18,
                    "main_payment_type_id": 1,
                    "name": "Gcash / PayMaya / Grab Pay",
                    "value": "EWALLET",
                    "is_installment": False,
                }
            ],
        },
        payment_option="Pay Later",
        product_brand="YOKOHAMA",
        service_path="installation",
        turn_id="turn_reservation_click",
    )
    harness = RuntimeV7Harness(
        model_client=EmptyModel(),
        tools=ProductToolHarness(),
        service_tools=RuntimeV7ServiceTools(),
    )
    harness.choice_presentation_history = [
        {**surface, "delivery_status": "success"}
    ]
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="generic click",
        idempotency_key="reservation_click_1",
        flow_context={
            "choice_action_context": {
                "presentation_ref": surface["presentation_ref"],
                "choice_ref": surface["choices"][0]["choice_ref"],
                "choice_type": "payment_method_selection",
            }
        },
    )

    _remember_choice_action_attempt(harness, request)

    assert "reservation payment method under Pay Later" in request.user_text
    assert "not Pay Now" in request.user_text
    commercial_signals = {
        row["key"]: row["value"]
        for row in harness.signal_ledger.load(harness.session_id)
        if row.get("source") == "validated_choice_action"
    }
    assert commercial_signals == {
        "payment_option": "Pay Later",
        "reservation_payment_method": "Gcash / PayMaya / Grab Pay",
    }


def test_validated_checkout_click_overrides_conflicting_model_order_plan() -> None:
    harness = RuntimeV7Harness(
        model_client=EmptyModel(),
        tools=ProductToolHarness(),
        service_tools=RuntimeV7ServiceTools(),
    )
    harness.current_validated_choice_context = {
        "validation_status": "valid",
        "choice_type": "payment_method_selection",
        "payment_option": "Pay Later / Pay After Service",
        "payment_stage": "reservation_fee",
        "label": "Gcash / PayMaya / Grab Pay",
        "value": "EWALLET",
        "choice_ref": "method_18",
        "presentation_ref": "pres_payment_methods_test",
    }

    validated = harness._apply_current_validated_checkout_choice(
        {
            "payment_option": "Pay Now",
            "payment_method": "GCash",
            "bank": "BPI",
            "installment_months": 6,
            "quantity": 4,
        }
    )

    assert validated == {
        "payment_option": "Pay Later / Pay After Service",
        "reservation_payment_method": "Gcash / PayMaya / Grab Pay",
        "quantity": 4,
    }


def test_pay_later_surface_applies_brand_allowlist_without_brand_rules() -> None:
    surface = build_payment_method_surface(
        metadata={
            "source": "gulong_api_checkout_metadata",
            "payment_options": [{"id": 1, "name": "Pay Later"}],
            "transaction_types": [{"id": 1, "trans_type": "Install"}],
            "payment_types": [
                {
                    "id": 10,
                    "main_payment_type_id": 1,
                    "name": "BPI 6-mos Installment (0% interest)",
                    "is_installment": True,
                    "available_brands": "MICHELIN, APOLLO, ARIVO",
                },
                {
                    "id": 9,
                    "main_payment_type_id": 1,
                    "name": "3-mos Installment (0% interest)",
                    "is_installment": True,
                    "available_brands": None,
                },
            ],
        },
        payment_option="Pay Later",
        product_brand="YOKOHAMA",
        service_path="installation",
        turn_id="turn_yokohama_methods",
    )

    assert [choice["payment_type_id"] for choice in surface["choices"]] == ["9"]


def test_final_composer_receives_order_progression_without_runtime_script() -> None:
    summary_ref = "order_summary_ready_1"
    messages = _build_final_composer_messages(
        current_user_message="09171234567 Juan Dela Cruz jdc@example.com",
        request_time="2026-07-28 16:00:00",
        active_working_memory="",
        background_signals=[
            {
                "key": "contact_number",
                "value": "09171234567",
                "source": "latest_user_message",
            },
            {
                "key": "first_name",
                "value": "Juan",
                "source": "latest_user_message",
            },
            {
                "key": "last_name",
                "value": "Dela Cruz",
                "source": "latest_user_message",
            },
            {
                "key": "email_address",
                "value": "jdc@example.com",
                "source": "latest_user_message",
            },
        ],
        lead_qualification={},
        order_readiness={"status": "ready", "missing": []},
        capability_profile={"selected_domains": ["order"]},
        tool_results=[
            {
                "name": "build_order_summary",
                "full_result": {
                    "status": "ready",
                    "order_summary_ref": summary_ref,
                    "card_runtime_insert": True,
                    "missing_fields": [],
                    "summary_update": {
                        "display_action": "show_form",
                        "reason": "became_ready",
                    },
                },
                "result": {"status": "ready"},
            }
        ],
        draft_assistant_text="Noted po.",
    )

    payload = json.loads(messages[-1]["content"])
    assert "order_progression_context" not in payload
    assert summary_ref in {
        item["surface_ref"]
        for item in payload["surface_authorization"]["available_surfaces"]
    }
    assert payload["order_readiness"]["status"] == "ready"
    assert "runtime_order_form_progression" not in messages[0]["content"]


def test_successful_submit_continues_to_validated_payment_request() -> None:
    context = _ready_payment_request_retry_context(
        tool_schemas=[
            {
                "type": "function",
                "function": {
                    "name": "prepare_payment_request",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        tool_results=[
            {
                "name": "submit_order",
                "result": {
                    "status": "success",
                    "order_id": "36799",
                    "order_payload_ref": "order_payload_36799",
                    "can_request_payment": True,
                    "recommended_next_tool": "prepare_payment_request",
                },
            }
        ],
        retry_events=[],
    )

    assert context == {
        "order_id": "36799",
        "order_payload_ref": "order_payload_36799",
    }


def test_typed_payment_option_uses_composer_before_renderer_methods() -> None:
    signals = [
        {
            "key": "payment_option",
            "value": "Pay Later",
            "source": "latest_user_message",
        }
    ]
    readiness = {
        "status": "ready_for_summary",
        "customer_order_intent": "high",
        "collected": {
            "Product": "APOLLO AMAZER XP 175/65R14",
            "Payment option": "Pay Later / Pay After Service",
        },
        "missing": [
            "Contact number",
            "First name",
            "Last name",
            "Email address",
            "Reservation payment method",
        ],
    }

    assert _no_tool_order_progression_requires_composer(
        background_signals=signals,
        order_readiness=readiness,
    )
    messages = _build_final_composer_messages(
        current_user_message="Pay Later po.",
        request_time="2026-07-28 19:04:00",
        active_working_memory="",
        background_signals=signals,
        lead_qualification={},
        order_readiness=readiness,
        capability_profile={"selected_domains": ["order"]},
        tool_results=[],
        draft_assistant_text="",
    )
    payload = json.loads(messages[-1]["content"])
    assert "order_progression_context" not in payload
    assert payload["background_signals"][0]["key"] == "payment_option"


def test_unconfirmed_payment_inquiry_does_not_advance_composer_progression() -> None:
    signals = [
        {
            "key": "payment_method",
            "value": "home credit",
            "source": "latest_user_message",
            "status": "mentioned_unconfirmed",
        }
    ]
    readiness = {
        "status": "ready_for_summary",
        "collected": {"Product": "APOLLO AMAZER XP 175/65R14"},
        "missing": ["Payment method"],
    }

    assert not _no_tool_order_progression_requires_composer(
        background_signals=signals,
        order_readiness=readiness,
    )
    messages = _build_final_composer_messages(
        current_user_message="Pwede Home Credit?",
        request_time="2026-07-28 19:04:00",
        active_working_memory="",
        background_signals=signals,
        lead_qualification={},
        order_readiness=readiness,
        capability_profile={"selected_domains": ["order"]},
        tool_results=[],
        draft_assistant_text="",
    )
    payload = json.loads(messages[-1]["content"])
    assert "order_progression_context" not in payload
    assert payload["background_signals"][0]["status"] == "mentioned_unconfirmed"


def test_confirmed_typed_payment_selection_keeps_checkout_metadata_authority() -> None:
    signal = {
        "key": "payment_method",
        "value": "gcash",
        "source": "latest_user_message",
        "status": "confirmed_by_latest_user_message",
        "metadata": {
            "normalization": {
                "status": "checkout_metadata_canonicalized",
                "payment_type": {
                    "id": 18,
                    "name": "Gcash / PayMaya / Grab Pay",
                },
                "payment_option": {"id": 1, "name": "Pay Later"},
            }
        },
    }

    assert _signal_has_validated_checkout_choice_ref(signal)
    signal["status"] = "mentioned_unconfirmed"
    assert not _signal_has_validated_checkout_choice_ref(signal)


def test_submit_authorization_guard_never_claims_unconfirmed_submission() -> None:
    turn = {
        "runtime_final_response": "Submitted na po.",
        "tool_results": [
            {
                "name": "submit_order",
                "full_result": {
                    "status": "needs_explicit_order_confirmation",
                    "reason": (
                        "latest_customer_message_did_not_confirm_submission"
                    ),
                    "order_payload_ref": "order_payload_test",
                    "order_submitted": False,
                },
            }
        ],
    }

    _apply_submit_authorization_truth_guard(turn)

    assert turn["response_owner"] == "runtime_submit_authorization_guard"
    assert "hindi pa na-submit" in turn["runtime_final_response"]
    assert "Pakiconfirm" in turn["runtime_final_response"]


def test_payment_option_click_supersedes_previous_method_signals() -> None:
    surface = build_payment_option_surface(
        quote={
            "quote_ref": "quote_switch",
            "quote_breakdown": {
                "payment_options_preview": {
                    "pay_now": {"discount_text": "PHP 100.00"},
                    "pay_later": {"reservation_fee_text": "PHP 500.00"},
                }
            },
        },
        metadata={
            "source": "gulong_api_checkout_metadata",
            "payment_options": [
                {"id": 1, "name": "Pay Later"},
                {"id": 2, "name": "Pay Now"},
            ],
        },
        turn_id="turn_payment_switch",
    )
    harness = RuntimeV7Harness(
        model_client=EmptyModel(),
        tools=ProductToolHarness(),
        service_tools=RuntimeV7ServiceTools(),
    )
    harness.signal_ledger.save(
        harness.session_id,
        [
            {"key": "payment_option", "value": "Pay Later"},
            {"key": "payment_method", "value": "BPI installment"},
            {"key": "bank", "value": "BPI"},
            {"key": "installment_months", "value": "6"},
        ],
    )
    harness.choice_presentation_history = [
        {**surface, "delivery_status": "success"}
    ]
    pay_now = next(
        choice
        for choice in surface["choices"]
        if choice["label"] == "Pay Now"
    )
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="generic click",
        idempotency_key="option_switch_1",
        flow_context={
            "choice_action_context": {
                "presentation_ref": surface["presentation_ref"],
                "choice_ref": pay_now["choice_ref"],
                "choice_type": "payment_option_selection",
            }
        },
    )

    _remember_choice_action_attempt(harness, request)

    signals = {
        row["key"]: row["value"]
        for row in harness.signal_ledger.load(harness.session_id)
    }
    assert signals == {"payment_option": "Pay Now"}


def test_validated_price_category_choice_supersedes_older_category_signal():
    harness = RuntimeV7Harness(
        model_client=EmptyModel(),
        tools=ProductToolHarness(),
        service_tools=RuntimeV7ServiceTools(),
    )
    harness.signal_ledger.save(
        harness.session_id,
        [
            {
                "key": "tire_category_preference",
                "label": "Tire category preference",
                "value": "Mid Range",
                "status": "remembered_signal",
                "source": "signal_ledger",
            }
        ],
    )

    api_runtime._remember_validated_commercial_choice_signals(
        harness,
        {
            "validation_status": "valid",
            "choice_type": "price_category",
            "label": "Economy",
            "category": "economy",
            "choice_ref": "price_category:economy",
            "presentation_ref": "price_categories_1",
        },
    )

    signals = harness.signal_ledger.load(harness.session_id)
    assert len(signals) == 1
    assert signals[0]["key"] == "tire_category_preference"
    assert signals[0]["value"] == "Economy"
    assert signals[0]["source"] == "validated_choice_action"
    assert signals[0]["relation"] == "selected"


def test_validated_location_choice_persists_surface_scoped_installation_intent():
    harness = RuntimeV7Harness(
        model_client=EmptyModel(),
        tools=ProductToolHarness(),
        service_tools=RuntimeV7ServiceTools(),
    )

    api_runtime._remember_validated_commercial_choice_signals(
        harness,
        {
            "validation_status": "valid",
            "choice_type": "serviceable_city",
            "label": "Bacoor",
            "province_label": "Cavite",
            "choice_ref": "location:city:PH-CAV-003",
            "presentation_ref": "serviceable_cities_cavite_1",
        },
    )

    signals = {
        row["key"]: row
        for row in harness.signal_ledger.load(harness.session_id)
    }
    assert signals["location"]["value"] == "Bacoor, Cavite"
    assert signals["location"]["source"] == "validated_choice_action"
    assert signals["service_type"]["value"] == "installation"
    assert signals["service_type"]["source"] == "validated_choice_action"
    assert signals["service_type"]["safe_for_action"] is True


def test_ambiguous_payment_clicks_commit_only_after_validated_model_decision():
    harness = RuntimeV7Harness(
        model_client=EmptyModel(),
        tools=ProductToolHarness(),
        service_tools=RuntimeV7ServiceTools(),
    )
    harness.signal_ledger.save(
        harness.session_id,
        [
            {
                "key": "payment_option",
                "value": "Pay Now",
                "source": "validated_choice_action",
                "status": "tool_grounded",
            }
        ],
    )
    snapshot = api_runtime._snapshot_interaction_transition_state(harness)
    pay_now = {
        "event_id": "evt-pay-now",
        "idempotency_key": "idem-pay-now",
        "choice_type": "payment_option_selection",
        "presentation_ref": "pres-payment",
        "choice_ref": "payment-option:pay-now",
        "label": "Pay Now",
        "value": "Pay Now",
        "validation_status": "valid",
        "delivery_status": "superseded_before_composition",
        "click_timestamp": "2026-07-28T10:00:00+08:00",
    }
    pay_later = {
        "event_id": "evt-pay-later",
        "idempotency_key": "idem-pay-later",
        "choice_type": "payment_option_selection",
        "presentation_ref": "pres-payment",
        "choice_ref": "payment-option:pay-later",
        "label": "Pay Later",
        "value": "Pay Later",
        "validation_status": "valid",
        "delivery_status": "pending",
        "click_timestamp": "2026-07-28T10:00:00.200+08:00",
    }
    harness.choice_action_history = [pay_now, pay_later]
    harness.latest_choice_action = pay_later

    api_runtime._remember_validated_commercial_choice_signals(
        harness,
        pay_later,
    )
    api_runtime._restore_interaction_transition_state(harness, snapshot)
    packet = api_runtime.compile_interaction_packet(
        choice_history=harness.choice_action_history,
        promo_history=[],
        current_event_id="evt-pay-later",
    )

    clarification_turn = {
        "interaction_packet": packet,
        "interaction_decision_validation": {
            "status": "valid",
            "interpretation": "clarify",
            "effective_event_ids": [],
            "needs_clarification": True,
        }
    }
    api_runtime._commit_validated_interaction_decision(
        harness,
        packet=packet,
        turn=clarification_turn,
    )
    values = {
        row["key"]: row["value"]
        for row in harness.signal_ledger.load(harness.session_id)
    }
    assert values == {"payment_option": "Pay Now"}
    api_runtime._remember_interaction_batch_delivery_result(
        harness,
        turn=clarification_turn,
        delivery_result={
            "status": "success",
            "delivery_mode": "send_content",
        },
    )
    assert {
        row["resolution_status"]
        for row in harness.choice_action_history
    } == {"clarification_delivered"}
    assert not any(
        row["effective_for_state"]
        for row in harness.choice_action_history
    )

    acceptance_turn = {
        "interaction_packet": packet,
        "interaction_decision_validation": {
            "status": "valid",
            "interpretation": "accept_latest",
            "effective_event_ids": ["evt-pay-later"],
            "needs_clarification": False,
        },
    }
    api_runtime._commit_validated_interaction_decision(
        harness,
        packet=packet,
        turn=acceptance_turn,
    )
    values = {
        row["key"]: row["value"]
        for row in harness.signal_ledger.load(harness.session_id)
    }
    assert values == {"payment_option": "Pay Later"}
    assert acceptance_turn["interaction_state_commit"]["status"] == (
        "payment_selection_committed"
    )

    api_runtime._remember_interaction_batch_delivery_result(
        harness,
        turn=acceptance_turn,
        delivery_result={
            "status": "skipped",
            "reason": "return_only",
            "delivery_mode": "return_only",
        },
    )
    assert {
        row["delivery_status"]
        for row in harness.choice_action_history
    } == {"evaluated"}
    assert {
        row["event_id"]: row["resolution_status"]
        for row in harness.choice_action_history
    } == {
        "evt-pay-now": "superseded_by_resolution",
        "evt-pay-later": "effective_selection_evaluated",
    }
    assert {
        row["event_id"]: row["effective_for_state"]
        for row in harness.choice_action_history
    } == {
        "evt-pay-now": False,
        "evt-pay-later": True,
    }


def test_checkout_controls_attach_after_validated_installation_schedule(
    monkeypatch,
) -> None:
    quote = {
        "quote_ref": "quote_1",
        "service_path": "installation",
        "quote_breakdown": {
            "payment_options_preview": {
                "pay_now": {
                    "discount_text": "PHP 100.00",
                    "amount_due_now_text": "PHP 17,029.60",
                },
                "pay_later": {
                    "reservation_fee_text": "PHP 500.00",
                    "balance_due_text": "PHP 16,629.60",
                },
            }
        },
    }
    metadata = {
        "source": "gulong_api_checkout_metadata",
        "payment_options": [
            {"id": 1, "name": "Pay Later"},
            {"id": 2, "name": "Pay Now"},
        ],
        "transaction_types": [{"id": 1, "trans_type": "Install"}],
        "payment_types": [],
    }
    monkeypatch.setattr(api_runtime, "calculate_order_quote", lambda **_kwargs: quote)
    monkeypatch.setattr(api_runtime, "checkout_metadata", lambda _provider: metadata)
    harness = SimpleNamespace(
        latest_selected_product_context={
            "product_summary": {"brand": "YOKOHAMA"}
        },
        tools=SimpleNamespace(store=object()),
        service_tools=SimpleNamespace(
            store=SimpleNamespace(
                latest_validated_slot_context=lambda: {
                    "validation_status": "slot_validated"
                }
            )
        ),
        canonical_values_provider=object(),
    )
    turn = {
        "turn_id": "turn_checkout_1",
        "order_readiness_after_tools": {
            "customer_order_intent": "active",
            "collected": {"Fulfillment": "installation"},
        },
        "background_signals_before_turn": [
            {
                "key": "order_summary_review_confirmation",
                "value": "yes",
                "source": "latest_user_message",
                "status": "provided_by_latest_user_message",
            }
        ],
    }

    _attach_checkout_choice_surface(
        turn,
        request=RuntimeV7APIRequest(user_id="trial", user_text="proceed"),
        harness=harness,
    )

    assert turn["checkout_choice_surface"]["choice_type"] == (
        "payment_option_selection"
    )
    assert {
        choice["label"]
        for choice in turn["checkout_choice_surface"]["choices"]
    } == {"Pay Now", "Pay Later"}
    assert "runtime_final_response" not in turn


def test_checkout_uses_latest_free_text_payment_option_over_stale_snapshot(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        api_runtime,
        "calculate_order_quote",
        lambda **_kwargs: {
            "quote_ref": "quote_latest_payment",
            "service_path": "installation",
            "quote_breakdown": {},
        },
    )
    monkeypatch.setattr(
        api_runtime,
        "checkout_metadata",
        lambda _provider: {
            "source": "gulong_api_checkout_metadata",
            "payment_options": [
                {"id": 1, "name": "Pay Later"},
                {"id": 2, "name": "Pay Now"},
            ],
            "transaction_types": [{"id": 10, "trans_type": "Install"}],
            "payment_types": [
                {
                    "id": 20,
                    "main_payment_type_id": 2,
                    "name": "Straight Credit Card / Debit Card",
                    "value": "CARD",
                    "available_brands": "MICHELIN,APOLLO",
                    "is_disabled": 0,
                }
            ],
        },
    )
    harness = SimpleNamespace(
        latest_selected_product_context={
            "product_summary": {"brand": "APOLLO"}
        },
        tools=SimpleNamespace(store=object()),
        service_tools=SimpleNamespace(
            store=SimpleNamespace(
                latest_validated_slot_context=lambda: {
                    "validation_status": "slot_validated"
                }
            )
        ),
        canonical_values_provider=object(),
    )
    turn = {
        "turn_id": "turn_full_payment_text",
        "order_readiness_after_tools": {
            "customer_order_intent": "active",
            "collected": {
                "Fulfillment": "installation",
                "Payment option": "Pay Later / Pay After Service",
            },
        },
        "background_signals_before_turn": [
            {
                "key": "payment_option",
                "value": "Pay Now",
                "source": "latest_user_message",
                "status": "confirmed",
            }
        ],
    }

    _attach_checkout_choice_surface(
        turn,
        request=RuntimeV7APIRequest(
            user_id="trial",
            user_text="Full payment po.",
        ),
        harness=harness,
    )

    surface = turn["checkout_choice_surface"]
    assert surface["choice_type"] == "payment_method_selection"
    assert surface["payment_option"] == "Pay Now"
    assert [choice["label"] for choice in surface["choices"]] == [
        "Straight Credit Card / Debit Card"
    ]


def test_checkout_waits_for_source_backed_installation_serviceability(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        api_runtime,
        "calculate_order_quote",
        lambda **_kwargs: {
            "quote_ref": "quote_unvalidated_area",
            "service_path": "installation",
            "quote_breakdown": {},
        },
    )
    harness = SimpleNamespace(
        latest_selected_product_context={
            "product_summary": {"brand": "APOLLO"}
        },
        tools=SimpleNamespace(store=object()),
        service_tools=SimpleNamespace(
            store=SimpleNamespace(
                latest_validated_slot_context=lambda: {},
                latest_installation_slots_observation=lambda **_kwargs: None,
            )
        ),
        canonical_values_provider=object(),
    )
    turn = {
        "turn_id": "turn_unvalidated_area",
        "order_readiness_after_tools": {
            "customer_order_intent": "active",
            "collected": {
                "Fulfillment": "installation",
                "Installation area": "Ozamiz City",
                "Preferred installation schedule": "Tomorrow morning",
            },
        },
        "background_signals_before_turn": [],
    }

    _attach_checkout_choice_surface(
        turn,
        request=RuntimeV7APIRequest(
            user_id="trial",
            user_text="Proceed",
        ),
        harness=harness,
    )

    assert "checkout_choice_surface" not in turn
    assert turn["checkout_choice_surface_status"]["reason"] == (
        "installation_serviceability_not_validated"
    )


def test_checkout_controls_reuse_current_order_summary_payment_preview(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        api_runtime,
        "calculate_order_quote",
        lambda **_kwargs: {
            "quote_ref": "quote_without_preview",
            "service_path": "installation",
            "quote_breakdown": {},
        },
    )
    monkeypatch.setattr(
        api_runtime,
        "checkout_metadata",
        lambda _provider: {
            "source": "gulong_api_checkout_metadata",
            "payment_options": [
                {"id": 1, "name": "Pay Later"},
                {"id": 2, "name": "Pay Now"},
            ],
            "transaction_types": [{"id": 1, "trans_type": "Install"}],
            "payment_types": [],
        },
    )
    harness = SimpleNamespace(
        latest_selected_product_context={
            "product_summary": {"brand": "APOLLO"}
        },
        tools=SimpleNamespace(store=object()),
        service_tools=SimpleNamespace(
            store=SimpleNamespace(
                latest_validated_slot_context=lambda: {
                    "validation_status": "slot_validated"
                }
            )
        ),
        canonical_values_provider=object(),
    )
    turn = {
        "turn_id": "turn_checkout_summary_preview",
        "order_readiness_before_turn": {
            "customer_order_intent": "active",
            "collected": {"Fulfillment": "installation"},
        },
        "background_signals_before_turn": [],
        "tool_results": [
            {
                "name": "build_order_summary",
                "full_result": {
                    "order_summary_ref": "summary_1",
                    "quote_summary": {
                        "payment_options_preview": {
                            "pay_now": {
                                "discount_text": "PHP 100.00",
                                "amount_due_now_text": "PHP 18,380.00",
                            },
                            "pay_later": {
                                "reservation_fee_text": "PHP 500.00",
                                "balance_due_text": "PHP 17,980.00",
                            },
                        }
                    },
                },
            }
        ],
    }

    _attach_checkout_choice_surface(
        turn,
        request=RuntimeV7APIRequest(
            user_id="trial",
            user_text="I selected the validated installation slot.",
            flow_context={
                "choice_action_runtime_context": {
                    "validation_status": "valid",
                    "choice_type": "schedule_selection",
                    "selection_kind": "exact_slot",
                }
            },
        ),
        harness=harness,
    )

    assert turn["checkout_choice_surface"]["choice_type"] == (
        "payment_option_selection"
    )


def test_product_choice_does_not_attach_checkout_from_stale_order_state(
    monkeypatch,
) -> None:
    quote = {
        "quote_ref": "quote_stale",
        "service_path": "delivery",
        "quote_breakdown": {
            "payment_options_preview": {
                "pay_now": {"discount_text": "PHP 100.00"},
                "pay_later": {"reservation_fee_text": "PHP 500.00"},
            }
        },
    }
    monkeypatch.setattr(api_runtime, "calculate_order_quote", lambda **_kwargs: quote)
    monkeypatch.setattr(
        api_runtime,
        "checkout_metadata",
        lambda _provider: {
            "source": "gulong_api_checkout_metadata",
            "payment_options": [
                {"id": 1, "name": "Pay Later"},
                {"id": 2, "name": "Pay Now"},
            ],
            "transaction_types": [],
            "payment_types": [],
        },
    )
    harness = SimpleNamespace(
        latest_selected_product_context={
            "product_summary": {"brand": "APOLLO"}
        },
        tools=SimpleNamespace(store=object()),
        service_tools=SimpleNamespace(store=object()),
        canonical_values_provider=object(),
    )
    turn = {
        "turn_id": "turn_product_click",
        "order_readiness_after_tools": {
            "customer_order_intent": "active",
            "collected": {
                "Fulfillment": "delivery",
                "Contact number": "09171234567",
                "Payment option": "Pay Later / Pay After Service",
            },
            "missing_fields": ["Complete delivery address"],
        },
        "background_signals_before_turn": [],
    }
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="I selected Apollo.",
        flow_context={
            "trigger": "choice_action",
            "choice_action_runtime_context": {
                "validation_status": "valid",
                "choice_type": "product_selection",
            },
        },
    )

    _attach_checkout_choice_surface(turn, request=request, harness=harness)

    assert "checkout_choice_surface" not in turn


def test_new_product_options_suppress_checkout_from_older_completed_state(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        api_runtime,
        "calculate_order_quote",
        lambda **_kwargs: {
            "quote_ref": "quote_old",
            "service_path": "delivery",
            "quote_breakdown": {
                "payment_options_preview": {
                    "pay_now": {"discount_text": "PHP 100.00"},
                    "pay_later": {"reservation_fee_text": "PHP 500.00"},
                }
            },
        },
    )
    harness = SimpleNamespace(
        latest_selected_product_context={
            "product_summary": {"brand": "APOLLO"}
        },
        tools=SimpleNamespace(store=object()),
        service_tools=SimpleNamespace(store=object()),
        canonical_values_provider=object(),
    )
    turn = {
        "turn_id": "turn_new_products",
        "tool_results": [
            {
                "name": "product_search",
                "full_result": {
                    "presentation_ref": "pres_new_products",
                    "product_cards": [
                        {"card_ref": "new_1"},
                        {"card_ref": "new_2"},
                    ],
                },
            }
        ],
        "order_readiness_after_tools": {
            "customer_order_intent": "active",
            "collected": {
                "Delivery address": "123 Example Street, San Pedro, Laguna"
            },
        },
        "background_signals_before_turn": [],
    }

    _attach_checkout_choice_surface(
        turn,
        request=RuntimeV7APIRequest(
            user_id="trial",
            user_text="Show me other tires.",
        ),
        harness=harness,
    )

    assert "checkout_choice_surface" not in turn
    assert turn["checkout_choice_surface_status"]["reason"] == (
        "model_or_guided_payment_progression_missing"
    )


def test_flexible_afternoon_selection_can_advance_to_order_form(
    monkeypatch,
) -> None:
    quote = {
        "quote_ref": "quote_afternoon",
        "service_path": "installation",
        "quote_breakdown": {
            "payment_options_preview": {
                "pay_now": {"discount_text": "PHP 100.00"},
                "pay_later": {"reservation_fee_text": "PHP 500.00"},
            }
        },
    }
    metadata = {
        "source": "gulong_api_checkout_metadata",
        "payment_options": [
            {"id": 1, "name": "Pay Later"},
            {"id": 2, "name": "Pay Now"},
        ],
        "transaction_types": [{"id": 1, "trans_type": "Install"}],
        "payment_types": [],
    }
    monkeypatch.setattr(api_runtime, "calculate_order_quote", lambda **_kwargs: quote)
    monkeypatch.setattr(api_runtime, "checkout_metadata", lambda _provider: metadata)
    harness = SimpleNamespace(
        latest_selected_product_context={
            "product_summary": {"brand": "APOLLO"}
        },
        tools=SimpleNamespace(store=object()),
        service_tools=SimpleNamespace(
            store=SimpleNamespace(
                latest_validated_slot_context=lambda: {},
                get_observation=lambda _ref: SimpleNamespace(
                    service_locations=[{"service_location_ref": "svc_1"}],
                    slot_groups=[{"date": "2026-07-28", "slots": [{}]}],
                    availability={"availability_status": "available"},
                ),
            )
        ),
        canonical_values_provider=object(),
    )
    turn = {
        "turn_id": "turn_afternoon",
        "order_readiness_after_tools": {
            "customer_order_intent": "active",
            "collected": {"Fulfillment": "installation"},
        },
        "background_signals_before_turn": [],
    }
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="Anytime in the afternoon.",
        flow_context={
            "trigger": "choice_action",
            "choice_action_runtime_context": {
                "validation_status": "valid",
                "choice_type": "schedule_selection",
                "selection_kind": "afternoon_preference",
                "observation_ref": "svc_obs_afternoon",
            },
        },
    )

    _attach_checkout_choice_surface(turn, request=request, harness=harness)

    assert turn["checkout_choice_surface"]["choice_type"] == (
        "payment_option_selection"
    )


def test_persisted_flexible_schedule_does_not_auto_advance_checkout_on_later_turn(
    monkeypatch,
) -> None:
    captured_payload = {}

    def fake_quote(**kwargs):
        captured_payload.update(kwargs["payload"])
        return {
            "quote_ref": "quote_persisted_afternoon",
            "service_path": "installation",
            "quote_breakdown": {
                "payment_options_preview": {
                    "pay_now": {"discount_text": "PHP 100.00"},
                    "pay_later": {"reservation_fee_text": "PHP 500.00"},
                }
            },
        }

    monkeypatch.setattr(api_runtime, "calculate_order_quote", fake_quote)
    monkeypatch.setattr(
        api_runtime,
        "checkout_metadata",
        lambda _provider: {
            "source": "gulong_api_checkout_metadata",
            "payment_options": [
                {"id": 1, "name": "Pay Later"},
                {"id": 2, "name": "Pay Now"},
            ],
            "transaction_types": [{"id": 1, "trans_type": "Install"}],
            "payment_types": [],
        },
    )
    harness = SimpleNamespace(
        latest_selected_product_context={
            "product_observation_ref": "obs_selected",
            "product_presentation_ref": "pres_selected",
            "product_card_ref": "card_selected",
            "product_item_ref": "prod_selected",
            "product_id": 7420,
            "slug": "michelin-energy-xm2",
            "product_summary": {"brand": "MICHELIN"},
        },
        tools=SimpleNamespace(store=object()),
        service_tools=SimpleNamespace(
            store=SimpleNamespace(
                latest_validated_slot_context=lambda: {},
                latest_installation_slots_observation=lambda **_kwargs: (
                    SimpleNamespace(
                        service_locations=[
                            {"service_location_ref": "svc_persisted"}
                        ],
                        slot_groups=[
                            {"date": "2026-07-28", "slots": [{}]}
                        ],
                        availability={"availability_status": "available"},
                    )
                ),
            )
        ),
        canonical_values_provider=object(),
    )
    turn = {
        "turn_id": "turn_contact_after_afternoon",
        "order_readiness_after_tools": {
            "customer_order_intent": "active",
            "missing": ["Payment option (Pay Now or Pay Later)"],
            "collected": {
                "Fulfillment": "installation",
                "Preferred installation schedule": "2026-07-28 afternoon",
                "Contact number": "09171234567",
                "First name": "Juan",
                "Last name": "Dela Cruz",
                "Email": "juan@example.com",
            },
        },
        "order_readiness_before_turn": {
            "missing": [
                "Contact number",
                "First name",
                "Last name",
                "Email address",
                "Payment option (Pay Now or Pay Later)",
            ],
        },
        "background_signals_before_turn": [],
    }

    _attach_checkout_choice_surface(
        turn,
        request=RuntimeV7APIRequest(
            user_id="trial",
            user_text=(
                "09171234567 Juan Dela Cruz juan@example.com"
            ),
        ),
        harness=harness,
    )

    assert "checkout_choice_surface" not in turn
    assert turn["checkout_choice_surface_status"]["reason"] == (
        "model_or_guided_payment_progression_missing"
    )
    assert captured_payload == {
        "product_observation_ref": "obs_selected",
        "product_presentation_ref": "pres_selected",
        "product_card_ref": "card_selected",
        "product_item_ref": "prod_selected",
        "product_id": 7420,
        "slug": "michelin-energy-xm2",
    }


def test_checkout_does_not_reask_collected_payment_after_exact_schedule(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        api_runtime,
        "calculate_order_quote",
        lambda **_kwargs: {
            "quote_ref": "quote_collected_payment",
            "service_path": "installation",
            "quote_breakdown": {},
        },
    )
    monkeypatch.setattr(
        api_runtime,
        "checkout_metadata",
        lambda _provider: {
            "source": "gulong_api_checkout_metadata",
            "payment_options": [
                {"id": 1, "name": "Pay Later"},
                {"id": 2, "name": "Pay Now"},
            ],
            "transaction_types": [{"id": 1, "trans_type": "Install"}],
            "payment_types": [],
        },
    )
    harness = SimpleNamespace(
        latest_selected_product_context={
            "product_summary": {"brand": "MICHELIN"}
        },
        tools=SimpleNamespace(store=object()),
        service_tools=SimpleNamespace(
            store=SimpleNamespace(
                latest_validated_slot_context=lambda: {
                    "validation_status": "slot_validated"
                }
            )
        ),
        canonical_values_provider=object(),
    )
    turn = {
        "turn_id": "turn_exact_after_payment",
        "order_readiness_after_tools": {
            "customer_order_intent": "active",
            "collected": {
                "Fulfillment": "installation",
                "Payment option": "Pay Later / Pay After Service",
                "Payment method": "credit card installment",
            },
        },
        "background_signals_before_turn": [],
    }
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="8:30 AM",
        flow_context={
            "choice_action_runtime_context": {
                "validation_status": "valid",
                "choice_type": "schedule_selection",
                "selection_kind": "exact_slot",
            }
        },
    )

    _attach_checkout_choice_surface(turn, request=request, harness=harness)

    assert "checkout_choice_surface" not in turn
    assert turn["checkout_choice_surface_status"]["reason"] == "surface_empty"
    assert turn["checkout_choice_surface_status"]["payment_option"] == (
        "Pay Later / Pay After Service"
    )
    assert turn["checkout_choice_surface_status"]["payment_method"] == (
        "credit card installment"
    )
    assert turn["checkout_choice_surface_status"]["payment_option_count"] == 2
    assert turn["checkout_choice_surface_status"]["payment_method_count"] == 0


def test_checkout_does_not_redisplay_payment_method_on_unrelated_faq_turn(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        api_runtime,
        "calculate_order_quote",
        lambda **_kwargs: {
            "quote_ref": "quote_unrelated_faq",
            "service_path": "installation",
            "quote_breakdown": {},
        },
    )
    harness = SimpleNamespace(
        latest_selected_product_context={
            "product_summary": {"brand": "MICHELIN"}
        },
        tools=SimpleNamespace(store=object()),
        service_tools=SimpleNamespace(
            store=SimpleNamespace(
                latest_validated_slot_context=lambda: {
                    "validation_status": "slot_validated"
                }
            )
        ),
        canonical_values_provider=object(),
    )
    turn = {
        "turn_id": "turn_unrelated_faq",
        "runtime_final_response": "Five years po ang listed warranty.",
        "order_readiness_after_tools": {
            "customer_order_intent": "active",
            "collected": {
                "Fulfillment": "installation",
                "Payment option": "Pay Later / Pay After Service",
            },
        },
        "background_signals_before_turn": [
            {
                "key": "payment_option",
                "value": "Pay Later",
                "source": "signal_ledger",
                "status": "tool_grounded",
                "metadata": {
                    "ledger": {
                        "authority_source": "validated_choice_action",
                        "authority_status": "tool_grounded",
                    }
                },
            }
        ],
    }

    _attach_checkout_choice_surface(
        turn,
        request=RuntimeV7APIRequest(
            user_id="trial",
            user_text="Ilang years ang warranty?",
        ),
        harness=harness,
    )

    assert "checkout_choice_surface" not in turn
    assert turn["checkout_choice_surface_status"]["reason"] == (
        "model_or_guided_payment_progression_missing"
    )


def test_new_payment_option_does_not_inherit_an_older_payment_method(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        api_runtime,
        "calculate_order_quote",
        lambda **_kwargs: {
            "quote_ref": "quote_switched_option",
            "service_path": "installation",
            "quote_breakdown": {},
        },
    )
    monkeypatch.setattr(
        api_runtime,
        "checkout_metadata",
        lambda _provider: {
            "source": "gulong_api_checkout_metadata",
            "payment_options": [
                {"id": 1, "name": "Pay Later"},
                {"id": 2, "name": "Pay Now"},
            ],
            "transaction_types": [{"id": 1, "trans_type": "Install"}],
            "payment_types": [
                {
                    "id": 20,
                    "main_payment_type_id": 2,
                    "name": "Gcash / PayMaya / Grab Pay",
                    "value": "E-WALLET",
                }
            ],
        },
    )
    harness = SimpleNamespace(
        latest_selected_product_context={
            "product_summary": {"brand": "MICHELIN"}
        },
        tools=SimpleNamespace(store=object()),
        service_tools=SimpleNamespace(
            store=SimpleNamespace(
                latest_validated_slot_context=lambda: {
                    "validation_status": "slot_validated"
                }
            )
        ),
        canonical_values_provider=object(),
    )
    turn = {
        "turn_id": "turn_switch_payment_option",
        "order_readiness_after_tools": {
            "customer_order_intent": "active",
            "collected": {
                "Fulfillment": "installation",
                "Payment option": "Pay Later / Pay After Service",
                "Payment method": "BPI-INSTALLMENT",
            },
        },
        "background_signals_before_turn": [],
    }
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="Pay Now",
        flow_context={
            "choice_action_runtime_context": {
                "validation_status": "valid",
                "choice_type": "payment_option_selection",
                "value": "Pay Now",
            }
        },
    )

    _attach_checkout_choice_surface(turn, request=request, harness=harness)

    assert turn["checkout_choice_surface"]["choice_type"] == (
        "payment_method_selection"
    )
    assert [
        choice["label"]
        for choice in turn["checkout_choice_surface"]["choices"]
    ] == ["Gcash / PayMaya / Grab Pay"]


def test_delivery_checkout_controls_require_complete_address(
    monkeypatch,
) -> None:
    quote = {
        "quote_ref": "quote_delivery",
        "service_path": "delivery",
        "quote_breakdown": {
            "payment_options_preview": {
                "pay_now": {"discount_text": "PHP 100.00"},
                "pay_later": {"reservation_fee_text": "PHP 500.00"},
            }
        },
    }
    metadata = {
        "source": "gulong_api_checkout_metadata",
        "payment_options": [
            {"id": 1, "name": "Pay Later"},
            {"id": 2, "name": "Pay Now"},
        ],
        "transaction_types": [{"id": 2, "trans_type": "Delivery"}],
        "payment_types": [],
    }
    monkeypatch.setattr(api_runtime, "calculate_order_quote", lambda **_kwargs: quote)
    monkeypatch.setattr(api_runtime, "checkout_metadata", lambda _provider: metadata)
    harness = SimpleNamespace(
        latest_selected_product_context={
            "product_summary": {"brand": "APOLLO"}
        },
        tools=SimpleNamespace(store=object()),
        service_tools=SimpleNamespace(store=object()),
        canonical_values_provider=object(),
    )
    request = RuntimeV7APIRequest(user_id="trial", user_text="Proceed")
    partial_turn = {
        "turn_id": "turn_delivery_partial",
        "order_readiness_after_tools": {
            "customer_order_intent": "active",
            "collected": {"Delivery area": "San Pedro, Laguna"},
        },
        "background_signals_before_turn": [],
    }
    complete_turn = {
        "turn_id": "turn_delivery_complete",
        "order_readiness_after_tools": {
            "customer_order_intent": "active",
            "collected": {
                "Delivery address": "123 Example Street, San Pedro, Laguna"
            },
        },
        "background_signals_before_turn": [
            {
                "key": "order_summary_review_confirmation",
                "value": "yes",
                "source": "latest_user_message",
                "status": "provided_by_latest_user_message",
            }
        ],
    }

    _attach_checkout_choice_surface(
        partial_turn,
        request=request,
        harness=harness,
    )
    _attach_checkout_choice_surface(
        complete_turn,
        request=request,
        harness=harness,
    )

    assert "checkout_choice_surface" not in partial_turn
    assert complete_turn["checkout_choice_surface"]["choice_type"] == (
        "payment_option_selection"
    )


def test_return_only_choice_delivery_is_recorded_as_evaluated() -> None:
    assert (
        api_runtime._interaction_delivery_status(
            {
                "status": "skipped",
                "reason": "return_only",
            }
        )
        == "evaluated"
    )
    assert (
        api_runtime._interaction_delivery_status({"status": "success"})
        == "success"
    )

    harness = SimpleNamespace(
        choice_presentation_history=[],
        latest_choice_presentation={},
    )
    rendered = SimpleNamespace(
        choice_presentations=[
            {
                "presentation_ref": "pres_return_only",
                "choice_type": "product_selection",
                "choices": [{"card_ref": "card_apollo"}],
            }
        ]
    )
    _remember_choice_delivery_result(
        harness,
        rendered,
        {
            "status": "skipped",
            "reason": "return_only",
            "delivery_mode": "return_only",
        },
    )

    assert harness.latest_choice_presentation["delivery_status"] == "evaluated"


def test_new_choice_surface_supersedes_older_location_surface() -> None:
    harness = SimpleNamespace(
        choice_presentation_history=[
            {
                "presentation_ref": "old_provinces",
                "choice_type": "serviceable_province",
                "choices": [{"choice_ref": "location:province:PH-40"}],
                "delivery_status": "success",
            }
        ],
        latest_choice_presentation={},
    )
    rendered = SimpleNamespace(
        choice_presentations=[
            {
                "presentation_ref": "new_products",
                "choice_type": "product_selection",
                "choices": [{"choice_ref": "product:card_1"}],
            }
        ]
    )

    _remember_choice_delivery_result(
        harness,
        rendered,
        {"status": "success"},
    )

    assert harness.choice_presentation_history[0]["superseded_at"]
    assert (
        harness.choice_presentation_history[0]["superseded_by_ref"]
        == "new_products"
    )


def test_same_recent_choice_is_a_semantic_duplicate() -> None:
    surface = build_payment_option_surface(
        quote={
            "quote_ref": "quote_duplicate",
            "quote_breakdown": {
                "payment_options_preview": {
                    "pay_now": {"discount_text": "PHP 100.00"},
                }
            },
        },
        metadata={
            "source": "gulong_api_checkout_metadata",
            "payment_options": [{"id": 2, "name": "Pay Now"}],
        },
        turn_id="turn_duplicate",
    )
    choice = surface["choices"][0]
    harness = RuntimeV7Harness(
        model_client=EmptyModel(),
        tools=ProductToolHarness(),
        service_tools=RuntimeV7ServiceTools(),
    )
    harness.choice_presentation_history = [
        {**surface, "delivery_status": "success"}
    ]
    harness.choice_action_history = [
        {
            "presentation_ref": surface["presentation_ref"],
            "choice_ref": choice["choice_ref"],
            "choice_type": "payment_option_selection",
            "validation_status": "valid",
            "delivery_status": "success",
            "delivered_at": datetime.now().astimezone().isoformat(),
        }
    ]
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="generic repeat click",
        idempotency_key="new_manychat_event_id",
        flow_context={
            "choice_action_context": {
                "presentation_ref": surface["presentation_ref"],
                "choice_ref": choice["choice_ref"],
                "choice_type": "payment_option_selection",
            }
        },
    )

    _remember_choice_action_attempt(harness, request)

    context = request.flow_context["choice_action_runtime_context"]
    assert context["validation_status"] == "duplicate"
    assert context["duplicate_reason"] == (
        "same_delivered_choice_recently_processed"
    )


def test_superseded_choice_surface_is_rejected() -> None:
    harness = RuntimeV7Harness(
        model_client=EmptyModel(),
        tools=ProductToolHarness(),
        service_tools=RuntimeV7ServiceTools(),
    )
    harness.choice_presentation_history = [
        {
            "presentation_ref": "old_payment",
            "choice_type": "payment_option_selection",
            "choices": [
                {
                    "choice_ref": "option_2",
                    "label": "Pay Now",
                    "value": "Pay Now",
                }
            ],
            "delivery_status": "success",
            "superseded_at": datetime.now().astimezone().isoformat(),
            "superseded_by_ref": "new_schedule",
        }
    ]
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="stale click",
        idempotency_key="stale_choice",
        flow_context={
            "choice_action_context": {
                "presentation_ref": "old_payment",
                "choice_ref": "option_2",
                "choice_type": "payment_option_selection",
            }
        },
    )

    _remember_choice_action_attempt(harness, request)

    assert (
        request.flow_context["choice_action_runtime_context"][
            "validation_status"
        ]
        == "stale"
    )


def test_promo_provider_failure_is_not_rendered_as_no_promo() -> None:
    turn = {
        "assistant_text": "Wala tayong active promos ngayon.",
        "runtime_final_response": "Wala tayong active promos ngayon.",
        "tool_results": [
            {
                "name": "search_promo_catalog",
                "full_result": {
                    "status": "unavailable",
                    "reason": "promo_catalog_disabled",
                },
            }
        ],
    }

    _apply_promo_provider_truth_guard(turn)

    assert turn["promo_provider_truth_guard"]["status"] == "rewritten"
    assert "hindi ko ma-verify" in turn["runtime_final_response"]
    assert "wala tayong active promos" not in turn["runtime_final_response"].casefold()


def test_unmatched_promo_brand_requires_answer_and_hides_partial_product_surface() -> None:
    turn = {
        "runtime_final_response": "Pakipili po ng option para makapagpatuloy tayo.",
        "tool_results": [
            {
                "name": "product_search",
                "full_result": {
                    "status": "partial_match",
                    "product_cards": [{"brand": "TOYO"}],
                },
            },
            {
                "name": "search_promo_catalog",
                "full_result": {
                    "status": "ok",
                    "requested_brands": ["Toyo"],
                    "matched_requested_brands": [],
                    "unmatched_requested_brands": ["Toyo"],
                    "exact_requested_brand_match": False,
                    "allowed_promo_refs": [
                        "promo:apollo",
                        "promo:michelin",
                    ],
                    "candidates": [
                        {
                            "promo_ref": "promo:apollo",
                            "brands": ["Apollo"],
                            "query_constraint_match": True,
                        },
                        {
                            "promo_ref": "promo:michelin",
                            "brands": ["Michelin"],
                            "query_constraint_match": True,
                        },
                    ],
                },
            },
            {
                "name": "present_promo_gallery",
                "full_result": {
                    "status": "ok",
                    "presentation_ref": "promo_gallery_alternatives",
                    "cards": [{"title": "Apollo 3+1"}],
                },
            },
        ],
    }

    _apply_promo_provider_truth_guard(turn)

    assert "current reviewed promos" in turn["runtime_final_response"]
    assert "Toyo" in turn["runtime_final_response"]
    assert "Apollo, Michelin" in turn["runtime_final_response"]
    assert "promo_gallery_alternatives" in turn["runtime_final_response"]
    assert '"type": "render_surface"' in turn["runtime_final_response"]
    assert turn["suppressed_channel_surface_tools"] == ["product_search"]
    assert turn["promo_provider_truth_guard"] == {
        "status": "rewritten",
        "reason": "unmatched_requested_promo_brand_requires_answer",
        "unmatched_requested_brands": ["Toyo"],
        "partial_product_surface_suppressed": True,
    }


def test_unmatched_promo_brand_keeps_correct_composer_answer() -> None:
    original = (
        "Wala akong verified current 3+1 promo for Toyo. "
        "May Apollo and Michelin alternatives."
    )
    turn = {
        "runtime_final_response": original,
        "tool_results": [
            {
                "name": "product_search",
                "full_result": {
                    "status": "partial_match",
                    "product_cards": [{"brand": "TOYO"}],
                },
            },
            {
                "name": "search_promo_catalog",
                "full_result": {
                    "status": "ok",
                    "requested_brands": ["Toyo"],
                    "unmatched_requested_brands": ["Toyo"],
                    "exact_requested_brand_match": False,
                },
            },
        ],
    }

    _apply_promo_provider_truth_guard(turn)

    assert turn["runtime_final_response"] == original
    assert turn["suppressed_channel_surface_tools"] == ["product_search"]
    assert turn["promo_provider_truth_guard"]["status"] == "validated"


def test_unmatched_promo_brand_keeps_grounded_alternative_product_surface() -> None:
    original = (
        "Wala tayong verified promo for Requested catalog brand. "
        "Here are current discounted alternatives for the same size."
    )
    turn = {
        "runtime_final_response": original,
        "tool_results": [
            {
                "name": "product_search",
                "full_result": {
                    "status": "partial_match",
                    "product_cards": [],
                },
            },
            {
                "name": "product_search",
                "full_result": {
                    "status": "ok",
                    "product_cards": [
                        {
                            "brand": "Alternative catalog brand",
                            "promo_savings_line": "Current catalog discount",
                            "pricing_facts": {
                                "included_promos": [
                                    "Current catalog discount"
                                ]
                            },
                        }
                    ],
                },
            },
            {
                "name": "search_promo_catalog",
                "full_result": {
                    "status": "ok",
                    "requested_brands": ["Requested catalog brand"],
                    "unmatched_requested_brands": [
                        "Requested catalog brand"
                    ],
                    "exact_requested_brand_match": False,
                    "allowed_promo_refs": [],
                },
            },
        ],
    }

    _apply_promo_provider_truth_guard(turn)

    assert turn["runtime_final_response"] == original
    assert "suppressed_channel_surface_tools" not in turn
    assert turn["promo_provider_truth_guard"] == {
        "status": "validated",
        "reason": "unmatched_requested_promo_brand_scoped_answer",
        "unmatched_requested_brands": ["Requested catalog brand"],
        "partial_product_surface_suppressed": False,
    }


def test_live_api_promo_authority_overrides_missing_gallery_brand() -> None:
    original = (
        "Yes po, kasali ang Vredestein sa current Buy 3 Get 1 promo. "
        "Ito ang matching option at price for four tires."
    )
    turn = {
        "runtime_final_response": original,
        "tool_results": [
            {
                "name": "product_search",
                "full_result": {
                    "status": "ok",
                    "promo_evidence": {
                        "authority": "gulong_api_promo_brands",
                        "verified_brands": [
                            "APOLLO",
                            "MICHELIN",
                            "VREDESTEIN",
                        ],
                    },
                    "product_cards": [
                        {
                            "brand": "VREDESTEIN",
                            "promo_savings_line": "Buy 3 Get 1 FREE",
                        }
                    ],
                },
            },
            {
                "name": "search_promo_catalog",
                "full_result": {
                    "status": "ok",
                    "requested_brands": ["Vredestein"],
                    "unmatched_requested_brands": ["Vredestein"],
                    "exact_requested_brand_match": False,
                },
            },
        ],
    }

    _apply_promo_provider_truth_guard(turn)

    assert turn["runtime_final_response"] == original
    assert "promo_provider_truth_guard" not in turn
    assert "suppressed_channel_surface_tools" not in turn


def test_structured_product_promo_overrides_missing_gallery_brand_without_evidence_block() -> None:
    original = (
        "Yes po, may current Buy 3 Get 1 ang Vredestein. "
        "PHP 12,840 yung total for four tires."
    )
    turn = {
        "runtime_final_response": original,
        "tool_results": [
            {
                "name": "search_promo_catalog",
                "args": {"promo_types": ["buy3get1"]},
                "full_result": {
                    "status": "ok",
                    "requested_brands": ["Vredestein"],
                    "unmatched_requested_brands": ["Vredestein"],
                    "exact_requested_brand_match": False,
                },
            },
            {
                "name": "product_search",
                "full_result": {
                    "status": "ok",
                    "product_cards": [
                        {
                            "brand": "VREDESTEIN",
                            "promo_savings_line": "Buy 3 Get 1 FREE",
                            "pricing_facts": {
                                "pricing_basis": "buy3get1",
                                "included_promos": ["Buy 3 Get 1 FREE"],
                            },
                        }
                    ],
                },
            },
        ],
    }

    _apply_promo_provider_truth_guard(turn)

    assert turn["runtime_final_response"] == original
    assert "promo_provider_truth_guard" not in turn
    assert "suppressed_channel_surface_tools" not in turn


def test_authoritative_payment_brand_exclusion_is_rendered_as_ineligible() -> None:
    turn = {
        "assistant_text": "Yokohama is not eligible for BPI 6 months.",
        "runtime_final_response": "Yokohama is not eligible for BPI 6 months.",
        "tool_results": [
            {
                "name": "answer_order_faq",
                "full_result": {
                    "status": "ok",
                    "payment_policy": {
                        "source": "gulong_api_checkout_metadata",
                        "requested_payment_method": "BPI 6 months 0%",
                        "requested_product_brand": "Yokohama",
                        "requested_brand_eligibility": "not_eligible",
                    },
                },
            }
        ],
    }

    _apply_payment_policy_truth_guard(turn)

    assert "payment_policy_truth_guard" not in turn
    assert turn["runtime_final_response"] == (
        "Yokohama is not eligible for BPI 6 months."
    )
    assert "Yokohama" in turn["runtime_final_response"]


def test_payment_guard_preserves_all_restrictive_facts_in_multi_question_turn() -> None:
    turn = {
        "runtime_final_response": (
            "Home Credit is not currently supported, but BPI 6 months is "
            "available for Yokohama."
        ),
        "tool_results": [
            {
                "name": "answer_order_faq",
                "full_result": {
                    "payment_policy": {
                        "source": "gulong_api_checkout_metadata",
                        "requested_payment_method": "Home Credit",
                        "requested_payment_status": "unsupported",
                    }
                },
            },
            {
                "name": "answer_order_faq",
                "full_result": {
                    "payment_policy": {
                        "source": "gulong_api_checkout_metadata",
                        "requested_payment_method": "BPI",
                        "requested_payment_status": "ready",
                        "requested_product_brand": "Yokohama",
                        "requested_brand_eligibility": "not_eligible",
                    }
                },
            },
        ],
    }

    _apply_payment_policy_truth_guard(turn)

    response = turn["runtime_final_response"]
    assert (
        "Hindi po available ang Home Credit bilang payment method"
        in response
    )
    assert "Hindi po available ang BPI para sa Yokohama" in response
    assert turn["payment_policy_truth_guard"] == {
        "status": "rewritten",
        "reason": "multi_claim_payment_facts_use_checkout_authority",
        "sources": ["gulong_api_checkout_metadata"],
        "claim_count": 2,
    }


def test_payment_guard_keeps_composer_multi_claim_answer_when_all_facts_are_covered() -> None:
    original = (
        "Home Credit is not currently supported. BPI 6 months is not "
        "available for Yokohama under Pay Later."
    )
    turn = {
        "runtime_final_response": original,
        "tool_results": [
            {
                "name": "answer_order_faq",
                "full_result": {
                    "payment_policy": {
                        "source": "gulong_api_checkout_metadata",
                        "requested_payment_method": "Home Credit",
                        "requested_payment_status": "unsupported",
                    }
                },
            },
            {
                "name": "answer_order_faq",
                "full_result": {
                    "payment_policy": {
                        "source": "gulong_api_checkout_metadata",
                        "requested_payment_method": "BPI 6 months",
                        "requested_payment_status": "ready",
                        "requested_product_brand": "Yokohama",
                        "requested_brand_eligibility": "not_eligible",
                    }
                },
            },
        ],
    }

    _apply_payment_policy_truth_guard(turn)

    assert turn["runtime_final_response"] == original
    assert "payment_policy_truth_guard" not in turn


def test_payment_guard_accepts_natural_taglish_without_exact_policy_labels() -> None:
    original = (
        "Para sa Yokohama tires, available po ang 3 months installment na "
        "0% interest under Pay Later. Pero, hindi po available ang BPI "
        "6 months installment na 0% interest para sa Yokohama. Anong tire "
        "size po ang hanap niyo?"
    )
    turn = {
        "runtime_final_response": original,
        "tool_results": [
            {
                "name": "answer_order_faq",
                "full_result": {
                    "payment_policy": {
                        "source": "gulong_api_checkout_metadata",
                        "requested_payment_method": "3 months installment",
                        "requested_payment_name": (
                            "3-mos Installment (0% interest)"
                        ),
                        "requested_payment_status": "ready",
                        "requested_payment_type_id": 9,
                        "requested_product_brand": "YOKOHAMA",
                        "requested_brand_eligibility": "not_brand_restricted",
                        "payment_option": "Pay Later",
                    }
                },
            },
            {
                "name": "answer_order_faq",
                "full_result": {
                    "payment_policy": {
                        "source": "gulong_api_checkout_metadata",
                        "requested_payment_method": "BPI 6 months installment",
                        "requested_payment_name": (
                            "BPI 6-mos Installment (0% interest)"
                        ),
                        "requested_payment_status": "ready",
                        "requested_payment_type_id": 10,
                        "requested_product_brand": "YOKOHAMA",
                        "requested_brand_eligibility": "not_eligible",
                        "payment_option": "Pay Later",
                    }
                },
            },
        ],
    }

    _apply_payment_policy_truth_guard(turn)

    assert turn["runtime_final_response"] == original
    assert "payment_policy_truth_guard" not in turn
    assert turn["commercial_payment_claims"] == [
        {
            "outcome": "eligible",
            "method": "3-mos Installment (0% interest)",
            "requested_method": "3 months installment",
            "brand": "YOKOHAMA",
            "payment_option": "Pay Later",
            "source": "gulong_api_checkout_metadata",
            "source_updated_at": None,
        },
        {
            "outcome": "not_eligible",
            "method": "BPI 6-mos Installment (0% interest)",
            "requested_method": "BPI 6 months installment",
            "brand": "YOKOHAMA",
            "payment_option": "Pay Later",
            "source": "gulong_api_checkout_metadata",
            "source_updated_at": None,
        },
    ]


def test_composer_owned_turn_still_records_provider_backed_payment_claims() -> None:
    turn = {
        "runtime_final_response": (
            "Home Credit is unavailable. The three-month option is available "
            "for Yokohama, but BPI six-month is not."
        ),
        "final_composer_status": "used",
        "tool_results": [
            {
                "name": "answer_order_faq",
                "full_result": {
                    "payment_policy": {
                        "source": "gulong_api_checkout_metadata",
                        "requested_payment_method": "Home Credit",
                        "requested_payment_status": "unsupported",
                    }
                },
            },
            {
                "name": "answer_order_faq",
                "full_result": {
                    "payment_policy": {
                        "source": "gulong_api_checkout_metadata",
                        "requested_payment_method": "3 months installment",
                        "requested_payment_name": "3-mos Installment (0% interest)",
                        "requested_payment_status": "ready",
                        "requested_product_brand": "YOKOHAMA",
                        "requested_brand_eligibility": "not_brand_restricted",
                        "payment_option": "Pay Later",
                    }
                },
            },
            {
                "name": "answer_order_faq",
                "full_result": {
                    "payment_policy": {
                        "source": "gulong_api_checkout_metadata",
                        "requested_payment_method": "BPI 6 months installment",
                        "requested_payment_name": "BPI 6-mos Installment (0% interest)",
                        "requested_payment_status": "ready",
                        "requested_product_brand": "YOKOHAMA",
                        "requested_brand_eligibility": "not_eligible",
                        "payment_option": "Pay Later",
                    }
                },
            },
        ],
    }

    claims = _record_commercial_payment_claims(turn)

    assert [claim["outcome"] for claim in claims] == [
        "unsupported",
        "eligible",
        "not_eligible",
    ]
    assert [claim["method"] for claim in claims] == [
        "Home Credit",
        "3-mos Installment (0% interest)",
        "BPI 6-mos Installment (0% interest)",
    ]
    assert turn["runtime_final_response"].startswith("Home Credit")


def test_commercial_claim_observability_does_not_infer_from_response_text() -> None:
    turn = {
        "runtime_final_response": "Home Credit is unavailable.",
        "final_composer_status": "used",
        "tool_results": [],
    }

    assert _record_commercial_payment_claims(turn) == []
    assert turn["commercial_payment_claims"] == []


def test_runtime_completes_each_compound_installment_brand_query() -> None:
    provider = SimpleNamespace(
        brands=lambda: ["APOLLO", "YOKOHAMA"],
        checkout_metadata=lambda: {
            "source": "gulong_api_checkout_metadata",
            "generated_at_epoch_s": 1785038400,
            "ttl_seconds": 900,
            "payment_options": [
                {"id": 1, "name": "Pay Later"},
                {"id": 2, "name": "Pay Now"},
            ],
            "transaction_types": [{"id": 1, "trans_type": "Installation"}],
            "payment_types": [
                {
                    "id": 10,
                    "main_payment_type_id": 1,
                    "name": "BPI 6-mos Installment (0% interest)",
                    "value": "BPI-INSTALLMENT",
                    "is_installment": True,
                    "available_brands": "MICHELIN, APOLLO",
                },
                {
                    "id": 9,
                    "main_payment_type_id": 1,
                    "name": "3-mos Installment (0% interest)",
                    "value": "3-MOS-INSTALLMENT",
                    "is_installment": True,
                    "available_brands": "",
                },
            ],
        },
    )
    harness = SimpleNamespace(
        latest_selected_product_context={},
        canonical_values_provider=provider,
    )
    turn = {
        "runtime_final_response": (
            "Yes, eligible ang Apollo for BPI 6 months under Pay Later. "
            "Hindi ko pa ma-confirm ang Yokohama 3-month installment."
        ),
        "order_readiness_before_turn": {"collected": {}},
        "payment_query_decision": {
            "decision": "payment_request",
            "payment_queries": [
                {
                    "scope_kind": "named_method",
                    "requested_payment_method": "BPI 6 months installment",
                    "requested_product_brand": "APOLLO",
                    "payment_option": "Pay Later",
                },
                {
                    "scope_kind": "named_method",
                    "requested_payment_method": "3 months installment",
                    "requested_product_brand": "YOKOHAMA",
                    "payment_option": "Pay Later",
                },
            ],
        },
        "background_signals_before_turn": [
            {
                "key": "required_brands",
                "value": ["APOLLO", "YOKOHAMA"],
                "source": "latest_user_message",
                "status": "mentioned_by_latest_user_message",
            }
        ],
        "tool_results": [
            {
                "name": "answer_order_faq",
                "full_result": {
                    "payment_policy": {
                        "source": "gulong_api_checkout_metadata",
                        "requested_payment_method": "BPI 6 months installment",
                        "requested_payment_status": "ready",
                        "requested_payment_type_id": 10,
                        "requested_product_brand": "APOLLO",
                        "requested_brand_eligibility": "eligible",
                        "payment_option": "Pay Later",
                    }
                },
            },
            {
                "name": "answer_order_faq",
                "full_result": {
                    "payment_policy": {
                        "source": "gulong_api_checkout_metadata",
                        "requested_payment_method": "BPI",
                        "requested_payment_status": "ready",
                        "requested_payment_type_id": 10,
                        "requested_product_brand": "APOLLO",
                        "requested_brand_eligibility": "eligible",
                        "payment_option": "Pay Later",
                    }
                },
            },
        ],
    }

    _apply_payment_policy_truth_guard(
        turn,
        request=RuntimeV7APIRequest(
            user_id="trial",
            user_text=(
                "Pwede ba BPI 6 months installment sa Apollo kung Pay Later? "
                "At 3 months installment sa Yokohama?"
            ),
        ),
        harness=harness,
    )

    assert len(turn["tool_results"]) == 3
    assert turn["payment_policy_lookup"] == {
        "status": "runtime_required",
        "reason": "model_omitted_compound_payment_policy_lookup",
        "lookup_count": 1,
    }
    response = turn["runtime_final_response"]
    assert (
        "Available po ang BPI 6 months installment para sa Apollo "
        "under Pay Later"
        in response
    )
    assert (
        "Available po ang 3-month installment 0% interest para sa "
        "Yokohama under Pay Later"
        in response
    )
    assert response.count("para sa Apollo") == 1
    assert "Anong tire size po ang hanap niyo?" not in response
    assert turn["payment_policy_truth_guard"]["claim_count"] == 2












def test_semantic_payment_query_plan_preserves_every_compound_scope() -> None:
    turn = {
        "payment_query_decision": {
            "decision": "payment_option_lookup",
            "payment_queries": [
                {
                    "requested_payment_method": "Example Finance",
                },
                {
                    "requested_payment_method": "3 months installment",
                    "requested_product_brand": "EXAMPLE BRAND",
                    "payment_option": "Pay Later",
                },
                {
                    "requested_payment_method": "BPI 6 months installment",
                    "requested_product_brand": "EXAMPLE BRAND",
                    "payment_option": "Pay Later",
                },
                {
                    "requested_payment_method": "available e-wallets",
                    "scope_kind": "method_category",
                    "method_category": "e_wallet",
                },
            ],
        }
    }
    request = RuntimeV7APIRequest(
        user_id="trial-semantic-payment",
        user_text="compound payment question",
    )

    plans = _semantic_customer_payment_query_plans(turn, request=request)

    assert plans == [
        {
            "question": "Example Finance",
            "requested_payment_method": "Example Finance",
        },
        {
            "question": "3 months installment",
            "requested_payment_method": "3 months installment",
            "requested_product_brand": "EXAMPLE BRAND",
            "payment_option": "Pay Later",
        },
        {
            "question": "BPI 6 months installment",
            "requested_payment_method": "BPI 6 months installment",
            "requested_product_brand": "EXAMPLE BRAND",
            "payment_option": "Pay Later",
        },
        {
            "question": "How do I Pay?",
            "requested_payment_category": "e_wallet",
        },
    ]




def test_wallet_aliases_do_not_absorb_distinct_financial_products() -> None:
    assert local_canonical_payment_method("Maya") == "maya"
    assert local_canonical_payment_method("via PayMaya wallet") == "maya"
    assert local_canonical_payment_method("GCash QR payment") == "gcash"
    assert local_canonical_payment_method("Maya Credit") is None
    assert local_canonical_payment_method("GCash loan") is None










def test_composer_payment_contract_dedupes_rows_and_repairs_missing_claim() -> None:
    tool_results = [
        {
            "name": "answer_order_faq",
            "result": {
                "payment_policy": {
                    "source": "gulong_api_checkout_metadata",
                    "requested_payment_method": "BPI",
                    "requested_payment_name": (
                        "BPI 6-mos Installment (0% interest)"
                    ),
                    "requested_payment_status": "ready",
                    "requested_payment_type_id": 10,
                    "requested_product_brand": "YOKOHAMA",
                    "requested_brand_eligibility": "not_eligible",
                    "payment_option": "Pay Later / Pay After Service",
                }
            },
        },
        {
            "name": "answer_order_faq",
            "result": {
                "payment_policy": {
                    "source": "gulong_api_checkout_metadata",
                    "requested_payment_method": "BPI installment",
                    "requested_payment_name": (
                        "BPI 6-mos Installment (0% interest)"
                    ),
                    "requested_payment_status": "ready",
                    "requested_payment_type_id": 10,
                    "requested_product_brand": "YOKOHAMA",
                    "requested_brand_eligibility": "not_eligible",
                    "payment_option": "Pay Later / Pay After Service",
                }
            },
        },
        {
            "name": "answer_order_faq",
            "result": {
                "payment_policy": {
                    "source": "gulong_api_checkout_metadata",
                    "requested_payment_method": "3 months installment",
                    "requested_payment_name": (
                        "3-mos Installment (0% interest)"
                    ),
                    "requested_payment_status": "ready",
                    "requested_payment_type_id": 9,
                    "requested_product_brand": "YOKOHAMA",
                    "requested_brand_eligibility": "not_brand_restricted",
                    "payment_option": "Pay Later / Pay After Service",
                }
            },
        },
    ]
    initial = json.dumps(
        {
            "response_units": [
                {
                    "type": "text",
                    "content": {
                        "text": (
                            "Hindi po available ang BPI 6 months installment "
                            "para sa Yokohama."
                        )
                    },
                },
                {
                    "type": "text",
                    "content": {
                        "text": (
                            "Iche-check ko pa ang 3 months installment para "
                            "sa Yokohama."
                        )
                    },
                },
            ]
        }
    )

    assert len(payment_policies_from_tool_results(tool_results)) == 2
    violations = payment_claim_contract_violations(initial, tool_results)
    missing_claims = [
        item
        for item in violations
        if item["type"]
        == "commercial_payment_claim_missing_or_contradicted"
    ]
    assert len(missing_claims) == 1
    assert missing_claims[0]["claim"]["outcome"] == "eligible"
    assert missing_claims[0]["claim"]["method"] == (
        "3-mos Installment (0% interest)"
    )
    assert any(
        item["type"] == "commercial_payment_scope_missing"
        for item in violations
    )

    repaired = json.dumps(
        {
            "response_units": [
                {
                    "type": "text",
                    "content": {
                        "text": (
                            "Para sa Yokohama under Pay Later, available po "
                            "ang 3-month installment na 0% interest. Hindi "
                            "naman po available ang BPI 6-month installment "
                            "na 0% interest para sa Yokohama."
                        )
                    },
                }
            ]
        }
    )
    assert payment_claim_contract_violations(repaired, tool_results) == []


def test_payment_claim_contract_accepts_natural_taglish_negative_phrasing() -> None:
    tool_results = [
        {
            "name": "answer_order_faq",
            "full_result": {
                "payment_policy": {
                    "source": "gulong_api_checkout_metadata",
                    "requested_payment_method": "BPI 6 months installment",
                    "requested_payment_name": (
                        "BPI 6-mos Installment (0% interest)"
                    ),
                    "requested_payment_status": "ready",
                    "requested_payment_type_id": 10,
                    "requested_product_brand": "YOKOHAMA",
                    "requested_brand_eligibility": "not_eligible",
                    "payment_option": "Pay Later",
                }
            },
        }
    ]

    for response in (
        "Sa Pay Later, hindi po kasama ang BPI 6 months option para sa Yokohama.",
        "Under Pay Later, BPI 6 months is not applicable for Yokohama.",
        "For Pay Later, BPI 6 months doesn't apply to Yokohama.",
        "Walang BPI 6 months installment para sa Yokohama under Pay Later.",
        (
            "Sa current Pay Later options natin, wala pa pong BPI 6 months "
            "para sa Yokohama."
        ),
    ):
        assert payment_claim_contract_violations(
            response,
            tool_results,
        ) == []


def test_payment_claim_contract_accepts_customer_credit_card_wording() -> None:
    tool_results = [
        {
            "name": "answer_order_faq",
            "full_result": {
                "payment_policy": {
                    "source": "gulong_api_checkout_metadata",
                    "requested_payment_method": "credit card",
                    "requested_payment_name": (
                        "Straight Credit Card / Debit Card"
                    ),
                    "requested_payment_status": "ready",
                    "requested_payment_type_id": 7,
                    "requested_product_brand": "APOLLO",
                    "requested_brand_eligibility": "not_brand_restricted",
                    "payment_option": "Pay Now",
                }
            },
        }
    ]

    assert payment_claim_contract_violations(
        "Yes po, puwede ang credit card for Apollo under Pay Now.",
        tool_results,
    ) == []
    assert any(
        item["type"] == "commercial_payment_claim_missing_or_contradicted"
        for item in payment_claim_contract_violations(
            "Yes po, puwede ang installment for Apollo under Pay Now.",
            tool_results,
        )
    )


def test_payment_claim_contract_requires_shared_payment_scope_once() -> None:
    tool_results = [
        {
            "name": "answer_order_faq",
            "full_result": {
                "payment_policy": {
                    "source": "gulong_api_checkout_metadata",
                    "requested_payment_method": "3 months installment",
                    "requested_payment_name": (
                        "3-mos Installment (0% interest)"
                    ),
                    "requested_payment_status": "ready",
                    "requested_payment_type_id": 9,
                    "requested_product_brand": "YOKOHAMA",
                    "requested_brand_eligibility": "not_brand_restricted",
                    "payment_option": "Pay Later",
                }
            },
        }
    ]

    missing_scope = payment_claim_contract_violations(
        "Para sa Yokohama, puwede po ang 3-month 0% installment.",
        tool_results,
    )
    assert any(
        item["type"] == "commercial_payment_scope_missing"
        for item in missing_scope
    )
    assert payment_claim_contract_violations(
        "Under Pay Later, puwede po ang 3-month 0% installment sa Yokohama.",
        tool_results,
    ) == []


def test_payment_claim_contract_accepts_shared_brand_scope_in_natural_sentence() -> None:
    tool_results = [
        {
            "name": "answer_order_faq",
            "full_result": {
                "payment_policy": {
                    "source": "gulong_api_checkout_metadata",
                    "requested_payment_method": "Home Credit",
                    "requested_payment_status": "unsupported",
                }
            },
        },
        {
            "name": "answer_order_faq",
            "full_result": {
                "payment_policy": {
                    "source": "gulong_api_checkout_metadata",
                    "requested_payment_method": "3 months installment",
                    "requested_payment_name": (
                        "3-mos Installment (0% interest)"
                    ),
                    "requested_payment_status": "ready",
                    "requested_payment_type_id": 9,
                    "requested_product_brand": "YOKOHAMA",
                    "requested_brand_eligibility": "not_brand_restricted",
                    "payment_option": "Pay Later",
                }
            },
        },
        {
            "name": "answer_order_faq",
            "full_result": {
                "payment_policy": {
                    "source": "gulong_api_checkout_metadata",
                    "requested_payment_method": "BPI 6 months installment",
                    "requested_payment_name": (
                        "BPI 6-mos Installment (0% interest)"
                    ),
                    "requested_payment_status": "ready",
                    "requested_payment_type_id": 10,
                    "requested_product_brand": "YOKOHAMA",
                    "requested_brand_eligibility": "not_eligible",
                    "payment_option": "Pay Later",
                }
            },
        },
    ]
    response = (
        "Sa current options natin, wala pa pong Home Credit. Sa Yokohama "
        "Pay Later naman, puwede yung 3-month 0%, pero hindi kasama yung "
        "BPI 6-month 0%."
    )

    assert payment_claim_contract_violations(response, tool_results) == []


def test_final_composer_requires_conversational_claim_synthesis() -> None:
    prompt = " ".join(
        __import__(
            "runtime_v7.runtime_harness",
            fromlist=["FINAL_COMPOSER_SYSTEM_PROMPT"],
        ).FINAL_COMPOSER_SYSTEM_PROMPT.split()
    )

    assert "Grounded claim objects are facts to preserve" in prompt
    assert "Do not use one bullet, paragraph, or repeated sentence template per fact" in prompt
    assert "Make the next question feel connected" in prompt
    assert "Naturalness must never soften, omit, or alter a validated fact" in prompt


def test_final_composer_payload_exposes_required_commercial_claims() -> None:
    messages = _build_final_composer_messages(
        current_user_message=(
            "Sa Yokohama Pay Later, 3 months o BPI 6 months?"
        ),
        request_time="2026-07-30 14:00:00",
        active_working_memory="",
        background_signals=[],
        lead_qualification={},
        order_readiness={},
        capability_profile={},
        tool_results=[
            {
                "name": "answer_order_faq",
                "full_result": {
                    "payment_policy": {
                        "source": "gulong_api_checkout_metadata",
                        "requested_payment_method": "3 months installment",
                        "requested_payment_name": (
                            "3-mos Installment (0% interest)"
                        ),
                        "requested_payment_status": "ready",
                        "requested_payment_type_id": 9,
                        "requested_product_brand": "YOKOHAMA",
                        "requested_brand_eligibility": (
                            "not_brand_restricted"
                        ),
                        "payment_option": "Pay Later / Pay After Service",
                    }
                },
            }
        ],
        draft_assistant_text="",
    )
    payload = json.loads(messages[-1]["content"])

    assert payload["required_commercial_claims"] == [
        {
            "availability": "puwede",
            "method": "3-month 0% installment",
            "brand": "YOKOHAMA",
            "payment_option": "Pay Later",
            "source": "gulong_api_checkout_metadata",
            "source_updated_at": None,
        }
    ]
    assert "friendly human Filipino customer-service agent" in messages[0]["content"]
    assert "policy row per fact" in messages[0]["content"]


def test_tracked_choice_uses_recent_free_text_for_language_register() -> None:
    messages = _build_final_composer_messages(
        current_user_message=(
            "I selected one exact tire from the product buttons. "
            "Continue from that validated product selection."
        ),
        request_time="2026-07-30 14:00:00",
        active_working_memory="",
        recent_turns=[
            {
                "role": "user",
                "content": (
                    "Budget but safe po, installation sa Dasmarinas."
                ),
            }
        ],
        background_signals=[],
        lead_qualification={},
        order_readiness={},
        capability_profile={},
        tool_results=[],
        draft_assistant_text="",
        tracked_interaction=True,
    )
    payload = json.loads(messages[-1]["content"])

    assert payload["customer_voice_contract"]["language"] == (
        "continue_recent_free_text_customer_language"
    )
    assert "tracked action text is synthetic" in (
        payload["customer_voice_contract"]["language_boundary"]
    )
    assert payload["customer_voice_contract"][
        "synthetic_action_text_is_language_sample"
    ] is False
    assert "this rule overrides" in messages[0]["content"]


def test_final_composer_keeps_validated_promo_action_scope() -> None:
    promo_context = {
        "status": "valid",
        "action": "promo_details",
        "promo": {
            "title": "APOLLO 3+1 PROMO",
            "offer_summary": (
                "Get 1 FREE for every purchase of 3 Apollo tires."
            ),
            "relevant_mechanics": [
                {"text": "This promo is applicable to Apollo tires."}
            ],
        },
    }
    messages = _build_final_composer_messages(
        current_user_message="Promo Details",
        request_time="2026-07-30 14:00:00",
        active_working_memory="",
        recent_turns=[
            {
                "role": "user",
                "content": "Ano yung Apollo promo?",
            }
        ],
        background_signals=[],
        lead_qualification={},
        order_readiness={},
        capability_profile={},
        tool_results=[],
        draft_assistant_text="",
        tracked_interaction=True,
        response_seed_overrides=[
            {
                "type": "promo_action",
                "priority": "high",
                "guidance": "Use only the reviewed promo details.",
                "evidence": promo_context,
            }
        ],
    )
    payload = json.loads(messages[-1]["content"])

    assert payload["response_seed_context"][0]["evidence"] == promo_context
    assert "does not prove that every SKU" in messages[0]["content"]
    assert 'never expand it to "all", "every", or "lahat"' in (
        messages[0]["content"]
    )


def test_composer_claims_hide_internal_eligibility_labels() -> None:
    claims = _final_composer_required_commercial_claims(
        [
            {
                "name": "answer_order_faq",
                "full_result": {
                    "payment_policy": {
                        "source": "gulong_api_checkout_metadata",
                        "requested_payment_method": (
                            "BPI 6 months installment"
                        ),
                        "requested_payment_name": (
                            "BPI 6-mos Installment (0% interest)"
                        ),
                        "requested_payment_status": "ready",
                        "requested_payment_type_id": 10,
                        "requested_product_brand": "YOKOHAMA",
                        "requested_brand_eligibility": "not_eligible",
                        "payment_option": "Pay Later",
                    }
                },
            }
        ]
    )

    assert claims[0]["availability"] == "hindi_kasama"
    assert "outcome" not in claims[0]
    assert "eligibility" not in claims[0]


def test_composer_payment_tool_payload_hides_internal_eligibility() -> None:
    payload = _final_composer_tool_result_payload(
        "answer_order_faq",
        {
            "status": "ok",
            "payment_policy": {
                "source": "gulong_api_checkout_metadata",
                "requested_payment_method": "BPI 6 months installment",
                "requested_payment_name": (
                    "BPI 6-mos Installment (0% interest)"
                ),
                "requested_payment_status": "ready",
                "requested_product_brand": "YOKOHAMA",
                "requested_brand_eligibility": "not_eligible",
                "payment_option": "Pay Later",
            },
        },
    )

    policy = payload["payment_policy"]
    assert policy["availability"] == "hindi_kasama"
    assert policy["method"] == "BPI 6-month 0% installment"
    assert "requested_brand_eligibility" not in policy
    assert "eligible" not in json.dumps(policy).casefold()


def test_final_composer_duplicate_intro_greeting_requires_model_repair() -> None:
    response = json.dumps(
        {
            "response_units": [
                {
                    "type": "text",
                    "content": {"text": "Hello po! Ito yung options."},
                }
            ]
        }
    )

    assert _final_composer_voice_contract_violations(
        response,
        first_turn_intro_context={"runtime_will_prepend": True},
    ) == [
        {
            "type": "duplicate_greeting_after_runtime_intro",
            "instruction": (
                "Runtime already prepends the welcome bubble. Remove the "
                "composer greeting and continue directly with the answer."
            ),
        }
    ]
    assert _final_composer_voice_contract_violations(
        response,
        first_turn_intro_context={"runtime_will_prepend": False},
    ) == []


def test_model_owned_first_turn_opening_must_precede_surface() -> None:
    response = json.dumps(
        {
            "response_units": [
                {
                    "type": "render_surface",
                    "content": {"surface_ref": "pres_product_opening_test"},
                },
                {
                    "type": "text",
                    "content": {
                        "text": "Good morning po! Gulong.ph here—ito yung choices."
                    },
                },
            ]
        }
    )

    assert _final_composer_voice_contract_violations(
        response,
        first_turn_intro_context={
            "runtime_will_prepend": False,
            "model_will_compose": True,
            "mode": "welcome_only",
        },
    ) == [
        {
            "type": "first_turn_model_opening_missing_before_surface",
            "instruction": (
                "Write one complete natural first-turn opening text unit "
                "before any renderer surface. "
                "Choose the greeting, acknowledgement, answer, tone, and "
                "wording for this customer; do not copy a fixed script."
            ),
        }
    ]


def test_model_owned_first_turn_opening_allows_natural_non_greeting_wording() -> None:
    response = json.dumps(
        {
            "response_units": [
                {
                    "type": "text",
                    "content": {
                        "text": (
                            "Yes po, available kami to assist. Ano po yung "
                            "tire concern na gusto ninyong ma-check?"
                        )
                    },
                },
                {
                    "type": "render_surface",
                    "content": {"surface_ref": "pres_service_opening_test"},
                },
            ]
        }
    )

    assert _final_composer_voice_contract_violations(
        response,
        first_turn_intro_context={
            "runtime_will_prepend": False,
            "model_will_compose": True,
            "mode": "welcome_only",
        },
    ) == []


def test_search_intermediary_inventory_voice_requires_model_repair() -> None:
    response = json.dumps(
        {
            "response_units": [
                {
                    "type": "text",
                    "content": {
                        "text": (
                            "Hello po! May nakita po kaming budget options "
                            "para sa size ninyo."
                        )
                    },
                },
                {
                    "type": "render_surface",
                    "content": {"surface_ref": "pres_product_voice_test"},
                },
            ]
        }
    )

    violations = _final_composer_voice_contract_violations(
        response,
        first_turn_intro_context={
            "runtime_will_prepend": False,
            "model_will_compose": True,
            "mode": "welcome_only",
        },
    )

    assert [item["type"] for item in violations] == [
        "search_intermediary_brand_voice"
    ]


def test_model_owned_first_turn_opening_rejects_blank_first_text() -> None:
    response = json.dumps(
        {
            "response_units": [
                {"type": "text", "content": {"text": "   "}},
                {
                    "type": "render_surface",
                    "content": {"surface_ref": "pres_product_blank_opening"},
                },
            ]
        }
    )

    assert _final_composer_voice_contract_violations(
        response,
        first_turn_intro_context={"model_will_compose": True},
    )[0]["type"] == "first_turn_model_opening_missing_before_surface"


def test_final_composer_payload_places_voice_contract_after_draft() -> None:
    messages = _build_final_composer_messages(
        current_user_message="Boss, may Home Credit ba?",
        request_time="2026-07-30 14:30:00",
        active_working_memory="",
        background_signals=[],
        lead_qualification={},
        order_readiness={},
        capability_profile={},
        tool_results=[],
        draft_assistant_text=(
            "Home Credit is unavailable bilang payment method."
        ),
        first_turn_intro_context={
            "runtime_will_prepend": False,
            "model_will_compose": True,
            "mode": "welcome_only",
        },
    )
    payload = json.loads(messages[-1]["content"])
    keys = list(payload)
    voice = payload["customer_voice_contract"]

    assert keys.index("customer_voice_contract") > keys.index(
        "draft_assistant_text"
    )
    assert voice["continuity"] == "compose_first_turn_opening"
    assert set(voice) == {
        "register",
        "language",
        "language_boundary",
        "continuity",
    }
    assert "English stays English" in voice["language_boundary"]


def test_commercial_answer_contract_groups_shared_scope_without_new_methods() -> None:
    tool_results = [
        {
            "name": "answer_order_faq",
            "full_result": {
                "payment_policy": {
                    "source": "gulong_api_checkout_metadata",
                    "requested_payment_method": "Home Credit",
                    "requested_payment_status": "unsupported",
                }
            },
        },
        {
            "name": "answer_order_faq",
            "full_result": {
                "payment_policy": {
                    "source": "gulong_api_checkout_metadata",
                    "requested_payment_method": "3 months installment",
                    "requested_payment_name": (
                        "3-mos Installment (0% interest)"
                    ),
                    "requested_payment_status": "ready",
                    "requested_payment_type_id": 9,
                    "requested_product_brand": "YOKOHAMA",
                    "requested_brand_eligibility": "not_brand_restricted",
                    "payment_option": "Pay Later",
                }
            },
        },
    ]

    contract = _final_composer_commercial_answer_contract(tool_results)

    assert contract["shared_scope"] == {
        "brand": "YOKOHAMA",
        "payment_option": "Pay Later",
    }
    assert "required factual qualifier" in contract["shared_scope_usage"]
    assert contract["allowed_methods"] == [
        "Home Credit",
        "3-month 0% installment",
    ]
    assert all(item["brand"] == "" for item in contract["facts"])
    assert contract["next_question_context"] == {
        "known_brand": "YOKOHAMA",
        "do_not_reask_known_brand": True,
        "preferred_focus_if_needed": "tire_size",
        "do_not_add_other_missing_fields": True,
    }
    assert "without adding as/bilang" in contract["facts"][0][
        "wording_hint"
    ]


def test_pure_payment_policy_turn_drops_untrusted_draft_wording() -> None:
    tool_results = [
        {
            "name": "answer_order_faq",
            "full_result": {
                "payment_policy": {
                    "source": "gulong_api_checkout_metadata",
                    "requested_payment_method": "Home Credit",
                    "requested_payment_status": "unsupported",
                }
            },
        }
    ]

    assert _final_composer_draft_text(
        "Home Credit is unavailable bilang payment method.",
        tool_results=tool_results,
    ) == ""
    assert _final_composer_draft_text(
        "May payment answer at product options.",
        tool_results=[
            *tool_results,
            {"name": "product_search", "full_result": {"status": "ok"}},
        ],
    ) == "May payment answer at product options."


def test_single_unsupported_method_uses_short_conversational_shape() -> None:
    contract = _final_composer_commercial_answer_contract(
        [
            {
                "name": "answer_order_faq",
                "full_result": {
                    "payment_policy": {
                        "source": "gulong_api_checkout_metadata",
                        "requested_payment_method": "Sample Wallet",
                        "requested_payment_status": "unsupported",
                    }
                },
            }
        ]
    )

    assert contract["style_shape"] == (
        "Wala pa po tayong {unsupported}. {one tire-size question}"
    )
    assert contract["next_question_context"][
        "do_not_add_other_missing_fields"
    ] is True


def test_payment_claim_contract_rejects_cross_method_association() -> None:
    tool_results = [
        {
            "name": "answer_order_faq",
            "full_result": {
                "payment_policy": {
                    "source": "gulong_api_checkout_metadata",
                    "requested_payment_method": "Home Credit",
                    "requested_payment_status": "unsupported",
                }
            },
        },
        {
            "name": "answer_order_faq",
            "full_result": {
                "payment_policy": {
                    "source": "gulong_api_checkout_metadata",
                    "requested_payment_method": "3 months installment",
                    "requested_payment_name": (
                        "3-mos Installment (0% interest)"
                    ),
                    "requested_payment_status": "ready",
                    "requested_payment_type_id": 9,
                    "requested_product_brand": "YOKOHAMA",
                    "requested_brand_eligibility": "not_brand_restricted",
                    "payment_option": "Pay Later",
                }
            },
        },
        {
            "name": "answer_order_faq",
            "full_result": {
                "payment_policy": {
                    "source": "gulong_api_checkout_metadata",
                    "requested_payment_method": "BPI 6 months installment",
                    "requested_payment_name": (
                        "BPI 6-mos Installment (0% interest)"
                    ),
                    "requested_payment_status": "ready",
                    "requested_payment_type_id": 10,
                    "requested_product_brand": "YOKOHAMA",
                    "requested_brand_eligibility": "not_eligible",
                    "payment_option": "Pay Later",
                }
            },
        },
    ]

    for response, leaked in (
        (
            "Home Credit is unavailable. Pwede ang BPI 3 months 0% "
            "for Yokohama. Hindi available ang BPI 6 months for Yokohama.",
            "bpi",
        ),
        (
            "Home Credit is unavailable. Available through Home Credit ang "
            "3 months 0% for Yokohama. Hindi available ang BPI 6 months "
            "for Yokohama.",
            "home",
        ),
    ):
        violations = payment_claim_contract_violations(
            response,
            tool_results,
        )
        association = [
            item
            for item in violations
            if item["type"]
            == "commercial_payment_claim_cross_association"
        ]
        assert association
        assert leaked in association[0]["leaked_method_anchors"]

    valid = (
        "Home Credit is unavailable. Pwede ang 3 months 0% for Yokohama "
        "under Pay Later. Hindi available ang BPI 6 months for Yokohama."
    )
    assert payment_claim_contract_violations(valid, tool_results) == []


def test_payment_claim_contract_rejects_cross_method_with_shared_brand_scope() -> None:
    tool_results = [
        {
            "name": "answer_order_faq",
            "full_result": {
                "payment_policy": {
                    "source": "gulong_api_checkout_metadata",
                    "requested_payment_method": "3 months installment",
                    "requested_payment_name": (
                        "3-mos Installment (0% interest)"
                    ),
                    "requested_payment_status": "ready",
                    "requested_payment_type_id": 9,
                    "requested_product_brand": "YOKOHAMA",
                    "requested_brand_eligibility": "not_brand_restricted",
                    "payment_option": "Pay Later",
                }
            },
        },
        {
            "name": "answer_order_faq",
            "full_result": {
                "payment_policy": {
                    "source": "gulong_api_checkout_metadata",
                    "requested_payment_method": "BPI 6 months installment",
                    "requested_payment_name": (
                        "BPI 6-mos Installment (0% interest)"
                    ),
                    "requested_payment_status": "ready",
                    "requested_payment_type_id": 10,
                    "requested_product_brand": "YOKOHAMA",
                    "requested_brand_eligibility": "not_eligible",
                    "payment_option": "Pay Later",
                }
            },
        },
    ]
    response = (
        "Para sa Yokohama Pay Later, for BPI installment puwede ang "
        "3 months 0%. Pero hindi kasama ang BPI 6 months 0%."
    )

    violations = payment_claim_contract_violations(response, tool_results)

    assert any(
        item["type"] == "commercial_payment_claim_cross_association"
        for item in violations
    )


def test_final_composer_voice_rules_are_top_priority() -> None:
    prompt = " ".join(FINAL_COMPOSER_SYSTEM_PROMPT.split())
    response_schema_index = prompt.index("Return one structured object")

    for required_rule in (
        "Highest-priority customer voice",
        "entirely English",
        'Never start with "Regarding"',
        'Never write "as payment method"',
        "never precede the CTA with a separate permission",
        "Do not attach a bank/provider",
        "Speak as Gulong.ph for routine grounded catalog and service results",
    ):
        assert required_rule in prompt
        assert prompt.index(required_rule) < response_schema_index


def test_final_composer_temperature_is_low_variance_and_overridable(
    monkeypatch,
) -> None:
    class TemperatureClient:
        def __init__(self) -> None:
            self.temperature = None

        def complete(
            self,
            *,
            messages,
            tools,
            tool_choice="auto",
            temperature=None,
        ):
            del messages, tools, tool_choice
            self.temperature = temperature
            return {"content": "{}"}

    monkeypatch.delenv("RUNTIME_V7_FINAL_COMPOSER_TEMPERATURE", raising=False)
    assert _final_composer_temperature() == 0.1
    monkeypatch.setenv("RUNTIME_V7_FINAL_COMPOSER_TEMPERATURE", "0.05")
    assert _final_composer_temperature() == 0.05

    client = TemperatureClient()
    _complete_model_client(
        client,
        messages=[],
        tools=[],
        temperature=_final_composer_temperature(),
    )
    assert client.temperature == 0.05


def test_payment_fallback_method_label_is_customer_friendly() -> None:
    assert _customer_payment_method_label(
        {
            "requested_payment_name": (
                "BPI 6-mos Installment (0% interest)"
            )
        }
    ) == "BPI 6-month installment 0% interest"
    assert _customer_payment_method_label(
        {
            "requested_payment_name": (
                "3-mos Installment (0% interest)"
            )
        }
    ) == "3-month installment 0% interest"


def test_payment_policy_dedupe_prefers_scoped_row_over_brandless_plan() -> None:
    policies = [
        {
            "requested_payment_type_id": 9,
            "requested_payment_name": "3-mos Installment (0% interest)",
            "requested_brand_eligibility": "needs_product_validation",
        },
        {
            "requested_payment_type_id": 9,
            "requested_payment_name": "3-mos Installment (0% interest)",
            "requested_product_brand": "YOKOHAMA",
            "requested_brand_eligibility": "not_brand_restricted",
        },
        {
            "requested_payment_type_id": 10,
            "requested_payment_name": "BPI 6-mos Installment (0% interest)",
            "requested_product_brand": "YOKOHAMA",
            "requested_brand_eligibility": "not_eligible",
        },
    ]

    deduped = dedupe_payment_policies(policies)

    assert len(deduped) == 2
    assert {
        (
            policy["requested_payment_type_id"],
            policy.get("requested_product_brand"),
        )
        for policy in deduped
    } == {(9, "YOKOHAMA"), (10, "YOKOHAMA")}


def test_payment_policy_dedupe_keeps_unbranded_fact_when_scoped_plan_conflicts() -> None:
    policies = [
        {
            "requested_payment_method": "Example Finance",
            "requested_payment_status": "unsupported",
        },
        {
            "requested_payment_method": "Example Finance",
            "requested_payment_status": "conflict",
            "requested_product_brand": "EXAMPLE BRAND",
        },
    ]

    deduped = dedupe_payment_policies(policies)

    assert len(deduped) == 2
    assert payment_claim(deduped[0])["outcome"] == "unsupported"


def test_payment_option_is_not_an_unsupported_payment_method_claim() -> None:
    assert payment_claim(
        {
            "requested_payment_method": "Pay Later",
            "requested_payment_status": "unsupported",
        }
    ) == {}


def test_unsupported_payment_method_claim_is_not_brand_scoped() -> None:
    claim = payment_claim(
        {
            "requested_payment_method": "Home Credit",
            "requested_payment_status": "unsupported",
            "requested_product_brand": "YOKOHAMA",
            "payment_option": "Pay Later",
        }
    )

    assert claim["outcome"] == "unsupported"
    assert claim["method"] == "Home Credit"
    assert claim["brand"] == ""
    assert claim["payment_option"] == ""


def test_runtime_completes_required_payment_lookup_when_model_omits_it() -> None:
    provider = SimpleNamespace(
        checkout_metadata=lambda: {
            "source": "gulong_api_checkout_metadata",
            "generated_at_epoch_s": 1785038400,
            "ttl_seconds": 900,
            "payment_options": [
                {"id": 1, "name": "Pay Later"},
                {"id": 2, "name": "Pay Now"},
            ],
            "transaction_types": [{"id": 1, "trans_type": "Installation"}],
            "payment_types": [
                {
                    "id": 10,
                    "main_payment_type_id": 1,
                    "name": "BPI 6-mos Installment (0% interest)",
                    "value": "BPI-INSTALLMENT",
                    "is_installment": True,
                    "available_brands": "MICHELIN, APOLLO",
                }
            ],
        }
    )
    harness = SimpleNamespace(
        latest_selected_product_context={
            "product_summary": {"brand": "YOKOHAMA"}
        },
        canonical_values_provider=provider,
    )
    turn = {
        "runtime_final_response": "I need to validate that later.",
        "payment_query_decision": {
            "decision": "payment_request",
            "payment_queries": [
                {
                    "scope_kind": "named_method",
                    "requested_payment_method": "BPI 6 months installment",
                    "requested_product_brand": "YOKOHAMA",
                    "payment_option": "Pay Later",
                }
            ],
        },
        "order_readiness_after_tools": {
            "collected": {
                "Product": "YOKOHAMA BLUEARTH ES32 175/65R14",
                "Fulfillment": "installation",
            }
        },
        "tool_results": [],
    }
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="Available ba BPI 6 months 0% for this Yokohama?",
    )

    _apply_payment_policy_truth_guard(
        turn,
        request=request,
        harness=harness,
    )

    assert "not currently available" in turn["runtime_final_response"]
    assert turn["payment_policy_lookup"]["status"] == "runtime_required"
    assert turn["tool_results"][-1]["source"] == (
        "runtime_required_payment_policy_lookup"
    )


def test_runtime_validates_parallel_product_and_payment_query_without_hiding_cards() -> None:
    provider = SimpleNamespace(
        checkout_metadata=lambda: {
            "source": "gulong_api_checkout_metadata",
            "generated_at_epoch_s": 1785038400,
            "ttl_seconds": 900,
            "payment_options": [
                {"id": 1, "name": "Pay Later"},
                {"id": 2, "name": "Pay Now"},
            ],
            "transaction_types": [
                {"id": 1, "trans_type": "Installation"},
                {"id": 3, "trans_type": "Delivery"},
            ],
            "payment_types": [
                {
                    "id": 10,
                    "main_payment_type_id": 1,
                    "name": "BPI 6-mos Installment (0% interest)",
                    "value": "BPI-INSTALLMENT",
                    "is_installment": True,
                    "available_brands": "MICHELIN, APOLLO",
                    "exclude_transaction_type_id": "3",
                },
                {
                    "id": 9,
                    "main_payment_type_id": 1,
                    "name": "3-mos Installment (0% interest)",
                    "value": "3-MOS-INSTALLMENT",
                    "is_installment": True,
                },
            ],
        }
    )
    harness = SimpleNamespace(
        latest_selected_product_context={},
        canonical_values_provider=provider,
    )
    turn = {
        "runtime_final_response": "May Yokohama options po.",
        "payment_query_decision": {
            "decision": "payment_option_lookup",
            "payment_queries": [
                {
                    "requested_payment_method": "BPI 6 months installment",
                    "requested_product_brand": "YOKOHAMA",
                    "payment_option": "Pay Later",
                }
            ],
        },
        "order_readiness_before_turn": {"collected": {}},
        "background_signals_before_turn": [
            {
                "key": "required_brands",
                "value": ["YOKOHAMA"],
                "source": "latest_user_message",
                "status": "mentioned_by_latest_user_message",
            },
            {
                "key": "payment_option",
                "value": "Pay Later",
                "source": "latest_user_message",
                "status": "mentioned_unconfirmed",
            },
            {
                "key": "payment_method",
                "value": "credit card installment",
                "source": "latest_user_message",
                "status": "mentioned_unconfirmed",
            },
            {
                "key": "bank",
                "value": "BPI",
                "source": "latest_user_message",
                "status": "mentioned_unconfirmed",
            },
            {
                "key": "installment_months",
                "value": "6",
                "source": "latest_user_message",
                "status": "mentioned_unconfirmed",
            },
        ],
        "tool_results": [
            {
                "name": "product_search",
                "full_result": {
                    "status": "ok",
                    "product_cards": [{"card_ref": "card_yokohama"}],
                },
            }
        ],
    }
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text=(
            "May Yokohama 195/60R15 ba? If Pay Later, available ba ang "
            "BPI 6 months 0%?"
        ),
    )

    _apply_payment_policy_truth_guard(
        turn,
        request=request,
        harness=harness,
    )

    assert "not currently available" in turn["runtime_final_response"]
    assert "YOKOHAMA" in turn["runtime_final_response"]
    assert turn["payment_policy_lookup"]["status"] == "runtime_required"
    assert "product_search" not in turn.get(
        "suppressed_channel_surface_tools",
        [],
    )


def test_runtime_does_not_insert_omitted_positive_payment_answer_after_composition() -> None:
    original = "May available po tayong Yokohama tires. Pili po sa product cards."
    turn = {
        "runtime_final_response": original,
        "order_readiness_before_turn": {"collected": {}},
        "tool_results": [
            {
                "name": "product_search",
                "full_result": {
                    "status": "ok",
                    "product_cards": [{"card_ref": "card_yokohama"}],
                },
            },
            {
                "name": "answer_order_faq",
                "full_result": {
                    "status": "ok",
                    "payment_policy": {
                        "source": "gulong_api_checkout_metadata",
                        "requested_payment_method": "3 months installment",
                        "requested_product_brand": "YOKOHAMA",
                        "requested_brand_eligibility": "not_brand_restricted",
                        "requested_payment_status": "ready",
                    },
                },
            },
        ],
    }

    _apply_payment_policy_truth_guard(
        turn,
        request=RuntimeV7APIRequest(
            user_id="trial",
            user_text=(
                "May Yokohama 195/60R15 ba? If Pay Later, available ba "
                "ang 3-month installment 0%?"
            ),
        ),
    )

    assert turn["runtime_final_response"] == original
    assert "payment_policy_truth_guard" not in turn
    assert "product_search" not in turn.get(
        "suppressed_channel_surface_tools",
        [],
    )


def test_runtime_keeps_model_answer_when_it_already_resolves_payment_query() -> None:
    original = (
        "Eligible po ang Michelin for BPI 6 months installment under Pay Later."
    )
    turn = {
        "runtime_final_response": original,
        "tool_results": [
            {
                "name": "answer_order_faq",
                "full_result": {
                    "payment_policy": {
                        "source": "gulong_api_checkout_metadata",
                        "requested_payment_method": "BPI 6 months installment",
                        "requested_product_brand": "MICHELIN",
                        "requested_brand_eligibility": "eligible",
                        "requested_payment_status": "ready",
                    },
                },
            }
        ],
    }

    _apply_payment_policy_truth_guard(
        turn,
        request=RuntimeV7APIRequest(
            user_id="trial",
            user_text=(
                "If Pay Later, available ba ang BPI 6 months for Michelin?"
            ),
        ),
    )

    assert turn["runtime_final_response"] == original
    assert "payment_policy_truth_guard" not in turn


def test_runtime_rejects_unknown_financing_provider_when_model_omits_lookup() -> None:
    provider = SimpleNamespace(
        checkout_metadata=lambda: {
            "source": "gulong_api_checkout_metadata",
            "generated_at_epoch_s": 1785038400,
            "ttl_seconds": 900,
            "payment_options": [
                {"id": 1, "name": "Pay Later"},
                {"id": 2, "name": "Pay Now"},
            ],
            "transaction_types": [{"id": 1, "trans_type": "Installation"}],
            "payment_types": [
                {
                    "id": 4,
                    "main_payment_type_id": 1,
                    "name": "GCash / PayMaya / Grab Pay",
                    "value": "E-WALLETS",
                    "is_installment": False,
                }
            ],
        }
    )
    harness = SimpleNamespace(
        latest_selected_product_context={},
        canonical_values_provider=provider,
    )
    turn = {
        "runtime_final_response": (
            "We can check Home Credit after you select a tire."
        ),
        "payment_query_decision": {
            "decision": "payment_request",
            "payment_queries": [
                {
                    "scope_kind": "named_method",
                    "requested_payment_method": "Home Credit",
                }
            ],
        },
        "tool_results": [],
        "background_signals_before_turn": [
            {
                "key": "payment_method",
                "value": "Home Credit",
                "source": "latest_user_message",
                "status": "mentioned_unconfirmed",
            }
        ],
    }
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="May 195/60R15 ba? Also, puwede ba Home Credit?",
    )

    _apply_payment_policy_truth_guard(
        turn,
        request=request,
        harness=harness,
    )

    assert "wala po sa current payment options" in turn["runtime_final_response"]
    assert "GCash / PayMaya / Grab Pay" in turn["runtime_final_response"]
    assert turn["payment_policy_lookup"]["status"] == "runtime_required"
    assert turn["payment_policy_truth_guard"]["reason"] == (
        "unsupported_method_uses_checkout_authority"
    )


def test_payment_policy_guard_does_not_treat_full_payment_as_a_method() -> None:
    turn = {
        "runtime_final_response": "Noted po ang full payment.",
        "tool_results": [
            {
                "name": "answer_order_faq",
                "full_result": {
                    "payment_policy": {
                        "source": "gulong_api_checkout_metadata",
                        "requested_payment_method": "Full payment",
                        "requested_payment_status": "unsupported",
                        "payment_option": "Pay Now",
                    }
                },
            }
        ],
    }

    _apply_payment_policy_truth_guard(turn)

    assert turn["runtime_final_response"] == "Noted po ang full payment."
    assert turn["payment_policy_truth_guard"] == {
        "status": "ignored",
        "reason": "payment_option_is_not_a_payment_method",
        "source": "gulong_api_checkout_metadata",
        "requested_payment_method": "Full payment",
    }








def test_payment_policy_guard_does_not_reask_size_after_product_selection() -> None:
    turn = {
        "runtime_final_response": "Yokohama is not eligible.",
        "order_readiness_after_tools": {
            "collected": {
                "Product": "YOKOHAMA BLUEARTH ES32 175/65R14",
                "Installation area": "San Pedro, Laguna",
            }
        },
        "tool_results": [
            {
                "name": "answer_order_faq",
                "full_result": {
                    "payment_policy": {
                        "source": "gulong_api_checkout_metadata",
                        "requested_payment_method": "BPI 6 months 0%",
                        "requested_product_brand": "Yokohama",
                        "requested_brand_eligibility": "needs_product_validation",
                    }
                },
            },
            {
                "name": "find_installation_slots",
                "full_result": {
                    "status": "ok",
                    "slot_groups": [{"date": "2026-07-29", "slots": [{}]}],
                },
            },
        ],
    }

    _apply_payment_policy_truth_guard(turn)

    response = turn["runtime_final_response"]
    assert "selected Yokohama" in response
    assert "Pili po muna ng preferred schedule" not in response
    assert "Ano pong tire size" not in response
    assert "preselecting" not in response


def test_payment_availability_question_without_policy_cannot_claim_support() -> None:
    turn = {
        "runtime_final_response": (
            "Good news, supported ang BPI 6 months for your selected tire."
        ),
        "payment_query_decision": {
            "decision": "payment_option_lookup",
            "payment_queries": [
                {
                    "requested_payment_method": "BPI 6 months installment",
                    "requested_product_brand": "YOKOHAMA",
                }
            ],
        },
        "order_readiness_after_tools": {
            "collected": {
                "Product": "YOKOHAMA BLUEARTH ES32 175/65R14",
            }
        },
        "tool_results": [
            {
                "name": "find_installation_slots",
                "full_result": {
                    "status": "ok",
                    "slot_groups": [{"date": "2026-07-29", "slots": [{}]}],
                },
            }
        ],
    }

    _apply_payment_policy_truth_guard(
        turn,
        request=RuntimeV7APIRequest(
            user_id="trial",
            user_text=(
                "Available ba ang BPI 6 months 0% for this selected Yokohama?"
            ),
        ),
    )

    response = turn["runtime_final_response"]
    assert "Hindi ko pa ma-confirm" in response
    assert "Pili po muna ng preferred schedule" not in response
    assert "Good news" not in response


def test_payment_truth_answer_survives_while_schedule_remains_only_choice(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE",
        "flow_test",
    )
    turn = _slot_turn()
    turn["runtime_final_response"] = (
        "Good news, supported ang BPI 6 months for the selected Yokohama."
    )
    turn["assistant_text"] = turn["runtime_final_response"]
    turn["payment_query_decision"] = {
        "decision": "payment_request",
        "payment_queries": [
            {
                "scope_kind": "named_method",
                "requested_payment_method": "BPI 6 months installment",
                "requested_product_brand": "YOKOHAMA",
                "payment_option": "Pay Later",
            }
        ],
    }
    turn["order_readiness_after_tools"] = {
        "collected": {
            "Product": "YOKOHAMA BLUEARTH ES32 175/65R14",
        }
    }
    turn["tool_results"].insert(
        0,
        {
            "name": "get_product_details",
            "full_result": {
                "status": "ok",
                "presentation_ref": "pres_selected_repeat",
                "selected_product_cards": [
                    {
                        "card_ref": "card_selected_repeat",
                        "sku_model": "YOKOHAMA BLUEARTH ES32 175/65R14",
                        "card_text": "YOKOHAMA BLUEARTH ES32 175/65R14",
                    }
                ],
                "card_runtime_insert": True,
            },
        },
    )

    _apply_payment_policy_truth_guard(
        turn,
        request=RuntimeV7APIRequest(
            user_id="trial",
            user_text=(
                "Available ba ang BPI 6 months 0% for this selected Yokohama?"
            ),
        ),
    )
    rendered = render_turn_for_channel(
        turn,
        service_environment="staging",
    )
    values = [
        str(action.get("value") or "")
        for message in rendered.content_messages
        if message.get("type") == "cards"
        for element in message.get("elements") or []
        for button in element.get("buttons") or []
        for action in button.get("actions") or []
    ]

    assert "Hindi ko pa ma-confirm" in rendered.text
    assert "Wala pa pong payment choice na na-set" in rendered.text
    assert "Pili po muna ng preferred schedule sa options" not in rendered.text
    assert "Good news" not in rendered.text
    assert any(value.startswith("ss1|") for value in values)
    assert not any(value.startswith(("po1|", "pm1|")) for value in values)
    assert "YOKOHAMA BLUEARTH ES32" in rendered.text
    assert "suppressed_channel_surface_tools" not in turn


def test_model_composed_turn_selects_one_of_schedule_and_payment_controls(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "PRICE_CATEGORY_LIVE_ROUTER_FLOW_NAMESPACE",
        "content_router",
    )
    slots = _slot_result(include_afternoon=True)
    payment = build_payment_option_surface(
        quote={
            "quote_ref": "quote_schedule_first",
            "quote_breakdown": {
                "payment_options_preview": {
                    "pay_now": {"discount_text": "PHP 100.00"},
                    "pay_later": {"reservation_fee_text": "PHP 500.00"},
                }
            },
        },
        metadata={
            "source": "gulong_api_checkout_metadata",
            "payment_options": [
                {"id": 1, "name": "Pay Later"},
                {"id": 2, "name": "Pay Now"},
            ],
        },
        turn_id="turn_schedule_first",
    )
    rendered = render_turn_for_channel(
        {
            "assistant_text": json.dumps(
                {
                    "response_units": [
                        {
                            "type": "render_surface",
                            "content": {
                                "surface_ref": slots["presentation_ref"]
                            },
                        }
                    ]
                }
            ),
            "final_composer": {"status": "used"},
            "tool_results": [
                {
                    "name": "find_installation_slots",
                    "round": 1,
                    "full_result": slots,
                }
            ],
            "checkout_choice_surface": payment,
        }
    )

    values = [
        action["value"]
        for message in rendered.content_messages
        if message.get("type") == "cards"
        for element in message.get("elements") or []
        for button in element.get("buttons") or []
        for action in button.get("actions") or []
    ]
    assert any(value.startswith("ss1|") for value in values)
    assert not any(value.startswith("po1|") for value in values)
    assert "choose how you want to pay" not in rendered.text.casefold()
