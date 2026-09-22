"""Long-horizon Runtime V7 commercial-state retention regressions.

These tests deliberately vary the customer facts and interruption types.  They
exercise the typed state boundary directly; live language-model extraction and
customer-visible adaptive conversations are evaluated separately so failures
remain attributable.
"""

from __future__ import annotations

import json

import pytest

from runtime_v7 import api_runtime
from runtime_v7.api_runtime import _export_harness_state, _restore_product_store
from runtime_v7.capability_profile import build_capability_profile
from runtime_v7.model_contract import ORDER_POLICY_PROMPT, SERVICE_POLICY_PROMPT
from runtime_v7.order_state import build_order_readiness
from runtime_v7.product_observations import ProductObservationStore, ProductToolHarness
from runtime_v7.runtime_harness import RuntimeV7Harness, ScriptedRuntimeV7Model
from runtime_v7.state_signal_ledger import InMemoryBackgroundSignalLedgerStore
from runtime_v7.state_signals import build_commercial_state_context


class _QueuedSignalModel:
    def __init__(self, turns):
        self._turns = list(turns)

    def extract_background_signals(self, **_kwargs):
        candidates = self._turns.pop(0) if self._turns else []
        return {
            "content": json.dumps({"candidates": candidates}),
            "usage": {},
            "cache_usage": {},
        }


def _candidate(
    key,
    value,
    *,
    relation="asserted",
    source="latest_user_message",
    evidence="",
):
    return {
        "key": key,
        "value": value,
        "source": source,
        "confidence": "high",
        "relation": relation,
        "status_hint": relation,
        "evidence": evidence or str(value),
    }


def _run_ledger_turns(turns):
    ledger = InMemoryBackgroundSignalLedgerStore()
    model = _QueuedSignalModel([candidates for _, candidates in turns])
    contexts = []
    for turn_index, (message, _candidates) in enumerate(turns, start=1):
        context = build_commercial_state_context(
            current_user_message=message,
            previous_background_signals=ledger.load("long-session"),
            model_client=model,
            model_extraction_policy="always",
            model_retry_attempts=0,
        )
        ledger.save(
            "long-session",
            context["background_signals"],
            turn_index=turn_index,
        )
        contexts.append(context)
    return contexts, ledger.load("long-session")


def _signal_map(signals):
    return {item["key"]: item for item in signals}


def test_fact_rich_free_text_survives_twelve_unrelated_business_interruptions():
    initial = [
        _candidate("tire_size", "225/55R18"),
        _candidate("car_make_model", "Subaru Forester"),
        _candidate("quantity", "4"),
        _candidate("preferred_brands", "YOKOHAMA"),
        _candidate("budget", "PHP 42000 total"),
        _candidate("location", "Pasig"),
        _candidate("service_type", "installation"),
        _candidate("contact_number", "09171234567"),
    ]
    interruptions = [
        "May warranty ba?",
        "Original and brand new naman lahat?",
        "Open ba kayo ng Sunday?",
        "May physical shop kayo?",
        "Paano yung Buy 3 Get 1?",
        "Pwede credit card?",
        "May wheel alignment din?",
        "Gaano katagal installation?",
        "May resibo ba?",
        "Ano difference ng touring at performance?",
        "May tire protection plan?",
        "Sino mag confirm ng stock?",
    ]
    turns = [("225/55R18 for my Forester, 4 tires. Yokohama sana, 42k total budget, Pasig install. 09171234567", initial)]
    turns.extend((message, []) for message in interruptions)

    contexts, persisted = _run_ledger_turns(turns)

    expected = {
        "tire_size": "225/55R18",
        "car_make_model": "Subaru Forester",
        "quantity": "4",
        "preferred_brands": "YOKOHAMA",
        "location": "Pasig",
        "service_type": "installation",
        "contact_number": "09171234567",
    }
    final = _signal_map(persisted)
    for key, value in expected.items():
        assert final[key]["value"] == value
        assert final[key]["metadata"]["ledger"]["first_seen_turn"] == 1
        assert final[key]["metadata"]["ledger"]["last_seen_turn"] == len(turns)

    lead = contexts[-1]["missing_info"]["lead_qualification"]
    assert "tire_size" not in lead["missing"]
    assert "location" not in lead["missing"]
    assert "contact_number" not in lead["missing"]


