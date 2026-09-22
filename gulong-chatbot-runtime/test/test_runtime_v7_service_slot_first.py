from runtime_v7.model_contract import (
    ALL_RUNTIME_V7_TOOL_SCHEMAS,
    CTA_POLICY_PROMPT,
    CORE_SYSTEM_PROMPT,
    SERVICE_POLICY_PROMPT,
    build_runtime_v7_context,
    build_tool_objectives,
)
from runtime_v7.runtime_harness import _compact_tool_result


def test_service_objective_prefers_slots_when_product_context_is_visible():
    signals = [
        {
            "key": "service_type",
            "value": "installation",
            "source": "latest_user_message",
        },
        {
            "key": "location",
            "value": "Molino Blvd, Bacoor, Cavite",
            "source": "latest_user_message",
            "resolution": {
                "status": "resolved_location",
                "display_label": "Bacoor, Cavite",
            },
        },
    ]
    capability_profile = {
        "candidate_tools": ["find_installation_partners", "find_installation_slots"],
        "exposed_tools": ["find_installation_partners", "find_installation_slots"],
        "available_context_refs": {"product_presentation": True},
        "matched_signal_keys": {
            "find_installation_partners": ["location", "service_type"],
            "find_installation_slots": ["location", "service_type"],
        },
    }

    objectives = build_tool_objectives(
        background_signals=signals,
        capability_profile=capability_profile,
    )

    service_objectives = [
        objective
        for objective in objectives
        if objective.get("objective") == "service_slot_availability"
    ]
    assert service_objectives
    assert service_objectives[0]["tool"] == "find_installation_slots"
    assert "anonymous partner choices" in service_objectives[0]["reason"]


def test_tracked_product_choice_resumes_retained_installation_with_slots():
    signals = [
        {
            "key": "latest_product_presentation",
            "value": "pres_product_search_1",
            "source": "latest_user_message",
            "status": "tool_grounded",
        },
        {
            "key": "specific_sku_model",
            "value": "FRONWAY ECOGREEN ONE 175/65R14",
            "source": "latest_user_message",
        },
        {
            "key": "service_type",
            "value": "installation",
            "source": "signal_ledger",
            "status": "remembered_signal",
        },
        {
            "key": "location",
            "value": "Dasmarinas City, Cavite",
            "source": "signal_ledger",
            "status": "remembered_signal",
            "resolution": {
                "status": "resolved_location",
                "display_label": "Dasmarinas City, Cavite",
            },
        },
    ]
    capability_profile = {
        "candidate_tools": [
            "find_installation_slots",
            "build_order_summary",
        ],
        "exposed_tools": [
            "find_installation_slots",
            "build_order_summary",
        ],
        "available_context_refs": {
            "product_observation": True,
            "product_presentation": False,
        },
        "selection_reasons": [
            "validated_product_click:product_resolution_satisfied",
        ],
        "order_readiness": {
            "high_intent_signals": ["product selected", "installation context"],
        },
        "matched_signal_keys": {
            "find_installation_slots": ["location", "service_type"],
        },
    }

    objectives = build_tool_objectives(
        background_signals=signals,
        capability_profile=capability_profile,
    )

    service = next(
        row
        for row in objectives
        if row.get("objective") == "service_slot_availability"
    )
    assert service["priority"] == "primary"
    assert service["tool"] == "find_installation_slots"


def test_stale_unselected_product_observation_does_not_resume_installation():
    signals = [
        {
            "key": "specific_sku_model",
            "value": "FRONWAY ECOGREEN ONE 175/65R14",
            "source": "latest_user_message",
        },
        {
            "key": "service_type",
            "value": "installation",
            "source": "signal_ledger",
            "status": "remembered_signal",
        },
        {
            "key": "location",
            "value": "Dasmarinas City, Cavite",
            "source": "signal_ledger",
            "status": "remembered_signal",
        },
    ]
    objectives = build_tool_objectives(
        background_signals=signals,
        capability_profile={
            "candidate_tools": ["find_installation_slots"],
            "exposed_tools": ["find_installation_slots"],
            "available_context_refs": {
                "product_observation": True,
                "product_presentation": False,
            },
            "matched_signal_keys": {
                "find_installation_slots": ["location", "service_type"],
            },
        },
    )

    assert not any(
        row.get("objective") == "service_slot_availability"
        for row in objectives
    )


