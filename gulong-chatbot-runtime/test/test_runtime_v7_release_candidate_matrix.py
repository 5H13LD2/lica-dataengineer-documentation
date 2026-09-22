"""Regression tests for deployed Runtime V7 release-gate evaluation."""

from copy import deepcopy
from http.client import RemoteDisconnected

import pytest

import scripts.runtime_v7_release_candidate_matrix as release_matrix
from scripts.runtime_v7_release_candidate_matrix import (
    CASES,
    DEFAULT_FEATURE_EXPECTATIONS,
    OPERATIONAL_FUNNEL_CONTRACTS,
    _after_turn_customer_signal_evidence,
    _reviewed_profile_renderer_accepted,
    _runner_exception_row,
    _visible_contact_request,
    _visible_location_request,
    build_operational_funnel_contract,
    customer_text,
    evaluate,
    feature_surface_decision,
    resolve_feature_expectations,
    operational_funnel_definition_digest,
    scenario_definition_digest,
)
from runtime_v7.promotion_health_evaluator import (
    ALLOWED_JOURNEY_ACTIONS,
    APPROVED_OPERATIONAL_FUNNEL_DEFINITION_DIGESTS,
    APPROVED_SCENARIO_DEFINITION_DIGESTS,
)
from scripts.runtime_v7_composer_tone_probe import (
    _customer_answer_without_runtime_intro,
    evaluate_customer_reply,
)


def _promo_fallback_response() -> dict:
    """Return the minimum safe deterministic-promo fallback evidence."""

    return {
        "_probe_http_status": 200,
        "status": "success",
        "release_version": "candidate",
        "delivery_result": {"status": "skipped", "reason": "return_only"},
        "tagging_result": {
            "tag_apply_skipped": True,
            "tag_apply_skip_reason": "return_only",
        },
        "debug": {
            "tool_calls": [],
            "final_composer_status": "promo_fact_safe_fallback",
            "response_guard_events": [
                {
                    "type": "promo_fact_safe_fallback_used",
                    "reason": "semantic_scope_audit_not_satisfied",
                }
            ],
            "promo_fact_scope_audits": [{"decision": "unsupported"}],
        },
    }


def test_release_gate_accepts_typed_safe_promo_fallback() -> None:
    failures = evaluate(
        {"require_supported_promo_audit": True},
        _promo_fallback_response(),
        expected_release="candidate",
    )

    assert failures == []


def test_evaluators_keep_model_answer_merged_with_branded_opening() -> None:
    merged = (
        "Welcome to Gulong.ph! Yes po, online store kami and may installation "
        "partners in supported areas."
    )

    assert customer_text({"response": {"bubble1": merged}}) == merged
    assert _customer_answer_without_runtime_intro([merged]) == merged


def test_evaluators_drop_only_the_exact_fixed_runtime_welcome() -> None:
    fixed = (
        "Hi po! Welcome to Gulong.ph 😊\n"
        "We'll help you find brand-new, legit tires that fit your car, budget, and area."
    )

    assert customer_text(
        {"response": {"bubble1": fixed, "bubble2": "Direct answer"}}
    ) == ("Direct answer")
    assert _customer_answer_without_runtime_intro([fixed, "Direct answer"]) == (
        "Direct answer"
    )


def test_tone_probe_accepts_model_owned_first_greeting_across_multiple_units() -> None:
    result = evaluate_customer_reply(
        {"expected": {}},
        bubbles=["Hello po! Puwede po ang credit card.", "Ano pong tire size?"],
        response_payload={
            "status": "success",
            "debug": {"final_composer_status": "used"},
        },
        http_status=200,
        error="",
    )

    assert "duplicate_greeting_after_runtime_intro" not in result["failures"]


def test_tone_probe_counts_independent_grounded_compound_authorities() -> None:
    result = evaluate_customer_reply(
        {"expected": {"minimum_commercial_claims": 2}},
        bubbles=[
            "Hello po! Puwede ang credit card. Sa promo naman, eligible Apollo tires ang covered.",
            "Ano pong tire size?",
        ],
        response_payload={
            "status": "success",
            "debug": {
                "final_composer_status": "used",
                "commercial_payment_claims": [],
                "tool_calls": [
                    {"name": "answer_order_faq", "status": "ok"},
                    {"name": "search_promo_catalog", "status": "ok"},
                ],
            },
        },
        http_status=200,
        error="",
    )

    assert result["failures"] == []


def test_release_gate_rejects_unmarked_promo_fallback() -> None:
    response = deepcopy(_promo_fallback_response())
    response["debug"]["response_guard_events"] = []

    failures = evaluate(
        {"require_supported_promo_audit": True},
        response,
        expected_release="candidate",
    )

    assert "promo_fact_audit_not_supported" in failures
    assert "composer_status:promo_fact_safe_fallback" in failures


def test_release_gate_accepts_guarded_provider_owned_promo_result() -> None:
    response = _promo_fallback_response()
    response["debug"]["final_composer_status"] = "promo_fact_scoped_result"
    response["debug"]["response_guard_events"] = [
        {
            "type": "promo_fact_scoped_result_rendered",
            "reason": "provider_owned_empty_scope_and_surface_boundary",
        }
    ]

    failures = evaluate(
        {"require_supported_promo_audit": True},
        response,
        expected_release="candidate",
    )

    assert failures == []


def test_release_gate_accepts_exact_zero_call_reviewed_brand_renderer() -> None:
    profile = {"about_brand": "Reviewed neutral brand profile."}
    response = {
        "response": {"bubble1": "Reviewed neutral brand profile."},
        "debug": {"tool_calls": [], "final_composer_status": ""},
    }

    assert _reviewed_profile_renderer_accepted(response, profile) is True

    response["response"]["bubble1"] = "Generic brand response."
    assert _reviewed_profile_renderer_accepted(response, profile) is False


def test_release_gate_accepts_guarded_answer_goal_safe_fallback() -> None:
    response = {
        "_probe_http_status": 200,
        "status": "success",
        "release_version": "candidate",
        "delivery_result": {"status": "skipped", "reason": "return_only"},
        "tagging_result": {
            "tag_apply_skipped": True,
            "tag_apply_skip_reason": "return_only",
        },
        "debug": {
            "tool_calls": [{"name": "answer_policy_faq", "status": "ok"}],
            "final_composer_status": "answer_goal_safe_fallback",
            "response_guard_events": [{"type": "answer_goal_safe_fallback_used"}],
            "semantic_answer_goal_audits": [{"decision": "unsupported"}],
        },
    }
    case = {
        "required_tools": ("answer_policy_faq",),
        "required_composer_statuses": (
            "used",
            "repaired",
            "answer_goal_safe_fallback",
        ),
    }

    assert evaluate(case, response, expected_release="candidate") == []

    response["debug"]["response_guard_events"] = []
    assert "answer_goal_safe_fallback_not_guarded" in evaluate(
        case,
        response,
        expected_release="candidate",
    )


