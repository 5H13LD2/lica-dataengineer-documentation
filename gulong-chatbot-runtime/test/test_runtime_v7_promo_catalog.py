from __future__ import annotations

import asyncio
import json
from copy import deepcopy

import httpx
import pytest

from channels.manychat.api_client import ManyChatAPI
from runtime_v7.api_runtime import (
    RuntimeV7APIRequest,
    RuntimeV7APIService,
    _apply_promo_action_runtime_context,
    _export_harness_state,
    _hydrate_harness,
    _remember_choice_action_attempt,
    _response_seed_overrides_for_flow,
)
from runtime_v7.channel_renderer import render_turn_for_channel
from runtime_v7.choice_actions import parse_price_category_token
from runtime_v7.model_contract import (
    PROMO_TOOL_SCHEMAS,
    build_runtime_v7_system_prompt,
)
from runtime_v7.promo_catalog import (
    PromoCatalogRepository,
    PromoCatalogService,
    _select_compact_mechanic_rows,
    build_promo_click_token,
    evaluate_promo_applicability,
    is_targeted_promo_query,
    normalize_promo_query,
    parse_promo_click_token,
    promo_search_evidence_ref,
    promo_catalog_enabled_for_user,
    rerank_promo_candidates,
    promo_candidate_matches_explicit_constraints,
)
from runtime_v7.product_observations import ProductToolHarness
from runtime_v7.runtime_harness import (
    FINAL_COMPOSER_SYSTEM_PROMPT,
    RuntimeV7Harness,
    _named_catalog_promo_tool_context,
    _sanitize_duplicate_supporting_replacement_prose,
)


def test_promo_catalog_user_allowlist_gate() -> None:
    assert promo_catalog_enabled_for_user("trial", enabled_value="1", allowlist_value="") is True
    assert promo_catalog_enabled_for_user("trial", enabled_value="true", allowlist_value="trial, second") is True
    assert promo_catalog_enabled_for_user("other", enabled_value="1", allowlist_value="trial;second") is False
    assert promo_catalog_enabled_for_user("trial", enabled_value="0", allowlist_value="trial") is False


def test_tpp_prompt_delegates_warranty_gallery_to_runtime_without_model_promo_call() -> None:
    from runtime_v7.model_contract import CTA_POLICY_PROMPT

    assert "runtime automatically" in CTA_POLICY_PROMPT
    assert "Do not call\n  search_promo_catalog solely" in CTA_POLICY_PROMPT
    assert "supporting replacement for the old warranty spiel" in CTA_POLICY_PROMPT


def _button(caption: str, action: str, brand: str = "") -> dict:
    return {
        "type": "flow",
        "caption": caption,
        "targets": {
            "staging": "content-staging-promo-router",
            "live": "content-live-promo-router",
        },
        "action": action,
        "selected_brand": brand,
        "actions": [
            {"action": "set_field_value", "field_name": "promo_catalog_version", "value": "catalog-v1"},
            {"action": "set_field_value", "field_name": "promo_selected_id", "value": "promo-1"},
            {"action": "set_field_value", "field_name": "promo_selected_card_id", "value": "card-1"},
            {"action": "set_field_value", "field_name": "promo_selected_action", "value": action},
            {"action": "set_field_value", "field_name": "promo_selected_brand", "value": brand},
            {"action": "set_field_value", "field_name": "promo_source", "value": "runtime_v7_promo_gallery"},
            {"action": "set_field_value", "field_name": "chatbot_state", "value": "promo_action"},
        ],
    }


def _card(
    promo_id: str,
    title: str,
    brands: list[str],
    summary: str,
    *,
    distance: float = 0.2,
    order: int = 1,
    promo_type: str = "fixed_discount",
) -> dict:
    return {
        "catalog_version_id": "catalog-v1",
        "promo_id": promo_id,
        "title": title,
        "brands": brands,
        "offer_summary": summary,
        "promo_type": promo_type,
        "retrieval_aliases": [title, summary],
        "display_order": order,
        "status": "published",
        "enabled": True,
        "vector_distance": distance,
        "source_evidence": [f"evidence:{promo_id}"],
        "display_cards": [
            {
                "card_id": f"{promo_id}-card-1",
                "title": title,
                "subtitle": summary,
                "image_url": f"https://storage.googleapis.com/gulong-chatbot-459723-promo-media/catalog/catalog-v1/cards/{promo_id}.jpg",
                "buttons": [_button("Promo Details", "promo_details")],
            }
        ],
    }


class FakePromoRepository:
    def __init__(self) -> None:
        self.cards = [
            _card(
                "michelin-japan",
                "Michelin Passion Experience 2026",
                ["Michelin"],
                "Chance to win a trip to Japan.",
                order=1,
                promo_type="event",
            ),
            _card(
                "michelin-3plus1",
                "Michelin 3+1 Promo",
                ["Michelin"],
                "Buy 3 get 1 free Michelin tire.",
                order=2,
                promo_type="buy_3_get_1",
            ),
            _card(
                "apollo-3plus1",
                "Apollo 3+1 Promo",
                ["Apollo"],
                "Buy 3 get 1 free Apollo tire.",
                order=3,
                promo_type="buy_3_get_1",
            ),
            _card(
                "yokohama-5200",
                "Yokohama PHP 5,200 Off",
                ["Yokohama"],
                "PHP 5,200 off a set of four.",
                distance=0.05,
                order=4,
            ),
            _card(
                "yokohama-6000",
                "Yokohama PHP 6,000 Off",
                ["Yokohama"],
                "PHP 6,000 off a set of four.",
                distance=0.25,
                order=5,
            ),
        ]

    def active_config(self) -> dict:
        return {"catalog_version_id": "catalog-v1"}

    def list_cards(self, catalog_version_id: str) -> list[dict]:
        assert catalog_version_id == "catalog-v1"
        return deepcopy(self.cards)

    def vector_candidates(self, *, catalog_version_id: str, query_text: str, limit: int) -> list[dict]:
        assert catalog_version_id == "catalog-v1"
        normalized = normalize_promo_query(query_text)
        cards = deepcopy(self.cards)
        if "japan" in normalized:
            cards[0]["vector_distance"] = 0.02
        if "3+1" in normalized or "buy 3 get 1" in normalized:
            cards[1]["vector_distance"] = 0.03
            cards[2]["vector_distance"] = 0.04
        return cards[:limit]

    def mechanics_for_promos(self, *, catalog_version_id: str, promo_ids, max_chunks_per_promo: int = 4) -> dict:
        return {
            promo_id: [
                {
                    "text": f"Reviewed mechanics for {promo_id}",
                    "source_evidence": [f"mechanic-evidence:{promo_id}"],
                    "status": "published",
                }
            ]
            for promo_id in promo_ids
        }

    def brand_profile(self, *, catalog_version_id: str, brand: str) -> dict:
        return {
            "brand": brand,
            "summary": f"Reviewed {brand} profile",
            "source_evidence": ["profile-evidence"],
            "status": "published",
        }


def test_repository_reads_runtime_embedding_service_account(monkeypatch) -> None:
    service_account = "promo-catalog-bot@gulong-chatbot-459723.iam.gserviceaccount.com"
    monkeypatch.setenv("PROMO_CATALOG_EMBEDDING_SERVICE_ACCOUNT", service_account)

    repository = PromoCatalogRepository(firestore_client=object())

    assert repository._embedding_service_account == service_account


def test_exact_amount_rerank_beats_closer_similar_amount() -> None:
    candidates = [
        _card("yokohama-5200", "Yokohama PHP 5,200 Off", ["Yokohama"], "PHP 5,200 off", distance=0.02),
        _card("yokohama-6000", "Yokohama PHP 6,000 Off", ["Yokohama"], "PHP 6,000 off", distance=0.30),
    ]

    ranked = rerank_promo_candidates("Ano mechanics ng Yokohama PHP 6,000?", candidates)

    assert ranked[0]["promo_id"] == "yokohama-6000"


def test_targeted_negative_brand_keeps_relevant_alternatives() -> None:
    service = PromoCatalogService(FakePromoRepository())

    result = service.search_promo_catalog(
        {
            "query": "May Bridgestone 3+1 promo ba? Other brands okay.",
            "mode": "targeted",
            "top_k": 5,
            "alternative_scope": "same_mechanic",
        }
    )

    assert result["status"] == "ok"
    assert result["requested_brands"] == ["Bridgestone"]
    assert result["matched_requested_brands"] == []
    assert result["unmatched_requested_brands"] == ["Bridgestone"]
    assert result["exact_requested_brand_match"] is False
    assert all(
        row["query_constraint_match"] is True
        or row["alternative_constraint_match"] is True
        for row in result["candidates"]
        if row["promo_ref"] in result["allowed_promo_refs"]
    )
    assert result["primary_promo_refs"] == []
    assert len(result["alternative_promo_refs"]) == 2
    assert {row["promo_id"] for row in result["candidates"][:2]} == {
        "michelin-3plus1",
        "apollo-3plus1",
    }
    assert result["evidence_ref"].startswith(
        "promo_search:catalog-v1:"
    )


def test_promo_search_evidence_ref_is_stable_and_scope_bound() -> None:
    baseline = promo_search_evidence_ref(
        catalog_version_id="catalog-v1",
        mode="targeted",
        query=" May Bridgestone 3+1 promo ba? ",
        tire_size="195 60 15",
        requested_brands=["Bridgestone"],
    )
    equivalent = promo_search_evidence_ref(
        catalog_version_id="catalog-v1",
        mode="TARGETED",
        query="may bridgestone 3+1 promo ba?",
        tire_size="195/60R15",
        requested_brands=["bridgestone", "BRIDGESTONE"],
    )
    different_scope = promo_search_evidence_ref(
        catalog_version_id="catalog-v1",
        mode="targeted",
        query="May current promo ba?",
        tire_size="195/60R15",
        requested_brands=[],
    )
    same_search_with_alternatives = promo_search_evidence_ref(
        catalog_version_id="catalog-v1",
        mode="targeted",
        query="may bridgestone 3+1 promo ba?",
        tire_size="195/60R15",
        requested_brands=["Bridgestone"],
        alternative_scope="same_mechanic",
    )

    assert baseline == equivalent
    assert baseline != different_scope
    assert baseline != same_search_with_alternatives
    assert baseline.startswith("promo_search:catalog-v1:")


