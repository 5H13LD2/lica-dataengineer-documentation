from __future__ import annotations

import json
from types import SimpleNamespace

from runtime.gateways.analytics_gateway import MemoryAnalyticsGateway
from runtime_v7.api_runtime import (
    RuntimeV7APIRequest,
    _attach_location_choice_surface,
    _emit_interaction_events,
    _execute_location_choice_plan,
    _model_requested_location_surface_allowed,
    _plan_customer_turn_surfaces,
    _remember_choice_action_attempt,
)
from runtime_v7.channel_renderer import RuntimeV7ChannelRender, render_turn_for_channel
from runtime_v7.choice_actions import (
    build_location_choice_token,
    parse_location_choice_token,
)
from runtime_v7.location_choices import ServiceableLocationChoicesProvider


class FakeHTTP:
    def __init__(self) -> None:
        self.rows = {
            "/get_province": [
                {"PROV_CODE": "PH-00", "PROV_NAME": "METRO MANILA"},
                {"PROV_CODE": "PH-40", "PROV_NAME": "CAVITE"},
            ],
            "/get_city": [
                {"CITY_CODE": "PH-00-MKT", "CITY_NAME": "MAKATI CITY", "PROV_CODE": "PH-00"},
                {"CITY_CODE": "PH-00-QZC", "CITY_NAME": "QUEZON CITY", "PROV_CODE": "PH-00"},
                {"CITY_CODE": "PH-40-BAC", "CITY_NAME": "BACOOR", "PROV_CODE": "PH-40"},
                {
                    "CITY_CODE": "PH-40-DAS",
                    "CITY_NAME": "DASMARINAS CITY",
                    "PROV_CODE": "PH-40",
                },
                {"CITY_CODE": "PH-40-CAV", "CITY_NAME": "CAVITE CITY", "PROV_CODE": "PH-40"},
            ],
            "/branch_list_loc": [
                {"id": 1, "area": "Makati", "address": "Makati City", "name": "A"},
                {"id": 2, "area": "Quezon City", "address": "Quezon City", "name": "B"},
                {"id": 3, "area": "Cavite", "address": "Molino, Bacoor, Cavite", "name": "C"},
                {
                    "id": 4,
                    "area": "Cavite",
                    "address": "Paliparan, Dasmarinas, Cavite",
                    "name": "D",
                },
            ],
        }

    def get_json(self, path, params=None):
        return self.rows[path]


def test_serviceable_hierarchy_uses_only_active_branch_locations() -> None:
    provider = ServiceableLocationChoicesProvider(http_client=FakeHTTP())

    provinces = provider.province_surface(turn_id="turn_1")
    cavite = provider.city_surface(province_code="PH-40", turn_id="turn_2")

    assert [item["label"] for item in provinces["choices"]] == [
        "Metro Manila",
        "Cavite",
        "Others",
    ]
    assert [item["label"] for item in cavite["choices"]] == [
        "Bacoor",
        "Dasmarinas City",
    ]
    assert all(item["label"] != "Cavite City" for item in cavite["choices"])
    assert provinces["diagnostics"]["mapped_branch_count"] == 4


def test_location_choice_token_round_trip() -> None:
    token = build_location_choice_token(
        presentation_ref="loc_123",
        level="city",
        parent_code="PH-40",
        choice_code="PH-40-BAC",
    )

    assert parse_location_choice_token(token) == {
        "presentation_ref": "loc_123",
        "level": "city",
        "parent_code": "PH-40",
        "choice_code": "PH-40-BAC",
    }