def test_release_gate_accepts_guarded_payment_surface_fallback_only() -> None:
    case = next(item for item in CASES if item["id"] == "nonlinear_product_first")
    response = {
        "_probe_http_status": 200,
        "status": "success",
        "release_version": "candidate",
        "delivery_result": {"status": "skipped", "reason": "return_only"},
        "tagging_result": {
            "tag_apply_skipped": True,
            "tag_apply_skip_reason": "return_only",
        },
        "content_messages": [
            {
                "type": "cards",
                "elements": [
                    {
                        "buttons": [
                            {
                                "actions": [
                                    {"value": ("ps1|pres_product_search_test|card_1")}
                                ]
                            }
                        ]
                    }
                ],
            }
        ],
        "debug": {
            "tool_calls": [{"name": "product_search", "status": "ok"}],
            "final_composer_status": ("payment_claim_safe_surface_fallback"),
            "response_guard_events": [
                {
                    "type": "payment_claim_safe_surface_fallback_used",
                    "preserved_surface_count": 1,
                }
            ],
        },
    }

    assert evaluate(case, response, expected_release="candidate") == []

    response["debug"]["commercial_payment_claims"] = [{"method": "unsupported"}]
    assert "payment_claim_safe_surface_fallback_not_guarded" in evaluate(
        case,
        response,
        expected_release="candidate",
    )
    response["debug"]["commercial_payment_claims"] = []

    response["debug"]["response_guard_events"] = []
    assert "payment_claim_safe_surface_fallback_not_guarded" in evaluate(
        case,
        response,
        expected_release="candidate",
    )

    other_case = {"required_tools": ("product_search",)}
    assert "composer_status:payment_claim_safe_surface_fallback" in evaluate(
        other_case,
        response,
        expected_release="candidate",
    )


def test_provider_grounded_payment_composition_requires_authority_and_visible_claims() -> None:
    case = next(item for item in CASES if item["id"] == "payment_yokohama_home_credit")

    planned_calls = [
        {
            "id": "call_home_credit",
            "name": "answer_order_faq",
            "args": {"requested_payment_method": "Home Credit"},
        },
        {
            "id": "call_yokohama_three",
            "name": "answer_order_faq",
            "args": {
                "requested_payment_method": "3 months installment 0% interest",
                "requested_product_brand": "YOKOHAMA",
                "payment_option": "Pay Later",
            },
        },
        {
            "id": "call_yokohama_bpi_six",
            "name": "answer_order_faq",
            "args": {"requested_payment_method": "BPI 0%"},
        },
    ]

    def payment_tool(call_id, method, outcome, brand="", option=""):
        args = {"requested_payment_method": method}
        if brand:
            args["requested_product_brand"] = brand
        if option:
            args["payment_option"] = option
        return {
            "round": 1,
            "tool_call_id": call_id,
            "name": "answer_order_faq",
            "status": "ok",
            "args": args,
            "payment_scope": {
                "requested_method": method,
                "requested_status": "unsupported" if outcome == "unsupported" else "supported",
                "brand": brand,
                "brand_eligibility": (
                    "eligible"
                    if outcome == "eligible"
                    else "not_eligible"
                    if outcome == "not_eligible"
                    else None
                ),
                "payment_option": option,
            },
            "authority": {"source": "checkout", "evidence_ref": method},
        }

    response = {
        "_probe_http_status": 200,
        "status": "success",
        "release_version": "candidate",
        "delivery_result": {"status": "skipped", "reason": "return_only"},
        "tagging_result": {
            "tag_apply_skipped": True,
            "tag_apply_skip_reason": "return_only",
        },
        "response": {
            "bubble1": (
                "Wala pa kaming Home Credit. Para sa Yokohama Pay Later, "
                "available ang 3-month 0% installment. Hindi po available ang "
                "BPI 6-month 0% installment."
            )
        },
        "debug": {
            "final_composer_status": "provider_grounded_payment_composition",
            "tool_dedupe_events": [],
            "turn_trace": {
                "component_spans": [
                    {
                        "component_type": "model_call",
                        "round": 1,
                        "tool_calls": planned_calls,
                    }
                ]
            },
            "tool_calls": [
                payment_tool("call_home_credit", "Home Credit", "unsupported"),
                payment_tool(
                    "call_yokohama_three",
                    "3-mos Installment (0% interest)", "eligible", "YOKOHAMA", "Pay Later"
                ),
                payment_tool(
                    "call_yokohama_bpi_six",
                    "BPI 6-mos Installment (0% interest)",
                    "not_eligible",
                    "YOKOHAMA",
                    "Pay Later",
                ),
            ],
            "commercial_payment_claims": [
                {
                    "method": "Home Credit",
                    "outcome": "unsupported",
                    "brand": "",
                    "payment_option": "",
                },
                {
                    "method": "3-mos Installment (0% interest)",
                    "outcome": "eligible",
                    "brand": "YOKOHAMA",
                    "payment_option": "Pay Later",
                },
                {
                    "method": "BPI 6-mos Installment (0% interest)",
                    "outcome": "not_eligible",
                    "brand": "YOKOHAMA",
                    "payment_option": "Pay Later",
                },
            ],
        },
    }


    assert evaluate(case, response, expected_release="candidate") == []

    response["response"]["bubble1"] = (
        "Wala pa kaming Home Credit para sa Yokohama Pay Later."
    )
    failures = evaluate(case, response, expected_release="candidate")
    assert any(
        failure.startswith("provider_grounded_payment_visible_method_missing:BPI")
        for failure in failures
    )

    assert "provider_grounded_payment_composition_not_payment_only" in evaluate(
        {"required_tools": ("answer_order_faq",)},
        response,
        expected_release="candidate",
    )