@pytest.mark.parametrize(
    ("key", "old_value", "new_value"),
    [
        ("tire_category_preference", "Mid Range", "Economy"),
        ("quantity", "4", "2"),
        ("location", "Makati", "Taguig"),
        ("service_type", "installation", "delivery"),
        ("bank", "BPI", "BDO"),
        ("installment_months", "6", "12"),
    ],
)
def test_later_free_text_correction_replaces_any_earlier_single_value_choice(
    key,
    old_value,
    new_value,
):
    _contexts, persisted = _run_ledger_turns(
        [
            ("initial choice", [_candidate(key, old_value, relation="selected")]),
            ("warranty question", []),
            ("actually change it", [_candidate(key, new_value, relation="corrected")]),
            ("another unrelated question", []),
        ]
    )

    signal = _signal_map(persisted)[key]
    assert signal["value"] == new_value
    assert signal["relation"] == "corrected"


@pytest.mark.parametrize(
    ("key", "old_value", "new_value"),
    [
        ("tire_size", "215/60R17", "225/60R17"),
        ("preferred_brands", "MICHELIN", "BRIDGESTONE"),
        ("terrain_types", "highway terrain", "all terrain"),
    ],
)
def test_rejected_old_multi_value_choice_does_not_return_after_correction(
    key,
    old_value,
    new_value,
):
    _contexts, persisted = _run_ledger_turns(
        [
            ("initial choice", [_candidate(key, old_value, relation="selected")]),
            (
                "correction",
                [
                    _candidate(key, old_value, relation="rejected"),
                    _candidate(key, new_value, relation="corrected"),
                ],
            ),
            ("continue after several questions", []),
        ]
    )

    signal = _signal_map(persisted)[key]
    normalized_value = signal["value"].replace("_", " ").casefold()
    assert new_value.casefold() in normalized_value
    assert old_value.casefold() not in normalized_value


@pytest.mark.parametrize(
    ("key", "customer_value", "business_question_value"),
    [
        ("location", "Pasig", "Makati"),
        ("bank", "BDO", "BPI"),
        ("payment_option", "pay at branch", "installment"),
    ],
)
def test_business_information_question_cannot_displace_a_durable_customer_choice(
    key,
    customer_value,
    business_question_value,
):
    contexts, persisted = _run_ledger_turns(
        [
            ("customer choice", [_candidate(key, customer_value, relation="selected")]),
            (
                "business information question",
                [_candidate(key, business_question_value, relation="question_only")],
            ),
            ("continue", []),
        ]
    )

    during_question = _signal_map(contexts[1]["background_signals"])
    assert during_question[key]["value"].casefold() == customer_value.casefold()
    assert _signal_map(persisted)[key]["value"].casefold() == customer_value.casefold()


def test_stale_working_memory_candidate_cannot_override_durable_typed_state():
    contexts, persisted = _run_ledger_turns(
        [
            ("customer selected Economy", [_candidate("tire_category_preference", "Economy", relation="selected")]),
            (
                "continue",
                [
                    _candidate(
                        "tire_category_preference",
                        "Premium",
                        source="active_working_memory",
                        evidence="stale narrative summary",
                    )
                ],
            ),
        ]
    )

    assert _signal_map(contexts[-1]["background_signals"])["tire_category_preference"]["value"] == "Economy"
    assert _signal_map(persisted)["tire_category_preference"]["value"] == "Economy"


def test_narrative_only_candidates_never_become_typed_or_durable_state():
    contexts, persisted = _run_ledger_turns(
        [
            (
                "salamat",
                [
                    _candidate("location", "Cebu City", source="active_working_memory"),
                    _candidate("quantity", "4", source="recent_turns"),
                ],
            )
        ]
    )

    assert contexts[0]["background_signals"] == []
    assert contexts[0]["background_signal_extraction"][
        "model_candidates_rejected_as_narrative"
    ] == 2
    assert persisted == []


