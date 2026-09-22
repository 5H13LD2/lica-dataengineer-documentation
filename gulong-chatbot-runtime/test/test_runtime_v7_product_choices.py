from __future__ import annotations

from runtime_v7.api_runtime import (
    RuntimeV7APIRequest,
    _delivered_product_price_list_fingerprints,
    _remember_choice_action_attempt,
    _response_seed_overrides_for_flow,
)
from runtime_v7.capability_profile import CapabilityProfile
from runtime_v7.choice_actions import (
    build_product_choice_token,
    parse_product_choice_token,
)
from runtime_v7.fulfillment_aliases import resolve_fulfillment_alias
from runtime_v7.model_contract import SERVICE_POLICY_PROMPT, build_runtime_v7_context
from runtime_v7.product_observations import ProductToolHarness
from runtime_v7.runtime_harness import (
    FINAL_COMPOSER_SYSTEM_PROMPT,
    RuntimeV7Harness,
    _apply_validated_choice_signal_boundaries,
    _build_final_composer_messages,
    _hydrate_service_tool_args,
    _prune_irrelevant_promo_tools_for_location_product_resume,
    _prune_redundant_product_tools_for_validated_choice,
)
from runtime_v7.service_observations import ServiceObservationStore
from runtime_v7.service_tools import _match_slot_candidate


class EmptyModel:
    def complete(self, **_kwargs):
        return {}


def _harness_with_delivered_product() -> RuntimeV7Harness:
    tools = ProductToolHarness()
    tools.store.save_search_result(
        {
            "observation_ref": "obs_products_1",
            "presentation_ref": "pres_products_1",
            "product_cards": [
                {
                    "card_ref": "card_1",
                    "item_ref": "prod_8255",
                    "product_id": 8255,
                    "slug": "falken-z154-195-65-r15",
                    "brand": "FALKEN",
                    "sku_model": "FALKEN ZIEX ZE154 195/65R15",
                    "tire_size": "195/65R15",
                    "deal_price_line": "PHP 18,480.00 for 4 tires",
                }
            ],
        }
    )
    harness = RuntimeV7Harness(model_client=EmptyModel(), tools=tools)
    harness.choice_presentation_history = [
        {
            "presentation_ref": "pres_products_1",
            "observation_ref": "obs_products_1",
            "surface_type": "product_choices",
            "choice_type": "product_selection",
            "delivery_status": "success",
            "choices": [
                {
                    "choice_ref": "product:card_1",
                    "card_ref": "card_1",
                    "item_ref": "prod_8255",
                    "product_id": "8255",
                    "slug": "falken-z154-195-65-r15",
                    "label": "FALKEN ZIEX ZE154 195/65R15",
                    "brand": "FALKEN",
                    "tire_size": "195/65R15",
                    "deal_price_line": "PHP 18,480.00 for 4 tires",
                    "position": 1,
                }
            ],
        }
    ]
    return harness


def test_product_choice_token_round_trip() -> None:
    token = build_product_choice_token(
        presentation_ref="pres_products_1",
        card_ref="card_1",
    )

    assert parse_product_choice_token(token) == {
        "presentation_ref": "pres_products_1",
        "card_ref": "card_1",
    }


def test_product_click_binds_exact_trusted_card_before_model_turn() -> None:
    harness = _harness_with_delivered_product()
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="generic click",
        idempotency_key="product_click_1",
        flow_context={
            "choice_action_context": {
                "presentation_ref": "pres_products_1",
                "card_ref": "card_1",
                "choice_type": "product_selection",
            }
        },
    )

    _remember_choice_action_attempt(harness, request)

    runtime_context = request.flow_context["choice_action_runtime_context"]
    assert runtime_context["validation_status"] == "valid"
    assert runtime_context["item_ref"] == "prod_8255"
    assert harness.latest_selected_product_context["product_card_ref"] == "card_1"
    assert harness.latest_selected_product_context["product_id"] == 8255
    assert "FALKEN ZIEX ZE154" in request.user_text
    assert "PHP 18,480.00 for 4 tires" not in request.user_text
    assert "4 tires" not in request.user_text
    assert resolve_fulfillment_alias(request.user_text) is None