def test_post_json_retries_transient_disconnect_with_same_payload(monkeypatch) -> None:
    calls = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read() -> bytes:
            return b'{"status":"success"}'

    def fake_urlopen(request, timeout):
        calls.append((request.data, timeout))
        if len(calls) == 1:
            raise RemoteDisconnected("closed")
        return FakeResponse()

    monkeypatch.setattr(release_matrix.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(release_matrix.time, "sleep", lambda _seconds: None)

    result = release_matrix.post_json(
        "https://runtime.example/tester",
        {"idempotency_key": "same-event", "message": "hello"},
        95,
    )

    assert result["status"] == "success"
    assert result["_probe_http_status"] == 200
    assert result["_probe_attempt_count"] == 2
    assert result["_probe_transport_errors"] == [
        "RemoteDisconnected: closed"
    ]
    assert calls[0][0] == calls[1][0]


def test_operational_funnel_contract_uses_reviewed_data_derived_scenarios() -> None:
    contract = build_operational_funnel_contract("promotion")

    assert contract["required_scenario_ids"] == list(OPERATIONAL_FUNNEL_CONTRACTS)
    assert contract["measurement_boundary"] == (
        "rendered_response_and_planned_qualification_before_delivery"
    )
    assert (
        operational_funnel_definition_digest("promotion")
        == (APPROVED_OPERATIONAL_FUNNEL_DEFINITION_DIGESTS["promotion"])
    )
    assert all(
        str(item.get("provenance") or "").startswith(
            "privacy_safe_july_transcript_corpus:"
        )
        for item in OPERATIONAL_FUNNEL_CONTRACTS.values()
    )


def test_post_turn_signal_evidence_uses_customer_owned_sources_only() -> None:
    response = {
        "debug": {
            "turn_trace": {
                "state_snapshots": [
                    {
                        "state_name": "background_signal_ledger_after_turn",
                        "state_json": [
                            {
                                "key": "tire_size",
                                "value": "185/65R15",
                                "source": "latest_user_message",
                            },
                            {
                                "key": "preferred_brands",
                                "value": "MICHELIN",
                                "source": "latest_user_message",
                            },
                            {
                                "key": "location",
                                "value": "Quezon City",
                                "source": "validated_choice_action",
                            },
                            {
                                "key": "contact_number",
                                "value": "09170000000",
                                "source": "assistant_presented_card",
                            },
                        ],
                    }
                ]
            }
        }
    }

    evidence = _after_turn_customer_signal_evidence(response)

    assert evidence["keys"] == ["location", "tire_brand", "tire_size"]
    assert "contact_number" not in evidence["keys"]


def test_missing_or_malformed_post_turn_ledger_fails_closed() -> None:
    assert _after_turn_customer_signal_evidence({}) == {
        "ledger_present": False,
        "keys": [],
        "sources_by_key": {},
    }


@pytest.mark.parametrize(
    "text",
    (
        "Saan po kayo located?",
        "Anong city or area po kayo?",
        "Paki-send po ang inyong location.",
    ),
)
def test_location_request_matcher_accepts_reviewed_wording_variations(text) -> None:
    assert _visible_location_request({"response": {"bubble1": text}}) is True


def test_location_request_matcher_accepts_structured_serviceable_area_prompt() -> None:
    response = {
        "debug": {"final_composer_status": "skipped"},
        "content_messages": [
            {
                "type": "text",
                "text": (
                    "Sige po, para makita natin ang installation options, saan po "
                    "sa mga serviceable areas natin sa Pilipinas ang prefer niyo?"
                ),
            }
        ],
    }

    assert _visible_location_request(response) is True


def test_release_gate_accepts_exact_location_progression_guard_ownership() -> None:
    response = _promo_fallback_response()
    response["response"] = {
        "bubble1": (
            "Para ma-check ang installation o delivery options, "
            "saang city o area po kayo?"
        )
    }
    response["product_presentations"] = [
        {
            "presentation_ref": "pres_exact_product",
            "cards": [{"card_ref": "card_1"}],
        }
    ]
    response["debug"]["final_composer_status"] = "skipped"
    response["debug"]["location_progression_guard"] = {
        "status": "rewritten",
        "reason": "single_exact_size_brand_result_requires_location_question",
        "product_card_count": 1,
        "preserved_surface_refs": ["pres_exact_product"],
    }

    assert evaluate(
        {"allow_location_progression_guard": True},
        response,
        expected_release="candidate",
    ) == []


@pytest.mark.parametrize(
    "mutation",
    [
        lambda response: response["debug"]["location_progression_guard"].update(
            {"reason": "unknown"}
        ),
        lambda response: response.update({"product_presentations": []}),
        lambda response: response["response"].update(
            {"bubble1": "May exact tire option po tayo."}
        ),
    ],
)
def test_release_gate_rejects_unproven_location_progression_guard(
    mutation,
) -> None:
    response = _promo_fallback_response()
    response["response"] = {"bubble1": "Saang city o area po kayo?"}
    response["product_presentations"] = [
        {
            "presentation_ref": "pres_exact_product",
            "cards": [{"card_ref": "card_1"}],
        }
    ]
    response["debug"]["final_composer_status"] = "skipped"
    response["debug"]["location_progression_guard"] = {
        "status": "rewritten",
        "reason": "single_exact_size_brand_result_requires_location_question",
        "product_card_count": 1,
        "preserved_surface_refs": ["pres_exact_product"],
    }
    mutation(response)

    failures = evaluate(
        {"allow_location_progression_guard": True},
        response,
        expected_release="candidate",
    )

    assert "composer_status:skipped" in failures


def _service_sanitized_response() -> dict:
    response = _promo_fallback_response()
    response["response"] = {
        "bubble1": (
            "May 3 current installation partner options para sa Quezon City. "
            "Gusto niyo bang i-check ang installation schedule?"
        )
    }
    response["debug"]["final_composer_status"] = (
        "service_claim_surface_sanitized"
    )
    response["debug"]["response_guard_events"] = [
        {
            "type": "provider_owned_service_claim_prose_sanitized",
            "reason": "availability_fact_owned_by_exact_query_area_surface",
            "removed_response_unit_count": 1,
            "remaining_violations": [],
        }
    ]
    response["debug"]["tool_calls"] = [
        {
            "name": "find_installation_partners",
            "status": "ok",
            "args": {"location": "Quezon City, Metro Manila"},
            "authority": {
                "source": "runtime_v7_gulong_branch_catalog",
                "presentation_ref": "pres_installation_partners_1",
            },
        }
    ]
    return response


def test_release_gate_accepts_exact_service_surface_sanitizer_evidence() -> None:
    assert evaluate(
        {"allow_service_claim_surface_sanitized": True},
        _service_sanitized_response(),
        expected_release="candidate",
    ) == []


@pytest.mark.parametrize(
    "mutation",
    (
        lambda response: response["debug"]["response_guard_events"][0].update(
            {"remaining_violations": [{"type": "service_claim"}]}
        ),
        lambda response: response["debug"]["tool_calls"][0]["authority"].update(
            {"presentation_ref": ""}
        ),
        lambda response: response.update({"response": {}}),
    ),
)
def test_release_gate_rejects_unproven_service_surface_sanitizer(
    mutation,
) -> None:
    response = _service_sanitized_response()
    mutation(response)

    failures = evaluate(
        {"allow_service_claim_surface_sanitized": True},
        response,
        expected_release="candidate",
    )

    assert "composer_status:service_claim_surface_sanitized" in failures


@pytest.mark.parametrize(
    "text",
    (
        "Location ng store?",
        "May branch ba near me?",
        "Ano ang service areas ninyo?",
        "May serviceable areas kami sa Pilipinas para sa installation.",
        "Location is used to calculate installation options.",
    ),
)
def test_location_request_matcher_rejects_customer_business_questions(text) -> None:
    assert _visible_location_request({"response": {"bubble1": text}}) is False


def test_location_request_matcher_rejects_check_in_known_customer_city() -> None:
    response = {
        "response": {
            "bubble1": (
                "Since nasa Quezon City po kayo, gusto niyo po bang i-check "
                "natin kung saan pwede ang installation?"
            )
        }
    }

    assert _visible_location_request(response) is False


def test_contact_fallback_matcher_accepts_customer_number_not_hotline() -> None:
    assert _visible_contact_request(
        {"response": {"bubble1": "Paki-send po ang inyong mobile number."}}
    )
    assert not _visible_contact_request(
        {"response": {"bubble1": "Ang hotline number namin ay 0956-701-9222."}}
    )


def test_release_gate_requires_visible_authored_policy_facts() -> None:
    response = {
        "_probe_http_status": 200,
        "status": "success",
        "release_version": "candidate",
        "delivery_result": {"status": "skipped", "reason": "return_only"},
        "tagging_result": {
            "tag_apply_skipped": True,
            "tag_apply_skip_reason": "return_only",
        },
        "response": {"bubble1": "Paki-clarify po ang concern."},
        "debug": {"final_composer_status": "used", "tool_calls": []},
    }
    case = {
        "required_response_substrings": (
            "Greater Manila Area",
            "Lalamove",
            "7-10 days",
        )
    }

    failures = evaluate(case, response, expected_release="candidate")

    assert failures == [
        "missing_response_fact:Greater Manila Area",
        "missing_response_fact:Lalamove",
        "missing_response_fact:7-10 days",
    ]


def test_requested_brand_promo_gate_tracks_provider_refs() -> None:
    case = next(item for item in CASES if item["id"] == "promo_toyo_truth")

    assert set(case["required_tools"]) == {
        "search_promo_catalog",
        "present_promo_gallery",
    }
    assert "required_tools_any" not in case
    assert "require_product_or_category_surface" not in case
    assert case["promo_token_tracks_current_refs"] is True
    assert case["require_scoped_negative_promo_contract"] is True
    assert case["expected_promo_requested_brand"] == "TOYO"
    assert case["expected_promo_unmatched_brand"] == "TOYO"


def _provider_product_promo_response() -> dict:
    response = _promo_fallback_response()
    response["response"] = {
        "bubble1": (
            "Yes po, may Apollo Buy 3 Get 1 FREE para sa 175/65R14. "
            "PHP 12,690.00 ang payable total for 4 tires."
        )
    }
    response["debug"]["final_composer_status"] = "used"
    response["debug"]["tool_calls"] = [
        {
            "name": "search_promo_catalog",
            "status": "ok",
            "commercial_scope": {"requested_brands": ["Apollo"]},
        },
        {"name": "product_search", "status": "ok"},
    ]
    response["product_presentations"] = [
        {
            "presentation_ref": "pres-product-1",
            "observation_ref": "obs-product-1",
            "cards": [
                {
                    "card_ref": "card-1",
                    "product_id": 4332,
                    "brand": "APOLLO",
                    "tire_size": "175/65R14",
                    "pricing_facts": {
                        "quantity": 4,
                        "pricing_basis": "buy3get1",
                        "payable_total": 12690.0,
                        "included_promos": ["Buy 3 Get 1 FREE"],
                    },
                }
            ],
        }
    ]
    return response


def test_release_gate_accepts_dynamic_provider_backed_product_promo_claim() -> None:
    case = next(item for item in CASES if item["id"] == "promo_apollo_valid")

    assert (
        evaluate(
            case,
            _provider_product_promo_response(),
            expected_release="candidate",
        )
        == []
    )


@pytest.mark.parametrize(
    ("mutation", "expected_failure"),
    (
        (
            lambda response: response["product_presentations"][0]["cards"][0].update(
                {"tire_size": "185/65R14"}
            ),
            "product_promo_claim_evidence_missing",
        ),
        (
            lambda response: response["response"].update(
                {
                    "bubble1": (
                        "Yes po, may Apollo Buy 3 Get 1 FREE para sa 175/65R14. "
                        "PHP 11,000.00 ang payable total for 4 tires."
                    )
                }
            ),
            "product_promo_visible_total_mismatch",
        ),
        (
            lambda response: response["response"].update(
                {
                    "bubble1": (
                        "Yes po, may Apollo promo para sa 175/65R14. "
                        "PHP 12,690.00 ang payable total for 4 tires."
                    )
                }
            ),
            "product_promo_visible_mechanic_missing",
        ),
        (
            lambda response: response["product_presentations"][0].update(
                {"presentation_ref": ""}
            ),
            "product_promo_claim_identity_missing",
        ),
    ),
)
def test_release_gate_rejects_product_promo_claim_drift(
    mutation,
    expected_failure: str,
) -> None:
    case = next(item for item in CASES if item["id"] == "promo_apollo_valid")
    response = _provider_product_promo_response()
    mutation(response)

    failures = evaluate(case, response, expected_release="candidate")

    assert expected_failure in failures


def test_release_gate_accepts_scoped_negative_promo_guard() -> None:
    case = next(item for item in CASES if item["id"] == "promo_toyo_truth")
    response = _promo_fallback_response()
    response["response"] = {
        "bubble1": "Sa reviewed promos, wala pang confirmed match para sa Toyo."
    }
    response["debug"]["final_composer_status"] = "used"
    response["debug"]["tool_calls"] = [
        {
            "name": "search_promo_catalog",
            "status": "ok",
            "commercial_scope": {
                "requested_brands": ["Toyo"],
                "unmatched_requested_brands": ["Toyo"],
            },
        },
        {"name": "present_promo_gallery", "status": "ok"},
    ]
    response["debug"]["promo_provider_truth_guard"] = {
        "status": "rewritten",
        "unmatched_requested_brands": ["Toyo"],
    }

    assert evaluate(case, response, expected_release="candidate") == []


def test_release_gate_accepts_typed_partial_product_promo_disclosure() -> None:
    case = next(item for item in CASES if item["id"] == "promo_toyo_truth")
    response = _promo_fallback_response()
    response["response"] = {
        "bubble1": (
            "Walang option na tugma sa requested promo at requested brand "
            "(TOYO). Parehong exact tire size ang options sa ibaba."
        )
    }
    response["debug"]["final_composer_status"] = "used"
    response["debug"]["tool_calls"] = [
        {
            "name": "search_promo_catalog",
            "status": "ok",
            "commercial_scope": {
                "requested_brands": ["Toyo"],
                "unmatched_requested_brands": ["Toyo"],
            },
        },
        {"name": "present_promo_gallery", "status": "ok"},
    ]
    response["debug"]["promo_provider_truth_guard"] = {
        "status": "validated",
        "reason": "unmatched_promo_brand_scoped_by_product_disclosure",
        "unmatched_requested_brands": ["Toyo"],
        "requested_promo_types": ["buy3get1"],
        "partial_product_surface_suppressed": False,
    }

    assert evaluate(case, response, expected_release="candidate") == []


def test_release_gate_rejects_broad_negative_without_scoped_guard() -> None:
    case = next(item for item in CASES if item["id"] == "promo_toyo_truth")
    response = _promo_fallback_response()
    response["response"] = {"bubble1": "Walang Buy 3 Get 1 promo ang Toyo tires."}
    response["debug"]["final_composer_status"] = "used"

    failures = evaluate(case, response, expected_release="candidate")

    assert "scoped_negative_promo_guard_missing" in failures
    assert "scoped_negative_promo_brand_missing" in failures
    assert "scoped_negative_promo_visible_scope_missing" in failures


def test_ambiguous_store_location_asks_customer_area_without_address_or_picker() -> (
    None
):
    case = next(item for item in CASES if item["id"] == "semantic_store_location")

    assert case["forbidden_token_prefixes"] == ("lc1|",)
    assert "skipped" in case["required_composer_statuses"]
    assert "present_serviceable_location_choices" in case["forbidden_tools"]
    assert case["required_response_facts"][0]["id"] == "customer_location_question"
    assert case["forbidden_response_facts"][0]["id"] == (
        "unsolicited_head_office_address"
    )

    response = _promo_fallback_response()
    response["response"] = {
        "bubble1": "Saang city or area po kayo para mahanapan namin ng convenient option?"
    }
    response["debug"]["final_composer_status"] = "skipped"
    assert evaluate(case, response, expected_release="candidate") == []

    response["response"] = {
        "bubble1": (
            "Ang head office po namin ay 1166 Chino Roces Avenue, Makati. "
            "Saang city or area po kayo?"
        )
    }
    failures = evaluate(case, response, expected_release="candidate")
    assert "missing_response_fact:customer_location_question" not in failures
    assert "forbidden_response_fact:unsolicited_head_office_address" in failures


def test_explicit_head_office_address_remains_a_direct_business_answer() -> None:
    case = next(item for item in CASES if item["id"] == "explicit_head_office_address")
    response = _promo_fallback_response()
    response["response"] = {
        "bubble1": "Ang head office po namin ay 1166 Chino Roces Avenue, Makati."
    }
    response["debug"]["final_composer_status"] = "skipped"

    assert evaluate(case, response, expected_release="candidate") == []


def test_forbidden_response_fact_is_phrase_tolerant() -> None:
    response = _promo_fallback_response()
    response["response"] = {"bubble1": "Matatagpuan kami sa 1166 Chino Roces Ave."}
    response["debug"]["final_composer_status"] = "used"

    failures = evaluate(
        {
            "forbidden_response_facts": (
                {
                    "id": "address",
                    "any_of": ({"all_terms": ("1166", "Chino", "Roces")},),
                },
            )
        },
        response,
        expected_release="candidate",
    )

    assert failures == ["forbidden_response_fact:address"]


def test_checked_in_scenario_definitions_match_approved_digests() -> None:
    assert {
        tier: scenario_definition_digest(tier)
        for tier in ("smoke", "promotion", "full")
    } == dict(APPROVED_SCENARIO_DEFINITION_DIGESTS)


def test_product_journey_allows_direct_schedule_after_known_location() -> None:
    assert (
        "chat",
        "click_product",
        "click_schedule",
        "click_payment_option",
        "click_payment_method",
    ) in ALLOWED_JOURNEY_ACTIONS["product_location_schedule_payment_journey"]


def test_reordered_two_brand_payment_case_scores_complete_tool_chains() -> None:
    case = next(
        item for item in CASES if item["id"] == "payment_two_brand_reordered_typo"
    )
    calls = [
        {
            "id": "call_michelin_bpi_six",
            "name": "answer_order_faq",
            "args": {
                "requested_payment_method": "BPI 6-month 0%",
                "requested_product_brand": "MICHELIN",
            },
        },
        {
            "id": "call_yokohama_three",
            "name": "answer_order_faq",
            "args": {
                "requested_payment_method": "3 months installment 0% interest",
                "requested_product_brand": "YOKOHAMA",
                "payment_option": "Pay Later",
            },
        },
    ]
    response = {
        "_probe_http_status": 200,
        "status": "success",
        "release_version": "candidate",
        "delivery_result": {"status": "skipped", "reason": "return_only"},
        "tagging_result": {
            "tag_apply_skipped": True,
            "tag_apply_skip_reason": "return_only",
        },
        "debug": {
            "final_composer_status": "used",
            "tool_dedupe_events": [],
            "turn_trace": {
                "component_spans": [
                    {
                        "component_type": "model_call",
                        "round": 1,
                        "tool_calls": calls,
                    }
                ]
            },
            "tool_calls": [
                {
                    "round": 1,
                    "tool_call_id": "call_michelin_bpi_six",
                    "name": "answer_order_faq",
                    "status": "ok",
                    "args": calls[0]["args"],
                    "payment_scope": {
                        "requested_method": "BPI 6-mos Installment (0% interest)",
                        "requested_status": "supported",
                        "brand": "MICHELIN",
                        "brand_eligibility": "eligible",
                        "payment_option": "Pay Now",
                    },
                    "authority": {
                        "source": "checkout_metadata",
                        "evidence_ref": "faq:order:payment",
                    },
                },
                {
                    "round": 1,
                    "tool_call_id": "call_yokohama_three",
                    "name": "answer_order_faq",
                    "status": "ok",
                    "args": calls[1]["args"],
                    "payment_scope": {
                        "requested_method": "3-mos Installment (0% interest)",
                        "requested_status": "supported",
                        "brand": "YOKOHAMA",
                        "brand_eligibility": "not_brand_restricted",
                        "payment_option": "Pay Later",
                    },
                    "authority": {
                        "source": "checkout_metadata",
                        "evidence_ref": "faq:order:payment",
                    },
                },
            ],
            "commercial_payment_claims": [
                {
                    "method": "BPI 6-mos Installment (0% interest)",
                    "outcome": "eligible",
                    "brand": "MICHELIN",
                    "payment_option": "Pay Now",
                },
                {
                    "method": "3-mos Installment (0% interest)",
                    "outcome": "eligible",
                    "brand": "YOKOHAMA",
                    "payment_option": "Pay Later",
                },
            ],
        },
    }

    assert set(release_matrix.CASE_COVERAGE[case["id"]]["variation_tags"]) == {
        "compound",
        "reordered",
        "two_brands",
        "short_form",
        "typo",
    }
    assert evaluate(case, response, expected_release="candidate") == []


def test_reordered_two_brand_payment_allows_partial_model_plan_but_requires_exact_execution() -> (
    None
):
    case = next(
        item for item in CASES if item["id"] == "payment_two_brand_reordered_typo"
    )
    contract = next(
        item
        for item in case["expected_tool_chain_contracts"]
        if item["id"] == "michelin_bpi_six_month_scope"
    )

    assert contract["pre_args"]["requested_payment_method"]["contains"] == "BPI"
    assert contract["pre_args"]["requested_product_brand"]["equals"] == "MICHELIN"
    assert contract["post_args"]["requested_payment_method"]["contains"] == "BPI 6"
    assert contract["post_args"]["payment_option"] == {"absent": True}


def test_yokohama_payment_case_scores_runtime_hydration_after_partial_model_scope() -> (
    None
):
    case = next(item for item in CASES if item["id"] == "payment_yokohama_home_credit")
    contract = next(
        item
        for item in case["expected_tool_chain_contracts"]
        if item["id"] == "yokohama_bpi_six_month_scope"
    )

    assert set(contract["pre_args"]) == {"requested_payment_method"}
    assert contract["pre_args"]["requested_payment_method"]["contains"] == "BPI"
    assert set(contract["post_args"]) == {
        "requested_payment_method",
        "requested_product_brand",
        "payment_option",
    }


def test_release_matrix_uses_tester_only_routes(monkeypatch) -> None:
    calls = []

    def fake_post(url, payload, timeout_s):
        calls.append((url, payload, timeout_s))
        return {"status": "success"}

    monkeypatch.setattr(release_matrix, "post_json", fake_post)

    release_matrix.chat(
        "https://candidate.example",
        user_id="synthetic-user",
        message="Hello",
        event_id="event-1",
        reset=True,
        timeout_s=10,
    )
    release_matrix.click(
        "https://candidate.example",
        user_id="synthetic-user",
        token="pc1|choice",
        event_id="event-2",
        timeout_s=10,
    )

    assert calls[0][0].endswith("/gulong/v7/chat/tester")
    assert calls[1][0].endswith("/gulong/v7/choice-action/tester")
    assert all(call[1]["delivery_mode"] == "return_only" for call in calls)
    assert all(call[1]["save_analytics"] == 0 for call in calls)


def test_release_gate_rejects_missing_tag_suppression_and_mutation_tool() -> None:
    response = _promo_fallback_response()
    response["tagging_result"] = {}
    response["debug"]["tool_calls"] = [{"name": "submit_order", "status": "ok"}]

    failures = evaluate({}, response, expected_release="candidate")

    assert "unsafe_tagging:{}" in failures
    assert "mutating_tool_called:submit_order" in failures


def test_release_gate_accepts_return_only_turn_with_empty_tag_plan() -> None:
    response = _promo_fallback_response()
    response["tagging_result"] = {
        "tags_to_add": [],
        "tags_applied": [],
        "tags_failed": [],
        "apply_status": "no_tags",
    }

    failures = evaluate({}, response, expected_release="candidate")

    assert not any(failure.startswith("unsafe_tagging:") for failure in failures)


def test_release_gate_rejects_unmarked_nonempty_tag_plan() -> None:
    response = _promo_fallback_response()
    response["tagging_result"] = {
        "tags_to_add": [{"tag": "Moderate Intent"}],
        "tags_applied": [],
        "tags_failed": [],
        "apply_status": "no_tags",
    }

    failures = evaluate({}, response, expected_release="candidate")

    assert any(failure.startswith("unsafe_tagging:") for failure in failures)


def test_runner_exception_becomes_failed_evidence_row() -> None:
    row = _runner_exception_row(
        "case-a",
        RuntimeError("boom"),
        coverage={"domain": "payment"},
    )

    assert row["passed"] is False
    assert row["domain"] == "payment"
    assert row["response"]["status"] == "error"
    assert row["failures"] == ["runner_exception:RuntimeError: boom"]


def _choice_message(caption: str, token: str) -> list[dict]:
    return [
        {
            "type": "cards",
            "elements": [
                {
                    "buttons": [
                        {
                            "caption": caption,
                            "actions": [{"type": "postback", "value": token}],
                        }
                    ]
                }
            ],
        }
    ]


def _safe_journey_response(
    *,
    token: str = "",
    caption: str = "Select",
    choice_type: str = "",
    tools: list[dict] | None = None,
    collected: dict | None = None,
    tagging_result: dict | None = None,
) -> dict:
    tagging = dict(tagging_result or {"tag_apply_skipped": True})
    if tagging.get("tag_apply_skipped") is True:
        tagging.setdefault("tag_apply_skip_reason", "return_only")
    response = {
        "_probe_http_status": 200,
        "status": "success",
        "release_version": "candidate",
        "delivery_result": {"status": "skipped", "reason": "return_only"},
        "tagging_result": tagging,
        "debug": {
            "final_composer_status": "used",
            "tool_calls": list(tools or []),
            "order_readiness_before_turn": {"collected": dict(collected or {})},
        },
        "content_messages": _choice_message(caption, token) if token else [],
    }
    if choice_type:
        response["choice_action_validation"] = {
            "status": "accepted",
            "validation_status": "valid",
            "choice_type": choice_type,
        }
    return response


def test_feature_expectation_profile_is_explicit_and_fail_closed() -> None:
    resolved = resolve_feature_expectations(
        {"promo_guided_actions": "forbidden_when_disabled"}
    )

    assert resolved["promo_guided_actions"] == "forbidden_when_disabled"
    assert resolved["product_choices"] == "required_when_enabled"
    assert (
        feature_surface_decision(
            feature="product_choices",
            token="",
            feature_expectations=resolved,
        )["failure"]
        == "required_feature_surface_missing:product_choices"
    )
    assert (
        feature_surface_decision(
            feature="promo_guided_actions",
            token="pc1|promo",
            feature_expectations=resolved,
        )["failure"]
        == "forbidden_feature_surface_rendered:promo_guided_actions"
    )
    assert (
        feature_surface_decision(
            feature="promo_guided_actions",
            token="",
            feature_expectations=resolved,
        )["status"]
        == "forbidden_and_absent"
    )


def test_feature_expectation_requires_authoritative_unavailability() -> None:
    expectations = resolve_feature_expectations()

    unproven = feature_surface_decision(
        feature="promo_guided_actions",
        token="",
        feature_expectations=expectations,
    )
    proven = feature_surface_decision(
        feature="promo_guided_actions",
        token="",
        feature_expectations=expectations,
        unavailable=True,
        unavailable_reason="no_current_promo_refs",
    )

    assert unproven["failure"] == (
        "feature_unavailability_not_proven:promo_guided_actions"
    )
    assert proven["status"] == "not_applicable"


def test_feature_expectation_profile_rejects_unknown_features_and_modes() -> None:
    for override in (
        {"unknown_surface": "required_when_enabled"},
        {"product_choices": "sometimes"},
    ):
        try:
            resolve_feature_expectations(override)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected invalid profile: {override}")


def test_choice_validation_requires_public_valid_status() -> None:
    response = _safe_journey_response(choice_type="payment_method_selection")
    response["choice_action_validation"]["validation_status"] = "stale"

    assert release_matrix._choice_validation_failures(
        response, "payment_method_selection"
    ) == ["choice_action_not_valid:payment_method_selection:stale"]


def test_product_journey_tracks_payment_option_and_method_clicks(monkeypatch) -> None:
    responses = [
        _safe_journey_response(
            token="ps1|product",
            caption="Select tire",
            tools=[{"name": "product_search", "status": "ok"}],
        ),
        _safe_journey_response(
            token="lc1|province",
            caption="Cavite",
            choice_type="product_selection",
        ),
        _safe_journey_response(
            token="ss1|schedule",
            caption="Sep 12",
            choice_type="serviceable_province",
        ),
        _safe_journey_response(
            token="po1|pay-now",
            caption="Pay Now",
            choice_type="schedule_selection",
        ),
        _safe_journey_response(
            token="pm1|card",
            caption="Credit Card",
            choice_type="payment_option_selection",
        ),
        _safe_journey_response(
            choice_type="payment_method_selection",
            collected={
                "Payment option": "Pay Now",
                "Payment method": "Credit Card",
            },
            tagging_result={
                "tag_apply_skipped": True,
                "tags_to_add": [
                    {"tag": "Moderate Intent"},
                    {"tag": "High Intent"},
                ],
                "analytical_qualifications": [
                    {
                        "schema_version": 1,
                        "kind": "analytical_qualification",
                        "qualification_level": "moderate",
                        "countable": True,
                        "decision_mode": "deterministic",
                        "rule_version": "gulong_intent_v2_test",
                        "qualification_event_id": ("aq_v1_0123456789abcdef01234567"),
                        "event_identity": {
                            "event_id": "run-1_journey_payment_method_1",
                            "idempotency_key": "run-1_journey_payment_method_1",
                        },
                    }
                ],
            },
        ),
    ]
    clicks = []

    monkeypatch.setattr(release_matrix, "chat", lambda *args, **kwargs: responses[0])

    def fake_click(*args, **kwargs):
        clicks.append(kwargs["token"])
        return responses[len(clicks)]

    monkeypatch.setattr(release_matrix, "click", fake_click)

    result = release_matrix.run_product_location_journey(
        base_url="https://candidate.example",
        timeout_s=10,
        run_id="run-1",
        expected_release="candidate",
        feature_expectations=DEFAULT_FEATURE_EXPECTATIONS,
    )

    assert result["passed"] is True
    assert clicks == [
        "ps1|product",
        "lc1|province",
        "ss1|schedule",
        "po1|pay-now",
        "pm1|card",
    ]
    assert [step["action"] for step in result["steps"]][-2:] == [
        "click_payment_option",
        "click_payment_method",
    ]
    assert {item["feature"] for item in result["feature_outcomes"]} == {
        "product_choices",
        "location_choices",
        "schedule_choices",
        "payment_option_choices",
        "payment_method_choices",
    }


def test_product_journey_skips_location_picker_when_schedule_is_already_resolved(
    monkeypatch,
) -> None:
    responses = [
        _safe_journey_response(
            token="ps1|product",
            caption="Select tire",
            tools=[{"name": "product_search", "status": "ok"}],
        ),
        _safe_journey_response(
            token="ss1|schedule",
            caption="Sep 12",
            choice_type="product_selection",
        ),
        _safe_journey_response(
            token="po1|pay-now",
            caption="Pay Now",
            choice_type="schedule_selection",
        ),
        _safe_journey_response(
            token="pm1|card",
            caption="Credit Card",
            choice_type="payment_option_selection",
        ),
        _safe_journey_response(
            choice_type="payment_method_selection",
            collected={
                "Payment option": "Pay Now",
                "Payment method": "Credit Card",
            },
            tagging_result={
                "tag_apply_skipped": True,
                "tags_to_add": [
                    {"tag": "Moderate Intent"},
                    {"tag": "High Intent"},
                ],
                "analytical_qualifications": [
                    {
                        "schema_version": 1,
                        "kind": "analytical_qualification",
                        "qualification_level": "moderate",
                        "countable": True,
                        "decision_mode": "deterministic",
                        "rule_version": "gulong_intent_v2_test",
                        "qualification_event_id": "aq_v1_0123456789abcdef01234567",
                        "event_identity": {
                            "event_id": "run-1_journey_payment_method_1",
                            "idempotency_key": "run-1_journey_payment_method_1",
                        },
                    }
                ],
            },
        ),
    ]
    clicks = []
    monkeypatch.setattr(release_matrix, "chat", lambda *args, **kwargs: responses[0])

    def fake_click(*args, **kwargs):
        clicks.append(kwargs["token"])
        return responses[len(clicks)]

    monkeypatch.setattr(release_matrix, "click", fake_click)

    result = release_matrix.run_product_location_journey(
        base_url="https://candidate.example",
        timeout_s=10,
        run_id="run-1",
        expected_release="candidate",
        feature_expectations=DEFAULT_FEATURE_EXPECTATIONS,
    )

    assert result["passed"] is True
    assert clicks == [
        "ps1|product",
        "ss1|schedule",
        "po1|pay-now",
        "pm1|card",
    ]
    location_outcome = next(
        item
        for item in result["feature_outcomes"]
        if item["feature"] == "location_choices"
    )
    assert location_outcome == {
        "feature": "location_choices",
        "expectation": "required_when_enabled",
        "status": "not_required_location_already_resolved",
        "token_present": False,
        "reason": "validated_schedule_surface_proves_location_resolution",
    }


def test_product_journey_types_schedule_after_known_location_prompt(
    monkeypatch,
) -> None:
    first = _safe_journey_response(
        token="ps1|product",
        caption="Select tire",
        tools=[{"name": "product_search", "status": "ok"}],
    )
    selected = _safe_journey_response(choice_type="product_selection")
    selected["response"] = {
        "bubble1": "Kailan niyo po gustong magpa-install?"
    }
    selected["debug"]["turn_trace"] = {
        "state_snapshots": [
            {
                "state_name": "latest_order_summary_snapshot_after_turn",
                "state_json": {
                    "fields": {
                        "Installation Area": "Dasmarinas City, Cavite",
                        "Schedule": "-",
                    }
                },
            }
        ]
    }
    schedule_surface = _safe_journey_response(
        token="ss1|schedule",
        caption="Tomorrow",
    )
    payment_option = _safe_journey_response(
        token="po1|pay-now",
        caption="Pay Now",
        choice_type="schedule_selection",
    )
    payment_method = _safe_journey_response(
        token="pm1|card",
        caption="Credit Card",
        choice_type="payment_option_selection",
    )
    completed = _safe_journey_response(
        choice_type="payment_method_selection",
        collected={
            "Payment option": "Pay Now",
            "Payment method": "Credit Card",
        },
        tagging_result={
            "tag_apply_skipped": True,
            "tags_to_add": [
                {"tag": "Moderate Intent"},
                {"tag": "High Intent"},
            ],
            "analytical_qualifications": [
                {
                    "schema_version": 1,
                    "kind": "analytical_qualification",
                    "qualification_level": "moderate",
                    "countable": True,
                    "decision_mode": "deterministic",
                    "rule_version": "gulong_intent_v2_test",
                    "qualification_event_id": "aq_v1_0123456789abcdef01234567",
                    "event_identity": {
                        "event_id": "run-1_journey_payment_method_1",
                        "idempotency_key": "run-1_journey_payment_method_1",
                    },
                }
            ],
        },
    )
    chat_responses = iter((first, schedule_surface))
    click_responses = iter((selected, payment_option, payment_method, completed))
    typed_messages = []

    def fake_chat(*args, **kwargs):
        typed_messages.append(kwargs["message"])
        return next(chat_responses)

    monkeypatch.setattr(release_matrix, "chat", fake_chat)
    monkeypatch.setattr(
        release_matrix,
        "click",
        lambda *args, **kwargs: next(click_responses),
    )

    result = release_matrix.run_product_location_journey(
        base_url="https://candidate.example",
        timeout_s=10,
        run_id="run-1",
        expected_release="candidate",
        feature_expectations=DEFAULT_FEATURE_EXPECTATIONS,
    )

    assert result["passed"] is True
    assert typed_messages[-1] == "Bukas po."
    assert [step["action"] for step in result["steps"]] == [
        "chat",
        "click_product",
        "chat_schedule",
        "click_schedule",
        "click_payment_option",
        "click_payment_method",
    ]
    location_outcome = next(
        item
        for item in result["feature_outcomes"]
        if item["feature"] == "location_choices"
    )
    assert location_outcome["reason"] == (
        "order_snapshot_and_schedule_request_prove_location_resolution"
    )


def test_empty_promo_catalog_is_explicitly_not_applicable(monkeypatch) -> None:
    first = _safe_journey_response(
        tools=[
            {
                "name": "search_promo_catalog",
                "status": "ok",
                "commercial_scope": {"allowed_promo_refs": []},
            }
        ]
    )
    monkeypatch.setattr(release_matrix, "chat", lambda *args, **kwargs: first)
    monkeypatch.setattr(
        release_matrix,
        "click",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("empty catalog must not be clicked")
        ),
    )

    result = release_matrix.run_promo_details_journey(
        base_url="https://candidate.example",
        timeout_s=10,
        run_id="run-1",
        expected_release="candidate",
        feature_expectations=DEFAULT_FEATURE_EXPECTATIONS,
    )

    assert result["passed"] is True
    assert result["feature_outcomes"] == [
        {
            "feature": "promo_guided_actions",
            "expectation": "not_applicable_when_unavailable",
            "status": "not_applicable",
            "token_present": False,
            "reason": "no_current_promo_refs",
        }
    ]