def test_search_excludes_expired_published_cards_before_ranking() -> None:
    repository = FakePromoRepository()
    repository.cards[1]["valid_until"] = "2000-01-01"
    service = PromoCatalogService(repository)

    result = service.search_promo_catalog(
        {"query": "Buy 3 Get 1", "mode": "targeted", "top_k": 5}
    )

    assert result["published_candidate_count"] == 5
    assert result["current_candidate_count"] == 4
    assert result["expired_candidate_count"] == 1
    assert "promo:michelin-3plus1" not in result["allowed_promo_refs"]
    assert all(
        row["promo_id"] != "michelin-3plus1"
        for row in result["candidates"]
    )


def test_targeted_multi_brand_query_reports_each_unmatched_brand() -> None:
    service = PromoCatalogService(FakePromoRepository())

    result = service.search_promo_catalog(
        {
            "query": "May Bridgestone at Michelin 3+1 promo ba?",
            "mode": "targeted",
            "top_k": 5,
        }
    )

    assert result["requested_brands"] == ["Bridgestone", "Michelin"]
    assert result["matched_requested_brands"] == ["Michelin"]
    assert result["unmatched_requested_brands"] == ["Bridgestone"]
    assert result["exact_requested_brand_match"] is True


def test_targeted_search_rejects_brand_added_only_by_model_plan() -> None:
    service = PromoCatalogService(FakePromoRepository())

    result = service.search_promo_catalog(
        {
            "query": "May Toyo o Yokohama Buy 3 Get 1 promo ba?",
            "mode": "targeted",
            "top_k": 5,
            "_customer_query_text": (
                "May Buy 3 Get 1 ba ang Toyo? "
                "Kung wala, anong current brands ang meron?"
            ),
            "_customer_requested_brands": ["TOYO", "YOKOHAMA"],
        }
    )

    assert result["requested_brands"] == ["Toyo"]
    assert result["matched_requested_brands"] == []
    assert result["unmatched_requested_brands"] == ["Toyo"]
    assert result["rejected_plan_brands"] == ["Yokohama"]
    assert "Yokohama" not in result["query"]
    assert {row["promo_id"] for row in result["candidates"][:2]} == {
        "michelin-3plus1",
        "apollo-3plus1",
    }


def test_explicit_three_plus_one_constraint_rejects_unrelated_brand_offer() -> None:
    candidate = {
        "title": "Toyo PHP 1,000 Off",
        "offer_summary": "Get PHP 1,000 off per tire",
        "relevant_mechanics": [{"text": "Buy four tires with a discount"}],
    }

    assert (
        promo_candidate_matches_explicit_constraints(
            "May Toyo Buy 3 Get 1 promo ba?",
            candidate,
        )
        is False
    )


def test_explicit_offer_amount_constraint_ignores_tire_size_numbers() -> None:
    candidate = {
        "title": "Yokohama PHP 5,200 Off",
        "offer_summary": "PHP 5,200 off",
        "relevant_mechanics": [],
    }

    assert promo_candidate_matches_explicit_constraints(
        "May 5200 off ba sa Yokohama 175/65R14?",
        candidate,
    )
    assert promo_candidate_matches_explicit_constraints(
        "May promo ba sa Yokohama 175/65R14?",
        candidate,
    )


def test_reviewed_promo_applicability_requires_exact_size_visible_product() -> None:
    card = _card("michelin-3plus1", "Michelin 3+1", ["Michelin"], "Buy 3 get 1")
    card["eligibility"] = {
        "scope": "all_brand_products",
        "included_brands": ["Michelin"],
        "excluded_brands": [],
        "included_patterns": [],
        "excluded_patterns": [],
        "included_sizes": [],
        "excluded_sizes": [],
    }

    eligible = evaluate_promo_applicability(
        card,
        tire_size="195/60R15",
        products=[{"brand": "Michelin", "tire_size": "195/60R15", "product_id": "m1"}],
        inventory_checked=True,
    )
    unavailable = evaluate_promo_applicability(
        card,
        tire_size="195/60R14",
        products=[{"brand": "Michelin", "tire_size": "195/60R15", "product_id": "m1"}],
        inventory_checked=True,
    )

    assert eligible["status"] == "eligible"
    assert unavailable == {
        "status": "ineligible",
        "reason": "no_visible_eligible_exact_size_product",
        "tire_size": "195/60R14",
    }


def test_size_qualified_search_allows_only_inventory_verified_promos() -> None:
    repository = FakePromoRepository()
    for card in repository.cards:
        card["eligibility"] = {
            "scope": "selected_patterns" if card["promo_id"] == "michelin-japan" else "all_brand_products",
            "included_brands": card["brands"],
            "excluded_brands": [],
            "included_patterns": ["Pilot Sport"] if card["promo_id"] == "michelin-japan" else [],
            "excluded_patterns": [],
            "included_sizes": [],
            "excluded_sizes": [],
        }
    service = PromoCatalogService(
        repository,
        product_lookup=lambda _size, _brands: [
            {"brand": "Michelin", "tire_size": "195/60R15", "product_id": "m1"}
        ],
    )

    result = service.search_promo_catalog(
        {"query": "", "mode": "general", "top_k": 8, "tire_size": "195 60 15"}
    )

    assert result["tire_size"] == "195/60R15"
    assert result["allowed_promo_refs"] == ["promo:michelin-3plus1"]


def test_targeted_promo_composer_requires_direct_source_backed_answer() -> None:
    prompt = " ".join(FINAL_COMPOSER_SYSTEM_PROMPT.split())

    assert "answer the customer's promo question directly" in prompt
    assert "offer_summary and relevant_mechanics" in prompt
    assert "A gallery or Promo Details button does not replace" in prompt


def test_present_only_accepts_current_search_refs_and_caps_targeted_to_three() -> None:
    service = PromoCatalogService(FakePromoRepository())
    search = service.search_promo_catalog({"query": "promo", "mode": "targeted", "top_k": 5})

    denied = service.present_promo_gallery({"promo_refs": ["promo:not-returned"], "trigger_mode": "targeted"})
    shown = service.present_promo_gallery(
        {"promo_refs": search["allowed_promo_refs"], "trigger_mode": "targeted"}
    )

    assert denied["status"] == "error"
    assert shown["status"] == "ok"
    assert len(shown["promo_refs"]) == 3
    assert len(shown["cards"]) == 3
    assert shown["promo_types"]
    assert shown["promo_titles"]


def test_present_exposes_reviewed_warranty_type_for_renderer_composition() -> None:
    repository = FakePromoRepository()
    repository.cards.append(
        _card(
            "double-warranty",
            "The Gulong Double Warranty",
            [],
            "Two source-backed warranty layers.",
            promo_type="warranty",
        )
    )
    repository.cards[-1]["eligibility"] = {
        "scope": "all_brand_products",
        "included_brands": [],
        "excluded_brands": [],
        "included_patterns": [],
        "excluded_patterns": [],
        "included_sizes": [],
        "excluded_sizes": [],
    }
    service = PromoCatalogService(repository)
    search = service.search_promo_catalog(
        {
            "query": "The Gulong Double Warranty",
            "mode": "targeted",
            "top_k": 1,
        }
    )

    shown = service.present_promo_gallery(
        {
            "promo_refs": search["allowed_promo_refs"],
            "trigger_mode": "targeted",
        }
    )

    assert shown["status"] == "ok"
    assert shown["promo_types"] == ["warranty"]
    assert shown["promo_titles"] == ["The Gulong Double Warranty"]


def test_exact_title_gallery_completion_does_not_expand_to_related_promos() -> None:
    repository = FakePromoRepository()
    repository.cards.append(
        _card(
            "double-warranty",
            "The Gulong Double Warranty",
            [],
            "Two source-backed warranty layers.",
            promo_type="warranty",
        )
    )
    repository.cards[-1]["eligibility"] = {
        "scope": "all_brand_products",
        "included_brands": [],
        "excluded_brands": [],
        "included_patterns": [],
        "excluded_patterns": [],
        "included_sizes": [],
        "excluded_sizes": [],
    }
    service = PromoCatalogService(repository)
    harness = RuntimeV7Harness(
        model_client=NoopModel(),
        tools=ProductToolHarness(runner=NoopRunner()),
        promo_catalog=service,
        profile_fields={"channel": "manychat"},
    )
    search_args = {
        "query": "The Gulong Double Warranty",
        "mode": "targeted",
        "top_k": 5,
        "presentation_mode": "gallery_if_available",
        "supporting_context": True,
    }
    search_result = service.search_promo_catalog(search_args)
    record = {
        "user_message": "185/60R15 options please.",
        "tool_results": [
            {
                "name": "product_search",
                "args": {"quantity": 4},
                "full_result": {
                    "status": "ok",
                    "presentation_ref": "pres_product_exact_promo",
                    "product_cards": [
                        {
                            "card_ref": "card_1",
                            "brand": "ARIVO",
                            "tire_size": "185/60R15",
                            "tire_protection_plan": (
                                "Tire Protection Plan (6 Months)"
                            ),
                        }
                    ],
                },
            },
        ],
    }

    gallery_record = harness._complete_requested_promo_gallery(
        search_result=search_result,
        search_args=search_args,
        round_index=2,
        record=record,
    )

    assert gallery_record["args"]["promo_refs"] == [
        "promo:double-warranty"
    ]
    assert gallery_record["full_result"]["promo_titles"] == [
        "The Gulong Double Warranty"
    ]
    assert gallery_record["completion_source"] == (
        "product_tpp_supporting_surface_policy"
    )

    from runtime_v7.runtime_harness import _build_customer_turn_plan

    record["tool_results"].append(gallery_record)
    plan = _build_customer_turn_plan(
        record=record,
        order_readiness={},
        draft_assistant_text="",
    )
    assert {
        surface["surface_type"]
        for surface in plan["available_surfaces"]
    } == {"promo_catalog", "product_cards"}