def test_retained_delivery_does_not_open_installation_slots_after_product_choice():
    objectives = build_tool_objectives(
        background_signals=[
            {
                "key": "specific_sku_model",
                "value": "MICHELIN PRIMACY SUV+ 215/70R16",
                "source": "latest_user_message",
            },
            {
                "key": "service_type",
                "value": "delivery",
                "source": "signal_ledger",
                "status": "remembered_signal",
            },
            {
                "key": "location",
                "value": "Cebu City",
                "source": "signal_ledger",
                "status": "remembered_signal",
            },
        ],
        capability_profile={
            "candidate_tools": ["find_installation_slots"],
            "exposed_tools": ["find_installation_slots"],
            "available_context_refs": {
                "product_observation": True,
                "product_presentation": False,
            },
            "selection_reasons": [
                "validated_product_click:product_resolution_satisfied",
            ],
            "matched_signal_keys": {
                "find_installation_slots": ["location", "service_type"],
            },
        },
    )

    assert not any(
        row.get("objective") == "service_slot_availability"
        for row in objectives
    )


def test_selected_product_without_location_does_not_open_installation_slots():
    objectives = build_tool_objectives(
        background_signals=[
            {
                "key": "specific_sku_model",
                "value": "TOYO PROXES CR1 195/65R15",
                "source": "latest_user_message",
            },
            {
                "key": "service_type",
                "value": "installation",
                "source": "signal_ledger",
                "status": "remembered_signal",
            },
        ],
        capability_profile={
            "candidate_tools": ["find_installation_slots"],
            "exposed_tools": ["find_installation_slots"],
            "available_context_refs": {
                "product_observation": True,
                "product_presentation": False,
            },
            "selection_reasons": [
                "validated_product_click:product_resolution_satisfied",
            ],
            "matched_signal_keys": {
                "find_installation_slots": ["service_type"],
            },
        },
    )

    assert not any(
        row.get("objective") == "service_slot_availability"
        for row in objectives
    )


def test_active_installation_without_location_offers_guided_location_choice():
    objectives = build_tool_objectives(
        background_signals=[
            {
                "key": "service_type",
                "value": "installation",
                "source": "latest_user_message",
                "status": "mentioned_by_latest_user_message",
            },
        ],
        capability_profile={
            "candidate_tools": [
                "find_installation_partners",
                "present_serviceable_location_choices",
            ],
            "exposed_tools": [
                "find_installation_partners",
                "present_serviceable_location_choices",
            ],
            "available_context_refs": {
                "product_observation": False,
                "product_presentation": False,
            },
            "matched_signal_keys": {
                "find_installation_partners": ["service_type"],
            },
        },
    )

    location = next(
        row
        for row in objectives
        if row.get("objective") == "service_location_choice"
    )
    assert location["priority"] == "primary"
    assert location["tool"] == "present_serviceable_location_choices"
    assert "call present_serviceable_location_choices in this turn" in location["use_rule"]
    assert "rather than asking for a typed province" in location["use_rule"]


def test_delivered_product_help_offers_location_as_preferred_reengagement():
    objectives = build_tool_objectives(
        background_signals=[],
        capability_profile={
            "candidate_tools": ["present_serviceable_location_choices"],
            "exposed_tools": ["present_serviceable_location_choices"],
            "available_context_refs": {
                "product_observation": True,
                "product_presentation": True,
            },
            "selection_reasons": [
                "present_serviceable_location_choices:"
                "delivered_product_help_without_usable_service_location"
            ],
            "matched_signal_keys": {},
        },
    )

    location = next(
        row
        for row in objectives
        if row.get("objective") == "service_location_choice"
    )
    assert location["priority"] == "preferred"
    assert location["tool"] == "present_serviceable_location_choices"
    assert "do not interrupt active fitment or product narrowing" in location["use_rule"]
    assert "call present_serviceable_location_choices in this turn" in location["use_rule"]
    assert "rather than ask for a typed province" in location["use_rule"]


def test_product_observation_without_delivered_presentation_does_not_offer_location():
    objectives = build_tool_objectives(
        background_signals=[],
        capability_profile={
            "candidate_tools": ["present_serviceable_location_choices"],
            "exposed_tools": ["present_serviceable_location_choices"],
            "available_context_refs": {
                "product_observation": True,
                "product_presentation": False,
            },
            "matched_signal_keys": {},
        },
    )

    assert not any(
        row.get("objective") == "service_location_choice"
        for row in objectives
    )