def test_validated_product_click_exposes_next_layer_tools_without_reresolution() -> None:
    profile = CapabilityProfile(
        exposed_tools=[
            "product_search",
            "resolve_product_reference",
            "get_product_details",
            "find_installation_partners",
            "find_installation_slots",
            "answer_service_faq",
        ]
    )

    _prune_redundant_product_tools_for_validated_choice(
        profile,
        validated_choice_context={
            "validation_status": "valid",
            "choice_type": "product_selection",
            "card_ref": "card_1",
        },
        selected_product_context={
            "product_card_ref": "card_1",
            "product_id": 8255,
        },
    )

    assert profile.exposed_tools == [
        "find_installation_partners",
        "find_installation_slots",
    ]
    assert (
        "validated_product_click:product_resolution_satisfied"
        in profile.selection_reasons
    )


def test_unvalidated_product_reference_keeps_product_tools_available() -> None:
    profile = CapabilityProfile(
        exposed_tools=["product_search", "resolve_product_reference"]
    )

    _prune_redundant_product_tools_for_validated_choice(
        profile,
        validated_choice_context={
            "validation_status": "stale",
            "choice_type": "product_selection",
        },
        selected_product_context={"product_card_ref": "card_1"},
    )

    assert profile.exposed_tools == [
        "product_search",
        "resolve_product_reference",
    ]


def test_same_product_click_is_noop_when_prior_transition_is_in_state() -> None:
    harness = _harness_with_delivered_product()
    first = RuntimeV7APIRequest(
        user_id="trial",
        user_text="generic click",
        idempotency_key="product_click_first",
        flow_context={
            "choice_action_context": {
                "presentation_ref": "pres_products_1",
                "card_ref": "card_1",
                "choice_type": "product_selection",
            }
        },
    )
    _remember_choice_action_attempt(harness, first)
    harness.latest_choice_action["delivery_status"] = "success"
    harness.choice_action_history = []
    repeated = RuntimeV7APIRequest(
        user_id="trial",
        user_text="generic repeat click",
        idempotency_key="product_click_repeat",
        flow_context={
            "choice_action_context": {
                "presentation_ref": "pres_products_1",
                "card_ref": "card_1",
                "choice_type": "product_selection",
            }
        },
    )

    _remember_choice_action_attempt(harness, repeated)

    context = repeated.flow_context["choice_action_runtime_context"]
    assert context["validation_status"] == "duplicate"
    assert context["duplicate_reason"] == (
        "choice_already_applied_to_current_state"
    )


def test_same_product_click_is_noop_after_product_surface_is_superseded() -> None:
    harness = _harness_with_delivered_product()
    first = RuntimeV7APIRequest(
        user_id="trial",
        user_text="generic click",
        idempotency_key="product_click_first",
        flow_context={
            "choice_action_context": {
                "presentation_ref": "pres_products_1",
                "card_ref": "card_1",
                "choice_type": "product_selection",
            }
        },
    )
    _remember_choice_action_attempt(harness, first)
    harness.latest_choice_action["delivery_status"] = "success"
    harness.choice_action_history = []
    harness.choice_presentation_history[0]["superseded_at"] = (
        "2026-07-27 10:00:00"
    )
    harness.choice_presentation_history[0]["superseded_by_ref"] = (
        "location_choices_1"
    )
    repeated = RuntimeV7APIRequest(
        user_id="trial",
        user_text="generic repeat click",
        idempotency_key="product_click_repeat",
        flow_context={
            "choice_action_context": {
                "presentation_ref": "pres_products_1",
                "card_ref": "card_1",
                "choice_type": "product_selection",
            }
        },
    )

    _remember_choice_action_attempt(harness, repeated)

    context = repeated.flow_context["choice_action_runtime_context"]
    assert context["validation_status"] == "duplicate"
    assert context["duplicate_reason"] == (
        "choice_already_applied_to_current_state"
    )