def test_automatic_warranty_gallery_requires_exact_reviewed_title_and_keeps_text_fallback() -> None:
    service = PromoCatalogService(FakePromoRepository())
    harness = RuntimeV7Harness(
        model_client=NoopModel(),
        tools=ProductToolHarness(runner=NoopRunner()),
        promo_catalog=service,
        profile_fields={"channel": "manychat"},
    )
    product_result = {
        "status": "ok",
        "presentation_ref": "pres_product_tpp_without_exact_warranty",
        "product_cards": [
            {
                "card_ref": "card_1",
                "brand": "ARIVO",
                "tire_size": "185/60R15",
                "card_text": "ARIVO 185/60R15 - PHP 3,500",
                "tire_protection_plan": "Tire Protection Plan (6 Months)",
            }
        ],
    }
    record = {
        "user_message": "185/60R15 options please.",
        "tool_results": [
            {
                "name": "product_search",
                "args": {"quantity": 4},
                "full_result": product_result,
            }
        ],
    }

    harness._complete_product_supporting_promo_gallery(record)

    assert [item["name"] for item in record["tool_results"]] == [
        "product_search",
        "search_promo_catalog",
    ]
    assert not any(
        item.get("name") == "present_promo_gallery"
        for item in record["tool_results"]
    )
    assert record["response_guard_events"][-1]["gallery_status"] == (
        "not_available"
    )

    unrelated_search = service.search_promo_catalog(
        {"query": "promo", "mode": "general", "top_k": 1}
    )
    unrelated_search["query"] = "The Gulong Double Warranty"
    exact_miss_record = {"tool_results": [], "response_guard_events": []}
    exact_miss_gallery = harness._complete_requested_promo_gallery(
        search_result=unrelated_search,
        search_args={
            "query": "The Gulong Double Warranty",
            "mode": "targeted",
            "top_k": 1,
            "presentation_mode": "gallery_if_available",
            "supporting_context": True,
        },
        round_index=0,
        record=exact_miss_record,
    )
    assert exact_miss_gallery == {}
    assert exact_miss_record["response_guard_events"] == [
        {
            "type": "supporting_promo_exact_title_not_found",
            "reason": (
                "automatic_warranty_replacement_requires_exact_reviewed_title"
            ),
            "query": "The Gulong Double Warranty",
        }
    ]

    from runtime_v7.runtime_harness import _compose_runtime_final_response

    rendered = _compose_runtime_final_response(
        json.dumps(
            {
                "response_units": [
                    {
                        "type": "render_surface",
                        "content": {
                            "surface_ref": product_result["presentation_ref"]
                        },
                    }
                ]
            }
        ),
        record["tool_results"],
    )
    assert "ARIVO 185/60R15 - PHP 3,500" in rendered
    assert "The Gulong Tire Protection Plan" in rendered
    assert "Michelin Passion Experience" not in rendered


def test_targeted_brand_gallery_does_not_expand_to_related_brand_promos() -> None:
    service = PromoCatalogService(FakePromoRepository())
    harness = RuntimeV7Harness(
        model_client=NoopModel(),
        tools=ProductToolHarness(runner=NoopRunner()),
        promo_catalog=service,
        profile_fields={"channel": "manychat"},
    )
    search_args = {
        "query": "Apollo buy 3 get 1 promo mechanics",
        "mode": "targeted",
        "top_k": 5,
        "presentation_mode": "gallery_if_available",
        "_customer_query_text": "Ano mechanics ng Apollo buy 3 get 1 promo?",
        "_customer_requested_brands": ["APOLLO"],
    }
    search_result = service.search_promo_catalog(search_args)

    gallery_record = harness._complete_requested_promo_gallery(
        search_result=search_result,
        search_args=search_args,
        round_index=1,
        record={"user_message": search_args["_customer_query_text"], "tool_results": []},
    )

    assert search_result["matched_requested_brands"] == ["Apollo"]
    assert gallery_record["args"]["promo_refs"] == ["promo:apollo-3plus1"]
    assert gallery_record["full_result"]["promo_titles"] == ["Apollo 3+1 Promo"]


def test_specific_promo_prompt_prefers_one_useful_visual_without_forcing_repeats() -> None:
    prompt = " ".join(build_runtime_v7_system_prompt(["product"]).split())
    tool = next(
        item["function"]
        for item in PROMO_TOOL_SCHEMAS
        if item["function"]["name"] == "search_promo_catalog"
    )
    presentation_description = tool["parameters"]["properties"]["presentation_mode"]["description"]

    assert "first explicit question about a specific active promotion" in prompt
    assert "presentation_mode=gallery_if_available" in prompt
    assert "single relevant card" in prompt
    assert "visual was already shown" in prompt
    assert "Never broaden a named-brand promo question into unrelated brand cards" in prompt
    assert "first explicit question about a specific active promo" in presentation_description
    assert "The text answer must still be direct" in presentation_description


def test_model_gallery_call_is_scoped_to_exact_catalog_title_search() -> None:
    repository = FakePromoRepository()
    repository.cards.append(
        _card(
            "double-warranty",
            "The Gulong Double Warranty",
            [],
            "Two source-backed warranty layers.",
            promo_type="warranty",
        )
    )
    repository.cards[-1]["eligibility"] = {
        "scope": "all_brand_products",
        "included_brands": [],
        "excluded_brands": [],
        "included_patterns": [],
        "excluded_patterns": [],
        "included_sizes": [],
        "excluded_sizes": [],
    }
    service = PromoCatalogService(repository)
    harness = RuntimeV7Harness(
        model_client=NoopModel(),
        tools=ProductToolHarness(runner=NoopRunner()),
        promo_catalog=service,
        profile_fields={"channel": "manychat"},
    )
    search_args = {
        "query": "Ano po yung Gulong Double Warranty? Paki-show yung current promo details.",
        "mode": "targeted",
        "top_k": 5,
        "presentation_mode": "gallery_if_available",
        "explicit_redisplay": False,
    }
    search = service.search_promo_catalog(search_args)
    assert "promo:double-warranty" in search["allowed_promo_refs"]
    automatic = harness._complete_requested_promo_gallery(
        search_result=search,
        search_args=search_args,
        round_index=1,
        record={"tool_results": [], "response_guard_events": []},
    )
    assert automatic["args"]["promo_refs"] == ["promo:double-warranty"]
    assert automatic["full_result"]["promo_titles"] == [
        "The Gulong Double Warranty"
    ]
    harness.latest_promo_presentation = {}
    harness.promo_presentation_history = []
    record = {
        "tool_results": [
            {
                "name": "search_promo_catalog",
                "args": search_args,
                "full_result": search,
            }
        ]
    }
    model_args = {
        "promo_refs": list(search["allowed_promo_refs"]),
        "trigger_mode": "targeted",
        "explicit_redisplay": False,
    }

    result, _compact, _latency_ms, reused = (
        harness._execute_tool_call_with_turn_cache(
            {"id": "model-gallery", "name": "present_promo_gallery"},
            model_args,
            round_index=1,
            record=record,
            tool_result_cache={},
            allowed_tool_names=["present_promo_gallery"],
            current_user_message="Ano po yung Gulong Double Warranty?",
            active_working_memory="",
            background_signals=[],
            order_readiness={},
        )
    )

    assert reused is False
    assert model_args["promo_refs"] == ["promo:double-warranty"]
    assert result["promo_titles"] == ["The Gulong Double Warranty"]
    assert record["tool_arg_normalization_events"] == [
        {
            "round": 1,
            "type": "exact_catalog_title_gallery_scope",
            "name": "present_promo_gallery",
            "tool_call_id": "model-gallery",
            "proposed_promo_refs": search["allowed_promo_refs"],
            "authorized_promo_refs": ["promo:double-warranty"],
        }
    ]


def test_present_keeps_allowed_refs_from_mixed_model_proposal() -> None:
    service = PromoCatalogService(FakePromoRepository())
    search = service.search_promo_catalog(
        {"query": "Michelin promo", "mode": "targeted", "top_k": 5}
    )
    allowed = search["allowed_promo_refs"][:2]

    shown = service.present_promo_gallery(
        {
            "promo_refs": [*allowed, "promo:not-returned"],
            "trigger_mode": "targeted",
        }
    )

    assert shown["status"] == "ok"
    assert shown["promo_refs"] == allowed
    assert shown["rejected_promo_refs"] == ["promo:not-returned"]
    assert shown["selection_normalized"] is True


def test_customer_wording_never_deterministically_preloads_promo_tools() -> None:
    harness = RuntimeV7Harness(
        model_client=NoopModel(),
        tools=ProductToolHarness(runner=NoopRunner()),
        promo_catalog=PromoCatalogService(FakePromoRepository()),
    )

    assert harness._prepare_promo_context_for_turn(
        user_message="Hi hm po 195 60 15 promo magkano",
        background_signals=[],
    ) == []
    assert is_targeted_promo_query("Ano po yung Michelin trip to Japan promo?")


def test_typed_current_promo_discovery_preloads_provider_gallery() -> None:
    harness = RuntimeV7Harness(
        model_client=NoopModel(),
        tools=ProductToolHarness(runner=NoopRunner()),
        promo_catalog=PromoCatalogService(FakePromoRepository()),
    )

    records = harness._prepare_promo_context_for_turn(
        user_message="Patingin po ng mga promo ngayon.",
        background_signals=[
            {
                "key": "promo_discovery_scope",
                "value": "all_current",
                "source": "latest_user_message",
                "relation": "question_only",
            }
        ],
    )

    assert [record["name"] for record in records] == [
        "search_promo_catalog",
        "present_promo_gallery",
    ]
    assert records[0]["args"] == {
        "query": "",
        "mode": "general",
        "top_k": 8,
        "presentation_mode": "gallery_if_available",
        "explicit_redisplay": True,
    }
    assert records[0]["full_result"]["allowed_promo_refs"]
    assert records[1]["full_result"]["status"] == "ok"
    assert records[1]["full_result"]["cards"]
    assert records[1]["completion_source"] == (
        "semantic_current_promo_discovery_scope"
    )


