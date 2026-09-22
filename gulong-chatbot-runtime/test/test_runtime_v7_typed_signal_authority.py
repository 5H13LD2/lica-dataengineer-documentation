"""Focused authority-boundary regressions for Runtime V7 typed signals."""

from __future__ import annotations

from runtime_v7.order_state import (
    _signal_has_validated_checkout_choice_ref,
    _signal_value,
    build_order_readiness,
)
from runtime_v7.product_observations import ProductObservationStore
from runtime_v7.service_observations import ServiceObservationStore
from runtime_v7.state_signal_ledger import InMemoryBackgroundSignalLedgerStore
from runtime_v7.state_signal_normalization import _normalize_candidate
from runtime_v7.state_signal_schema import (
    signal_has_durable_authority,
    signal_is_advisory_context,
    signal_is_lookup_only_evidence,
)
from runtime_v7.state_signals import build_commercial_state_context


class _CategoryProvider:
    def tire_categories(self):
        return ["Quiet Touring"]


class _SignalModel:
    def __init__(self, candidates):
        self.candidates = list(candidates)

    def extract_background_signals(self, **_kwargs):
        import json

        return {
            "content": json.dumps({"candidates": self.candidates}),
            "usage": {},
            "cache_usage": {},
            "latency_ms": 1,
        }


class _LocationRoleResolver:
    """Small resolver fixture for role-preserving multi-location tests."""

    _cities = {
        "rosario cavite": "Rosario",
        "dasmarinas": "Dasmarinas City",
        "imus": "Imus City",
        "bacoor": "Bacoor City",
    }

    def resolve(self, value, *, allow_geocode=True):
        del allow_geocode
        normalized = " ".join(str(value).casefold().replace(",", " ").split())
        city = self._cities.get(normalized)
        return {
            "status": "gazetteer_city_match" if city else "not_geocoded",
            "normalized": normalized,
            "city_hint": city,
            "province_hint": "Cavite" if city else None,
            "landmark_hint": None,
            "location_precision": "city" if city else None,
            "requires_point_geocode": False,
            "provider": "gazetteer" if city else "none",
            "coordinates": None,
            "geocode_queries": [],
            "geocode_attempts": 0,
            "geocode_last_status": None,
            "gazetteer_status": "resolved" if city else "no_match",
            "city_candidates": [],
            "selected_city_candidate": {},
            "ambiguity_status": False,
            "ambiguity_reason": None,
            "clarification_options": [],
        }


def test_anchor_and_acceptable_service_locations_keep_distinct_roles():
    context = build_commercial_state_context(
        current_user_message=(
            "I'm from Rosario, Cavite; okay din sa Dasmarinas, Imus, or Bacoor."
        ),
        model_client=_SignalModel(
            [
                {
                    "key": "location",
                    "value": "Rosario Cavite",
                    "source": "latest_user_message",
                    "confidence": "high",
                },
                {
                    "key": "acceptable_service_locations",
                    "value": ["Dasmarinas", "Imus", "Bacoor"],
                    "source": "latest_user_message",
                    "confidence": "high",
                },
            ]
        ),
        location_resolver=_LocationRoleResolver(),
    )

    signals = {row["key"]: row for row in context["background_signals"]}
    assert signals["location"]["value"] == "Rosario, Cavite"
    alternatives = signals["acceptable_service_locations"]
    assert alternatives["value"] == (
        "Dasmarinas City, Cavite | Imus City, Cavite | Bacoor City, Cavite"
    )
    assert [
        row["value"] for row in alternatives["resolution"]["locations"]
    ] == [
        "Dasmarinas City, Cavite",
        "Imus City, Cavite",
        "Bacoor City, Cavite",
    ]
    assert alternatives["safe_for_action"] is False
    assert alternatives["resolution"]["requires_individual_tool_validation"] is True


def test_new_customer_anchor_retires_carried_service_alternatives():
    context = build_commercial_state_context(
        current_user_message="Bacoor na lang po.",
        previous_background_signals=[
            {
                "key": "location",
                "value": "Rosario, Cavite",
                "source": "signal_ledger",
                "confidence": "high",
                "relation": "asserted",
                "metadata": {
                    "ledger": {
                        "authority_source": "latest_user_message",
                        "authority_relation": "asserted",
                    },
                    "normalization": {
                        "status": "location_resolved",
                    },
                },
            },
            {
                "key": "acceptable_service_locations",
                "value": "Dasmarinas City, Cavite | Imus City, Cavite",
                "source": "signal_ledger",
                "confidence": "high",
                "relation": "asserted",
                "metadata": {
                    "ledger": {
                        "authority_source": "latest_user_message",
                        "authority_relation": "asserted",
                    },
                    "normalization": {
                        "status": "acceptable_service_locations_resolved",
                        "locations": [],
                    },
                },
            },
        ],
        model_client=_SignalModel(
            [
                {
                    "key": "location",
                    "value": "Bacoor",
                    "source": "latest_user_message",
                    "confidence": "high",
                    "relation": "corrected",
                }
            ]
        ),
        location_resolver=_LocationRoleResolver(),
    )

    signals = {row["key"]: row for row in context["background_signals"]}
    assert signals["location"]["value"] == "Bacoor City, Cavite"
    assert "acceptable_service_locations" not in signals