def test_missing_promo_scope_does_not_masquerade_as_unavailable(monkeypatch) -> None:
    first = _safe_journey_response(
        tools=[{"name": "search_promo_catalog", "status": "ok"}]
    )
    monkeypatch.setattr(release_matrix, "chat", lambda *args, **kwargs: first)

    result = release_matrix.run_promo_details_journey(
        base_url="https://candidate.example",
        timeout_s=10,
        run_id="run-1",
        expected_release="candidate",
        feature_expectations=DEFAULT_FEATURE_EXPECTATIONS,
    )

    assert result["passed"] is False
    assert result["failures"] == [
        "feature_unavailability_not_proven:promo_guided_actions"
    ]


def _rendered_promo_catalog_without_about_brand(*, complete: bool = True) -> dict:
    first = _safe_journey_response(
        tools=[
            {
                "name": "search_promo_catalog",
                "status": "ok",
                "commercial_scope": {"allowed_promo_refs": ["promo-1", "promo-2"]},
            }
        ]
    )
    first["promo_presentation"] = {"card_refs": ["promo-1", "promo-2"]}
    rendered_refs = ["promo-1", "promo-2"] if complete else ["promo-1"]
    first["content_messages"] = [
        {
            "type": "cards",
            "elements": [
                {
                    "buttons": [
                        {
                            "caption": "Find Tires",
                            "actions": [
                                {"type": "postback", "value": f"pc1|find|{ref}"}
                            ],
                        },
                        {
                            "caption": "Promo Details",
                            "actions": [
                                {"type": "postback", "value": f"pc1|details|{ref}"}
                            ],
                        },
                    ]
                }
                for ref in rendered_refs
            ],
        }
    ]
    return first