def test_renderer_splits_large_city_set_and_tracks_one_presentation(monkeypatch) -> None:
    monkeypatch.setenv("PRICE_CATEGORY_LIVE_ROUTER_FLOW_NAMESPACE", "content_router")
    monkeypatch.setenv("PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE", "content_router")
    choices = [
        {
            "choice_ref": f"location:city:C{i}",
            "code": f"C{i}",
            "label": f"City {i}",
            "partner_count": 1,
            "province_code": "P1",
            "province_label": "Province",
            "serviceability_status": "serviceable",
        }
        for i in range(13)
    ]
    rendered = render_turn_for_channel(
        {
            "runtime_final_response": "Choose your city.",
            "tool_results": [],
            "location_choice_surface": {
                "presentation_ref": "loc_abc",
                "surface_type": "serviceable_city_choices",
                "choice_type": "serviceable_city",
                "level": "city",
                "parent_code": "P1",
                "parent_label": "Province",
                "choices": choices,
                "source": "branch_api",
                "source_paths": ["/branch_list_loc"],
                "source_version": "v1",
                "freshness_ttl_seconds": 300,
                "renderer_variant": "manychat_serviceable_location_cards_v1",
            },
        }
    )

    galleries = [item for item in rendered.content_messages if item.get("type") == "cards"]
    assert [len(item["elements"]) for item in galleries] == [10, 3]
    assert len(rendered.choice_presentations) == 1
    assert rendered.choice_presentations[0]["choice_type"] == "serviceable_city"
    assert all(
        element["buttons"][0]["target"] == "content_router"
        for gallery in galleries
        for element in gallery["elements"]
    )


def test_model_composed_price_category_surface_omits_unselected_province_surface(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "PRICE_CATEGORY_LIVE_ROUTER_FLOW_NAMESPACE",
        "content_router",
    )
    monkeypatch.setenv(
        "PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE",
        "content_router",
    )
    rendered = render_turn_for_channel(
        {
            "assistant_text": json.dumps(
                {
                    "response_units": [
                        {
                            "type": "text",
                            "content": {
                                "text": "Which price range works for you?"
                            },
                        },
                        {
                            "type": "render_surface",
                            "content": {
                                "surface_ref": "price_categories_1"
                            },
                        },
                    ]
                }
            ),
            "final_composer": {"status": "used"},
            "tool_results": [
                {
                    "name": "discover_brand_buckets",
                    "round": 1,
                    "full_result": {
                        "presentation_ref": "price_categories_1",
                        "query_basis": {
                            "normalized_filters": {
                                "section_width": "195",
                                "aspect_ratio": "60",
                                "rim_size": "R15",
                            }
                        },
                        "bucket_cards": [
                            {
                                "choice_ref": "price_category:budget",
                                "bucket": "budget",
                                "label": "Budget",
                                "brand_count": 2,
                                "product_count": 4,
                                "min_price_text": "PHP 2,000",
                                "max_price_text": "PHP 3,000",
                            },
                            {
                                "choice_ref": "price_category:premium",
                                "bucket": "premium",
                                "label": "Premium",
                                "brand_count": 2,
                                "product_count": 4,
                                "min_price_text": "PHP 5,000",
                                "max_price_text": "PHP 7,000",
                            },
                        ],
                    },
                }
            ],
            "location_choice_surface": {
                "presentation_ref": "provinces_stale",
                "surface_type": "serviceable_province_choices",
                "choice_type": "serviceable_province",
                "level": "province",
                "parent_code": "PH",
                "choices": [
                    {
                        "choice_ref": "location:province:PH-40",
                        "code": "PH-40",
                        "label": "Cavite",
                        "partner_count": 17,
                    }
                ],
            },
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
    assert values
    assert all(value.startswith("bc1|") for value in values)
    assert not any(value.startswith("lc1|") for value in values)
    assert "price range" in rendered.text.casefold()
    assert "anong city" not in rendered.text.casefold()
    assert len(rendered.choice_presentations) == 1
    assert rendered.choice_presentations[0]["choice_type"] == "price_category"


def test_location_click_is_validated_against_delivered_choice() -> None:
    harness = SimpleNamespace(
        choice_presentation_history=[
            {
                "presentation_ref": "loc_abc",
                "choice_type": "serviceable_city",
                "delivery_status": "success",
                "parent_code": "PH-00",
                "source": "branch_api",
                "source_version": "v1",
                "choices": [
                    {
                        "choice_ref": "location:city:PH-00-MKT",
                        "code": "PH-00-MKT",
                        "label": "Makati City",
                        "province_code": "PH-00",
                        "province_label": "Metro Manila",
                        "position": 1,
                    }
                ],
            }
        ],
        choice_action_history=[],
        latest_choice_action={},
    )
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="generic click",
        idempotency_key="click_1",
        flow_context={
            "choice_action_context": {
                "presentation_ref": "loc_abc",
                "choice_type": "serviceable_city",
                "choice_code": "PH-00-MKT",
                "level": "city",
                "parent_code": "PH-00",
            }
        },
    )

    _remember_choice_action_attempt(harness, request)

    context = request.flow_context["choice_action_runtime_context"]
    assert context["validation_status"] == "valid"
    assert context["source_version"] == "v1"
    assert context["selected_product_ready"] is False
    assert "Makati City, Metro Manila" in request.user_text
    assert "not selected a tire product yet" in request.user_text
    assert "before checking schedules" in request.user_text


def test_location_click_with_selected_product_can_progress_to_service() -> None:
    harness = SimpleNamespace(
        choice_presentation_history=[
            {
                "presentation_ref": "loc_selected",
                "choice_type": "serviceable_city",
                "delivery_status": "success",
                "choices": [
                    {
                        "choice_ref": "location:city:PH-CAV-010",
                        "code": "PH-CAV-010",
                        "label": "Imus",
                        "province_label": "Cavite",
                    }
                ],
            }
        ],
        choice_action_history=[],
        latest_choice_action={},
        latest_selected_product_context={
            "product_summary": {"sku_model": "Selected tire"}
        },
    )
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="generic click",
        idempotency_key="click_selected",
        flow_context={
            "choice_action_context": {
                "presentation_ref": "loc_selected",
                "choice_type": "serviceable_city",
                "choice_code": "PH-CAV-010",
                "level": "city",
            }
        },
    )

    _remember_choice_action_attempt(harness, request)

    context = request.flow_context["choice_action_runtime_context"]
    assert context["selected_product_ready"] is True
    assert "sales-progression state" in request.user_text