def _carried_signal(key, value, *, authority_source):
    return {
        "key": key,
        "value": value,
        "source": "signal_ledger",
        "confidence": "high",
        "relation": "selected",
        "metadata": {
            "ledger": {
                "authority_source": authority_source,
                "authority_relation": "selected",
                "persisted_in_signal_ledger": True,
            }
        },
    }


def test_external_evidence_is_advisory_but_never_persisted_or_readiness_authority():
    context = build_commercial_state_context(
        current_user_message="Ito po yung sidewall photo.",
        external_evidence_candidates=[
            {
                "key": "contact_number",
                "value": "09171234567",
                "source": "external_evidence",
                "status_hint": "external_image_ocr_unvalidated",
                "confidence": "high",
                "relation": "asserted",
            }
        ],
        model_extraction_policy="never",
    )

    signal = context["background_signals"][0]
    assert signal["source"] == "external_evidence"
    assert signal["status"] == "external_evidence_unvalidated"
    assert signal_is_advisory_context(signal) is True
    assert signal_is_lookup_only_evidence(signal) is True
    assert signal_has_durable_authority(signal) is False
    assert _signal_value({"contact_number": signal}, "contact_number") == ""

    ledger = InMemoryBackgroundSignalLedgerStore()
    ledger.save("external-only", context["background_signals"], turn_index=1)
    assert ledger.load("external-only") == []


def test_customer_fulfillment_choice_outranks_later_service_lookup_scope():
    previous = [
        {
            "key": "service_type",
            "value": "delivery",
            "source": "signal_ledger",
            "confidence": "high",
            "relation": "selected",
            "metadata": {
                "ledger": {
                    "authority_source": "latest_user_message",
                    "authority_relation": "selected",
                    "persisted_in_signal_ledger": True,
                }
            },
        }
    ]
    context = build_commercial_state_context(
        current_user_message="How much is shipping?",
        previous_background_signals=previous,
        latest_service_observation={
            "observation_ref": "svc_obs_installation_lookup",
            "presentation_ref": "svc_pres_installation_lookup",
            "query_basis": {"service_type": "installation"},
        },
        model_extraction_policy="never",
    )

    signals = {item["key"]: item for item in context["background_signals"]}
    assert signals["service_type"]["value"] == "delivery"
    assert signals["service_type"]["source"] == "signal_ledger"


def test_current_validated_choice_outranks_reemitted_older_customer_history():
    context = build_commercial_state_context(
        current_user_message="Continue po.",
        previous_background_signals=[
            _carried_signal(
                "tire_category_preference",
                "Budget",
                authority_source="validated_choice_action",
            )
        ],
        model_client=_SignalModel(
            [
                {
                    "key": "tire_category_preference",
                    "value": "Premium",
                    "source": "customer_history",
                    "confidence": "high",
                    "relation": "selected",
                    "evidence": "older customer choice",
                }
            ]
        ),
    )

    signal = {
        item["key"]: item for item in context["background_signals"]
    }["tire_category_preference"]
    assert signal["value"] == "Budget"
    assert signal["source"] == "signal_ledger"


def test_new_latest_customer_correction_replaces_current_carried_state():
    context = build_commercial_state_context(
        current_user_message="Premium pala.",
        previous_background_signals=[
            _carried_signal(
                "tire_category_preference",
                "Budget",
                authority_source="validated_choice_action",
            )
        ],
        model_client=_SignalModel(
            [
                {
                    "key": "tire_category_preference",
                    "value": "Premium",
                    "source": "latest_user_message",
                    "confidence": "high",
                    "relation": "corrected",
                    "evidence": "Premium pala",
                }
            ]
        ),
    )

    signal = {
        item["key"]: item for item in context["background_signals"]
    }["tire_category_preference"]
    assert signal["value"] == "Premium"
    assert signal["source"] == "latest_user_message"


def test_service_lookup_scope_is_context_only_and_does_not_enter_ledger():
    context = build_commercial_state_context(
        current_user_message="Please check that option.",
        latest_service_observation={
            "observation_ref": "svc_obs_context_only",
            "presentation_ref": "svc_pres_context_only",
            "query_basis": {"service_type": "installation"},
        },
        model_extraction_policy="never",
    )
    signals = {item["key"]: item for item in context["background_signals"]}
    assert signals["service_type"]["value"] == "installation"
    assert signal_has_durable_authority(signals["service_type"]) is False

    ledger = InMemoryBackgroundSignalLedgerStore()
    ledger.save("service-observation-only", list(signals.values()), turn_index=1)
    saved = {item["key"]: item for item in ledger.load("service-observation-only")}
    assert "service_type" not in saved
    assert "latest_service_presentation" not in saved