@pytest.mark.parametrize("tool_name", ["search_promo_catalog", "present_promo_gallery"])
def test_model_repeat_reuses_successful_runtime_promo_preload(
    tool_name: str,
) -> None:
    harness = RuntimeV7Harness(
        model_client=NoopModel(),
        tools=ProductToolHarness(runner=NoopRunner()),
        promo_catalog=PromoCatalogService(FakePromoRepository()),
    )
    preloaded = harness._prepare_promo_context_for_turn(
        user_message="Show me the current promos.",
        background_signals=[
            {
                "key": "promo_discovery_scope",
                "value": "all_current",
                "source": "latest_user_message",
                "relation": "question_only",
            }
        ],
    )
    record = {"tool_results": preloaded}

    full, compact, latency_ms, reused = harness._execute_tool_call_with_turn_cache(
        {"id": f"model_repeat_{tool_name}", "name": tool_name},
        {},
        round_index=2,
        record=record,
        tool_result_cache={},
        allowed_tool_names=[],
        current_user_message="Show me the current promos.",
        active_working_memory="",
        background_signals=[],
        order_readiness={},
    )

    assert full["status"] == "ok"
    assert compact["status"] == "ok"
    assert latency_ms == 0
    assert reused is True
    assert not record.get("tool_guard_events")
    assert record["tool_dedupe_events"] == [
        {
            "round": 2,
            "type": "runtime_preloaded_tool_call_reused",
            "name": tool_name,
            "tool_call_id": f"model_repeat_{tool_name}",
            "first_round": 0,
            "first_tool_call_id": f"runtime_preload_{tool_name}",
            "args": {},
            "observation_ref": compact.get("observation_ref"),
            "presentation_ref": compact.get("presentation_ref"),
        }
    ]


@pytest.mark.parametrize(
    "signal",
    [
        {
            "key": "promo_discovery_scope",
            "value": "all_current",
            "source": "customer_history",
            "relation": "question_only",
        },
        {
            "key": "promo_discovery_scope",
            "value": "all_current",
            "source": "signal_ledger",
            "relation": "question_only",
            "metadata": {
                "ledger": {"authority_source": "latest_user_message"}
            },
        },
        {
            "key": "promo_discovery_scope",
            "value": "all_current",
            "source": "latest_user_message",
            "relation": "asserted",
        },
        {
            "key": "promo_discovery_scope",
            "value": "one_brand",
            "source": "latest_user_message",
            "relation": "question_only",
        },
    ],
)
def test_promo_discovery_preload_rejects_non_current_browse_scope(
    signal: dict,
) -> None:
    harness = RuntimeV7Harness(
        model_client=NoopModel(),
        tools=ProductToolHarness(runner=NoopRunner()),
        promo_catalog=PromoCatalogService(FakePromoRepository()),
    )

    assert harness._prepare_promo_context_for_turn(
        user_message="promo",
        background_signals=[signal],
    ) == []


def test_semantic_promo_signal_runs_through_harness_and_renderer() -> None:
    signal_client = StaticBackgroundSignalModel(
        {
            "key": "promo_discovery_scope",
            "value": "all_current",
            "source": "latest_user_message",
            "confidence": "high",
            "relation": "question_only",
        }
    )
    harness = RuntimeV7Harness(
        model_client=NoopModel(),
        tools=ProductToolHarness(runner=NoopRunner()),
        promo_catalog=PromoCatalogService(FakePromoRepository()),
        background_signal_model_client=signal_client,
    )

    record = harness.run_turn("Pwede makita lahat ng deals niyo ngayon?")
    rendered = render_turn_for_channel(
        record,
        service_environment="staging",
    )

    assert [item["name"] for item in record["tool_results"][:2]] == [
        "search_promo_catalog",
        "present_promo_gallery",
    ]
    exposed_schema_names = {
        schema["function"]["name"]
        for schema in record["llm_calls"][0]["tool_schemas"]
    }
    assert "search_promo_catalog" not in exposed_schema_names
    assert "present_promo_gallery" not in exposed_schema_names
    assert (
        "typed_current_promo_discovery:catalog_and_gallery_preloaded"
        in record["capability_profile"]["selection_reasons"]
    )
    assert any(
        message.get("type") == "cards"
        for message in rendered.content_messages
    )
    assert "promo_discovery_scope" not in {
        signal["key"]
        for signal in harness.signal_ledger.load(harness.session_id)
    }


def test_exact_named_catalog_reference_is_dynamic_and_not_general_warranty() -> None:
    repository = FakePromoRepository()
    repository.cards.append(
        _card(
            "double-warranty",
            "The Gulong Double Warranty",
            [],
            "Two source-backed warranty layers.",
            promo_type="warranty",
        )
    )
    service = PromoCatalogService(repository)

    assert service.exact_named_promo_reference(
        "Ano ang mechanics ng The Gulong Double Warranty?"
    )["promo_id"] == "double-warranty"
    assert service.exact_named_promo_reference(
        "Ano po yung Gulong Double Warranty?"
    )["promo_id"] == "double-warranty"
    assert service.exact_named_promo_reference("May warranty ba ang tires?") == {}


def test_named_catalog_reference_selects_promo_tool_without_general_faq() -> None:
    repository = FakePromoRepository()
    repository.cards.append(
        _card(
            "double-warranty",
            "The Gulong Double Warranty",
            [],
            "Two source-backed warranty layers.",
            promo_type="warranty",
        )
    )
    context = _named_catalog_promo_tool_context(
        current_user_message="Ano ang mechanics ng The Gulong Double Warranty?",
        promo_catalog=PromoCatalogService(repository),
        tool_schemas=PROMO_TOOL_SCHEMAS,
    )

    assert context["tool_name"] == "search_promo_catalog"
    assert context["promo_id"] == "double-warranty"


def test_named_catalog_reference_exposes_context_without_forcing_tool() -> None:
    repository = FakePromoRepository()
    repository.cards.append(
        _card(
            "double-warranty",
            "The Gulong Double Warranty",
            [],
            "Two source-backed warranty layers.",
            promo_type="warranty",
        )
    )
    harness = RuntimeV7Harness(
        model_client=NoopModel(),
        tools=ProductToolHarness(runner=NoopRunner()),
        promo_catalog=PromoCatalogService(repository),
    )

    record = harness.run_turn("Ano ang mechanics ng The Gulong Double Warranty?")

    assert record["llm_calls"][0]["tool_choice"] == "auto"
    assert record["tool_routing_events"][0]["type"] == (
        "named_catalog_promo_context_available"
    )
    assert record["tool_routing_events"][0]["tool_choice"] == "model_owned"


def test_first_tpp_pricelist_reuses_reviewed_warranty_catalog_surface() -> None:
    repository = FakePromoRepository()
    repository.cards.append(
        _card(
            "double-warranty",
            "The Gulong Double Warranty",
            [],
            "Two source-backed warranty layers.",
            promo_type="warranty",
        )
    )
    repository.cards[-1]["eligibility"] = {
        "scope": "all_brand_products",
        "included_brands": [],
        "excluded_brands": [],
        "included_patterns": [],
        "excluded_patterns": [],
        "included_sizes": [],
        "excluded_sizes": [],
    }
    harness = RuntimeV7Harness(
        model_client=NoopModel(),
        tools=ProductToolHarness(runner=NoopRunner()),
        promo_catalog=PromoCatalogService(
            repository,
            product_lookup=lambda _size, _brands: [
                {
                    "brand": "ARIVO",
                    "tire_size": "185/60R15",
                    "product_id": "prod-arivo",
                }
            ],
        ),
        profile_fields={"channel": "manychat"},
    )
    record = {
        "user_message": "185/60R15 pala yung nasa sidewall.",
        "tool_results": [
            {
                "name": "product_search",
                "args": {"quantity": 4},
                "full_result": {
                    "status": "ok",
                    "presentation_ref": "pres_product_tpp",
                    "product_cards": [
                        {
                            "card_ref": "card_1",
                            "brand": "ARIVO",
                            "tire_size": "185/60R15",
                            "tire_protection_plan": "Tire Protection Plan (6 Months)",
                        }
                    ],
                },
            },
            {
                "name": "present_promo_gallery",
                "args": {
                    "promo_refs": [],
                    "explicit_redisplay": False,
                },
                "full_result": {
                    "status": "error",
                    "reason": "search_promo_catalog must run before presentation",
                    "presentation_surfaces": [],
                },
            },
        ],
    }

    harness._complete_product_supporting_promo_gallery(record)

    assert [item["name"] for item in record["tool_results"]] == [
        "product_search",
        "present_promo_gallery",
        "search_promo_catalog",
        "present_promo_gallery",
    ]
    gallery = record["tool_results"][-1]["full_result"]
    assert gallery["status"] == "ok"
    assert gallery["promo_types"] == ["warranty"]
    assert gallery["promo_titles"] == ["The Gulong Double Warranty"]
    assert record["response_guard_events"][-1] == {
        "type": "supporting_promo_catalog_lookup",
        "reason": "first_tpp_product_pricelist",
        "status": "ok",
        "gallery_status": "ok",
    }

    from runtime_v7.runtime_harness import (
        _build_customer_turn_plan,
        _final_composer_presentation_surfaces,
        _final_composer_renderer_contract_violations,
        _final_composer_tool_results,
        _promo_fact_audit_context,
    )

    plan = _build_customer_turn_plan(
        record=record,
        order_readiness={},
        draft_assistant_text="",
    )
    assert {
        surface["surface_type"]
        for surface in plan["available_surfaces"]
    } == {"promo_catalog", "product_cards"}
    assert {
        surface["decision_layer"]
        for surface in plan["available_surfaces"]
    } == {"product"}
    planned_by_type = {
        surface["surface_type"]: surface
        for surface in plan["available_surfaces"]
    }
    assert planned_by_type["product_cards"]["response_role"] == "direct_answer"
    assert planned_by_type["product_cards"]["required"] is True
    assert planned_by_type["promo_catalog"]["response_role"] == (
        "supporting_replacement"
    )
    assert planned_by_type["promo_catalog"]["required"] is True
    assert plan["request_obligations"] == [
        {
            "obligation_id": "surface:pres_product_tpp",
            "objective": "product",
            "required_response_modes": ["surface"],
            "authorized_surface_refs": ["pres_product_tpp"],
        }
    ]
    composer_surfaces = _final_composer_presentation_surfaces(
        record["tool_results"]
    )
    supporting = next(
        surface
        for surface in composer_surfaces
        if surface.get("type") == "promo_catalog"
    )
    assert supporting["supporting_context"] is True
    assert "active product choice" in supporting["composer_guidance"]
    assert "caption" in supporting["composer_guidance"]
    assert "card_headers" not in supporting
    assert "promo_refs" not in supporting
    product_surface = next(
        surface
        for surface in composer_surfaces
        if surface.get("type") == "product_cards"
    )
    assert all("warranty" not in card for card in product_surface["cards"])
    assert all(
        "tire_protection_plan" not in card
        for card in product_surface["cards"]
    )
    compact_tool_results = _final_composer_tool_results(record["tool_results"])
    assert all(row["name"] != "search_promo_catalog" for row in compact_tool_results)
    assert [
        row["name"] for row in compact_tool_results
    ].count("present_promo_gallery") == 1
    assert _promo_fact_audit_context(record["tool_results"]) == {}
    assert not _final_composer_renderer_contract_violations(
        [
            {
                "type": "render_surface",
                "content": {"surface_ref": "pres_product_tpp"},
            },
            {
                "type": "render_surface",
                "content": {
                    "surface_ref": gallery["presentation_ref"],
                },
            },
        ],
        record["tool_results"],
        customer_turn_plan=plan,
    )
    duplicate_prose_violations = _final_composer_renderer_contract_violations(
        [
            {
                "type": "text",
                "content": {
                    "text": (
                        "May Double Warranty din ito. Gusto mo bang i-check "
                        "ang warranty details?"
                    )
                },
            },
            {
                "type": "render_surface",
                "content": {"surface_ref": "pres_product_tpp"},
            },
            {
                "type": "render_surface",
                "content": {"surface_ref": gallery["presentation_ref"]},
            },
        ],
        record["tool_results"],
        customer_turn_plan=plan,
    )
    assert any(
        item["type"] == "duplicate_supporting_replacement_prose"
        for item in duplicate_prose_violations
    )
    duplicate_payload = {
        "response_units": [
            {
                "type": "text",
                "content": {
                    "text": (
                        "May Double Warranty din ito. Ang alin sa tire "
                        "options ang gusto mong tingnan?"
                    )
                },
            },
            {
                "type": "render_surface",
                "content": {"surface_ref": "pres_product_tpp"},
            },
            {
                "type": "render_surface",
                "content": {"surface_ref": gallery["presentation_ref"]},
            },
        ]
    }
    sanitized_text, sanitized_units, removed_count = (
        _sanitize_duplicate_supporting_replacement_prose(
            json.dumps(duplicate_payload),
            duplicate_payload["response_units"],
            customer_turn_plan=plan,
        )
    )
    assert removed_count == 1
    assert "Double Warranty" not in sanitized_text
    assert "alin sa tire options" in sanitized_units[0]["content"]["text"]
    assert not _final_composer_renderer_contract_violations(
        sanitized_units,
        record["tool_results"],
        customer_turn_plan=plan,
    )
    explicit_warranty_plan = deepcopy(plan)
    explicit_warranty_plan.setdefault("progression_context", {})[
        "required_faq_fact_answers"
    ] = [
        {
            "faq_id": "product_tire_protection_plan",
            "domain": "product",
            "authored_answer": "Grounded Tire Protection Plan coverage answer.",
            "answer_required": True,
        }
    ]
    assert not any(
        item["type"] == "duplicate_supporting_replacement_prose"
        for item in _final_composer_renderer_contract_violations(
            [
                {
                    "type": "text",
                    "content": {
                        "text": "Here is the grounded Tire Protection Plan coverage."
                    },
                },
                {
                    "type": "render_surface",
                    "content": {"surface_ref": "pres_product_tpp"},
                },
                {
                    "type": "render_surface",
                    "content": {"surface_ref": gallery["presentation_ref"]},
                },
            ],
            record["tool_results"],
            customer_turn_plan=explicit_warranty_plan,
        )
    )
    explicit_answer_plus_second_cta = (
        _final_composer_renderer_contract_violations(
            [
                {
                    "type": "text",
                    "content": {
                        "text": (
                            "Here is the grounded Tire Protection Plan coverage. "
                            "Would you like to check promo details nito?"
                        )
                    },
                },
                {
                    "type": "render_surface",
                    "content": {"surface_ref": "pres_product_tpp"},
                },
                {
                    "type": "render_surface",
                    "content": {"surface_ref": gallery["presentation_ref"]},
                },
            ],
            record["tool_results"],
            customer_turn_plan=explicit_warranty_plan,
        )
    )
    assert any(
        item["type"] == "duplicate_supporting_replacement_prose"
        for item in explicit_answer_plus_second_cta
    )

    second_record = {
        "user_message": "May iba pa bang option?",
        "tool_results": list(record["tool_results"][:1]),
    }
    harness._complete_product_supporting_promo_gallery(second_record)

    assert [item["name"] for item in second_record["tool_results"]] == [
        "product_search"
    ]


