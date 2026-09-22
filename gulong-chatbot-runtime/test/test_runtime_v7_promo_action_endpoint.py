from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from apps.api.routers import gulong
from runtime_v7.choice_actions import (
    build_location_choice_token,
    build_payment_method_choice_token,
    build_payment_option_choice_token,
    build_price_category_token,
    build_product_choice_token,
    build_schedule_choice_token,
)


@pytest.fixture(autouse=True)
def _enable_trial_user_promo_catalog(monkeypatch) -> None:
    monkeypatch.setenv("RUNTIME_V7_PROMO_CATALOG_ENABLED", "1")
    monkeypatch.setenv("RUNTIME_V7_PROMO_CATALOG_USER_ALLOWLIST", "4843256405786522")


class FakePromoService:
    def __init__(self, validation: dict) -> None:
        self.validation = validation

    def validate_action(self, payload: dict) -> dict:
        self.payload = payload
        return self.validation


def _request(**overrides):
    payload = {
        "user_id": "4843256405786522",
        "catalog_version_id": "catalog-v1",
        "promo_id": "michelin-3plus1",
        "card_id": "michelin-3plus1-card-1",
        "action": "promo_details",
        "selected_brand": "Michelin",
        "click_timestamp": "2026-07-20T10:00:00+08:00",
        "event_id": "promo-click-1",
        "idempotency_key": "promo-click-1",
        "delivery_mode": "return_only",
    }
    payload.update(overrides)
    return gulong.PromoActionV7RequestPayload(**payload)


def test_valid_promo_action_routes_through_normal_v7_path(monkeypatch) -> None:
    asyncio.run(_assert_valid_promo_action_routes_through_normal_v7_path(monkeypatch))


def test_non_allowlisted_promo_action_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        gulong,
        "_promo_catalog_service",
        lambda: pytest.fail("catalog should not be loaded for a non-allowlisted user"),
    )

    response = asyncio.run(gulong._handle_promo_action(_request(user_id="999")))

    assert response["status"] == "error"
    assert response["message"] == "promo_catalog_disabled"
    assert response["promo_action_validation"] == {
        "status": "invalid",
        "reason": "feature_disabled",
    }


async def _assert_valid_promo_action_routes_through_normal_v7_path(monkeypatch) -> None:
    validation = {
        "status": "valid",
        "catalog_version_id": "catalog-v1",
        "action": "promo_details",
        "selected_brand": "Michelin",
        "promo": {"title": "Michelin 3+1 Promo", "relevant_mechanics": [{"text": "Buy 3 get 1"}]},
    }
    captured = {}

    async def fake_handle_chat(request, *, tester=False, ingress_idempotency=True):
        captured["request"] = request
        captured["ingress_idempotency"] = ingress_idempotency
        return {"status": "success", "promo_presentation": {}}

    monkeypatch.setattr(gulong, "_promo_catalog_service", lambda: FakePromoService(validation))
    monkeypatch.setattr(gulong, "_handle_chat", fake_handle_chat)

    response = await gulong._handle_promo_action(_request())

    assert response["status"] == "success"
    assert response["promo_action_validation"]["status"] == "valid"
    assert captured["request"].flow_context["promo_action_context"] == validation
    assert captured["request"].message_id == "promo-click-1"
    assert "Michelin" not in captured["request"].user_text
    assert "information request only" in captured["request"].user_text
    assert captured["request"].profile_fields["promo_selected_brand"] == ""
    assert captured["request"].profile_fields["_promo_action_mirror"]["selected_brand"] == ""
    assert captured["ingress_idempotency"] is False


def test_stale_click_never_applies_old_mechanics(monkeypatch) -> None:
    asyncio.run(_assert_stale_click_never_applies_old_mechanics(monkeypatch))