def test_service_observation_alone_does_not_create_fulfillment_or_readiness():
    store = ServiceObservationStore()
    store.save_location_result(
        {
            "observation_ref": "svc_obs_lookup_only",
            "presentation_ref": "svc_pres_lookup_only",
            "query_basis": {
                "location": "Cavite",
                "service_type": "installation",
            },
            "service_locations": [{"name": "Example installation partner"}],
        }
    )

    readiness = build_order_readiness(
        background_signals=[],
        service_observation_store=store,
    ).to_dict()

    assert readiness["status"] == "not_started"
    assert readiness["customer_order_intent"] == "none"
    assert readiness["high_intent_signals"] == []
    assert "Fulfillment" not in readiness["collected"]


def test_product_observation_requires_explicit_selected_product_context_for_readiness():
    store = ProductObservationStore()
    store.save_search_result(
        {
            "observation_ref": "obs_product_lookup_only",
            "presentation_ref": "pres_product_lookup_only",
            "product_cards": [
                {
                    "card_ref": "card_product_one",
                    "item_ref": "item_product_one",
                    "product_id": 101,
                    "slug": "example-product",
                    "sku_model": "EXAMPLE PRODUCT 205/55R16",
                    "price": 5000,
                }
            ],
            "presented_products": [
                {
                    "item_ref": "item_product_one",
                    "product_id": 101,
                    "slug": "example-product",
                    "sku_model": "EXAMPLE PRODUCT 205/55R16",
                    "price": 5000,
                }
            ],
        }
    )

    lookup_only = build_order_readiness(
        background_signals=[],
        product_observation_store=store,
    ).to_dict()
    selected = build_order_readiness(
        background_signals=[],
        product_observation_store=store,
        selected_product_context={
            "product_observation_ref": "obs_product_lookup_only",
            "product_presentation_ref": "pres_product_lookup_only",
            "product_card_ref": "card_product_one",
            "product_item_ref": "item_product_one",
            "product_id": 101,
            "slug": "example-product",
        },
    ).to_dict()

    assert lookup_only["status"] == "not_started"
    assert lookup_only["high_intent_signals"] == []
    assert "Product" not in lookup_only["collected"]
    assert selected["status"] != "not_started"
    assert "Product" in selected["collected"]


def test_unvalidated_status_text_cannot_skip_canonical_provider_lookup():
    normalized = _normalize_candidate(
        {
            "key": "tire_category_preference",
            "value": "Quiet Tour",
            "source": "external_evidence",
            # Regression: the previous substring check treated this as
            # validated because it contained the word "validated".
            "status_hint": "external_image_ocr_unvalidated",
            "confidence": "high",
        },
        canonical_values_provider=_CategoryProvider(),
    )

    assert normalized is not None
    assert normalized["value"] == "Quiet Touring"


def test_payment_stage_must_use_the_closed_candidate_key_not_explanation_prose():
    normalized = _normalize_candidate(
        {
            "key": "payment_method",
            "value": "GCash",
            "source": "latest_user_message",
            "evidence": "customer asks about a reservation",
            "status_hint": "reservation payment question",
        }
    )

    assert normalized is not None
    assert normalized["key"] == "payment_method"


def test_payment_choice_refs_require_validated_guided_choice_provenance():
    refs = {
        "choice_ref": "option_2",
        "presentation_ref": "pres_payment_options_test",
    }
    external = {
        "key": "payment_option",
        "value": "Pay Now",
        "source": "external_evidence",
        "status": "tool_grounded",
        "metadata": refs,
    }
    untrusted_customer_metadata = {
        "key": "payment_option",
        "value": "Pay Now",
        "source": "latest_user_message",
        "status": "provided_by_latest_user_message",
        "metadata": refs,
    }
    delivered_choice = {
        "key": "payment_option",
        "value": "Pay Now",
        "source": "validated_choice_action",
        "status": "tool_grounded",
        "metadata": refs,
    }

    assert _signal_has_validated_checkout_choice_ref(external) is False
    assert _signal_has_validated_checkout_choice_ref(untrusted_customer_metadata) is False
    assert _signal_has_validated_checkout_choice_ref(delivered_choice) is True


def test_legacy_ledger_row_without_original_provenance_is_not_revived_as_authority():
    legacy = {
        "key": "payment_option",
        "value": "Pay Now",
        "source": "signal_ledger",
        "status": "remembered_signal",
        "metadata": {"ledger": {}},
    }

    assert signal_is_advisory_context(legacy) is False
    assert signal_has_durable_authority(legacy) is False
    assert _signal_value({"payment_option": legacy}, "payment_option") == ""


def test_human_agent_history_is_context_not_customer_or_commercial_authority():
    signal = {
        "key": "payment_option",
        "value": "Pay Now",
        "source": "human_agent_history",
        "relation": "asserted",
    }

    assert signal_is_advisory_context(signal) is True
    assert signal_has_durable_authority(signal) is False
    assert _signal_value({"payment_option": signal}, "payment_option") == ""
