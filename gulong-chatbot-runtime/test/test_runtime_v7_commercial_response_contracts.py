"""Focused commercial-response contracts for the Runtime V7 candidate.

These tests intentionally exercise authority and rendering boundaries instead of
asserting one model wording, brand, or SKU.  They are cheap deterministic checks
to run before the more expensive adaptive conversation replays.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime_v7.api_runtime import (
    _apply_promo_provider_truth_guard,
    _apply_single_product_location_progression_guard,
)
from runtime_v7.channel_renderer import render_turn_for_channel
from runtime_v7.faq_tools import (
    answer_order_faq,
    order_faq_entries,
    resolve_faq_id_for_payload,
)
from runtime_v7.model_contract import CORE_SYSTEM_PROMPT, ORDER_POLICY_PROMPT, ORDER_TOOL_SCHEMAS
from runtime_v7.payment_provider_display import payment_provider_names_from_row
from runtime_v7.product_search import (
    ProductSearchRequest,
    _checkout_installments_for_brand,
    render_product_cards,
)
from runtime_v7.runtime_harness import (
    FINAL_COMPOSER_SYSTEM_PROMPT,
    _compact_payment_policy_for_composer,
    _hydrate_service_tool_args,
    _tool_execution_cache_key,
)


class CheckoutMetadataFixture:
    """Small source-shaped checkout fixture; no network calls are made."""

    def __init__(self, *, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = rows or [
            {
                "id": 301,
                "name": "BPI 6-month 0% installment",
                "description": "Pay using your BPI credit card",
                "main_payment_type_id": 2,
                "is_installment": True,
                "available_brands": "YOKOHAMA, MICHELIN",
            },
            {
                "id": 302,
                "name": "BPI 6-month 0% installment",
                "description": "Pay using your BPI credit card",
                "main_payment_type_id": 2,
                "is_installment": True,
                "available_brands": "YOKOHAMA, MICHELIN",
            },
            {
                "id": 303,
                "name": "BDO 3-month 0% installment",
                "description": "Pay using your BDO credit card",
                "main_payment_type_id": 2,
                "is_installment": True,
                "available_brands": "",
            },
            {
                "id": 304,
                "name": "Metrobank 12-month 1.5% installment",
                "description": "Pay using your Metrobank credit card",
                "main_payment_type_id": 2,
                "is_installment": True,
                "available_brands": "MICHELIN",
            },
            {
                "id": 305,
                "name": "GCash",
                "value": "GCASH",
                "main_payment_type_id": 2,
            },
        ]

    def checkout_metadata(self) -> dict[str, Any]:
        return {
            "source": "test_checkout_metadata",
            "transaction_types": [
                {"id": 10, "trans_type": "Install"},
                {"id": 11, "trans_type": "Delivery"},
            ],
            "payment_options": [
                {
                    "id": 1,
                    "name": "Pay Later",
                    "description": "Pay a reservation fee to secure your slot.",
                },
                {"id": 2, "name": "Pay Now"},
            ],
            "payment_types": list(self._rows),
        }


def _installment_payload(*, brand: str = "Yokohama") -> dict[str, Any]:
    return {
        "faq_id": "order_do_you_offer_installment_payments",
        "question": f"May installment po ba sa {brand}?",
        "requested_payment_method": "installment",
        "requested_product_brand": brand,
    }


def _payment_policy_text(result: dict[str, Any]) -> str:
    policy = result.get("payment_policy") or {}
    return json.dumps(policy, ensure_ascii=False, sort_keys=True).casefold()


def test_accepted_composer_cannot_turn_partial_product_match_into_broad_buy3get1_negative() -> None:
    turn = {
        "final_composer": {"status": "used"},
        "runtime_final_response": "Walang Buy 3 Get 1 promo ang Toyo tires.",
        "tool_results": [
            {
                "name": "search_promo_catalog",
                "args": {"promo_types": ["buy3get1"]},
                "full_result": {
                    "status": "ok",
                    "requested_brands": ["Toyo"],
                    "unmatched_requested_brands": ["Toyo"],
                    "exact_requested_brand_match": False,
                },
            },
            {
                "name": "product_search",
                "full_result": {
                    "status": "partial_match",
                    "result_level": "near_exact",
                    "product_cards": [{"brand": "TOYO"}],
                },
            },
        ],
    }

    _apply_promo_provider_truth_guard(turn)

    assert "current reviewed promos" in turn["runtime_final_response"].casefold()
    assert "wala pang confirmed" in turn["runtime_final_response"].casefold()
    assert "walang buy 3 get 1 promo ang toyo tires" not in turn["runtime_final_response"].casefold()
    assert turn["suppressed_channel_surface_tools"] == ["product_search"]
    assert turn["promo_provider_truth_guard"] == {
        "status": "rewritten",
        "reason": "unmatched_promo_brand_requires_exact_product_match",
        "unmatched_requested_brands": ["Toyo"],
        "partial_product_surface_suppressed": True,
    }


def test_partial_product_miss_preserves_provider_authorized_promo_alternative_surface() -> None:
    alternative_ref = "promo:catalog-v1:current-alternative"
    turn = {
        "final_composer": {"status": "used"},
        "runtime_final_response": "I-check ko pa po ang size.",
        "tool_results": [
            {
                "name": "search_promo_catalog",
                "args": {
                    "promo_types": ["buy3get1"],
                    "alternative_scope": "any_current",
                },
                "full_result": {
                    "status": "ok",
                    "tire_size": "175/65R14",
                    "requested_brands": ["Toyo"],
                    "unmatched_requested_brands": ["Toyo"],
                    "exact_requested_brand_match": False,
                    "allowed_promo_refs": [alternative_ref],
                    "alternative_promo_refs": [alternative_ref],
                    "candidates": [
                        {
                            "query_constraint_match": False,
                            "alternative_constraint_match": True,
                            "promo_ref": alternative_ref,
                            "brands": ["Apollo"],
                        }
                    ],
                },
            },
            {
                "name": "present_promo_gallery",
                "full_result": {
                    "status": "ok",
                    "promo_refs": [alternative_ref],
                    "presentation_ref": "pres_promo_current_alternative",
                    "cards": [{"card_id": "current-alternative-card"}],
                },
            },
            {
                "name": "product_search",
                "full_result": {
                    "status": "partial_match",
                    "result_level": "near_exact",
                    "product_cards": [{"brand": "Apollo"}],
                },
            },
        ],
    }

    _apply_promo_provider_truth_guard(turn)

    response = turn["runtime_final_response"].casefold()
    assert "toyo 175/65r14" in response
    assert "current verified promo alternatives" in response
    assert "exact tire size" not in response
    assert turn["promo_provider_truth_guard"]["status"] == "rewritten"
    assert "pres_promo_current_alternative" in turn["runtime_final_response"]


def test_campaign_miss_acknowledges_already_rendered_promo_alternative_surface() -> None:
    alternative_ref = "promo:catalog-v1:current-alternative"
    turn = {
        "final_composer": {"status": "used"},
        "runtime_final_response": "Puwede ko pong i-check ang ibang promo.",
        "tool_results": [
            {
                "name": "search_promo_catalog",
                "args": {
                    "promo_types": ["buy3get1"],
                    "alternative_scope": "any_current",
                },
                "full_result": {
                    "status": "ok",
                    "tire_size": "175/65R14",
                    "requested_brands": ["Toyo"],
                    "unmatched_requested_brands": ["Toyo"],
                    "exact_requested_brand_match": False,
                    "allowed_promo_refs": [alternative_ref],
                    "alternative_promo_refs": [alternative_ref],
                    "candidates": [
                        {
                            "query_constraint_match": False,
                            "alternative_constraint_match": True,
                            "promo_ref": alternative_ref,
                            "brands": [],
                        }
                    ],
                },
            },
            {
                "name": "present_promo_gallery",
                "full_result": {
                    "status": "ok",
                    "promo_refs": [alternative_ref],
                    "presentation_ref": "pres_promo_current_alternative",
                    "cards": [{"card_id": "current-alternative-card"}],
                },
            },
        ],
    }

    _apply_promo_provider_truth_guard(turn)

    response = turn["runtime_final_response"].casefold()
    assert "narito ang current verified promo alternatives" in response
    assert "puwede ko pong i-check" not in response
    assert "pres_promo_current_alternative" in turn["runtime_final_response"]


def test_unrenderable_promo_alternative_does_not_claim_or_preserve_gallery() -> None:
    alternative_ref = "promo:catalog-v1:no-visual"
    turn = {
        "final_composer": {"status": "used"},
        "runtime_final_response": "I-check ko pa po ang size.",
        "tool_results": [
            {
                "name": "search_promo_catalog",
                "full_result": {
                    "status": "ok",
                    "tire_size": "175/65R14",
                    "requested_brands": ["Toyo"],
                    "unmatched_requested_brands": ["Toyo"],
                    "exact_requested_brand_match": False,
                    "allowed_promo_refs": [alternative_ref],
                    "alternative_promo_refs": [alternative_ref],
                    "candidates": [
                        {
                            "query_constraint_match": False,
                            "alternative_constraint_match": True,
                            "promo_ref": alternative_ref,
                            "brands": ["Apollo"],
                        }
                    ],
                },
            },
            {
                "name": "present_promo_gallery",
                "full_result": {
                    "status": "ok",
                    "promo_refs": [alternative_ref],
                    "presentation_ref": "pres_promo_no_visual",
                    "cards": [],
                },
            },
            {
                "name": "product_search",
                "full_result": {
                    "status": "partial_match",
                    "result_level": "near_exact",
                    "product_cards": [{"brand": "Apollo"}],
                },
            },
        ],
    }

    _apply_promo_provider_truth_guard(turn)

    response = turn["runtime_final_response"].casefold()
    assert "narito" not in response
    assert "wala ring verified applicable promo alternative" in response
    assert "pres_promo_no_visual" not in turn["runtime_final_response"]


def test_accepted_composer_cannot_turn_campaign_no_match_into_broad_brand_negative() -> None:
    turn = {
        "final_composer": {"status": "used"},
        "runtime_final_response": "Walang Buy 3 Get 1 promo ang Toyo tires.",
        "tool_results": [
            {
                "name": "search_promo_catalog",
                "args": {"promo_types": ["buy3get1"]},
                "full_result": {
                    "status": "ok",
                    "requested_brands": ["Toyo"],
                    "unmatched_requested_brands": ["Toyo"],
                    "exact_requested_brand_match": False,
                    "allowed_promo_refs": ["promo_apollo_buy3get1"],
                    "candidates": [
                        {
                            "query_constraint_match": True,
                            "promo_ref": "promo_apollo_buy3get1",
                            "brands": ["Apollo"],
                        }
                    ],
                },
            }
        ],
    }

    _apply_promo_provider_truth_guard(turn)

    response = turn["runtime_final_response"].casefold()
    assert "sa current reviewed promos" in response
    assert "wala pong promo na tugma para sa toyo" in response
    assert "active promo options po para sa apollo" in response
    assert turn["promo_provider_truth_guard"]["status"] == "rewritten"
    assert turn["promo_provider_truth_guard"]["reason"] == (
        "unmatched_requested_promo_brand_requires_scoped_answer"
    )


def test_accepted_composer_keeps_already_scoped_campaign_no_match() -> None:
    original = (
        "Sa current reviewed promos namin, wala pong promo na tugma para sa Toyo."
    )
    turn = {
        "final_composer": {"status": "used"},
        "runtime_final_response": original,
        "tool_results": [
            {
                "name": "search_promo_catalog",
                "args": {"promo_types": ["buy3get1"]},
                "full_result": {
                    "status": "ok",
                    "requested_brands": ["Toyo"],
                    "unmatched_requested_brands": ["Toyo"],
                    "exact_requested_brand_match": False,
                },
            }
        ],
    }

    _apply_promo_provider_truth_guard(turn)

    assert turn["runtime_final_response"] == original
    assert turn["promo_provider_truth_guard"]["status"] == "validated"
    assert turn["promo_provider_truth_guard"]["reason"] == (
        "unmatched_requested_promo_brand_scoped_answer"
    )


def test_accepted_composer_keeps_exact_product_buy3get1_evidence() -> None:
    original = "Yes po, may current Buy 3 Get 1 ang Vredestein for this exact tire."
    turn = {
        "final_composer": {"status": "used"},
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
                    "result_level": "exact",
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


def test_specific_promo_miss_keeps_exact_size_brand_partial_product_surface() -> None:
    """A generic brand sale must not prove the requested promo mechanic."""

    original = json.dumps(
        {
            "response_units": [
                {
                    "type": "text",
                    "content": {
                        "text": (
                            "Walang option na tugma sa requested promo at "
                            "requested brand (TOYO)."
                        )
                    },
                },
                {
                    "type": "render_surface",
                    "content": {"surface_ref": "pres_products"},
                },
            ]
        }
    )
    turn = {
        "final_composer": {"status": "used"},
        "runtime_final_response": original,
        "tool_results": [
            {
                "name": "search_promo_catalog",
                "args": {"promo_types": ["buy3get1"]},
                "full_result": {
                    "status": "ok",
                    "requested_brands": ["Toyo"],
                    "unmatched_requested_brands": ["Toyo"],
                    "exact_requested_brand_match": False,
                },
            },
            {
                "name": "product_search",
                "full_result": {
                    "status": "partial_match",
                    "result_level": "near_exact",
                    "presentation_ref": "pres_products",
                    "query_basis": {"exact_base_query_verified": True},
                    "promo_evidence": {"verified_brands": ["TOYO"]},
                    "product_cards": [
                        {
                            "brand": "TOYO",
                            "tire_size": "175/65R14",
                            "promo_savings_line": "Current sale discount",
                            "missing_requested_filters": ["promo_only"],
                        },
                        {
                            "brand": "APOLLO",
                            "tire_size": "175/65R14",
                            "promo_savings_line": "Buy 3 Get 1 FREE",
                            "missing_requested_filters": ["brand"],
                        },
                    ],
                },
            },
        ],
    }

    _apply_promo_provider_truth_guard(turn)

    assert turn["runtime_final_response"] == original
    assert "suppressed_channel_surface_tools" not in turn
    assert turn["promo_provider_truth_guard"] == {
        "status": "validated",
        "reason": "unmatched_promo_brand_scoped_by_product_disclosure",
        "unmatched_requested_brands": ["Toyo"],
        "requested_promo_types": ["buy3get1"],
        "partial_product_surface_suppressed": False,
    }


def test_specific_promo_miss_reads_mechanic_from_product_search() -> None:
    """Cross-tool hydration must preserve an explicit customer mechanic."""

    original = json.dumps(
        {
            "response_units": [
                {
                    "type": "text",
                    "content": {
                        "text": (
                            "Exact size ito, pero hindi tugma ang TOYO option "
                            "sa requested Buy 3 Get 1 promo."
                        )
                    },
                }
            ]
        }
    )
    turn = {
        "final_composer": {"status": "used"},
        "runtime_final_response": original,
        "tool_results": [
            {
                "name": "product_search",
                "args": {"promo_types": ["buy3get1"]},
                "full_result": {
                    "status": "partial_match",
                    "result_level": "near_exact",
                    "query_basis": {"exact_base_query_verified": True},
                    "promo_evidence": {"verified_brands": ["TOYO"]},
                    "product_cards": [
                        {
                            "brand": "TOYO",
                            "promo_savings_line": "Current sale discount",
                            "missing_requested_filters": ["promo_only"],
                        }
                    ],
                },
            },
            {
                "name": "search_promo_catalog",
                "args": {"brands": ["TOYO"]},
                "full_result": {
                    "status": "ok",
                    "requested_brands": ["TOYO"],
                    "unmatched_requested_brands": ["TOYO"],
                    "exact_requested_brand_match": False,
                },
            },
        ],
    }

    _apply_promo_provider_truth_guard(turn)

    assert turn["runtime_final_response"] == original
    assert turn["promo_provider_truth_guard"] == {
        "status": "validated",
        "reason": "unmatched_promo_brand_scoped_by_product_disclosure",
        "unmatched_requested_brands": ["TOYO"],
        "requested_promo_types": ["buy3get1"],
        "partial_product_surface_suppressed": False,
    }


def _single_product_progression_turn() -> dict[str, Any]:
    response = json.dumps(
        {
            "response_units": [
                {
                    "type": "text",
                    "content": {"text": "May exact option po tayo."},
                },
                {
                    "type": "render_surface",
                    "content": {"surface_ref": "pres_exact_product"},
                },
                {
                    "type": "render_surface",
                    "content": {"surface_ref": "pres_supporting_promo"},
                },
                {
                    "type": "text",
                    "content": {
                        "text": "Gusto niyo bang i-check ang installation options?"
                    },
                },
            ]
        }
    )
    return {
        "assistant_text": response,
        "draft_assistant_text": response,
        "runtime_final_response": response,
        "background_signals_before_turn": [
            {
                "key": "tire_size",
                "value": "185/55R15",
                "source": "latest_user_message",
                "relation": "asserted",
            },
            {
                "key": "required_brands",
                "value": "WESTLAKE",
                "source": "latest_user_message",
                "relation": "asserted",
            },
        ],
        "tool_results": [
            {
                "name": "product_search",
                "full_result": {
                    "status": "ok",
                    "result_level": "exact",
                    "presentation_ref": "pres_exact_product",
                    "query_basis": {"exact_base_query_verified": True},
                    "product_cards": [
                        {
                            "brand": "WESTLAKE",
                            "tire_size": "185/55R15",
                        }
                    ],
                },
            },
            {
                "name": "present_promo_gallery",
                "full_result": {
                    "status": "ok",
                    "presentation_ref": "pres_supporting_promo",
                },
            },
        ],
    }


def test_single_exact_size_brand_result_asks_directly_for_area() -> None:
    turn = _single_product_progression_turn()

    _apply_single_product_location_progression_guard(turn)

    payload = json.loads(turn["runtime_final_response"])
    assert [unit["type"] for unit in payload["response_units"]] == [
        "text",
        "render_surface",
        "render_surface",
        "text",
    ]
    assert payload["response_units"][-1]["content"]["text"] == (
        "Para ma-check ang installation o delivery options, "
        "saang city o area po kayo?"
    )
    assert "Gusto niyo" not in turn["runtime_final_response"]
    assert turn["location_progression_guard"]["status"] == "rewritten"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda turn: turn["tool_results"][0]["full_result"]["product_cards"].append(
            {"brand": "WESTLAKE", "tire_size": "185/55R15"}
        ),
        lambda turn: turn["background_signals_before_turn"].append(
            {
                "key": "location",
                "value": "Quezon City, Metro Manila",
                "source": "signal_ledger",
                "relation": "asserted",
            }
        ),
        lambda turn: turn["tool_results"].append(
            {"name": "answer_order_faq", "full_result": {"status": "ok"}}
        ),
        lambda turn: turn.update(
            {
                "choice_action_validation": {
                    "validation_status": "valid",
                    "choice_type": "product_selection",
                }
            }
        ),
    ],
)
def test_single_product_location_progression_guard_respects_negative_controls(
    mutation,
) -> None:
    turn = _single_product_progression_turn()
    original = turn["runtime_final_response"]
    mutation(turn)

    _apply_single_product_location_progression_guard(turn)

    assert turn["runtime_final_response"] == original
    assert "location_progression_guard" not in turn


def test_accepted_composer_keeps_promo_provider_unavailable_fail_safe() -> None:
    turn = {
        "final_composer": {"status": "used"},
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

    assert "hindi ko ma-verify" in turn["runtime_final_response"].casefold()
    assert turn["promo_provider_truth_guard"]["reason"] == (
        "promo_provider_unavailable_is_not_negative_evidence"
    )


def test_generic_installment_policy_preserves_all_current_terms_and_providers() -> None:
    """A broad installment question must not silently choose the first row."""

    result = answer_order_faq(
        _installment_payload(brand="Yokohama"),
        canonical_values_provider=CheckoutMetadataFixture(),
    )

    assert result["status"] == "ok"
    policy = result["payment_policy"]
    assert policy["requested_payment_status"] == "multiple_options"
    options = policy["applicable_installment_options"]

    # BPI is duplicated in the fixture and must appear once in the applicable
    # list; the unrestricted BDO term also applies.  Metrobank is scoped to a
    # different brand and must not leak into Yokohama's answer.
    assert len(options) == 2
    option_names = [str(option.get("name") or "").casefold() for option in options]
    option_providers = [str(option.get("providers") or "").casefold() for option in options]
    assert option_names.count("bpi 6-month 0% installment") == 1
    assert "bdo 3-month 0% installment" in option_names
    assert "bpi credit cards" in option_providers
    assert "bdo credit cards" in option_providers
    assert "metrobank 12-month 1.5% installment" not in option_names
    assert "applicable installment options" in result["answer"].casefold()
    assert "pay now" not in result["answer"].casefold()
    assert "pay later" not in result["answer"].casefold()

    compact = _compact_payment_policy_for_composer(policy)
    assert compact["applicable_installment_options"] == options


def test_installment_composer_guidance_keeps_terms_without_standalone_option_labels() -> None:
    prompt = " ".join(ORDER_POLICY_PROMPT.split())
    composer_prompt = " ".join(FINAL_COMPOSER_SYSTEM_PROMPT.split())

    assert "applicable_installment_options" in prompt
    assert "state every returned term" in prompt
    assert "Do not state Pay Now or Pay Later as a standalone sentence" in prompt
    assert "applicable_installment_options is present" in composer_prompt
    assert "state every listed term" in composer_prompt.casefold()
    assert "never emit pay now or pay later as a standalone label" in composer_prompt.casefold()


def test_specific_installment_bank_and_term_remain_a_narrow_lookup() -> None:
    """An explicit plan must not expand into every catalog installment row."""

    result = answer_order_faq(
        {
            "faq_id": "order_do_you_offer_installment_payments",
            "question": "Pwede BPI 6 months installment sa Michelin?",
            "requested_payment_method": "BPI 6 months installment",
            "requested_product_brand": "Michelin",
        },
        canonical_values_provider=CheckoutMetadataFixture(),
    )

    policy = result["payment_policy"]
    assert policy["requested_payment_status"] == "ready"
    assert "bpi" in str(policy["requested_payment_name"]).casefold()
    assert policy["applicable_installment_options"] == []
    assert "metrobank" not in result["answer"].casefold()
    assert "bdo" not in result["answer"].casefold()


def test_payment_lookup_hydration_rejects_cross_field_extractor_placeholders() -> None:
    signals = [
        {
            "key": "payment_method",
            "value": "installment",
            "source": "latest_user_message",
            "status": "confirmed_by_latest_user_message",
        },
        {
            "key": "bank",
            "value": "credit card installment",
            "source": "latest_user_message",
            "status": "mentioned_unconfirmed",
        },
        {
            "key": "installment_months",
            "value": "credit card installment",
            "source": "latest_user_message",
            "status": "mentioned_unconfirmed",
        },
    ]

    hydrated = _hydrate_service_tool_args(
        "answer_order_faq",
        {"question": "Anong installment terms at banks ang puwede?"},
        signals,
    )

    assert hydrated["requested_payment_method"] == "installment"


def test_payment_lookup_hydration_keeps_explicit_bank_and_numeric_term() -> None:
    signals = [
        {
            "key": "payment_method",
            "value": "credit card installment",
            "source": "latest_user_message",
            "status": "confirmed_by_latest_user_message",
        },
        {
            "key": "bank",
            "value": "BPI",
            "source": "latest_user_message",
            "status": "confirmed_by_latest_user_message",
        },
        {
            "key": "installment_months",
            "value": "6 months",
            "source": "latest_user_message",
            "status": "confirmed_by_latest_user_message",
        },
    ]

    hydrated = _hydrate_service_tool_args(
        "answer_order_faq",
        {"question": "BPI six months puwede?"},
        signals,
    )

    assert hydrated["requested_payment_method"] == "BPI 6 months installment"


def test_generic_installment_without_brand_keeps_all_current_distinct_terms() -> None:
    result = answer_order_faq(
        {
            "faq_id": "order_do_you_offer_installment_payments",
            "question": "Ano-anong credit card installment ang meron?",
            "requested_payment_method": "credit card installment",
        },
        canonical_values_provider=CheckoutMetadataFixture(),
    )

    names = {
        str(option.get("name") or "").casefold()
        for option in result["payment_policy"]["applicable_installment_options"]
    }
    assert names == {
        "bpi 6-month 0% installment",
        "bdo 3-month 0% installment",
        "metrobank 12-month 1.5% installment",
    }


def test_downpayment_question_uses_reservation_fee_guidance_without_inventing_amount() -> None:
    result = answer_order_faq(
        {
            "faq_id": "order_why_do_i_need_to_pay_for_a_reservation_fee",
            "question": "Magkano po ang downpayment para sa tires?",
            "question_topics": ["reservation_fee"],
        },
        canonical_values_provider=CheckoutMetadataFixture(),
    )

    assert result["status"] == "ok"
    guidance = result["payment_policy"]["reservation_fee_guidance"]
    assert guidance["customer_term"] == "down payment"
    assert guidance["canonical_term"] == "reservation fee"
    assert guidance["purpose"]
    assert guidance["amount_available"] is False
    assert "php" not in json.dumps(guidance).casefold()
    assert "website" not in result["answer"].casefold()


def test_model_owned_reservation_scope_handles_compound_dp_question() -> None:
    result = answer_order_faq(
        {
            "faq_id": "order_do_you_offer_installment_payments",
            "question": "Paano umorder ng four tires installment? Magkano DP?",
            "requested_payment_method": "installment",
            "question_topics": ["installment_options", "reservation_fee"],
        },
        canonical_values_provider=CheckoutMetadataFixture(),
    )

    policy = result["payment_policy"]
    assert policy["applicable_installment_options"]
    assert policy["reservation_fee_guidance"]["canonical_term"] == "reservation fee"
    assert "applicable installment options" in result["answer"].casefold()
    assert "secure your slot" in result["answer"].casefold()
    bpi_option = next(
        option
        for option in policy["applicable_installment_options"]
        if str(option.get("name") or "").startswith("BPI")
    )
    assert bpi_option["eligible_brands"] == ["YOKOHAMA", "MICHELIN"]
    assert "do not quote, repeat, name, define, contrast" in result["composition_hint"].casefold()
    assert "do not describe a data/source gap" in result["composition_hint"].casefold()

    control = answer_order_faq(
        {
            "faq_id": "order_do_you_offer_installment_payments",
            "question": "May installment po ba?",
            "requested_payment_method": "installment",
            "question_topics": ["installment_options"],
        },
        canonical_values_provider=CheckoutMetadataFixture(),
    )
    assert control["payment_policy"]["reservation_fee_guidance"] == {}


def test_order_tool_exposes_typed_reservation_fee_semantic_scope() -> None:
    schema = next(
        item["function"]["parameters"]
        for item in ORDER_TOOL_SCHEMAS
        if item["function"]["name"] == "answer_order_faq"
    )
    topic_schema = schema["properties"]["question_topics"]
    assert "reservation_fee" in topic_schema["items"]["enum"]
    assert "model-owned semantic" in topic_schema["description"].casefold()


def test_order_faq_cache_separates_compound_reservation_scope() -> None:
    installment_only = _tool_execution_cache_key(
        "answer_order_faq",
        {
            "faq_id": "order_do_you_offer_installment_payments",
            "requested_payment_method": "installment",
            "question_topics": ["installment_options"],
        },
    )
    with_reservation = _tool_execution_cache_key(
        "answer_order_faq",
        {
            "faq_id": "order_do_you_offer_installment_payments",
            "requested_payment_method": "installment",
            "question_topics": ["reservation_fee", "installment_options"],
        },
    )
    reordered = _tool_execution_cache_key(
        "answer_order_faq",
        {
            "faq_id": "order_do_you_offer_installment_payments",
            "requested_payment_method": "installment",
            "question_topics": ["installment_options", "reservation_fee"],
        },
    )

    assert installment_only != with_reservation
    assert with_reservation == reordered


def test_checkout_provider_projection_is_shared_by_cards_and_payment_prose() -> None:
    row = {
        "id": 99,
        "name": "3-mos Installment (0% interest)",
        "description": "Pay using BDO, EWB, CBC, HSBC and BOC Credit Cards.",
        "icons": "https://example.test/metrobank.webp,https://example.test/bpi-4.webp",
        "is_installment": True,
        "main_payment_type_id": 2,
    }
    providers = payment_provider_names_from_row(row)
    card_rows = _checkout_installments_for_brand([row], "DEESTONE")
    card_providers = [item["bank_name"] for item in card_rows]

    assert providers == [
        "Metrobank",
        "BPI",
        "BDO",
        "EastWest",
        "China Bank",
        "HSBC",
        "Bank of Commerce",
    ]
    assert card_providers == providers

    result = answer_order_faq(
        {
            "faq_id": "order_do_you_offer_installment_payments",
            "question": "Anong banks ang puwede sa installment?",
            "requested_payment_method": "installment",
            "question_topics": ["installment_options"],
        },
        canonical_values_provider=CheckoutMetadataFixture(rows=[row]),
    )
    provider_text = result["payment_policy"]["applicable_installment_options"][0]["providers"]
    for provider in providers:
        assert provider in provider_text


def test_composer_silently_normalizes_clear_customer_terms_and_typos() -> None:
    core = " ".join(CORE_SYSTEM_PROMPT.split()).casefold()
    order = " ".join(ORDER_POLICY_PROMPT.split()).casefold()
    composer = " ".join(FINAL_COMPOSER_SYSTEM_PROMPT.split()).casefold()

    assert "silently use the correct term" in core
    assert "without quoting, echoing, or announcing" in core
    assert 'silently use "reservation fee"' in order
    assert "do not quote, echo, name, define, contrast, or explicitly correct" in composer
    assert "multiple plausible meanings" in composer
    assert "do not say the customer's term is \"called\" reservation fee" in composer
    assert 'such as "may reservation fee po para ma-secure ang slot."' in composer
    assert "do not expose a source/data gap" in composer
    assert "eligible_brands" in composer


def test_generic_how_to_order_does_not_use_obsolete_website_faq() -> None:
    entries = order_faq_entries()
    assert not any(entry.faq_id == "order_how_to_order" for entry in entries)

    payload = {"question": "How do I order tires online?"}
    assert resolve_faq_id_for_payload(payload, domain="order") != "order_how_to_order"
    result = answer_order_faq(payload)
    assert result.get("faq_id") != "order_how_to_order"
    assert "go to our website at gulong.ph" not in result.get("answer", "").casefold()

    # A website/checkout support question remains a distinct customer question;
    # it must not be silently rewritten as the removed generic order FAQ.
    website_support = answer_order_faq(
        {"question": "The gulong.ph checkout page is showing an error; can you help?"}
    )
    assert website_support.get("faq_id") != "order_how_to_order"


def _product_turn(
    *,
    include_warranty_surface: bool,
    warranty_surface_status: str = "ok",
    brand: str = "FIRESTONE",
    model: str = "FIRESTONE 225/65/R17 DESTINATION LE3",
) -> dict[str, Any]:
    units: list[dict[str, Any]] = [
        {"type": "render_surface", "content": {"surface_ref": "pres_products"}}
    ]
    tool_results: list[dict[str, Any]] = [
        {
            "name": "product_search",
            "round": 1,
            "result": {"status": "ok", "presentation_ref": "pres_products"},
            "full_result": {
                "status": "ok",
                "presentation_ref": "pres_products",
                "product_cards": [
                    {
                        "card_ref": "product_card_1",
                        "item_ref": "product_item_1",
                        "brand": brand,
                        "sku_model": model,
                        "card_text": (
                            f"[MID RANGE]\n{model}\n"
                            "PHP 4,510.00/tire | 2 tires: PHP 9,020.00"
                        ),
                        "warranty": "5 years",
                        "tire_protection_plan": "Tire Protection Plan (6 Months)",
                        "card_runtime_insert": True,
                    }
                ],
            },
        }
    ]
    if include_warranty_surface:
        if warranty_surface_status == "ok":
            units.append(
                {"type": "render_surface", "content": {"surface_ref": "pres_warranty"}}
            )
        title = "Reviewed Double Warranty Offer"
        tool_results.append(
            {
                "name": "present_promo_gallery",
                "round": 2,
                "result": {
                    "status": warranty_surface_status,
                    "presentation_ref": "pres_warranty",
                },
                "full_result": {
                    "status": warranty_surface_status,
                    "presentation_ref": "pres_warranty",
                    "promo_types": ["warranty"],
                    "promo_titles": [title],
                    "promo_refs": ["promo:reviewed-warranty"],
                    "promo_ids": ["reviewed-warranty"],
                    "card_refs": ["warranty_card_1"],
                    "cards": [
                        {
                            "card_id": "warranty_card_1",
                            "title": title,
                            "subtitle": "Manufacturer warranty plus Gulong tire protection warranty.",
                            "image_url": (
                                "https://storage.googleapis.com/gulong-chatbot-459723-"
                                "promo-media/catalog/catalog-v1/cards/reviewed-warranty.png"
                            ),
                            "buttons": [
                                {
                                    "caption": "Promo Details",
                                    "action": "promo_details",
                                    "targets": {"staging": "staging_router"},
                                    "actions": [
                                        {
                                            "action": "set_field_value",
                                            "field_name": "promo_catalog_version",
                                            "value": "catalog-v1",
                                        },
                                        {
                                            "action": "set_field_value",
                                            "field_name": "promo_selected_id",
                                            "value": "reviewed-warranty",
                                        },
                                        {
                                            "action": "set_field_value",
                                            "field_name": "promo_selected_card_id",
                                            "value": "warranty_card_1",
                                        },
                                    ],
                                }
                            ],
                        }
                    ],
                    "card_runtime_insert": True,
                },
            }
        )
        if warranty_surface_status != "ok":
            tool_results[-1]["full_result"] = {
                "status": warranty_surface_status,
                "reason": "reviewed warranty surface unavailable",
                "presentation_surfaces": [],
            }
    return {
        "assistant_text": json.dumps({"response_units": units}),
        "tool_results": tool_results,
    }


def test_unavailable_warranty_surface_retains_grounded_fallback() -> None:
    rendered = render_turn_for_channel(
        _product_turn(include_warranty_surface=True, warranty_surface_status="error")
    )
    texts = [
        message["text"]
        for message in rendered.content_messages
        if message.get("type") == "text"
    ]
    assert any("Warranty and inclusions:" in text for text in texts)
    assert any("unconditional warranty" in text for text in texts)
    assert not any("Reviewed Double Warranty Offer" in text for text in texts)


def test_renderable_warranty_surface_replaces_long_fallback() -> None:
    rendered = render_turn_for_channel(
        _product_turn(include_warranty_surface=True),
        service_environment="staging",
    )
    texts = [
        message["text"]
        for message in rendered.content_messages
        if message.get("type") == "text"
    ]
    assert not any("Warranty and inclusions:" in text for text in texts)
    assert any(
        "Reviewed Double Warranty Offer" in json.dumps(message, ensure_ascii=False)
        for message in rendered.content_messages
    )


@pytest.mark.parametrize("invalid_part", ["image", "target"])
def test_nonrenderable_warranty_card_does_not_suppress_grounded_fallback(
    invalid_part: str,
) -> None:
    turn = _product_turn(include_warranty_surface=True)
    card = turn["tool_results"][-1]["full_result"]["cards"][0]
    if invalid_part == "image":
        card["image_url"] = "https://example.com/untrusted.png"
    else:
        card["buttons"][0]["targets"] = {}

    rendered = render_turn_for_channel(turn, service_environment="staging")
    texts = [
        message["text"]
        for message in rendered.content_messages
        if message.get("type") == "text"
    ]

    assert any("Warranty and inclusions:" in text for text in texts)
    assert not any(
        "Reviewed Double Warranty Offer" in json.dumps(message, ensure_ascii=False)
        for message in rendered.content_messages
    )


@pytest.mark.parametrize(
    ("brand", "model", "quantity", "expected_total"),
    [
        ("KAPSEN", "KAPSEN 205/55/R16 H202", 2, "PHP 6,420.00 for 2 tires"),
        ("FIRESTONE", "FIRESTONE 225/65/R17 DESTINATION LE3", 3, "PHP 13,530.00 for 3 tires"),
        ("BRIDGESTONE", "BRIDGESTONE 215/60/R17 TURANZA T005", 1, ""),
    ],
)
def test_deterministic_product_card_preserves_customer_quantity(
    brand: str,
    model: str,
    quantity: int,
    expected_total: str,
) -> None:
    product = {
        "brand": brand,
        "model": model,
        "size": model.split(maxsplit=1)[1].split(maxsplit=1)[0],
        "price": 3210.0 if quantity == 2 else 4510.0 if quantity == 3 else 6890.0,
        "category": "Mid Range",
        "warranty": "3 years",
        "url": "https://gulong.ph/product/test-product",
        "installments": [],
        "bundle_pricing": {},
    }
    card = render_product_cards(
        ProductSearchRequest.from_mapping({"quantity": quantity}),
        [product],
    )[0]

    assert card["quantity"] == quantity
    assert f"for {quantity} tires" in card["card_text"] if quantity > 1 else "for 1 tire" not in card["card_text"]
    if expected_total:
        assert expected_total in card["card_text"]
    assert f"for {4} tires" not in card["card_text"] if quantity != 4 else True