async def _assert_stale_click_never_applies_old_mechanics(monkeypatch) -> None:
    validation = {
        "status": "stale",
        "reason": "catalog_version_is_not_active",
        "active_catalog_version_id": "catalog-v2",
    }
    captured = {}

    async def fake_handle_chat(request, *, tester=False, ingress_idempotency=True):
        captured["request"] = request
        return {"status": "success", "promo_presentation": {"catalog_version_id": "catalog-v2"}}

    monkeypatch.setattr(gulong, "_promo_catalog_service", lambda: FakePromoService(validation))
    monkeypatch.setattr(gulong, "_handle_chat", fake_handle_chat)

    response = await gulong._handle_promo_action(_request())

    assert "no longer current" in captured["request"].user_text
    assert captured["request"].flow_context["promo_action_status"] == "stale"
    assert response["promo_presentation"]["catalog_version_id"] == "catalog-v2"


def test_invalid_card_action_is_rejected_before_runtime(monkeypatch) -> None:
    asyncio.run(_assert_invalid_card_action_is_rejected_before_runtime(monkeypatch))


async def _assert_invalid_card_action_is_rejected_before_runtime(monkeypatch) -> None:
    monkeypatch.setattr(
        gulong,
        "_promo_catalog_service",
        lambda: FakePromoService({"status": "invalid", "reason": "action_not_allowed_for_card"}),
    )

    response = await gulong._handle_promo_action(_request())

    assert response["status"] == "error"
    assert response["message"] == "action_not_allowed_for_card"


def test_promo_action_requires_nonempty_idempotency_data() -> None:
    with pytest.raises(ValidationError):
        _request(event_id="")

    with pytest.raises(ValidationError):
        _request(idempotency_key="")


def test_click_token_overrides_empty_router_fields(monkeypatch) -> None:
    asyncio.run(_assert_click_token_overrides_empty_router_fields(monkeypatch))


async def _assert_click_token_overrides_empty_router_fields(monkeypatch) -> None:
    token = "pc1|catalog-v1|michelin-3plus1|michelin-card-1|about_brand|Michelin"
    service = FakePromoService(
        {
            "status": "valid",
            "catalog_version_id": "catalog-v1",
            "action": "about_brand",
            "selected_brand": "Michelin",
            "promo": {"title": "Michelin 3+1 Promo"},
        }
    )
    captured = {}

    async def fake_handle_chat(request, *, tester=False, ingress_idempotency=True):
        captured["request"] = request
        return {"status": "success"}

    monkeypatch.setattr(gulong, "_promo_catalog_service", lambda: service)
    monkeypatch.setattr(gulong, "_handle_chat", fake_handle_chat)

    response = await gulong._handle_promo_action(
        _request(promo_id=token, card_id="", action="", selected_brand="")
    )

    assert response["status"] == "success"
    assert service.payload["promo_id"] == "michelin-3plus1"
    assert service.payload["card_id"] == "michelin-card-1"
    assert service.payload["action"] == "about_brand"
    assert captured["request"].profile_fields["promo_selected_id"] == "michelin-3plus1"
    assert captured["request"].profile_fields["_promo_action_mirror"] == {
        "promo_id": "michelin-3plus1",
        "card_id": "michelin-card-1",
        "action": "about_brand",
        "selected_brand": "",
        "click_timestamp": "2026-07-20T10:00:00+08:00",
    }
    assert captured["request"].flow_context["promo_action_context"]["selected_brand"] == "Michelin"
    assert "Michelin" not in captured["request"].user_text


def test_choose_brand_requests_eligible_prices_for_current_size() -> None:
    validation = {
        "status": "valid",
        "action": "choose_brand",
        "selected_brand": "Michelin",
        "promo": {"title": "Michelin and Yokohama Promo"},
    }

    text = gulong._promo_action_user_text(validation)

    assert "Michelin" in text
    assert "eligible promo tire prices" in text
    assert "current tire size" in text