def test_zero_card_product_observation_routes_service_to_partner_coverage():
    objectives = build_tool_objectives(
        background_signals=[
            {
                "key": "service_type",
                "value": "installation",
                "source": "latest_user_message",
            },
            {
                "key": "location",
                "value": "Rosario, Cavite",
                "source": "latest_user_message",
            },
        ],
        capability_profile={
            "candidate_tools": [
                "find_installation_partners",
                "find_installation_slots",
            ],
            "exposed_tools": [
                "find_installation_partners",
                "find_installation_slots",
            ],
            "available_context_refs": {
                "product_observation": True,
                "product_presentation": False,
            },
            "selection_reasons": [],
            "order_readiness": {"high_intent_signals": []},
            "matched_signal_keys": {
                "find_installation_partners": ["location", "service_type"],
                "find_installation_slots": ["location", "service_type"],
            },
        },
    )

    assert any(
        row.get("objective") == "service_partner_coverage"
        and row.get("tool") == "find_installation_partners"
        for row in objectives
    )
    assert not any(
        row.get("objective") == "service_slot_availability"
        for row in objectives
    )
    partner = next(
        row for row in objectives if row.get("tool") == "find_installation_partners"
    )
    assert "never generalize one result" in partner["use_rule"]


def test_active_product_refinement_keeps_location_reengagement_conditional():
    objectives = build_tool_objectives(
        background_signals=[
            {
                "key": "preferred_brands",
                "value": ["Yokohama"],
                "source": "latest_user_message",
            }
        ],
        capability_profile={
            "candidate_tools": [
                "product_search",
                "present_serviceable_location_choices",
            ],
            "exposed_tools": [
                "product_search",
                "present_serviceable_location_choices",
            ],
            "available_context_refs": {
                "product_observation": True,
                "product_presentation": True,
            },
            "selection_reasons": [
                "present_serviceable_location_choices:"
                "delivered_product_help_without_usable_service_location"
            ],
            "matched_signal_keys": {
                "product_search": ["preferred_brands"],
            },
        },
    )

    product = next(row for row in objectives if row.get("tool") == "product_search")
    location = next(
        row
        for row in objectives
        if row.get("objective") == "service_location_choice"
    )
    assert product["priority"] == "primary"
    assert location["priority"] == "preferred"
    assert "after completing currently owed product or policy help" in location["use_rule"]
    assert "prior product surface may remain unresolved" in location["use_rule"]
    assert "do not stack it with another decision in the same turn" in location["use_rule"]


def test_location_button_contract_covers_branch_install_and_free_text_exceptions():
    location_schema = next(
        schema["function"]
        for schema in ALL_RUNTIME_V7_TOOL_SCHEMAS
        if schema["function"]["name"] == "present_serviceable_location_choices"
    )
    contract = " ".join(
        f"{CORE_SYSTEM_PROMPT} {location_schema['description']}".split()
    )

    assert "which branch or service area applies" in contract
    assert "call the tool in that turn so the runtime shows buttons" in contract
    assert "rather than replacing them with prose" in contract
    assert "text city/barangay/landmark question" in contract
    assert "a partial or concrete location is already available" in contract
    assert "another decision surface must stay active" in contract


def test_concrete_location_uses_grounded_lookup_not_province_buttons():
    objectives = build_tool_objectives(
        background_signals=[
            {
                "key": "service_type",
                "value": "installation",
                "source": "latest_user_message",
            },
            {
                "key": "location",
                "value": "Makati City",
                "source": "latest_user_message",
                "resolution": {
                    "status": "resolved_location",
                    "display_label": "Makati City",
                    "city_hint": "Makati City",
                    "location_precision": "city",
                },
            },
        ],
        capability_profile={
            "candidate_tools": [
                "find_installation_partners",
                "present_serviceable_location_choices",
            ],
            "exposed_tools": [
                "find_installation_partners",
                "present_serviceable_location_choices",
            ],
            "available_context_refs": {},
            "matched_signal_keys": {},
        },
    )

    assert any(
        row.get("objective") == "service_partner_coverage"
        and row.get("tool") == "find_installation_partners"
        for row in objectives
    )
    assert not any(
        row.get("objective") == "service_location_choice"
        for row in objectives
    )