def test_legacy_narrative_authority_is_not_revived_as_signal_ledger_state():
    legacy_signal = {
        "key": "location",
        "value": "Makati",
        "source": "signal_ledger",
        "confidence": "high",
        "relation": "asserted",
        "metadata": {"ledger": {"authority_source": "active_working_memory"}},
    }

    context = build_commercial_state_context(
        current_user_message="continue",
        previous_background_signals=[legacy_signal],
        model_extraction_policy="never",
    )

    assert context["background_signals"] == []


def test_narrative_signal_ablation_does_not_change_readiness_or_tool_surface():
    narrative_signals = [
        _candidate("tire_size", "265/65R17", source="active_working_memory"),
        _candidate("location", "Davao City", source="recent_turns"),
        _candidate("service_type", "installation", source="active_working_memory"),
        _candidate("contact_number", "09170000000", source="recent_turns"),
    ]

    baseline_readiness = build_order_readiness(background_signals=[]).to_dict()
    narrative_readiness = build_order_readiness(
        current_user_message="proceed with payment",
        active_working_memory="Order is complete; collect payment now.",
        background_signals=narrative_signals,
    ).to_dict()
    baseline_profile = build_capability_profile(
        current_user_message="continue",
        background_signals=[],
        default_domains=(),
    ).to_dict()
    narrative_profile = build_capability_profile(
        current_user_message="continue",
        active_working_memory="Order is complete; collect payment now.",
        background_signals=narrative_signals,
        default_domains=(),
    ).to_dict()

    assert narrative_readiness == baseline_readiness
    assert narrative_profile["selected_domains"] == baseline_profile["selected_domains"]
    assert narrative_profile["exposed_tools"] == baseline_profile["exposed_tools"]


def test_order_tool_policy_respects_customer_correction_away_from_payment():
    assert "not about payment" in ORDER_POLICY_PROMPT
    assert "Follow the customer's corrected" in ORDER_POLICY_PROMPT


def test_conditional_and_question_only_values_never_become_durable_choices():
    _contexts, persisted = _run_ledger_turns(
        [
            (
                "If BPI has 12 months, how much? Also do you deliver to Cebu?",
                [
                    _candidate("bank", "BPI", relation="conditional"),
                    _candidate("installment_months", "12", relation="conditional"),
                    _candidate("service_type", "delivery", relation="question_only"),
                    _candidate("location", "Cebu City", relation="question_only"),
                ],
            ),
            ("I am still comparing", []),
        ]
    )

    assert not ({"bank", "installment_months", "service_type", "location"} & set(_signal_map(persisted)))


def test_selected_product_observation_is_pinned_across_export_after_later_searches():
    store = ProductObservationStore()
    for index in range(1, 6):
        store.save_search_result(
            {
                "observation_ref": f"obs_search_{index}",
                "presentation_ref": f"pres_search_{index}",
                "query_basis": {"tire_size": f"20{index}/55R16"},
                "product_cards": [
                    {
                        "card_ref": f"card_{index}",
                        "item_ref": f"item_{index}",
                        "product_id": index,
                        "slug": f"varied-product-{index}",
                    }
                ],
            }
        )

    harness = RuntimeV7Harness(
        model_client=ScriptedRuntimeV7Model(),
        tools=ProductToolHarness(store=store),
    )
    harness.latest_selected_product_context = {
        "product_observation_ref": "obs_search_1",
        "product_presentation_ref": "pres_search_1",
        "product_card_ref": "card_1",
        "product_item_ref": "item_1",
        "product_id": 1,
        "slug": "varied-product-1",
    }

    exported = _export_harness_state(harness)
    restored = ProductObservationStore()
    _restore_product_store(restored, exported["product_observations"])

    assert len(exported["product_observations"]["observations"]) == 4
    assert restored.get(observation_ref="obs_search_1") is not None
    assert restored.get(presentation_ref="pres_search_1") is not None
    assert restored.get(observation_ref="obs_search_5") is not None