def test_about_brand_is_not_applicable_when_complete_current_cards_lack_action(
    monkeypatch,
) -> None:
    first = _rendered_promo_catalog_without_about_brand()
    monkeypatch.setattr(release_matrix, "chat", lambda *args, **kwargs: first)
    monkeypatch.setattr(
        release_matrix,
        "click",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("an unavailable action must not be clicked")
        ),
    )

    result = release_matrix.run_about_brand_journey(
        base_url="https://candidate.example",
        timeout_s=10,
        run_id="run-1",
        expected_release="candidate",
        feature_expectations=DEFAULT_FEATURE_EXPECTATIONS,
    )

    assert result["passed"] is True
    assert result["feature_outcomes"] == [
        {
            "feature": "promo_guided_actions",
            "expectation": "not_applicable_when_unavailable",
            "status": "not_applicable",
            "token_present": False,
            "reason": "rendered_current_promo_cards_lack_action",
        }
    ]


def test_about_brand_action_unavailability_requires_complete_rendered_cards(
    monkeypatch,
) -> None:
    first = _rendered_promo_catalog_without_about_brand(complete=False)
    monkeypatch.setattr(release_matrix, "chat", lambda *args, **kwargs: first)

    result = release_matrix.run_about_brand_journey(
        base_url="https://candidate.example",
        timeout_s=10,
        run_id="run-1",
        expected_release="candidate",
        feature_expectations=DEFAULT_FEATURE_EXPECTATIONS,
    )

    assert result["passed"] is False
    assert result["failures"] == [
        "feature_unavailability_not_proven:promo_guided_actions"
    ]