def test_final_composer_requires_all_explicit_subquestions_to_be_covered() -> None:
    normalized_prompt = " ".join(FINAL_COMPOSER_SYSTEM_PROMPT.split())
    assert "check each distinct subquestion" in FINAL_COMPOSER_SYSTEM_PROMPT
    assert "Do not silently drop a subquestion" in FINAL_COMPOSER_SYSTEM_PROMPT
    assert (
        "If the customer is actively continuing and a post-surface question is useful"
        in FINAL_COMPOSER_SYSTEM_PROMPT
    )
    assert "A pause or close without a new question/action takes precedence" in normalized_prompt
    assert "make the product/size confirmation the only next requested" in (
        FINAL_COMPOSER_SYSTEM_PROMPT
    )
    assert "do not claim that other promos are shown" in (
        FINAL_COMPOSER_SYSTEM_PROMPT
    )
    assert "reasonable to request them" in FINAL_COMPOSER_SYSTEM_PROMPT
    assert "formal all-English form spiel" in FINAL_COMPOSER_SYSTEM_PROMPT
    assert 'Do not say "final na ang order"' in FINAL_COMPOSER_SYSTEM_PROMPT
    assert "Customer preferences guide the recommendation" in (
        FINAL_COMPOSER_SYSTEM_PROMPT
    )
    assert "Serviceable province/city choice cards" in (
        FINAL_COMPOSER_SYSTEM_PROMPT
    )
    assert "A gallery with tracked buttons is another decision layer" in (
        FINAL_COMPOSER_SYSTEM_PROMPT
    )


def test_service_prompt_requires_city_choices_before_province_schedule_progression() -> None:
    from runtime_v7.model_contract import build_runtime_v7_system_prompt

    service_prompt = build_runtime_v7_system_prompt(["service"])
    normalized_prompt = " ".join(service_prompt.split())

    assert "A province shown in the serviceable-province surface is valid installation" in normalized_prompt
    assert "not be described as rejected or unsupported" in normalized_prompt
    assert "discovery_mode=recommend_serviceable_cities" in service_prompt
    assert "retain the province instead of repeating the city CTA" in normalized_prompt


def test_validated_city_without_product_seeds_model_led_product_resume() -> None:
    seeds = _response_seed_overrides_for_flow(
        {
            "choice_action_runtime_context": {
                "validation_status": "valid",
                "choice_type": "serviceable_city",
                "label": "Mabalacat",
                "province_label": "Pampanga",
                "selected_product_ready": False,
            }
        }
    )

    assert len(seeds) == 1
    assert seeds[0]["type"] == "validated_location_before_product"
    assert "call product_search or discover_brand_buckets" in seeds[0][
        "guidance"
    ]
    assert "Do not repeat a broad promo gallery" in seeds[0]["guidance"]


def test_validated_city_with_product_does_not_force_product_resume() -> None:
    seeds = _response_seed_overrides_for_flow(
        {
            "choice_action_runtime_context": {
                "validation_status": "valid",
                "choice_type": "serviceable_city",
                "selected_product_ready": True,
            }
        }
    )

    assert not any(
        seed.get("type") == "validated_location_before_product"
        for seed in seeds
    )