def test_compact_mechanics_keep_bounded_operational_url_after_core_rows() -> None:
    rows = [
        {"ordinal": ordinal, "text": f"Core mechanic {ordinal}"}
        for ordinal in range(1, 7)
    ]
    rows.append(
        {
            "ordinal": 7,
            "text": "Complete the Google Form: https://docs.google.com/forms/d/e/example/viewform",
        }
    )

    selected = _select_compact_mechanic_rows(rows, max_chunks=5)

    assert [row["ordinal"] for row in selected[:4]] == [1, 2, 3, 4]
    assert selected[-1]["ordinal"] == 7
    assert len(selected) == 5


def test_validated_brandless_promo_search_completes_renderer_gallery() -> None:
    service = PromoCatalogService(FakePromoRepository())
    harness = RuntimeV7Harness(
        model_client=NoopModel(),
        tools=ProductToolHarness(runner=NoopRunner()),
        promo_catalog=service,
        profile_fields={"channel": "manychat"},
    )
    args = {
        "query": "current Buy 3 Get 1 promos",
        "mode": "general",
        "top_k": 5,
        "promo_types": ["buy3get1"],
    }
    search = harness._execute_tool("search_promo_catalog", args)
    record = {
        "tool_results": [
            {
                "name": "search_promo_catalog",
                "args": args,
                "full_result": search,
            }
        ]
    }

    harness._complete_validated_promo_gallery(record)

    gallery = record["tool_results"][-1]
    assert gallery["name"] == "present_promo_gallery"
    assert gallery["runtime_preloaded"] is True
    assert gallery["full_result"]["status"] == "ok"
    assert gallery["full_result"]["card_runtime_insert"] is True
    assert record["response_guard_events"] == [
        {
            "type": "validated_promo_surface_completed",
            "reason": "brandless_promo_discovery",
            "status": "ok",
        }
    ]