def test_intent_observability_contract_requires_tags_and_qualification_identity() -> (
    None
):
    response = {"tagging_result": {"tags_to_add": [{"tag": "Moderate Intent"}]}}

    assert release_matrix._intent_observability_failures(
        response,
        expected_tags=("Moderate Intent", "High Intent"),
    ) == [
        "missing_intent_trigger:High Intent",
        "missing_moderate_analytical_qualification",
    ]


def test_intent_observability_rejects_empty_or_unbound_identity() -> None:
    response = {
        "tagging_result": {
            "tags_to_add": [
                {"tag": "Moderate Intent"},
                {"tag": "High Intent"},
            ],
            "analytical_qualifications": [
                {
                    "schema_version": 1,
                    "kind": "analytical_qualification",
                    "qualification_level": "moderate",
                    "countable": True,
                    "decision_mode": "deterministic",
                    "rule_version": "gulong_intent_v2_test",
                    "qualification_event_id": "aq_v1_",
                    "event_identity": {},
                }
            ],
        }
    }

    assert release_matrix._intent_observability_failures(
        response,
        expected_tags=("Moderate Intent", "High Intent"),
        expected_event_id="expected-event",
    ) == [
        "invalid_analytical_qualification:qualification_event_id",
        "invalid_analytical_qualification:event_identity.event_id",
        "invalid_analytical_qualification:event_identity.idempotency_key",
        "analytical_qualification_event_identity_mismatch",
    ]