def test_tampered_location_click_is_marked_stale() -> None:
    harness = SimpleNamespace(
        choice_presentation_history=[
            {
                "presentation_ref": "loc_abc",
                "choice_type": "serviceable_city",
                "delivery_status": "success",
                "choices": [{"code": "PH-00-MKT", "label": "Makati City"}],
            }
        ],
        choice_action_history=[],
        latest_choice_action={},
    )
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="generic click",
        idempotency_key="click_2",
        flow_context={
            "choice_action_context": {
                "presentation_ref": "loc_abc",
                "choice_type": "serviceable_city",
                "choice_code": "PH-00-QZC",
            }
        },
    )

    _remember_choice_action_attempt(harness, request)

    assert request.flow_context["choice_action_runtime_context"]["validation_status"] == "stale"
    assert "no longer current" in request.user_text


def test_valid_province_click_attaches_only_its_city_surface() -> None:
    class FakeProvider:
        def city_surface(self, *, province_code, turn_id):
            assert province_code == "PH-40"
            return {"presentation_ref": f"{turn_id}_cities", "choices": [{"code": "BAC"}]}

        def province_surface(self, *, turn_id):
            raise AssertionError("province surface should not be used")

    turn = {"turn_id": "turn_9"}
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="Cavite",
        flow_context={
            "choice_action_runtime_context": {
                "validation_status": "valid",
                "choice_type": "serviceable_province",
                "choice_code": "PH-40",
            }
        },
    )

    _attach_location_choice_surface(turn, request=request, provider=FakeProvider())

    assert turn["location_choice_surface"]["presentation_ref"] == "turn_9_cities"