def test_active_installation_context_uses_guided_tool_instead_of_typed_province():
    context = build_runtime_v7_context(
        current_user_message="Gusto ko rin magpakabit",
        background_signals=[
            {
                "key": "service_type",
                "value": "installation",
                "source": "latest_user_message",
                "status": "mentioned_by_latest_user_message",
            }
        ],
        capability_profile={
            "candidate_tools": ["present_serviceable_location_choices"],
            "exposed_tools": ["present_serviceable_location_choices"],
            "available_context_refs": {},
            "matched_signal_keys": {},
        },
    )

    assert "guided province choice is eligible" in context
    assert "rather than asking the customer to type a province" in context


def test_product_reengagement_context_prefers_guided_location_over_typed_province():
    context = build_runtime_v7_context(
        current_user_message="Hindi pa ako sure kung alin",
        background_signals=[],
        capability_profile={
            "candidate_tools": ["present_serviceable_location_choices"],
            "exposed_tools": ["present_serviceable_location_choices"],
            "available_context_refs": {"product_presentation": True},
            "selection_reasons": [
                "present_serviceable_location_choices:"
                "delivered_product_help_without_usable_service_location"
            ],
            "matched_signal_keys": {},
        },
    )

    assert "useful product choices were already delivered" in context
    assert "answer currently owed help first" in context
    assert "rather than asking the customer to type a province" in context
    assert "do not wait for an explicit installation request" in context
    assert "prior product surface may remain unresolved" in context


def test_delivered_product_hesitation_prefers_model_led_location_move() -> None:
    objectives = build_tool_objectives(
        background_signals=[],
        capability_profile={
            "candidate_tools": ["present_serviceable_location_choices"],
            "exposed_tools": ["present_serviceable_location_choices"],
            "available_context_refs": {"product_presentation": True},
            "selection_reasons": [
                "present_serviceable_location_choices:"
                "delivered_product_help_without_usable_service_location"
            ],
            "matched_signal_keys": {},
        },
    )

    location = next(
        row for row in objectives
        if row.get("objective") == "service_location_choice"
    )
    assert location["priority"] == "preferred"
    assert "do not wait for an explicit installation request" in location["use_rule"]


def test_missing_delivery_location_does_not_open_installation_location_choices():
    objectives = build_tool_objectives(
        background_signals=[
            {
                "key": "service_type",
                "value": "delivery",
                "source": "latest_user_message",
            },
        ],
        capability_profile={
            "candidate_tools": [],
            "exposed_tools": ["present_serviceable_location_choices"],
            "available_context_refs": {},
            "matched_signal_keys": {},
        },
    )

    assert not any(
        row.get("objective") == "service_location_choice"
        for row in objectives
    )


def test_validated_installation_slot_does_not_repeat_slot_discovery_objective():
    objectives = build_tool_objectives(
        background_signals=[
            {
                "key": "specific_sku_model",
                "value": "BRIDGESTONE TURANZA T005A 225/45R18",
                "source": "latest_user_message",
            },
            {
                "key": "service_type",
                "value": "installation",
                "source": "signal_ledger",
                "status": "remembered_signal",
            },
            {
                "key": "location",
                "value": "Makati City",
                "source": "signal_ledger",
                "status": "remembered_signal",
            },
        ],
        capability_profile={
            "candidate_tools": ["find_installation_slots"],
            "exposed_tools": ["find_installation_slots"],
            "available_context_refs": {
                "product_observation": True,
                "product_presentation": False,
                "validated_service_slot": True,
            },
            "selection_reasons": [
                "validated_product_click:product_resolution_satisfied",
            ],
            "matched_signal_keys": {
                "find_installation_slots": ["location", "service_type"],
            },
        },
    )

    assert not any(
        row.get("objective") == "service_slot_availability"
        for row in objectives
    )


def test_area_only_partner_result_does_not_prescribe_the_next_sales_stage():
    compact = _compact_tool_result(
        "find_installation_partners",
        {
            "status": "ok",
            "observation_ref": "svc_obs_installation_partners_1",
            "presentation_ref": "pres_installation_partners_abc",
            "partner_detail_level": "area_only",
            "query_basis": {"location": "Bacoor, Cavite", "service_type": "installation"},
            "installation_partner_cards": [
                {
                    "card_ref": "partner_card_1",
                    "display_name": "Installation partner option 1",
                    "card_text": "Installation partner option 1 - Bacoor, Cavite area",
                    "partner_detail_level": "area_only",
                    "municipality_city": "Bacoor",
                }
            ],
            "coverage_assessment": {
                "presentable_partner_count": 1,
                "clarification_recommended": False,
                "customer_location_label": "Bacoor, Cavite",
            },
            "read_only": True,
        },
    )

    assert "suggested_next_tool" not in compact
    assert "next_lookup_goal" not in compact
    assert compact["cards_will_be_inserted_by_runtime"] is False
    assert compact["anonymous_partner_cards_suppressed"] is True
    assert "not customer-visible partner choices" in compact[
        "suppressed_card_reason"
    ]
    assert "presentation_surfaces" not in compact