def test_validated_product_promo_prevents_irrelevant_alternative_gallery() -> None:
    service = PromoCatalogService(FakePromoRepository())
    harness = RuntimeV7Harness(
        model_client=NoopModel(),
        tools=ProductToolHarness(runner=NoopRunner()),
        promo_catalog=service,
        profile_fields={"channel": "manychat"},
    )
    args = {
        "query": "Vredestein Buy 3 Get 1",
        "mode": "targeted",
        "top_k": 5,
        "promo_types": ["buy3get1"],
    }
    search = harness._execute_tool("search_promo_catalog", args)
    search["requested_brands"] = ["Vredestein"]
    search["unmatched_requested_brands"] = ["Vredestein"]
    record = {
        "tool_results": [
            {
                "name": "search_promo_catalog",
                "args": args,
                "full_result": search,
            },
            {
                "name": "product_search",
                "args": {"brands": ["Vredestein"], "quantity": 4},
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
        ]
    }

    harness._complete_validated_promo_gallery(record)

    assert [item["name"] for item in record["tool_results"]] == [
        "search_promo_catalog",
        "product_search",
    ]
    assert "response_guard_events" not in record


def test_promo_tool_contract_allows_only_model_declared_explicit_redisplay() -> None:
    tool = next(item["function"] for item in PROMO_TOOL_SCHEMAS if item["function"]["name"] == "present_promo_gallery")
    properties = tool["parameters"]["properties"]

    assert properties["explicit_redisplay"]["type"] == "boolean"
    assert "explicit_redisplay" in tool["parameters"]["required"]
    assert "explicitly asks to see, reopen, or resend" in tool["description"]


def test_promo_search_contract_combines_lookup_and_surface_decision() -> None:
    tool = next(
        item["function"]
        for item in PROMO_TOOL_SCHEMAS
        if item["function"]["name"] == "search_promo_catalog"
    )
    properties = tool["parameters"]["properties"]

    assert properties["presentation_mode"]["enum"] == [
        "answer_only",
        "gallery_if_available",
    ]
    assert properties["explicit_redisplay"]["type"] == "boolean"
    assert properties["alternative_scope"]["enum"] == [
        "none",
        "same_mechanic",
        "any_current",
    ]
    assert "presentation_mode" in tool["parameters"]["required"]
    assert "explicit_redisplay" in tool["parameters"]["required"]
    assert "alternative_scope" in tool["parameters"]["required"]


@pytest.mark.parametrize(
    ("alternative_scope", "expected_titles"),
    [
        ("none", set()),
        (
            "same_mechanic",
            {"Michelin 3+1 Promo", "Apollo 3+1 Promo"},
        ),
        (
            "any_current",
            {
                "Michelin Passion Experience 2026",
                "Michelin 3+1 Promo",
                "Apollo 3+1 Promo",
                "Yokohama PHP 5,200 Off",
                "Yokohama PHP 6,000 Off",
            },
        ),
    ],
)
def test_requested_promo_fallback_scope_authorizes_only_provider_ranked_refs(
    alternative_scope: str,
    expected_titles: set[str],
) -> None:
    service = PromoCatalogService(FakePromoRepository())

    result = service.search_promo_catalog(
        {
            "query": "Toyo Buy 3 Get 1",
            "mode": "targeted",
            "top_k": 8,
            "alternative_scope": alternative_scope,
        }
    )

    candidates_by_ref = {
        candidate["promo_ref"]: candidate
        for candidate in result["candidates"]
    }
    assert result["primary_promo_refs"] == []
    assert {
        candidates_by_ref[ref]["title"]
        for ref in result["alternative_promo_refs"]
    } == expected_titles
    assert result["allowed_promo_refs"] == result["alternative_promo_refs"]


def test_requested_any_current_promo_fallback_completes_gallery_without_model_round() -> None:
    service = PromoCatalogService(FakePromoRepository())
    harness = RuntimeV7Harness(
        model_client=NoopModel(),
        tools=ProductToolHarness(runner=NoopRunner()),
        promo_catalog=service,
        profile_fields={"channel": "manychat"},
    )
    args = {
        "query": "Toyo Buy 3 Get 1",
        "mode": "targeted",
        "top_k": 8,
        "presentation_mode": "gallery_if_available",
        "explicit_redisplay": False,
        "alternative_scope": "any_current",
    }
    search = harness._execute_tool("search_promo_catalog", args)

    gallery = harness._complete_requested_promo_gallery(
        search_result=search,
        search_args=args,
        round_index=1,
        record={"tool_results": []},
    )

    assert gallery["name"] == "present_promo_gallery"
    assert gallery["full_result"]["status"] == "ok"
    assert gallery["args"]["promo_refs"] == search["alternative_promo_refs"][:3]


def test_requested_promo_gallery_is_completed_without_model_selection_round() -> None:
    service = PromoCatalogService(FakePromoRepository())
    harness = RuntimeV7Harness(
        model_client=NoopModel(),
        tools=ProductToolHarness(runner=NoopRunner()),
        promo_catalog=service,
        profile_fields={"channel": "manychat"},
    )
    args = {
        "query": "Michelin promos",
        "mode": "targeted",
        "top_k": 3,
        "presentation_mode": "gallery_if_available",
        "explicit_redisplay": False,
    }
    search = harness._execute_tool("search_promo_catalog", args)
    record = {"tool_results": [], "response_guard_events": []}

    gallery = harness._complete_requested_promo_gallery(
        search_result=search,
        search_args=args,
        round_index=0,
        record=record,
    )

    assert gallery["name"] == "present_promo_gallery"
    assert gallery["runtime_completed"] is True
    assert gallery["latency_ms"] == 0
    assert gallery["completion_source"] == "search_presentation_mode"
    assert gallery["full_result"]["status"] == "ok"
    assert record["response_guard_events"] == [
        {
            "type": "requested_promo_surface_completed",
            "reason": "model_selected_gallery_if_available",
            "status": "ok",
        }
    ]
    assert record["execution_efficiency_events"] == [
        {
            "type": "promo_gallery_completed_from_search_contract",
            "model_selection_rounds_avoided": 1,
            "trigger_mode": "targeted",
            "promo_ref_count": 2,
            "status": "ok",
        }
    ]


def test_answer_only_promo_search_does_not_complete_gallery() -> None:
    service = PromoCatalogService(FakePromoRepository())
    harness = RuntimeV7Harness(
        model_client=NoopModel(),
        tools=ProductToolHarness(runner=NoopRunner()),
        promo_catalog=service,
    )
    args = {
        "query": "Michelin promos",
        "mode": "targeted",
        "top_k": 3,
        "presentation_mode": "answer_only",
        "explicit_redisplay": False,
    }
    search = harness._execute_tool("search_promo_catalog", args)

    assert harness._complete_requested_promo_gallery(
        search_result=search,
        search_args=args,
        round_index=0,
        record={"tool_results": []},
    ) == {}


def test_failed_presentation_before_search_does_not_block_authorized_gallery() -> None:
    service = PromoCatalogService(FakePromoRepository())
    harness = RuntimeV7Harness(
        model_client=NoopModel(),
        tools=ProductToolHarness(runner=NoopRunner()),
        promo_catalog=service,
        profile_fields={"channel": "manychat"},
    )
    args = {
        "query": "Michelin promos",
        "mode": "targeted",
        "top_k": 3,
        "presentation_mode": "gallery_if_available",
        "explicit_redisplay": False,
    }
    record = {
        "tool_results": [
            {
                "name": "present_promo_gallery",
                "args": {"promo_refs": ["model-guessed-ref"]},
                "full_result": {
                    "status": "tool_plan_not_authorized",
                    "message": "Search must establish current catalog refs first.",
                },
            }
        ],
        "response_guard_events": [],
    }
    search = harness._execute_tool("search_promo_catalog", args)

    gallery = harness._complete_requested_promo_gallery(
        search_result=search,
        search_args=args,
        round_index=1,
        record=record,
    )

    assert gallery["full_result"]["status"] == "ok"
    assert gallery["runtime_completed"] is True


@pytest.mark.parametrize("delivery_status", ["success", "pending", "unknown"])
def test_general_gallery_repeat_is_suppressed_by_delivery_attempt_not_words(
    delivery_status: str,
) -> None:
    service = PromoCatalogService(FakePromoRepository())
    harness = RuntimeV7Harness(
        model_client=NoopModel(),
        tools=ProductToolHarness(runner=NoopRunner()),
        promo_catalog=service,
        profile_fields={"channel": "manychat"},
    )
    harness.latest_promo_presentation = {
        "catalog_version_id": "catalog-v1",
        "delivery_status": delivery_status,
    }
    search = harness._execute_tool("search_promo_catalog", {"query": "", "mode": "general", "top_k": 8})

    result = harness._execute_tool(
        "present_promo_gallery",
        {"promo_refs": search["allowed_promo_refs"], "trigger_mode": "general"},
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "general_promo_catalog_already_presented"


def test_targeted_gallery_unknown_delivery_is_not_retried() -> None:
    service = PromoCatalogService(FakePromoRepository())
    harness = RuntimeV7Harness(
        model_client=NoopModel(),
        tools=ProductToolHarness(runner=NoopRunner()),
        promo_catalog=service,
        profile_fields={"channel": "manychat"},
    )
    search = harness._execute_tool(
        "search_promo_catalog",
        {"query": "Michelin promo", "mode": "targeted", "top_k": 3},
    )
    first = service.present_promo_gallery(
        {"promo_refs": search["allowed_promo_refs"], "trigger_mode": "targeted"}
    )
    harness.latest_promo_presentation = {
        "selection_fingerprint": first["selection_fingerprint"],
        "delivery_status": "unknown",
    }

    result = harness._execute_tool(
        "present_promo_gallery",
        {"promo_refs": search["allowed_promo_refs"], "trigger_mode": "targeted"},
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "targeted_promo_selection_already_presented"


@pytest.mark.parametrize("trigger_mode", ["general", "targeted"])
@pytest.mark.parametrize("delivery_status", ["success", "pending", "unknown", "delivery_unknown"])
def test_explicit_customer_request_can_redisplay_a_previously_attempted_gallery(
    trigger_mode: str,
    delivery_status: str,
) -> None:
    service = PromoCatalogService(FakePromoRepository())
    harness = RuntimeV7Harness(
        model_client=NoopModel(),
        tools=ProductToolHarness(runner=NoopRunner()),
        promo_catalog=service,
        profile_fields={"channel": "manychat"},
    )
    search = harness._execute_tool(
        "search_promo_catalog",
        {"query": "" if trigger_mode == "general" else "Michelin promo", "mode": trigger_mode, "top_k": 8},
    )
    first = service.present_promo_gallery(
        {"promo_refs": search["allowed_promo_refs"], "trigger_mode": trigger_mode}
    )
    harness.latest_promo_presentation = {
        "catalog_version_id": first["catalog_version_id"],
        "selection_fingerprint": first["selection_fingerprint"],
        "delivery_status": delivery_status,
    }

    result = harness._execute_tool(
        "present_promo_gallery",
        {
            "promo_refs": search["allowed_promo_refs"],
            "trigger_mode": trigger_mode,
            "explicit_redisplay": True,
        },
    )

    assert result["status"] == "ok"
    assert result["explicit_redisplay"] is True
    assert harness.latest_promo_presentation["explicit_redisplay"] is True


def test_renderer_emits_square_gallery_and_contact_actions() -> None:
    service = PromoCatalogService(FakePromoRepository())
    search = service.search_promo_catalog({"query": "", "mode": "general", "top_k": 8})
    presentation = service.present_promo_gallery(
        {"promo_refs": search["allowed_promo_refs"], "trigger_mode": "general"}
    )
    presentation["show_count"] = 3
    turn = {
        "runtime_final_response": "Narito po ang current promos.",
        "tool_results": [
            {
                "name": "present_promo_gallery",
                "full_result": presentation,
                "result": {"presentation_ref": presentation["presentation_ref"]},
            }
        ],
    }

    rendered = render_turn_for_channel(
        turn,
        profile_fields={"promo_gallery_show_count": 2},
        service_environment="staging",
    )

    gallery = next(message for message in rendered.content_messages if message["type"] == "cards")
    assert gallery["image_aspect_ratio"] == "square"
    assert len(gallery["elements"]) == 5
    assert all("action_url" not in element for element in gallery["elements"])
    assert all(
        button["target"] == "content-staging-promo-router"
        for element in gallery["elements"]
        for button in element["buttons"]
    )
    assert all(
        len(button.get("actions") or []) == 1
        for element in gallery["elements"]
        for button in element["buttons"]
    )
    click = gallery["elements"][0]["buttons"][0]["actions"][0]
    assert click["field_name"] == "promo_selected_id"
    assert parse_promo_click_token(click["value"])["card_id"] == "card-1"
    fields = {action["field_name"]: action["value"] for action in rendered.contact_actions}
    assert len(rendered.contact_actions) == 5
    assert fields["promo_catalog_version"] == "catalog-v1"
    assert fields["promo_gallery_show_count"] == 3
    assert fields["promo_gallery_shown"] is True


def test_renderer_emits_tracked_price_category_gallery(monkeypatch) -> None:
    monkeypatch.setenv("PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE", "content-staging-promo-router")
    cards = [
        {
            "bucket_ref": f"bucket_{index}",
            "choice_ref": f"price_category:{category}",
            "bucket": category,
            "label": label,
            "brands": [brand],
            "brand_count": 1,
            "product_count": 2,
            "min_price_text": "PHP 4,000.00",
            "max_price_text": "PHP 5,500.00",
            "position": index,
            "card_text": label,
        }
        for index, (category, label, brand) in enumerate(
            [
                ("budget", "Budget", "Atlas"),
                ("economy", "Economy", "Apollo"),
                ("mid_range", "Mid Range", "Yokohama"),
                ("premium", "Premium", "Michelin"),
            ],
            start=1,
        )
    ]
    cards[0]["brands"] = ["FRONWAY", "BLACK ARROW", "A VERY LONG BRAND"]
    cards[0]["brand_count"] = 5
    result = {
        "status": "ok",
        "presentation_ref": "price_categories_abc123",
        "choice_type": "price_category",
        "query_basis": {
            "normalized_filters": {
                "section_width": "195",
                "aspect_ratio": "60",
                "rim_size": "R15",
            }
        },
        "bucket_cards": cards,
    }
    rendered = render_turn_for_channel(
        {
            "runtime_final_response": "Pili po kayo ng price category.",
            "tool_results": [
                {
                    "name": "discover_brand_buckets",
                    "full_result": result,
                    "result": {"presentation_ref": result["presentation_ref"]},
                }
            ],
        },
        service_environment="staging",
    )

    gallery = next(message for message in rendered.content_messages if message["type"] == "cards")
    assert len(gallery["elements"]) == 4
    assert all("image_url" not in element for element in gallery["elements"])
    assert all(element["buttons"][0]["target"] == "content-staging-promo-router" for element in gallery["elements"])
    assert len(gallery["elements"][0]["subtitle"]) <= 80
    assert gallery["elements"][0]["subtitle"].endswith("BLACK ARROW")
    assert not gallery["elements"][0]["subtitle"].endswith(",")
    token = gallery["elements"][3]["buttons"][0]["actions"][0]["value"]
    assert parse_price_category_token(token)["category"] == "premium"
    assert rendered.choice_presentations[0]["tire_size"] == "195/60R15"
    fields = {action["field_name"]: action["value"] for action in rendered.contact_actions}
    assert fields["discovery_surface_type"] == "price_category_choices"
    assert fields["discovery_surface_ref"] == "price_categories_abc123"


def test_price_category_renderer_preserves_one_model_owned_matching_cta(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE",
        "content-staging-promo-router",
    )
    result = {
        "status": "ok",
        "presentation_ref": "price_categories_model_cta",
        "choice_type": "price_category",
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
                "position": 1,
            },
            {
                "choice_ref": "price_category:premium",
                "bucket": "premium",
                "label": "Premium",
                "brand_count": 2,
                "product_count": 4,
                "position": 2,
            },
        ],
    }
    model_cta = "Aling category po ang gusto niyong i-check?"
    rendered = render_turn_for_channel(
        {
            "assistant_text": json.dumps(
                {
                    "response_units": [
                        {
                            "type": "render_surface",
                            "content": {
                                "surface_ref": result[
                                    "presentation_ref"
                                ]
                            },
                        },
                        {
                            "type": "text",
                            "content": {"text": model_cta},
                        },
                    ]
                }
            ),
            "tool_results": [
                {
                    "name": "discover_brand_buckets",
                    "full_result": result,
                    "result": {
                        "presentation_ref": result["presentation_ref"]
                    },
                }
            ],
        },
        service_environment="staging",
    )

    texts = [
        str(message.get("text") or "")
        for message in rendered.content_messages
        if message.get("type") == "text"
    ]
    assert texts == [model_cta]


def test_renderer_does_not_claim_category_impression_without_router(monkeypatch) -> None:
    monkeypatch.delenv("PRICE_CATEGORY_LIVE_ROUTER_FLOW_NAMESPACE", raising=False)
    monkeypatch.delenv("PROMO_LIVE_ROUTER_FLOW_NAMESPACE", raising=False)
    result = {
        "status": "ok",
        "presentation_ref": "price_categories_abc123",
        "choice_type": "price_category",
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
                "brands": ["Atlas"],
                "brand_count": 1,
                "product_count": 2,
                "position": 1,
            }
        ],
    }

    rendered = render_turn_for_channel(
        {
            "runtime_final_response": "Pili po kayo ng price category.",
            "tool_results": [
                {
                    "name": "discover_brand_buckets",
                    "full_result": result,
                    "result": {"presentation_ref": result["presentation_ref"]},
                }
            ],
        },
        service_environment="shadow",
    )

    assert all(message["type"] != "cards" for message in rendered.content_messages)
    assert rendered.choice_presentations == []
    assert rendered.contact_actions == []