def test_delivery_address_suppresses_installation_location_surface() -> None:
    class FakeProvider:
        def province_surface(self, *, turn_id):
            raise AssertionError("delivery flow must not attach installation locations")

    turn = {
        "turn_id": "turn_delivery",
        "order_readiness_after_tools": {
            "collected": {
                "Fulfillment": "delivery",
                "Delivery address": "Unit 1, Makati City",
            }
        },
    }
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="For delivery to Unit 1, Makati City",
    )

    _attach_location_choice_surface(turn, request=request, provider=FakeProvider())

    assert "location_choice_surface" not in turn


def test_delivery_address_suppresses_prior_province_city_surface() -> None:
    class FakeProvider:
        def city_surface_for_province_label(self, *, province_label, turn_id):
            raise AssertionError("delivery must suppress stale province city choices")

    turn = {
        "turn_id": "turn_delivery_after_province",
        "order_readiness_after_tools": {
            "collected": {
                "Fulfillment": "delivery",
                "Delivery address": "123 Test St, Makati City",
            }
        },
        "background_signals_before_turn": [
            {
                "key": "location",
                "value": "Cavite",
                "source": "latest_user_message",
                "resolution": {
                    "province_hint": "Cavite",
                    "location_precision": "province_only",
                },
            }
        ],
    }
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="Delivery na lang sa Makati",
    )

    _attach_location_choice_surface(turn, request=request, provider=FakeProvider())

    assert "location_choice_surface" not in turn
    assert turn["location_choice_surface_status"]["reason"] == (
        "delivery_or_resolved_city_guard"
    )


def test_model_location_plan_returns_routing_only_provider_surface() -> None:
    provider = ServiceableLocationChoicesProvider(http_client=FakeHTTP())
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="Saan kayo may installation?",
        message_id="semantic_location_1",
    )

    result = _execute_location_choice_plan(
        {"discovery_mode": "serviceable_provinces"},
        request=request,
        harness=SimpleNamespace(),
        provider=provider,
    )

    assert result["status"] == "ok"
    assert result["routing_only"] is True
    assert result["read_only"] is True
    assert result["can_confirm_serviceability"] is False
    assert result["can_select_location"] is False
    assert result["can_confirm_booking"] is False
    assert result["location_choice_surface"]["source"] == (
        "gulong_api_serviceable_location_catalog"
    )
    assert [
        choice["label"]
        for choice in result["location_choice_surface"]["choices"]
    ] == ["Metro Manila", "Cavite", "Others"]


def test_model_requested_location_surface_attaches_and_renders_tracked_choices(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "PRICE_CATEGORY_LIVE_ROUTER_FLOW_NAMESPACE",
        "content_router",
    )
    monkeypatch.setenv(
        "PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE",
        "content_router",
    )
    provider = ServiceableLocationChoicesProvider(http_client=FakeHTTP())
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="Anong areas ang pwede kong piliin for installation?",
        message_id="semantic_location_2",
    )
    result = _execute_location_choice_plan(
        {"discovery_mode": "serviceable_provinces"},
        request=request,
        harness=SimpleNamespace(),
        provider=provider,
    )
    partial_turn = {
        "turn_id": "semantic_location_2",
        "runtime_final_response": (
            "Online store po ang Gulong.PH. Pili po kayo ng province below."
        ),
        "tool_results": [
            {
                "name": "present_serviceable_location_choices",
                "full_result": result,
            }
        ],
    }

    surfaces = _plan_customer_turn_surfaces(
        partial_turn,
        request=request,
        harness=SimpleNamespace(),
        provider=provider,
    )
    turn = {**partial_turn, **surfaces}
    rendered = render_turn_for_channel(turn)

    assert surfaces["location_choice_surface_status"] == {
        "status": "attached",
        "reason": "model_requested_serviceable_location_choices",
        "routing_only": True,
        "slots_authorized": False,
    }
    values = [
        action["value"]
        for message in rendered.content_messages
        if message.get("type") == "cards"
        for element in message.get("elements") or []
        for button in element.get("buttons") or []
        for action in button.get("actions") or []
    ]
    assert values
    assert all(value.startswith("lc1|") for value in values)
    assert all(
        button["target"] == "content_router"
        for message in rendered.content_messages
        if message.get("type") == "cards"
        for element in message.get("elements") or []
        for button in element.get("buttons") or []
    )
    assert len(rendered.choice_presentations) == 1
    assert rendered.choice_presentations[0]["choice_type"] == (
        "serviceable_province"
    )
    other_cards = [
        element
        for message in rendered.content_messages
        if message.get("type") == "cards"
        for element in message.get("elements") or []
        if element.get("title") == "Others"
    ]
    assert len(other_cards) == 1
    assert other_cards[0]["subtitle"] == (
        "Outside these areas? Check delivery options"
    )