def test_validated_city_without_product_keeps_product_tools_and_prunes_promos() -> None:
    profile = CapabilityProfile(
        candidate_tools=["find_installation_partners"],
        selected_domains=["service"],
        exposed_tools=[
            "find_installation_partners",
            "search_promo_catalog",
            "present_promo_gallery",
            "request_capability",
        ]
    )

    _prune_irrelevant_promo_tools_for_location_product_resume(
        profile,
        validated_choice_context={
            "validation_status": "valid",
            "choice_type": "serviceable_city",
        },
        selected_product_context={},
    )

    assert "product_search" in profile.exposed_tools
    assert "discover_brand_buckets" in profile.exposed_tools
    assert "product_search" in profile.candidate_tools
    assert "discover_brand_buckets" in profile.candidate_tools
    assert "product" in profile.selected_domains
    assert "find_installation_partners" in profile.exposed_tools
    assert "search_promo_catalog" not in profile.exposed_tools
    assert "present_promo_gallery" not in profile.exposed_tools
    assert "request_capability" in profile.exposed_tools


def test_validated_city_with_product_does_not_prune_promo_tools() -> None:
    profile = CapabilityProfile(
        exposed_tools=["product_search", "search_promo_catalog"]
    )

    _prune_irrelevant_promo_tools_for_location_product_resume(
        profile,
        validated_choice_context={
            "validation_status": "valid",
            "choice_type": "serviceable_city",
        },
        selected_product_context={"product_id": "prod-1"},
    )

    assert profile.exposed_tools == ["product_search", "search_promo_catalog"]


def test_tampered_product_click_does_not_change_selected_product_state() -> None:
    harness = _harness_with_delivered_product()
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="generic click",
        idempotency_key="product_click_2",
        flow_context={
            "choice_action_context": {
                "presentation_ref": "pres_products_1",
                "card_ref": "card_99",
                "choice_type": "product_selection",
            }
        },
    )

    _remember_choice_action_attempt(harness, request)

    assert request.flow_context["choice_action_runtime_context"]["validation_status"] == "stale"
    assert harness.latest_selected_product_context == {}
    assert "no longer current" in request.user_text


def test_validated_slot_context_exposes_exact_partner_for_high_intent_followup() -> None:
    store = ServiceObservationStore()
    store.save_installation_slots_result(
        {
            "observation_ref": "svc_slot_validated_1",
            "presentation_ref": "pres_slot_validated_1",
            "service_locations": [
                {
                    "installation_partner_ref": "partner_17",
                    "service_location_ref": "location_17",
                    "branch_id": 17,
                    "name": "RAPIDE SAN PEDRO",
                    "address": "National Highway, San Pedro, Laguna",
                    "area": "San Pedro, Laguna",
                }
            ],
            "slot_groups": [
                {
                    "slots": [
                        {
                            "slot_ref": "slot_17_2026-07-29_0930",
                            "date": "2026-07-29",
                            "time_text": "9:30 AM",
                        }
                    ]
                }
            ],
            "availability": {"availability_status": "slot_validated"},
        }
    )
    selected_product = {
        "product_observation_ref": "obs_products_1",
        "product_presentation_ref": "pres_products_1",
        "product_card_ref": "card_1",
        "product_item_ref": "prod_8255",
        "product_summary": {
            "brand": "FALKEN",
            "model": "FALKEN ZIEX ZE154 195/65R15",
            "size": "195/65R15",
            "customer_price_line": "PHP 18,480.00 for 4 tires",
        },
        "selection_source": "trusted_product_reference",
    }

    context = build_runtime_v7_context(
        current_user_message="Sige, pero saan ito i-install?",
        selected_product_context=selected_product,
        validated_installation_context=store.latest_validated_slot_context(),
        order_readiness={
            "status": "ready_for_summary",
            "customer_order_intent": "active",
            "can_prepare_order_summary": True,
            "collected": {
                "Product": "FALKEN ZIEX ZE154 195/65R15",
                "Schedule": "2026-07-29 9:30 AM",
            },
        },
    )

    assert "## Validated Selected Product" in context
    assert "Do not ask which product" in context
    assert "FALKEN ZIEX ZE154 195/65R15" in context
    assert "## Validated Installation Selection" in context
    assert "RAPIDE SAN PEDRO" in context
    assert "National Highway, San Pedro, Laguna" in context
    assert "not a booking" in context