def test_brandless_promo_discovery_does_not_open_product_decision_layer():
    objectives = build_tool_objectives(
        background_signals=[
            {
                "key": "promo_types",
                "value": ["buy3get1"],
                "source": "latest_user_message",
            },
            {
                "key": "quantity",
                "value": 4,
                "source": "latest_user_message",
            },
        ],
        capability_profile={
            "candidate_tools": [
                "search_promo_catalog",
                "product_search",
            ],
            "exposed_tools": [
                "search_promo_catalog",
                "present_promo_gallery",
                "product_search",
            ],
            "available_context_refs": {
                "product_presentation": False,
            },
            "matched_signal_keys": {
                "search_promo_catalog": ["promo_types"],
                "product_search": ["promo_types", "quantity"],
            },
        },
    )

    assert any(
        row.get("objective") == "promo_discovery"
        and row.get("priority") == "primary"
        for row in objectives
    )
    assert not any(
        row.get("objective") == "product_discovery"
        for row in objectives
    )


def test_province_schedule_objective_directs_model_to_city_recommendations():
    objectives = build_tool_objectives(
        background_signals=[
            {
                "key": "service_type",
                "value": "installation",
                "source": "latest_user_message",
            },
            {
                "key": "location",
                "value": "Pampanga",
                "source": "latest_user_message",
            },
            {
                "key": "chosen_schedule_slot",
                "value": "tomorrow",
                "source": "latest_user_message",
            },
        ],
        capability_profile={
            "candidate_tools": ["find_installation_slots"],
            "exposed_tools": ["find_installation_slots"],
            "available_context_refs": {
                "product_presentation": False,
            },
            "matched_signal_keys": {
                "find_installation_slots": [
                    "chosen_schedule_slot",
                    "location",
                    "service_type",
                ],
            },
        },
    )

    service = next(
        row
        for row in objectives
        if row.get("objective") == "service_slot_availability"
    )
    assert "recommend_serviceable_cities" in service["use_rule"]
    assert "exact_city_slots" in service["use_rule"]


def test_model_guidance_keeps_one_cta_and_exposes_serviceable_city_choices():
    assert "Use one customer-facing CTA" in CTA_POLICY_PROMPT
    assert "must not also tell the customer" in CTA_POLICY_PROMPT
    assert "discovery_mode=recommend_serviceable_cities" in SERVICE_POLICY_PROMPT
    assert "without the available city choices" in SERVICE_POLICY_PROMPT


def test_final_composer_does_not_frame_size_as_direct_schedule_unlock():
    from runtime_v7.runtime_harness import FINAL_COMPOSER_SYSTEM_PROMPT

    normalized = " ".join(FINAL_COMPOSER_SYSTEM_PROMPT.split())
    assert "choose a suitable tire before schedule lookup" in normalized
    assert "tire size alone is the final missing input" in normalized
    assert "keep that CTA entirely on tire/product discovery" in normalized
    assert "do not mention checking slots, schedules, dates, or times" in normalized


def test_size_reply_in_existing_service_thread_resumes_product_choice_not_promos():
    objectives = build_tool_objectives(
        background_signals=[
            {
                "key": "tire_size",
                "value": "225/55R18",
                "source": "latest_user_message",
            }
        ],
        capability_profile={
            "candidate_tools": [
                "search_promo_catalog",
                "discover_brand_buckets",
                "product_search",
            ],
            "exposed_tools": [
                "search_promo_catalog",
                "discover_brand_buckets",
                "product_search",
            ],
            "available_context_refs": {
                "service_observation": True,
                "service_location": True,
                "product_presentation": False,
            },
            "matched_signal_keys": {
                "search_promo_catalog": ["tire_size"],
                "discover_brand_buckets": ["tire_size"],
                "product_search": ["tire_size"],
            },
        },
    )

    assert objectives[0]["objective"] == (
        "product_choice_for_service_continuation"
    )
    assert objectives[0]["priority"] == "primary"
    assert "broad promo gallery" in objectives[0]["use_rule"]
    assert not any(
        row.get("objective") == "product_discovery_from_complete_size"
        for row in objectives
    )