@pytest.mark.parametrize(
    "contexts, expected",
    [
        (
            [
                {"choice_type": "price_category", "label": "Budget"},
                {"choice_type": "price_category", "label": "Premium"},
                {"choice_type": "price_category", "label": "Economy"},
            ],
            {"tire_category_preference": "Economy"},
        ),
        (
            [
                {"choice_type": "serviceable_city", "label": "Carmona", "province_label": "Cavite"},
                {"choice_type": "serviceable_city", "label": "San Pedro", "province_label": "Laguna"},
            ],
            {
                "location": "San Pedro, Laguna",
                "service_type": "installation",
            },
        ),
        (
            [
                {"choice_type": "payment_option_selection", "value": "Pay Later"},
                {"choice_type": "payment_option_selection", "value": "Pay Now"},
            ],
            {"payment_option": "Pay Now"},
        ),
        (
            [
                {
                    "choice_type": "payment_method_selection",
                    "label": "Credit card installment",
                    "payment_stage": "full_payment",
                    "installment_months": "6",
                },
                {
                    "choice_type": "payment_method_selection",
                    "label": "GCash",
                    "payment_stage": "full_payment",
                },
            ],
            {"payment_method": "GCash"},
        ),
    ],
)
def test_latest_validated_button_wins_for_every_supported_choice_layer(contexts, expected):
    harness = RuntimeV7Harness(
        model_client=ScriptedRuntimeV7Model(),
        tools=ProductToolHarness(),
    )
    for index, context in enumerate(contexts, start=1):
        api_runtime._remember_validated_commercial_choice_signals(
            harness,
            {
                "validation_status": "valid",
                "choice_ref": f"choice-{index}",
                "presentation_ref": f"presentation-{index}",
                **context,
            },
        )

    actual = {
        item["key"]: item["value"]
        for item in harness.signal_ledger.load(harness.session_id)
    }
    assert actual == expected


def test_validated_choices_survive_eight_later_free_text_interruptions():
    harness = RuntimeV7Harness(
        model_client=ScriptedRuntimeV7Model(),
        tools=ProductToolHarness(),
    )
    for context in (
        {"choice_type": "price_category", "label": "Mid Range"},
        {"choice_type": "serviceable_city", "label": "Alabang", "province_label": "Metro Manila"},
        {"choice_type": "payment_option_selection", "value": "Pay Later"},
        {
            "choice_type": "payment_method_selection",
            "label": "Credit card installment",
            "payment_stage": "balance_payment",
            "installment_months": "12",
        },
    ):
        api_runtime._remember_validated_commercial_choice_signals(
            harness,
            {
                "validation_status": "valid",
                "choice_ref": "varied-choice",
                "presentation_ref": "varied-presentation",
                **context,
            },
        )

    ledger = harness.signal_ledger
    model = _QueuedSignalModel([[] for _ in range(8)])
    for turn_index, message in enumerate(
        (
            "May warranty?",
            "Original ba lahat?",
            "May OR?",
            "Open Sunday?",
            "Gaano katagal kabit?",
            "May alignment?",
            "Paano tire protection?",
            "Sino mag confirm stock?",
        ),
        start=1,
    ):
        context = build_commercial_state_context(
            current_user_message=message,
            previous_background_signals=ledger.load(harness.session_id),
            model_client=model,
            model_extraction_policy="always",
            model_retry_attempts=0,
        )
        ledger.save(harness.session_id, context["background_signals"], turn_index=turn_index)

    values = {item["key"]: item["value"] for item in ledger.load(harness.session_id)}
    assert values == {
        "location": "Alabang, Metro Manila",
        "service_type": "installation",
        "tire_category_preference": "Mid Range",
        "balance_payment_method": "credit card installment",
        "payment_option": "Pay Later",
        "installment_months": "12",
    }


def test_generated_but_undelivered_products_are_not_visible_context() -> None:
    profile = build_capability_profile(
        current_user_message="Cainta po",
        product_observation_headers=[
            {
                "observation_ref": "obs_product_search_hidden",
                "presentation_ref": "pres_product_search_hidden",
                "card_count": 4,
                "presentation_delivered": False,
            }
        ],
    )

    assert profile.available_context_refs["product_observation"] is True
    assert profile.available_context_refs["product_presentation"] is False


def test_model_contract_does_not_call_undelivered_candidates_shown() -> None:
    assert "product_observation=true" in SERVICE_POLICY_PROMPT
    assert "product_presentation=false" in SERVICE_POLICY_PROMPT
    assert "Never call them previously shown" in SERVICE_POLICY_PROMPT