def test_validated_slot_survives_a_later_partner_discovery_observation() -> None:
    store = ServiceObservationStore()
    store.save_installation_slots_result(
        {
            "observation_ref": "svc_slot_validated_1",
            "presentation_ref": "pres_slot_validated_1",
            "service_locations": [
                {
                    "installation_partner_ref": "partner_17",
                    "service_location_ref": "location_17",
                    "name": "RAPIDE SAN PEDRO",
                    "address": "National Highway, San Pedro, Laguna",
                }
            ],
            "slot_groups": [
                {
                    "slots": [
                        {
                            "slot_ref": "slot_17_2026-07-29_0930",
                            "date": "2026-07-29",
                            "time_text": "9:30 AM",
                        }
                    ]
                }
            ],
            "availability": {"availability_status": "slot_validated"},
        }
    )
    store.save_location_result(
        {
            "observation_ref": "svc_partner_lookup_2",
            "presentation_ref": "pres_partner_lookup_2",
            "service_locations": [
                {
                    "installation_partner_ref": "partner_99",
                    "service_location_ref": "location_99",
                    "name": "ANOTHER PARTNER",
                }
            ],
            "availability": {"availability_status": "partners_found"},
        }
    )

    context = store.latest_validated_slot_context()

    assert context["observation_ref"] == "svc_slot_validated_1"
    assert context["service_location"]["name"] == "RAPIDE SAN PEDRO"
    assert context["selected_slot"]["time_text"] == "9:30 AM"


def test_final_composer_receives_validated_installation_selection() -> None:
    validated_installation = {
        "validation_status": "slot_validated",
        "service_location": {
            "name": "RAPIDE SAN PEDRO",
            "address": "National Highway, San Pedro, Laguna",
        },
        "selected_slot": {
            "date": "2026-07-29",
            "time_text": "9:30 AM",
        },
    }

    messages = _build_final_composer_messages(
        current_user_message="Saan mismo ito i-install?",
        request_time="2026-07-24T14:00:00+08:00",
        active_working_memory="",
        recent_turns=[],
        background_signals=[],
        lead_qualification={},
        order_readiness={"missing": ["Contact number"]},
        capability_profile={},
        tool_results=[],
        draft_assistant_text="",
        validated_installation_context=validated_installation,
    )

    assert '"validated_installation_selection"' in messages[1]["content"]
    assert "RAPIDE SAN PEDRO" in messages[1]["content"]
    assert "do not render a general partner" in FINAL_COMPOSER_SYSTEM_PROMPT


def test_slot_validation_remains_customer_choice_driven() -> None:
    assert "Use validate_installation_slot only when the customer chooses" in (
        SERVICE_POLICY_PROMPT
    )
    assert "visible slot" in SERVICE_POLICY_PROMPT


def test_authoritative_tire_size_replaces_conflicting_model_search_args() -> None:
    events = []
    hydrated = _hydrate_service_tool_args(
        "product_search",
        {
            "section_width": "255",
            "aspect_ratio": "65",
            "rim_size": "R17",
        },
        [
            {
                "key": "tire_size",
                "value": "225/65R17",
                "source": "latest_user_message",
                "status": "corrected",
                "relation": "corrected",
            }
        ],
        normalization_events=events,
    )

    assert hydrated["section_width"] == "225"
    assert hydrated["aspect_ratio"] == "65"
    assert hydrated["rim_size"] == "R17"
    assert events == [
        {
            "type": "tool_args_restored_from_authoritative_tire_size",
            "tool_name": "product_search",
            "signal_key": "tire_size",
            "tire_size": "225/65R17",
            "replacements": {
                "section_width": {
                    "model_value": "255",
                    "authoritative_value": "225",
                }
            },
        }
    ]