def test_generic_choose_brand_does_not_select_promo_as_product() -> None:
    validation = {
        "status": "valid",
        "action": "choose_brand",
        "selected_brand": "",
        "promo": {"title": "THE GULONG DOUBLE WARRANTY"},
    }

    text = gulong._promo_action_user_text(validation)

    assert "available tire-brand choices" in text
    assert "not selected a brand or product" in text
    assert "THE GULONG DOUBLE WARRANTY" not in text


def test_price_category_token_routes_to_focused_runtime_turn(monkeypatch) -> None:
    token = build_price_category_token(
        presentation_ref="price_categories_abc123",
        category="premium",
        section_width="195",
        aspect_ratio="60",
        rim_size="R15",
    )
    captured = {}

    async def fake_handle_chat(request, *, tester=False, ingress_idempotency=True):
        captured["request"] = request
        captured["ingress_idempotency"] = ingress_idempotency
        return {"status": "success", "product_presentations": []}

    monkeypatch.setattr(gulong, "_handle_chat", fake_handle_chat)

    response = asyncio.run(
        gulong._handle_promo_action(
            _request(promo_id=token, card_id="", action="", selected_brand="")
        )
    )

    request = captured["request"]
    assert response["choice_action_validation"]["category"] == "premium"
    assert "Premium" in request.user_text
    assert "195/60R15" in request.user_text
    assert request.flow_context["choice_action_context"]["presentation_ref"] == "price_categories_abc123"
    assert captured["ingress_idempotency"] is False


def test_category_click_accepts_blank_promo_catalog_fields(monkeypatch) -> None:
    token = build_price_category_token(
        presentation_ref="price_categories_abc123",
        category="budget",
        section_width="195",
        aspect_ratio="60",
        rim_size="R15",
    )
    captured = {}

    async def fake_handle_chat(request, *, tester=False, ingress_idempotency=True):
        captured["request"] = request
        return {"status": "success"}

    monkeypatch.setattr(gulong, "_handle_chat", fake_handle_chat)
    request = _request(
        catalog_version_id="",
        promo_id=token,
        card_id="",
        action="",
        selected_brand="",
    )

    response = asyncio.run(gulong.chat_v7_choice_action(request))

    assert response["status"] == "success"
    assert captured["request"].flow_context["choice_action_context"]["choice_type"] == "price_category"


def test_choice_action_tester_preserves_test_session_routing(monkeypatch) -> None:
    token = build_price_category_token(
        presentation_ref="price_categories_tester",
        category="mid_range",
        section_width="195",
        aspect_ratio="65",
        rim_size="R15",
    )
    captured = {}

    async def fake_handle_chat(request, *, tester=False, ingress_idempotency=True):
        captured["tester"] = tester
        captured["request"] = request
        return {"status": "success"}

    monkeypatch.setattr(gulong, "_handle_chat", fake_handle_chat)

    response = asyncio.run(
        gulong.chat_v7_choice_action_tester(
            _request(
                catalog_version_id="",
                promo_id=token,
                card_id="",
                action="",
                selected_brand="",
                delivery_mode="send_content",
            )
        )
    )

    assert response["status"] == "success"
    assert captured["tester"] is True
    assert captured["request"].delivery_mode == "return_only"
    assert captured["request"].flow_context["choice_action_context"] == {
        "presentation_ref": "price_categories_tester",
        "category": "mid_range",
        "section_width": "195",
        "aspect_ratio": "65",
        "rim_size": "R15",
        "choice_type": "price_category",
        "label": "Mid Range",
        "tire_size": "195/65R15",
    }