def test_model_requested_location_surface_is_rejected_for_delivery_state() -> None:
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="For delivery sa BGC",
    )
    turn = {
        "order_readiness_after_tools": {
            "collected": {
                "Fulfillment": "delivery",
                "Delivery address": "BGC, Taguig",
            }
        }
    }

    assert _model_requested_location_surface_allowed(
        turn,
        request=request,
    ) is False


def test_model_requested_province_surface_is_rejected_after_valid_city_choice() -> None:
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="Makati City",
        flow_context={
            "choice_action_runtime_context": {
                "validation_status": "valid",
                "choice_type": "serviceable_city",
                "choice_code": "PH-00-MKT",
            }
        },
    )

    assert _model_requested_location_surface_allowed(
        {},
        request=request,
    ) is False


def test_unresolved_product_selection_suppresses_location_surface() -> None:
    class FakeProvider:
        def province_surface(self, *, turn_id):
            raise AssertionError(
                "location controls must wait for exact product selection"
            )

    turn = {
        "turn_id": "turn_ambiguous_brand",
        "lead_qualification": {
            "present": {
                "tire_size": "265/65R17",
                "tire_brand": "MICHELIN",
            }
        },
    }
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="Michelin po",
    )

    _attach_location_choice_surface(
        turn,
        request=request,
        provider=FakeProvider(),
    )

    assert "location_choice_surface" not in turn


def test_location_impression_and_click_keep_source_provenance() -> None:
    analytics = MemoryAnalyticsGateway()
    rendered = RuntimeV7ChannelRender(
        response={"bubble1": "Choose Cavite."},
        content_messages=[
            {
                "type": "cards",
                "elements": [
                    {
                        "title": "Cavite",
                        "buttons": [
                            {
                                "actions": [
                                    {
                                        "field_name": "promo_selected_id",
                                        "value": "lc1|loc_abc|province|root|PH-40",
                                    }
                                ]
                            }
                        ],
                    }
                ],
            }
        ],
        choice_presentations=[
            {
                "presentation_ref": "loc_abc",
                "surface_type": "serviceable_province_choices",
                "choice_type": "serviceable_province",
                "level": "province",
                "parent_code": "root",
                "source": "branch_api",
                "source_version": "v1",
                "choices": [{"code": "PH-40", "label": "Cavite"}],
            }
        ],
    )
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="Cavite",
        idempotency_key="click_3",
        flow_context={
            "choice_action_runtime_context": {
                "validation_status": "valid",
                "presentation_ref": "loc_abc",
                "choice_type": "serviceable_province",
                "choice_ref": "location:province:PH-40",
                "choice_code": "PH-40",
                "label": "Cavite",
                "level": "province",
                "parent_code": "root",
                "source": "branch_api",
                "source_version": "v1",
            }
        },
    )

    _emit_interaction_events(
        analytics,
        request=request,
        rendered=rendered,
        delivery_result={"status": "success"},
        common={"request_id": "req_1"},
    )

    events = list(analytics.interaction_event_logs)
    assert [item["event_type"] for item in events] == [
        "surface_delivery_succeeded",
        "choice_clicked",
        "choice_response_delivered",
    ]
    assert all(item["surface_type"] == "serviceable_province_choices" for item in events)
    assert events[1]["details"]["source_version"] == "v1"