def test_authoritative_delivery_replaces_conflicting_installation_tool_arg() -> None:
    events = []
    hydrated = _hydrate_service_tool_args(
        "find_installation_partners",
        {"service_type": "installation"},
        [
            {
                "key": "service_type",
                "value": "delivery",
                "source": "signal_ledger",
                "status": "retained",
                "relation": "selected",
                "metadata": {
                    "ledger": {
                        "authority_source": "latest_user_message",
                        "authority_status": "selected",
                    }
                },
            }
        ],
        normalization_events=events,
    )

    assert hydrated["service_type"] == "delivery"
    assert events[0]["model_value"] == "installation"
    assert events[0]["authoritative_value"] == "delivery"


def test_other_area_boundary_does_not_erase_retained_delivery_state() -> None:
    state = {
        "background_signals": [
            {
                "key": "service_type",
                "value": "delivery",
                "source": "signal_ledger",
            },
            {
                "key": "delivery_address",
                "value": "Meycauayan, Bulacan",
                "source": "signal_ledger",
            },
            {
                "key": "location",
                "value": "outside current guided choices",
                "source": "latest_user_message",
            },
        ]
    }

    _apply_validated_choice_signal_boundaries(
        state,
        validated_choice_context={
            "validation_status": "valid",
            "choice_type": "serviceable_province",
            "choice_code": "other",
            "recommended_service_path": "delivery",
            "service_path_selected": False,
        },
    )

    assert [signal["key"] for signal in state["background_signals"]] == [
        "service_type",
        "delivery_address",
    ]
    assert state["validated_choice_signal_boundary"]["removed_keys"] == [
        "location"
    ]


def test_delivered_price_list_requires_commercial_fingerprints_for_suppression() -> None:
    base = {
        "presentation_ref": "pres_products_1",
        "renderer_variant": "manychat_product_price_list_gallery_v2",
        "price_list_included": True,
        "gallery_included": True,
        "delivery_status": "success",
        "cards": [{"item_ref": "prod_8255"}],
    }

    assert _delivered_product_price_list_fingerprints([base]) == []
    complete = {
        **base,
        "commercial_fingerprints": ["pcf1:1234567890abcdef"],
    }

    assert _delivered_product_price_list_fingerprints([complete]) == [
        {
            "presentation_ref": "pres_products_1",
            "card_identities": ["item_ref:prod_8255"],
            "commercial_fingerprints": ["pcf1:1234567890abcdef"],
        }
    ]


def test_natural_slot_choice_matches_one_visible_candidate_only() -> None:
    candidates = [
        {
            "partner": {
                "installation_partner_ref": "partner_17",
                "address": "National Highway, San Pedro, Laguna",
            },
            "slot": {
                "slot_ref": "slot_1",
                "date": "2026-07-29",
                "time_text": "9:30 AM",
            },
        },
        {
            "partner": {"installation_partner_ref": "partner_17"},
            "slot": {
                "slot_ref": "slot_2",
                "date": "2026-07-29",
                "time_text": "11:00 AM",
            },
        },
    ]

    match = _match_slot_candidate(
        candidates,
        slot_ref="",
        slot_ordinal=0,
        partner_ref="",
        preferred_datetime="July 29 at 9:30 AM",
        preferred_date="",
        preferred_time="",
    )

    assert match["slot"]["slot_ref"] == "slot_1"
    assert match["partner"]["address"] == "National Highway, San Pedro, Laguna"
    ambiguous = _match_slot_candidate(
        [
            candidates[0],
            {
                "partner": {"installation_partner_ref": "partner_18"},
                "slot": {
                    "slot_ref": "slot_3",
                    "date": "2026-07-30",
                    "time_text": "9:30 AM",
                },
            },
        ],
        slot_ref="",
        slot_ordinal=0,
        partner_ref="",
        preferred_datetime="9:30 AM",
        preferred_date="",
        preferred_time="",
    )
    assert ambiguous == {}