@pytest.mark.parametrize("delivery_status", ["success", "pending", "unknown"])
def test_price_category_click_is_validated_against_visible_or_ambiguous_session_surface(
    delivery_status: str,
) -> None:
    harness = RuntimeV7Harness(model_client=NoopModel(), tools=ProductToolHarness(runner=NoopRunner()))
    harness.choice_presentation_history = [
        {
            "presentation_ref": "price_categories_abc123",
            "delivery_status": delivery_status,
            "choices": [
                {
                    "choice_ref": "price_category:premium",
                    "category": "premium",
                    "position": 4,
                }
            ],
        }
    ]
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="I selected Premium.",
        message_id="choice-1",
        idempotency_key="choice-1",
        channel_event_id="choice-1",
        flow_context={
            "choice_action_context": {
                "presentation_ref": "price_categories_abc123",
                "category": "premium",
                "tire_size": "195/60R15",
            }
        },
    )

    _remember_choice_action_attempt(harness, request)

    runtime_context = request.flow_context["choice_action_runtime_context"]
    assert runtime_context["validation_status"] == "valid"
    assert runtime_context["position"] == 4
    assert harness.latest_choice_action["choice_ref"] == "price_category:premium"


def test_promo_click_token_round_trip_and_validation() -> None:
    token = build_promo_click_token(
        catalog_version_id="catalog-v1",
        promo_id="michelin-3plus1",
        card_id="michelin-card-1",
        action="choose_brand",
        selected_brand="Michelin",
    )

    assert parse_promo_click_token(token) == {
        "catalog_version_id": "catalog-v1",
        "promo_id": "michelin-3plus1",
        "card_id": "michelin-card-1",
        "action": "choose_brand",
        "selected_brand": "Michelin",
    }
    assert parse_promo_click_token("michelin-3plus1") == {}
    with pytest.raises(ValueError, match="Malformed"):
        parse_promo_click_token("pc1|bad")


def test_promo_action_reply_mirrors_normalized_manychat_fields() -> None:
    rendered = render_turn_for_channel(
        {"runtime_final_response": "Promo mechanics", "tool_results": []},
        profile_fields={
            "_promo_action_mirror": {
                "promo_id": "michelin-3plus1",
                "card_id": "michelin-card-1",
                "action": "promo_details",
                "selected_brand": "",
                "click_timestamp": "2026-07-20T10:00:00+08:00",
            }
        },
    )

    fields = {action["field_name"]: action["value"] for action in rendered.contact_actions}
    assert len(rendered.contact_actions) == 5
    assert fields == {
        "promo_selected_id": "michelin-3plus1",
        "promo_selected_card_id": "michelin-card-1",
        "promo_selected_action": "promo_details",
        "promo_source": "manychat_router_flow",
        "chatbot_state": "promo_action",
    }

    branded = render_turn_for_channel(
        {"runtime_final_response": "Brand selection", "tool_results": []},
        profile_fields={
            "_promo_action_mirror": {
                "promo_id": "michelin-3plus1",
                "card_id": "michelin-card-1",
                "action": "choose_brand",
                "selected_brand": "Michelin",
                "click_timestamp": "2026-07-20T10:00:00+08:00",
            }
        },
    )
    branded_fields = {action["field_name"]: action["value"] for action in branded.contact_actions}
    assert len(branded.contact_actions) == 5
    assert branded_fields["promo_selected_brand"] == "Michelin"
    assert branded_fields["promo_source"] == "manychat_router_flow"
    assert "chatbot_state" not in branded_fields


def test_promo_gallery_show_count_uses_successful_session_ledger() -> None:
    harness = RuntimeV7Harness(model_client=NoopModel(), tools=ProductToolHarness(runner=NoopRunner()))
    harness.promo_presentation_history = [
        {"catalog_version_id": "catalog-v1", "delivery_status": "success", "show_count": 4},
        {"catalog_version_id": "catalog-v1", "delivery_status": "failed", "show_count": 5},
        {"catalog_version_id": "catalog-v0", "delivery_status": "success", "show_count": 9},
    ]

    assert harness._next_promo_gallery_show_count("catalog-v1") == 5
    assert harness._next_promo_gallery_show_count("catalog-v2") == 1


class AtomicDeliveryClient:
    def __init__(self) -> None:
        self.calls = []

    async def send_content(self, messages, channel_subtype=None, actions=None):
        self.calls.append({"messages": messages, "channel_subtype": channel_subtype, "actions": actions})
        return {"status": "success"}


class _TimeoutAsyncClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def post(self, **kwargs):
        raise httpx.ReadTimeout("ManyChat did not answer after accepting the request")


def test_manychat_read_timeout_is_an_unknown_delivery_not_a_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "channels.manychat.api_client.httpx.AsyncClient",
        lambda **kwargs: _TimeoutAsyncClient(),
    )
    client = ManyChatAPI(api_key="test-key", psid="trial")

    result = asyncio.run(client.send_content([{"type": "text", "text": "hello"}]))

    assert result["status"] == "unknown"
    assert result["reason"] == "manychat_delivery_ambiguous"


class _GatewayResponse:
    status_code = 504
    text = "Gateway Time-out"


class _GatewayAsyncClient(_TimeoutAsyncClient):
    async def post(self, **kwargs):
        return _GatewayResponse()


def test_manychat_gateway_timeout_is_an_unknown_delivery(monkeypatch) -> None:
    monkeypatch.setattr(
        "channels.manychat.api_client.httpx.AsyncClient",
        lambda **kwargs: _GatewayAsyncClient(),
    )
    client = ManyChatAPI(api_key="test-key", psid="trial")

    result = asyncio.run(client.send_content([{"type": "text", "text": "hello"}]))

    assert result["status"] == "unknown"
    assert result["status_code"] == 504


def test_manychat_api_places_cards_and_contact_actions_in_one_v2_payload() -> None:
    captured = {}
    client = ManyChatAPI(api_key="test-key", psid="4843256405786522")

    async def fake_post(endpoint, payload):
        captured["endpoint"] = endpoint
        captured["payload"] = payload
        return {"status": "success"}

    client._post_json = fake_post
    asyncio.run(
        client.send_content(
            [{"type": "cards", "elements": [], "image_aspect_ratio": "square"}],
            actions=[{"action": "set_field_value", "field_name": "promo_gallery_shown", "value": True}],
        )
    )

    assert captured["endpoint"] == "sending/sendContent"
    assert captured["payload"]["data"] == {
        "version": "v2",
        "content": {
            "messages": [{"type": "cards", "elements": [], "image_aspect_ratio": "square"}],
            "actions": [
                {"action": "set_field_value", "field_name": "promo_gallery_shown", "value": True}
            ],
        },
    }


def test_gallery_and_actions_are_one_atomic_send_content_batch() -> None:
    asyncio.run(_assert_gallery_and_actions_are_one_atomic_send_content_batch())