def test_location_click_routes_without_promo_catalog_dependency(monkeypatch) -> None:
    token = build_location_choice_token(
        presentation_ref="loc_abc",
        level="province",
        parent_code="root",
        choice_code="PH-40",
    )
    captured = {}

    async def fake_handle_chat(request, *, tester=False, ingress_idempotency=True):
        captured["request"] = request
        return {"status": "success"}

    monkeypatch.setattr(gulong, "_handle_chat", fake_handle_chat)
    monkeypatch.setattr(
        gulong,
        "_promo_catalog_service",
        lambda: pytest.fail("location choices must not load promo data"),
    )

    response = asyncio.run(
        gulong.chat_v7_choice_action(
            _request(
                catalog_version_id="",
                promo_id=token,
                card_id="",
                action="",
                selected_brand="",
            )
        )
    )

    assert response["status"] == "success"
    context = captured["request"].flow_context["choice_action_context"]
    assert context["choice_type"] == "serviceable_province"
    assert context["choice_code"] == "PH-40"


def test_product_click_routes_exact_refs_without_promo_catalog_dependency(monkeypatch) -> None:
    token = build_product_choice_token(
        presentation_ref="pres_products_abc",
        card_ref="card_2",
    )
    captured = {}

    async def fake_handle_chat(request, *, tester=False, ingress_idempotency=True):
        captured["request"] = request
        return {"status": "success"}

    monkeypatch.setattr(gulong, "_handle_chat", fake_handle_chat)
    monkeypatch.setattr(
        gulong,
        "_promo_catalog_service",
        lambda: pytest.fail("product choices must not load promo data"),
    )

    response = asyncio.run(
        gulong.chat_v7_choice_action(
            _request(
                catalog_version_id="",
                promo_id=token,
                card_id="",
                action="",
                selected_brand="",
            )
        )
    )

    assert response["status"] == "success"
    context = captured["request"].flow_context["choice_action_context"]
    assert context == {
        "presentation_ref": "pres_products_abc",
        "card_ref": "card_2",
        "choice_type": "product_selection",
    }


def test_product_click_does_not_overwrite_runtime_stale_validation(
    monkeypatch,
) -> None:
    token = build_product_choice_token(
        presentation_ref="pres_products_old",
        card_ref="card_2",
    )

    async def fake_handle_chat(
        _request,
        *,
        tester=False,
        ingress_idempotency=True,
    ):
        return {
            "status": "success",
            "choice_action_validation": {
                "status": "stale",
                "validation_status": "stale",
                "reason": "choice_not_in_current_delivered_allowlist",
            },
        }

    monkeypatch.setattr(gulong, "_handle_chat", fake_handle_chat)

    response = asyncio.run(
        gulong.chat_v7_choice_action(
            _request(
                catalog_version_id="",
                promo_id=token,
                card_id="",
                action="",
                selected_brand="",
            )
        )
    )

    assert response["choice_action_validation"]["status"] == "stale"
    assert response["choice_action_validation"]["presentation_ref"] == (
        "pres_products_old"
    )


@pytest.mark.parametrize(
    ("builder", "choice_type"),
    [
        (build_schedule_choice_token, "schedule_selection"),
        (build_payment_option_choice_token, "payment_option_selection"),
        (build_payment_method_choice_token, "payment_method_selection"),
    ],
)
def test_reference_choice_routes_without_promo_catalog_dependency(
    monkeypatch,
    builder,
    choice_type,
) -> None:
    token = builder(
        presentation_ref="pres_reference_abc",
        choice_ref="choice_2",
    )
    captured = {}

    async def fake_handle_chat(request, *, tester=False, ingress_idempotency=True):
        captured["request"] = request
        return {"status": "success"}

    monkeypatch.setattr(gulong, "_handle_chat", fake_handle_chat)
    monkeypatch.setattr(
        gulong,
        "_promo_catalog_service",
        lambda: pytest.fail("reference choices must not load promo data"),
    )

    response = asyncio.run(
        gulong.chat_v7_choice_action(
            _request(
                catalog_version_id="",
                promo_id=token,
                card_id="",
                action="",
                selected_brand="",
            )
        )
    )

    assert response["status"] == "success"
    context = captured["request"].flow_context["choice_action_context"]
    assert context == {
        "presentation_ref": "pres_reference_abc",
        "choice_ref": "choice_2",
        "choice_type": choice_type,
    }