async def _assert_gallery_and_actions_are_one_atomic_send_content_batch() -> None:
    client = AtomicDeliveryClient()
    service = RuntimeV7APIService(
        sessions_gateway=object(),
        delivery_client_factory=lambda _request: client,
    )
    rendered = render_turn_for_channel(
        {
            "runtime_final_response": "Current promos po.",
            "tool_results": [
                {
                    "name": "present_promo_gallery",
                    "full_result": {
                        "status": "ok",
                        "catalog_version_id": "catalog-v1",
                        "presentation_ref": "promo-gallery-1",
                        "promo_refs": ["promo:michelin-japan"],
                        "promo_ids": ["michelin-japan"],
                        "card_refs": ["michelin-japan-card-1"],
                        "trigger_mode": "general",
                        "selection_fingerprint": "abc",
                        "card_runtime_insert": True,
                        "cards": FakePromoRepository().cards[0]["display_cards"],
                    },
                }
            ],
        },
        service_environment="staging",
    )

    result = await service._deliver(
        RuntimeV7APIRequest(user_id="4843256405786522", user_text="promos"),
        rendered,
        delivery_mode="send_content",
    )

    assert result["status"] == "success"
    assert len(client.calls) == 1
    assert client.calls[0]["actions"] == rendered.contact_actions
    assert any(message["type"] == "cards" for message in client.calls[0]["messages"])


class NoopModel:
    def complete(self, **kwargs):
        return {"content": "ok", "tool_calls": []}


class StaticBackgroundSignalModel:
    def __init__(self, candidate: dict) -> None:
        self.candidate = deepcopy(candidate)

    def extract_background_signals(
        self,
        *,
        system_prompt,
        user_prompt,
        metadata=None,
    ):
        del system_prompt, user_prompt, metadata
        return {
            "content": json.dumps(
                {"candidates": [self.candidate]},
                ensure_ascii=False,
            ),
            "usage": {},
            "cache_usage": {},
            "latency_ms": 1,
        }


class NoopRunner:
    def search(self, request):
        return {"status": "no_match", "products": []}


def test_promo_presentation_state_round_trips_through_session_gateway_payload() -> None:
    harness = RuntimeV7Harness(model_client=NoopModel(), tools=ProductToolHarness(runner=NoopRunner()))
    harness.latest_promo_presentation = {
        "catalog_version_id": "catalog-v1",
        "promo_refs": ["promo:michelin-japan"],
        "delivery_status": "success",
    }
    harness.promo_presentation_history = [deepcopy(harness.latest_promo_presentation)]
    harness.latest_promo_action = {
        "catalog_version_id": "catalog-v1",
        "promo_id": "michelin-japan",
        "card_id": "michelin-japan-card-1",
        "action": "promo_details",
        "delivery_status": "success",
    }
    harness.promo_action_history = [deepcopy(harness.latest_promo_action)]

    state = _export_harness_state(harness)
    restored = RuntimeV7Harness(model_client=NoopModel(), tools=ProductToolHarness(runner=NoopRunner()))
    _hydrate_harness(restored, state)

    assert restored.latest_promo_presentation == harness.latest_promo_presentation
    assert restored.promo_presentation_history == harness.promo_presentation_history
    assert restored.latest_promo_action == harness.latest_promo_action
    assert restored.promo_action_history == harness.promo_action_history


def test_promo_action_requires_exact_stored_action_brand_pair() -> None:
    repository = FakePromoRepository()
    repository.cards[0]["display_cards"][0]["buttons"] = [
        _button("About Brand", "about_brand", "Michelin"),
        _button("Promo Details", "promo_details", ""),
    ]
    service = PromoCatalogService(repository)
    base = {
        "catalog_version_id": "catalog-v1",
        "promo_id": "michelin-japan",
        "card_id": "michelin-japan-card-1",
    }

    assert service.validate_action({**base, "action": "about_brand", "selected_brand": ""})["reason"] == (
        "action_brand_pair_not_allowed_for_card"
    )
    assert service.validate_action({**base, "action": "promo_details", "selected_brand": "Michelin"})["reason"] == (
        "action_brand_pair_not_allowed_for_card"
    )
    assert service.validate_action({**base, "action": "about_brand", "selected_brand": "Michelin"})["status"] == (
        "valid"
    )


def test_promo_brand_click_reuses_trusted_size_and_advances_to_product_search() -> None:
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="I selected Yokohama from the promo gallery.",
        profile_fields={"tire_brand": "Michelin"},
        flow_context={
            "trigger": "promo_action",
            "promo_action_context": {
                "status": "valid",
                "action": "choose_brand",
                "selected_brand": "Yokohama",
                "promo": {"title": "Michelin and Yokohama PHP 1,000 Off Promo"},
            },
        },
    )
    state = {
        "latest_selected_product_context": {
            "product_summary": {
                "brand": "MICHELIN",
                "tire_size": "175/65/R14",
                "sku_model": "MICHELIN 175/65/R14 ENERGY XM2+ 82H",
            }
        }
    }

    _apply_promo_action_runtime_context(request, state)
    seeds = _response_seed_overrides_for_flow(request.flow_context)

    assert request.profile_fields["tire_brand"] == "Yokohama"
    assert request.profile_fields["tire_size"] == "175/65R14"
    assert "already confirmed as 175/65R14" in request.user_text
    assert request.flow_context["promo_action_runtime_context"] == {
        "action": "choose_brand",
        "selected_brand": "Yokohama",
        "trusted_tire_size": "175/65R14",
        "tire_size_source": "latest_selected_product_context",
        "interaction_mode": "selection",
        "selection_effect": "query_preference",
        "qualification_effect": "advance_after_grounded_results",
    }
    guidance = seeds[0]["guidance"]
    assert "Call product_search now" in guidance
    assert "Do not ask the customer to repeat either value" in guidance
    assert "prefer location, then contact number" in guidance


def test_promo_brand_click_without_trusted_size_asks_only_for_size() -> None:
    original_text = "I selected Michelin from the promo gallery and want to check the tire price."
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text=original_text,
        flow_context={
            "promo_action_context": {
                "status": "valid",
                "action": "check_price",
                "selected_brand": "Michelin",
                "promo": {"title": "Michelin 3+1 Promo"},
            }
        },
    )

    _apply_promo_action_runtime_context(request, {})
    seeds = _response_seed_overrides_for_flow(request.flow_context)

    assert request.profile_fields == {"tire_brand": "Michelin"}
    assert request.user_text == original_text
    guidance = seeds[0]["guidance"]
    assert "ask only for the exact tire size" in guidance
    assert "Do not repeat the promo summary or ask for the brand again" in guidance


def test_generic_choose_brand_is_navigation_and_defers_size_need_to_model_state() -> None:
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text=(
            "I clicked Choose Brand from the promo gallery. I have not "
            "selected a brand or product yet."
        ),
        flow_context={
            "promo_action_context": {
                "status": "valid",
                "action": "choose_brand",
                "selected_brand": "",
                "promo": {"title": "THE GULONG DOUBLE WARRANTY"},
            }
        },
    )

    state = {
        "background_signal_ledger": [
            {
                "key": "tire_size",
                "value": "235/60R18",
                "status": "remembered_signal",
                "source": "signal_ledger",
            }
        ],
        "active_working_memory": {
            "text": "Typed customer context: tire size 235/60R18."
        },
    }

    _apply_promo_action_runtime_context(request, state)
    seed = _response_seed_overrides_for_flow(request.flow_context)[0]

    assert request.profile_fields == {}
    assert request.flow_context["promo_action_runtime_context"] == {
        "action": "choose_brand",
        "selected_brand": "",
        "trusted_tire_size": "",
        "tire_size_source": "",
        "interaction_mode": "navigation",
        "selection_effect": "none",
        "qualification_effect": "model_resolve_from_current_state",
    }
    assert "no brand or product has been selected" in seed["guidance"]
    assert "Ask only for the exact tire size if it is still missing" in seed["guidance"]
    assert "If the exact size is already known" in seed["guidance"]
    assert "Do not treat the promo title as a product model" in seed["guidance"]


@pytest.mark.parametrize("action", ["promo_details", "about_brand"])
def test_informational_promo_click_does_not_advance_qualification(action: str) -> None:
    flow_context = {
        "promo_action_context": {
            "status": "valid",
            "action": action,
            "selected_brand": "Michelin",
            "promo": {"title": "Michelin 3+1 Promo"},
            "catalog_version_id": "catalog-v1",
            "brand_profile": {
                "brand": "Michelin",
                "summary": "Premium tire brand.",
                "evidence_refs": ["gs://brands/michelin.txt"],
            },
        },
        "promo_action_runtime_context": {
            "action": action,
            "selected_brand": "Michelin",
            "trusted_tire_size": "175/65R14",
        },
    }

    seed = _response_seed_overrides_for_flow(flow_context)[0]
    guidance = seed["guidance"]

    assert "not a brand, product, quantity, fulfillment, or purchase selection" in guidance
    assert "Do not advance qualification" in guidance
    assert "ask for location" in guidance
    assert "product_search now" not in guidance
    assert seed["evidence"] == flow_context["promo_action_context"]
    if action == "about_brand":
        assert "Premium tire brand." not in guidance
        assert "Michelin 3+1 Promo" not in guidance
        assert "Do not mention or restate any current offer" in guidance
        assert "promo_catalog_offer_summary_only" in guidance
        assert '"reviewed_background_available": false' in guidance


@pytest.mark.parametrize("action", ["promo_details", "about_brand"])
def test_informational_promo_click_does_not_write_brand_or_size_preference(
    action: str,
) -> None:
    request = RuntimeV7APIRequest(
        user_id="trial",
        user_text="Informational promo click",
        flow_context={
            "promo_action_context": {
                "status": "valid",
                "action": action,
                "selected_brand": "Michelin",
                "promo": {"title": "Michelin 3+1 Promo"},
            }
        },
    )
    state = {
        "latest_selected_product_context": {
            "product_summary": {
                "brand": "APOLLO",
                "tire_size": "175/65/R14",
            }
        }
    }

    _apply_promo_action_runtime_context(request, state)

    assert request.profile_fields == {}
    assert request.flow_context["promo_action_runtime_context"] == {
        "action": action,
        "selected_brand": "Michelin",
        "trusted_tire_size": "",
        "tire_size_source": "",
        "interaction_mode": "informational",
        "selection_effect": "none",
        "qualification_effect": "none",
    }
