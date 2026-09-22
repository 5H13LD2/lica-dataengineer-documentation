"""Tests for deterministic Runtime V7 promotion-health scoring."""

from copy import deepcopy

from runtime_v7.promotion_health_evaluator import (
    ALLOWED_OPERATIONAL_FUNNEL_ACTIONS,
    APPROVED_SCENARIO_DEFINITION_DIGESTS,
    APPROVED_OPERATIONAL_FUNNEL_DEFINITION_DIGESTS,
    ALLOWED_JOURNEY_ACTIONS,
    DEFAULT_HEALTH_POLICY,
    OPERATIONAL_FUNNEL_CONTRACT_SCHEMA_VERSION,
    OPERATIONAL_FUNNEL_CONTRACT_VERSION,
    REQUIRED_OPERATIONAL_FUNNEL_SCENARIOS_BY_TIER,
    REQUIRED_OPERATIONAL_FUNNEL_STAGES,
    REQUIRED_SCENARIOS_BY_TIER,
    SCENARIO_CONTRACT_SCHEMA_VERSION,
    SCENARIO_CONTRACT_VERSION,
    attach_artifact_integrity,
    canonical_equivalent,
    payment_authority_contract_failures,
    phrase_tolerant_fact_present,
    score_release_candidate,
    tool_argument_contract_failures,
    tool_argument_chain_contract_failures,
    tool_argument_chain_evidence,
)


def _response() -> dict:
    return {
        "_probe_http_status": 200,
        "_probe_elapsed_ms": 1200,
        "status": "success",
        "release_version": "candidate",
        "git_sha": "abc123",
        "service_environment": "staging",
        "_probe_model_usage_expectation": "required",
        "delivery_result": {"status": "skipped", "reason": "return_only"},
        "tagging_result": {
            "tags_to_add": [],
            "tag_apply_skipped": True,
            "tag_apply_skip_reason": "return_only",
        },
        "response": {
            "bubble1": (
                "Delivery is available in the Greater Manila Area through "
                "Lalamove and usually takes 7 to 10 days."
            )
        },
        "debug": {
            "turn_trace": {"component_spans": [{"component_type": "model_call"}]},
            "tool_calls": [
                {
                    "name": "answer_order_faq",
                    "status": "ok",
                    "latency_ms": 25,
                    "args": {
                        "requested_payment_method": "BPI 6-month 0%",
                        "requested_product_brand": "Yokohama",
                        "payment_option": "Pay Later",
                    },
                    "payment_scope": {
                        "requested_method": "BPI 6-mos Installment (0% interest)",
                        "requested_status": "supported",
                        "brand": "YOKOHAMA",
                        "brand_eligibility": "not_eligible",
                        "payment_option": "Pay Later",
                        "source": "gulong_checkout_metadata",
                    },
                    "authority": {
                        "source": "gulong_checkout_metadata",
                        "evidence_ref": "faq:order:order_how_do_i_pay",
                        "faq_id": "order_how_do_i_pay",
                    },
                }
            ],
            "commercial_payment_claims": [
                {
                    "method": "BPI 6-mos Installment (0% interest)",
                    "outcome": "not_eligible",
                    "brand": "YOKOHAMA",
                    "payment_option": "Pay Later",
                }
            ],
            "llm_usage_summary": {
                "prompt_tokens": 100,
                "cache_read_input_tokens": 40,
                "uncached_prompt_tokens": 60,
                "completion_tokens": 20,
                "reasoning_tokens": 0,
                "total_tokens": 120,
            },
            "runtime_phase_timings_ms": {
                "session_load": 10,
                "harness_run": 900,
                "handler_total": 1100,
            },
        },
    }


def _artifact() -> dict:
    artifact = {
        "schema_version": "runtime_v7_release_candidate_artifact_v1",
        "run_id": "run-1",
        "evaluation_profile": {
            "schema_version": "runtime_v7_release_candidate_matrix_v4",
            "tier": "smoke",
            "expected_release": "candidate",
            "expected_git_sha": "abc123",
            "expected_environment": "staging",
            "selected_case_ids": [
                "business_contact_grounded",
                "delivery_policy_grounded",
                "payment_yokohama_home_credit",
            ],
            "selected_journey_ids": [],
            "feature_expectations": {
                "promo_guided_actions": "not_applicable_when_unavailable",
            },
            "health_policy": dict(DEFAULT_HEALTH_POLICY),
        },
        "scenario_contract": {
            "schema_version": SCENARIO_CONTRACT_SCHEMA_VERSION,
            "contract_version": SCENARIO_CONTRACT_VERSION,
            "definition_digest": APPROVED_SCENARIO_DEFINITION_DIGESTS["smoke"],
            "required_case_ids": [
                "business_contact_grounded",
                "delivery_policy_grounded",
                "payment_yokohama_home_credit",
            ],
            "required_journey_ids": [],
        },
        "single_turn_cases": [
            {
                "case_id": case_id,
                "passed": True,
                "failures": [],
                "response": _response(),
            }
            for case_id in (
                "business_contact_grounded",
                "delivery_policy_grounded",
                "payment_yokohama_home_credit",
            )
        ],
        "journeys": [],
    }
    return attach_artifact_integrity(artifact)


def _promotion_artifact() -> dict:
    required = REQUIRED_SCENARIOS_BY_TIER["promotion"]
    cases = [
        {
            "case_id": case_id,
            "domain": "fixture",
            "passed": True,
            "failures": [],
            "response": _response(),
        }
        for case_id in required["cases"]
    ]
    journeys = [
        {
            "case_id": case_id,
            "domain": "fixture_journey",
            "passed": True,
            "failures": [],
            "steps": [
                {"action": action, "response": _response()}
                for action in ALLOWED_JOURNEY_ACTIONS[case_id][0]
            ],
        }
        for case_id in required["journeys"]
    ]
    for journey in journeys:
        for index, step in enumerate(journey["steps"], start=1):
            step["response"]["response"]["bubble1"] = (
                f"{journey['case_id']} step {index}"
            )
    operational_ids = REQUIRED_OPERATIONAL_FUNNEL_SCENARIOS_BY_TIER["promotion"]
    operational_rows = []
    for case_id in operational_ids:
        operational_rows.append(
            {
                "case_id": case_id,
                "domain": "size_brand_operational_funnel",
                "passed": True,
                "failures": [],
                "funnel_stages": {
                    stage: {
                        "applicable": True,
                        "passed": True,
                        "evidence": {"fixture": True},
                    }
                    for stage in REQUIRED_OPERATIONAL_FUNNEL_STAGES[case_id]
                },
                "steps": [
                    {"action": action, "response": _response()}
                    for action in ALLOWED_OPERATIONAL_FUNNEL_ACTIONS[case_id][0]
                ],
            }
        )
    artifact = {
        "schema_version": "runtime_v7_release_candidate_artifact_v1",
        "run_id": "promotion-run",
        "evaluation_profile": {
            "schema_version": "runtime_v7_release_candidate_matrix_v4",
            "tier": "promotion",
            "expected_release": "candidate",
            "expected_git_sha": "abc123",
            "expected_environment": "staging",
            "selected_case_ids": list(required["cases"]),
            "selected_journey_ids": list(required["journeys"]),
            "selected_operational_funnel_ids": list(operational_ids),
            "feature_expectations": {},
            "health_policy": dict(DEFAULT_HEALTH_POLICY),
        },
        "scenario_contract": {
            "schema_version": SCENARIO_CONTRACT_SCHEMA_VERSION,
            "contract_version": SCENARIO_CONTRACT_VERSION,
            "definition_digest": APPROVED_SCENARIO_DEFINITION_DIGESTS["promotion"],
            "required_case_ids": list(required["cases"]),
            "required_journey_ids": list(required["journeys"]),
        },
        "operational_funnel_contract": {
            "schema_version": OPERATIONAL_FUNNEL_CONTRACT_SCHEMA_VERSION,
            "contract_version": OPERATIONAL_FUNNEL_CONTRACT_VERSION,
            "definition_digest": APPROVED_OPERATIONAL_FUNNEL_DEFINITION_DIGESTS[
                "promotion"
            ],
            "required_scenario_ids": list(operational_ids),
        },
        "single_turn_cases": cases,
        "journeys": journeys,
        "operational_funnel_scenarios": operational_rows,
    }
    return attach_artifact_integrity(artifact)


def test_canonical_comparison_handles_payment_and_size_variants() -> None:
    assert canonical_equivalent(
        "BPI 6-month 0%",
        "BPI 6-mos Installment (0% interest)",
        kind="payment_method",
    )
    assert canonical_equivalent("195/60 R15", "195/60R15", kind="tire_size")


def test_phrase_tolerant_fact_uses_concepts_not_reference_sentence() -> None:
    fact = {
        "id": "lead_time",
        "any_of": ({"regex": r"7\s*(?:-|to|hanggang)\s*10\s*(?:days?|araw)"},),
    }

    assert phrase_tolerant_fact_present("Karaniwan ay 7 to 10 days po.", fact)
    assert phrase_tolerant_fact_present("Mga 7 hanggang 10 araw po.", fact)


def test_tool_argument_contract_uses_canonical_values() -> None:
    failures = tool_argument_contract_failures(
        [
            {
                "id": "scoped_payment",
                "tool": "answer_order_faq",
                "args": {
                    "requested_product_brand": {"equals": "YOKOHAMA", "kind": "brand"},
                    "payment_option": {"equals": "Pay Later", "kind": "payment_option"},
                },
            }
        ],
        _response(),
    )

    assert failures == []


def _chain_response() -> dict:
    response = _response()
    response["debug"]["tool_calls"][0].update(
        {
            "round": 1,
            "tool_call_id": "call_bpi_six",
        }
    )
    response["debug"]["tool_dedupe_events"] = []
    response["debug"]["turn_trace"] = {
        "component_spans": [
            {
                "component_type": "model_call",
                "round": 1,
                "tool_calls": [
                    {
                        "id": "call_bpi_six",
                        "name": "answer_order_faq",
                        "args": {
                            "requested_payment_method": "BPI 6mos 0%",
                            "requested_product_brand": "YOKOHAMA",
                            "payment_option": "Pay Later",
                        },
                    }
                ],
            }
        ]
    }
    return response


def _chain_contract() -> dict:
    return {
        "id": "yokohama_bpi_six",
        "tool": "answer_order_faq",
        "args": {
            "requested_payment_method": {
                "contains": "BPI 6",
                "kind": "payment_method",
            },
            "requested_product_brand": {"equals": "YOKOHAMA", "kind": "brand"},
            "payment_option": {"equals": "Pay Later", "kind": "payment_option"},
        },
    }


def test_tool_argument_chain_reaches_provider_with_same_call_identity() -> None:
    response = _chain_response()

    evidence = tool_argument_chain_evidence([_chain_contract()], response)

    assert evidence == [
        {
            "contract_id": "yokohama_bpi_six",
            "tool": "answer_order_faq",
            "required_matches": 1,
            "pre_hydration_matches": 1,
            "provider_execution_matches": 1,
            "equivalent_dedup_reuse": 0,
            "equivalent_dedup_reuse_allowed": True,
            "scope_changed_before_dedup": 0,
            "missing_call_identity": 0,
            "passed": True,
        }
    ]
    assert tool_argument_chain_contract_failures([_chain_contract()], response) == []


def test_tool_argument_chain_rejects_hydration_scope_corruption() -> None:
    response = _chain_response()
    response["debug"]["tool_calls"][0]["args"] = {
        "requested_payment_method": "Home Credit"
    }

    failures = tool_argument_chain_contract_failures([_chain_contract()], response)

    assert failures == ["tool_chain_provider_execution:yokohama_bpi_six:0<1"]


def test_tool_argument_chain_rejects_scope_change_before_deduplication() -> None:
    response = _chain_response()
    response["debug"]["tool_calls"] = []
    response["debug"]["tool_dedupe_events"] = [
        {
            "round": 1,
            "type": "duplicate_tool_call_reused",
            "name": "answer_order_faq",
            "tool_call_id": "call_bpi_six",
            "args": {"requested_payment_method": "Home Credit"},
        }
    ]

    failures = tool_argument_chain_contract_failures([_chain_contract()], response)

    assert failures == [
        "tool_chain_provider_execution:yokohama_bpi_six:0<1",
        "tool_chain_dedup_scope_changed:yokohama_bpi_six:1",
    ]


def test_tool_argument_chain_allows_equivalent_duplicate_reuse() -> None:
    response = _chain_response()
    duplicate = deepcopy(
        response["debug"]["turn_trace"]["component_spans"][0]["tool_calls"][0]
    )
    duplicate["id"] = "call_bpi_six_duplicate"
    response["debug"]["turn_trace"]["component_spans"][0]["tool_calls"].append(
        duplicate
    )
    response["debug"]["tool_dedupe_events"] = [
        {
            "round": 1,
            "type": "duplicate_tool_call_reused",
            "name": "answer_order_faq",
            "tool_call_id": "call_bpi_six_duplicate",
            "args": duplicate["args"],
        }
    ]

    evidence = tool_argument_chain_evidence([_chain_contract()], response)[0]

    assert evidence["pre_hydration_matches"] == 2
    assert evidence["provider_execution_matches"] == 1
    assert evidence["equivalent_dedup_reuse"] == 1
    assert evidence["passed"] is True


def test_tool_argument_chain_can_require_field_removal_after_hydration() -> None:
    response = _chain_response()
    model_args = response["debug"]["turn_trace"]["component_spans"][0]["tool_calls"][0][
        "args"
    ]
    model_args["requested_product_brand"] = "YOKOHAMA"
    response["debug"]["tool_calls"][0]["args"] = {
        "requested_payment_method": "BPI 6-month 0%"
    }
    contract = {
        "id": "unbranded_bpi_six",
        "tool": "answer_order_faq",
        "pre_args": {
            "requested_payment_method": {"contains": "BPI 6"},
        },
        "post_args": {
            "requested_payment_method": {"contains": "BPI 6"},
            "requested_product_brand": {"absent": True},
        },
    }

    assert tool_argument_chain_contract_failures([contract], response) == []


def test_payment_claim_must_match_provider_scope() -> None:
    response = _response()
    assert payment_authority_contract_failures(response) == []

    response["debug"]["commercial_payment_claims"][0]["outcome"] = "eligible"
    failures = payment_authority_contract_failures(response)
    assert failures[0].startswith("payment_claim_not_backed_by_authority:")


def test_not_brand_restricted_authority_maps_to_positive_claim() -> None:
    response = _response()
    response["debug"]["tool_calls"][0]["payment_scope"]["brand_eligibility"] = (
        "not_brand_restricted"
    )
    response["debug"]["commercial_payment_claims"][0]["outcome"] = "eligible"

    assert payment_authority_contract_failures(response) == []


def test_equivalent_payment_tool_scopes_do_not_inflate_claim_count() -> None:
    response = _response()
    duplicate = deepcopy(response["debug"]["tool_calls"][0])
    duplicate["payment_scope"]["brand"] = "yokohama"
    response["debug"]["tool_calls"].append(duplicate)

    assert payment_authority_contract_failures(response) == []


def test_distinct_payment_tool_scopes_each_require_a_typed_claim() -> None:
    response = _response()
    response["debug"]["tool_calls"].append(
        {
            "name": "answer_order_faq",
            "payment_scope": {
                "requested_method": "Home Credit",
                "requested_status": "unsupported",
                "brand": None,
                "brand_eligibility": None,
                "payment_option": None,
            },
            "authority": {
                "source": "gulong_checkout_metadata",
                "evidence_ref": "faq:order:order_how_do_i_pay",
            },
        }
    )

    failures = payment_authority_contract_failures(response)

    assert any(
        failure.startswith("payment_claim_not_backed_by_authority:")
        for failure in failures
    )
    assert "payment_claim_scope_count:1<2" in failures


def test_preverified_smoke_passes_without_claiming_promotion_approval() -> None:
    report = score_release_candidate(_artifact())

    assert report["mechanical"]["score_percent"] == 100.0
    assert report["grade"] == "green"
    assert report["promotion_status"] == "diagnostic_pass"
    assert report["technical"]["tokens"]["total_tokens"] == 360
    assert report["preverified_scenario_contract"]["status"] == "pass"
    assert report["artifact_integrity"]["status"] == "pass"


def test_partial_matrix_is_never_ready_for_promotion() -> None:
    artifact = _artifact()
    artifact["single_turn_cases"] = artifact["single_turn_cases"][:1]
    attach_artifact_integrity(artifact)
    report = score_release_candidate(artifact)

    assert report["grade"] == "red"
    assert "scenario_contract_case_set_incomplete" in report["blockers"]


def test_post_run_response_tampering_invalidates_artifact() -> None:
    artifact = _artifact()
    artifact["single_turn_cases"][0]["response"]["response"]["bubble1"] = "changed"
    report = score_release_candidate(artifact)

    assert report["grade"] == "red"
    assert "artifact_integrity_digest_mismatch" in report["blockers"]


def test_complete_promotion_contract_is_automatically_promotion_ready() -> None:
    report = score_release_candidate(_promotion_artifact())

    assert report["grade"] == "green"
    assert report["promotion_status"] == "ready_for_promotion"
    assert report["operational_funnel"]["status"] == "pass"
    assert report["operational_funnel"]["score_percent"] == 100.0


def test_operational_funnel_missing_stage_blocks_promotion() -> None:
    artifact = _promotion_artifact()
    row = artifact["operational_funnel_scenarios"][0]
    row["funnel_stages"].pop("canonical_location_captured")
    attach_artifact_integrity(artifact)

    report = score_release_candidate(artifact)

    assert report["grade"] == "red"
    assert (
        "operational_funnel_required_stage_missing:"
        "size_brand_typed_location_shortform:canonical_location_captured"
    ) in report["blockers"]


def test_operational_funnel_failed_province_only_path_blocks_promotion() -> None:
    artifact = _promotion_artifact()
    row = next(
        item
        for item in artifact["operational_funnel_scenarios"]
        if item["case_id"] == "size_brand_guided_location_choice"
    )
    row["passed"] = False
    row["failures"] = ["operational_stage_failed:guided_response_accepted"]
    row["funnel_stages"]["guided_response_accepted"] = {
        "applicable": True,
        "passed": False,
        "evidence": {
            "accepted_choice_type": "serviceable_province",
            "required_choice_type": "serviceable_city",
        },
    }
    attach_artifact_integrity(artifact)

    report = score_release_candidate(artifact)

    assert report["operational_funnel"]["status"] == "fail"
    assert (
        "operational_funnel_stage_failed:"
        "size_brand_guided_location_choice:guided_response_accepted"
    ) in report["blockers"]


def test_operational_rows_do_not_change_core_baseline_or_latency_denominators() -> None:
    artifact = _promotion_artifact()
    baseline = deepcopy(artifact)
    baseline["operational_funnel_scenarios"] = []
    baseline["evaluation_profile"]["selected_operational_funnel_ids"] = []
    baseline.pop("operational_funnel_contract")
    attach_artifact_integrity(baseline)

    report = score_release_candidate(artifact, baseline=baseline)

    core_response_count = len(
        list(REQUIRED_SCENARIOS_BY_TIER["promotion"]["cases"])
    ) + sum(
        len(ALLOWED_JOURNEY_ACTIONS[case_id][0])
        for case_id in REQUIRED_SCENARIOS_BY_TIER["promotion"]["journeys"]
    )
    assert report["technical"]["response_count"] == core_response_count
    assert report["baseline_comparison"]["status"] == "compatible"
    assert (
        report["metered_usage"]["total_tokens"]
        > report["technical"]["tokens"]["total_tokens"]
    )


def test_operational_latency_concern_marks_otherwise_green_gate_yellow() -> None:
    artifact = _promotion_artifact()
    for row in artifact["operational_funnel_scenarios"]:
        for step in row["steps"]:
            step["response"]["_probe_elapsed_ms"] = 50_000
    attach_artifact_integrity(artifact)

    report = score_release_candidate(artifact)

    assert report["grade"] == "yellow"
    assert report["promotion_status"] == "automated_gate_concern"
    assert "operational_funnel_p95_latency_ms:50000" in report["warnings"]


def test_empty_journey_evidence_cannot_pass_from_ids_alone() -> None:
    artifact = _promotion_artifact()
    artifact["journeys"][0]["steps"] = []
    attach_artifact_integrity(artifact)

    report = score_release_candidate(artifact)

    assert (
        "scenario_journey_actions_invalid:product_location_schedule_payment_journey"
        in report["blockers"]
    )


def test_missing_telemetry_marker_cannot_opt_out_of_usage() -> None:
    artifact = _promotion_artifact()
    artifact["single_turn_cases"][0]["response"].pop("_probe_model_usage_expectation")
    attach_artifact_integrity(artifact)

    report = score_release_candidate(artifact)

    assert any(
        item.startswith("telemetry_policy_missing:") for item in report["blockers"]
    )


def test_mixed_target_identity_blocks_promotion() -> None:
    artifact = _promotion_artifact()
    artifact["single_turn_cases"][0]["response"]["git_sha"] = "wrong"
    attach_artifact_integrity(artifact)

    report = score_release_candidate(artifact)

    assert "target_identity_mismatch:git_sha:1" in report["blockers"]


def test_missing_required_usage_telemetry_blocks_promotion() -> None:
    artifact = _artifact()
    artifact["single_turn_cases"][0]["response"]["debug"].pop("llm_usage_summary")
    attach_artifact_integrity(artifact)

    report = score_release_candidate(artifact)

    assert report["grade"] == "red"
    assert "missing_model_usage:1" in report["blockers"]


def test_unmetered_supplemental_model_call_blocks_promotion() -> None:
    artifact = _artifact()
    usage = artifact["single_turn_cases"][0]["response"]["debug"]["llm_usage_summary"]
    usage.update(
        {
            "llm_call_count": 2,
            "missing_usage_call_count": 1,
            "unmetered_retry_count": 0,
        }
    )
    attach_artifact_integrity(artifact)

    report = score_release_candidate(artifact)

    assert report["grade"] == "red"
    assert "missing_model_usage:1" in report["blockers"]


def test_cross_turn_repeated_bubble_is_not_a_duplicate_presentation_failure() -> None:
    artifact = _promotion_artifact()
    journey = artifact["journeys"][0]
    repeated = "Please send the remaining contact details."
    journey["steps"][0]["response"]["response"]["bubble1"] = repeated
    journey["steps"][1]["response"]["response"]["bubble1"] = repeated
    attach_artifact_integrity(artifact)

    report = score_release_candidate(artifact)

    concerns = [
        item
        for item in report["cs_structural_proxy"]["concerns"]
        if item["case_id"] == journey["case_id"]
    ]
    assert concerns == []


def test_same_turn_repeated_bubble_remains_a_structural_concern() -> None:
    artifact = _promotion_artifact()
    case = artifact["single_turn_cases"][0]
    repeated = case["response"]["response"]["bubble1"]
    case["response"]["response"]["bubble2"] = repeated
    attach_artifact_integrity(artifact)

    report = score_release_candidate(artifact)

    concerns = [
        item
        for item in report["cs_structural_proxy"]["concerns"]
        if item["case_id"] == case["case_id"]
    ]
    assert {item["dimension"] for item in concerns} == {
        "presentation",
        "consistency",
    }


def test_baseline_comparison_fails_closed_for_different_cohort() -> None:
    artifact = _artifact()
    baseline = deepcopy(artifact)
    baseline["evaluation_profile"]["tier"] = "promotion"
    attach_artifact_integrity(baseline)

    report = score_release_candidate(artifact, baseline=baseline)

    assert report["baseline_comparison"]["status"] == "inconclusive"
    assert "tier" in report["baseline_comparison"]["mismatched_fields"]


def test_baseline_comparison_fails_closed_for_feature_profile_change() -> None:
    artifact = _artifact()
    baseline = deepcopy(artifact)
    baseline["evaluation_profile"]["feature_expectations"] = {
        "promo_guided_actions": "forbidden_when_disabled",
    }
    attach_artifact_integrity(baseline)

    report = score_release_candidate(artifact, baseline=baseline)

    assert report["baseline_comparison"]["status"] == "inconclusive"
    assert "feature_expectations" in report["baseline_comparison"]["mismatched_fields"]


def test_baseline_comparison_accepts_only_approved_contract_bridge() -> None:
    artifact = _promotion_artifact()
    baseline = deepcopy(artifact)
    baseline["scenario_contract"]["contract_version"] = "2026-09-11.4"
    baseline["scenario_contract"]["definition_digest"] = (
        "5b803facd63ed902e01a3f81172137dff20e23c63974cde7d0bf342dc8d39ddf"
    )
    attach_artifact_integrity(baseline)

    report = score_release_candidate(artifact, baseline=baseline)
    comparison = report["baseline_comparison"]

    assert comparison["status"] == "compatible"
    assert comparison["contract_compatibility_bridge"] == {
        "status": "applied",
        "scope": "cost_and_latency_comparison_only",
        "from_contract_version": "2026-09-11.4",
        "from_definition_digest": (
            "5b803facd63ed902e01a3f81172137dff20e23c63974cde7d0bf342dc8d39ddf"
        ),
        "to_contract_version": SCENARIO_CONTRACT_VERSION,
        "to_definition_digest": APPROVED_SCENARIO_DEFINITION_DIGESTS["promotion"],
    }

    baseline["scenario_contract"]["definition_digest"] = "unapproved"
    attach_artifact_integrity(baseline)
    comparison = score_release_candidate(
        artifact,
        baseline=baseline,
    )["baseline_comparison"]
    assert comparison["status"] == "inconclusive"
    assert "scenario_contract.definition_digest" in comparison["mismatched_fields"]


def test_baseline_comparison_accepts_immediately_previous_contract() -> None:
    artifact = _promotion_artifact()
    baseline = deepcopy(artifact)
    baseline["scenario_contract"]["contract_version"] = "2026-09-13.1"
    baseline["scenario_contract"]["definition_digest"] = (
        "59455de47429e53e92726b035f456c37e29f0d957dfdffadf225793750cc90ef"
    )
    attach_artifact_integrity(baseline)

    comparison = score_release_candidate(
        artifact,
        baseline=baseline,
    )["baseline_comparison"]

    assert comparison["status"] == "compatible"
    assert comparison["contract_compatibility_bridge"]["from_contract_version"] == (
        "2026-09-13.1"
    )


def test_baseline_contract_bridge_still_requires_same_scenario_cohort() -> None:
    artifact = _promotion_artifact()
    baseline = deepcopy(artifact)
    baseline["scenario_contract"]["contract_version"] = "2026-09-11.4"
    baseline["scenario_contract"]["definition_digest"] = (
        "5b803facd63ed902e01a3f81172137dff20e23c63974cde7d0bf342dc8d39ddf"
    )
    baseline["scenario_contract"]["required_case_ids"] = ["different"]
    attach_artifact_integrity(baseline)

    comparison = score_release_candidate(
        artifact,
        baseline=baseline,
    )["baseline_comparison"]

    assert comparison["status"] == "inconclusive"
    assert "scenario_contract.required_case_ids" in comparison["mismatched_fields"]


def test_baseline_cost_comparison_matches_journey_actions_instead_of_zero_filling() -> (
    None
):
    artifact = _promotion_artifact()
    baseline = deepcopy(artifact)
    baseline["journeys"][0]["steps"] = baseline["journeys"][0]["steps"][:2]
    for step in artifact["journeys"][0]["steps"][2:]:
        step["response"]["debug"]["llm_usage_summary"] = {
            "prompt_tokens": 9_000,
            "cache_read_input_tokens": 0,
            "uncached_prompt_tokens": 9_000,
            "completion_tokens": 1_000,
            "reasoning_tokens": 0,
            "total_tokens": 10_000,
        }
    attach_artifact_integrity(artifact)
    attach_artifact_integrity(baseline)

    report = score_release_candidate(artifact, baseline=baseline)
    comparison = report["baseline_comparison"]

    assert comparison["status"] == "compatible"
    assert comparison["deltas"]["total_tokens_percent"] == 0.0
    assert comparison["aggregate_observed_deltas"]["total_tokens_percent"] > 25
    assert len(comparison["comparison_scope"]["candidate_only_actions"]) == 3
    assert not any(
        item.startswith("total_token_regression_percent:")
        for item in report["blockers"]
    )


def test_baseline_cost_comparison_excludes_missing_usage_with_coverage() -> None:
    artifact = _promotion_artifact()
    baseline = deepcopy(artifact)
    baseline["single_turn_cases"][0]["response"]["debug"].pop("llm_usage_summary")
    attach_artifact_integrity(baseline)

    report = score_release_candidate(artifact, baseline=baseline)
    scope = report["baseline_comparison"]["comparison_scope"]

    assert report["baseline_comparison"]["status"] == "compatible"
    assert scope["matched_baseline_coverage_percent"] >= 80
    assert len(scope["usage_excluded_actions"]) == 1


def test_required_baseline_fails_closed_below_matched_action_coverage() -> None:
    artifact = _promotion_artifact()
    artifact["evaluation_profile"]["require_compatible_baseline"] = True
    baseline = deepcopy(artifact)
    for row in baseline["single_turn_cases"][:6]:
        row["response"]["debug"].pop("llm_usage_summary")
    attach_artifact_integrity(artifact)
    attach_artifact_integrity(baseline)

    report = score_release_candidate(artifact, baseline=baseline)

    assert report["baseline_comparison"]["status"] == "inconclusive"
    assert report["baseline_comparison"]["reason"] == (
        "baseline_action_coverage_below_minimum"
    )
    assert "baseline:inconclusive" in report["blockers"]


def test_mutating_tool_is_a_hard_blocker() -> None:
    artifact = _artifact()
    artifact["single_turn_cases"][0]["response"]["debug"]["tool_calls"].append(
        {"name": "submit_order", "status": "ok"}
    )

    report = score_release_candidate(artifact)

    assert report["grade"] == "red"
    assert "mutating_tools:1" in report["blockers"]


def test_required_baseline_fails_closed_when_missing() -> None:
    artifact = _artifact()
    artifact["evaluation_profile"]["require_compatible_baseline"] = True

    report = score_release_candidate(artifact)

    assert report["grade"] == "red"
    assert "baseline:not_provided" in report["blockers"]


def test_provisional_p95_latency_policy_can_block_promotion() -> None:
    artifact = _artifact()
    artifact["single_turn_cases"][0]["response"]["_probe_elapsed_ms"] = 95_001

    report = score_release_candidate(artifact)

    assert report["grade"] == "red"
    assert "p95_latency_ms:95001" in report["blockers"]


def test_provisional_absolute_limits_match_approved_gate() -> None:
    assert DEFAULT_HEALTH_POLICY["latency_p95_fail_ms"] == 95_000
    assert DEFAULT_HEALTH_POLICY["max_total_tokens"] == 2_000_000
    assert DEFAULT_HEALTH_POLICY["max_operational_funnel_tokens"] == 1_200_000


def test_legacy_artifact_policy_inherits_the_separate_operational_cap() -> None:
    artifact = _artifact()
    artifact["evaluation_profile"]["health_policy"].pop(
        "max_operational_funnel_tokens"
    )
    attach_artifact_integrity(artifact)

    report = score_release_candidate(artifact)

    assert report["preverified_scenario_contract"]["status"] == "pass"
    assert report["health_policy"]["max_operational_funnel_tokens"] == 1_200_000


def test_provisional_p95_latency_limit_is_inclusive() -> None:
    artifact = _artifact()
    artifact["single_turn_cases"][0]["response"]["_probe_elapsed_ms"] = 95_000
    attach_artifact_integrity(artifact)

    report = score_release_candidate(artifact)

    assert "p95_latency_ms:95000" not in report["blockers"]
    assert "p95_latency_ms:95000" in report["warnings"]


def test_provisional_total_token_limit_is_inclusive_and_blocks_above_limit() -> None:
    artifact = _artifact()
    for case in artifact["single_turn_cases"]:
        usage = case["response"]["debug"]["llm_usage_summary"]
        usage.update(
            {
                "prompt_tokens": 0,
                "cache_read_input_tokens": 0,
                "uncached_prompt_tokens": 0,
                "completion_tokens": 0,
                "reasoning_tokens": 0,
                "total_tokens": 0,
            }
        )
    artifact["single_turn_cases"][0]["response"]["debug"]["llm_usage_summary"][
        "total_tokens"
    ] = 2_000_000
    attach_artifact_integrity(artifact)

    at_limit = score_release_candidate(artifact)

    assert not any(
        blocker.startswith("total_token_budget:") for blocker in at_limit["blockers"]
    )

    artifact["single_turn_cases"][0]["response"]["debug"]["llm_usage_summary"][
        "total_tokens"
    ] = 2_000_001
    attach_artifact_integrity(artifact)

    above_limit = score_release_candidate(artifact)

    assert "total_token_budget:2000001>2000000" in above_limit["blockers"]


def test_operational_funnel_has_a_separate_cap_and_combined_usage_report() -> None:
    artifact = _promotion_artifact()
    for row in [
        *artifact["single_turn_cases"],
        *artifact["journeys"],
        *artifact["operational_funnel_scenarios"],
    ]:
        for response in [
            row.get("response"),
            *(step.get("response") for step in row.get("steps") or []),
        ]:
            if not isinstance(response, dict):
                continue
            response["debug"]["llm_usage_summary"].update(
                {
                    "prompt_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "uncached_prompt_tokens": 0,
                    "completion_tokens": 0,
                    "reasoning_tokens": 0,
                    "total_tokens": 0,
                }
            )
    artifact["single_turn_cases"][0]["response"]["debug"]["llm_usage_summary"][
        "total_tokens"
    ] = 2_000_000
    artifact["operational_funnel_scenarios"][0]["steps"][0]["response"]["debug"][
        "llm_usage_summary"
    ]["total_tokens"] = 1_200_000
    attach_artifact_integrity(artifact)

    at_limits = score_release_candidate(artifact)

    assert not any("token_budget:" in blocker for blocker in at_limits["blockers"])
    assert at_limits["metered_usage"] == {
        "scope": "core_plus_operational_funnel",
        "core": {
            "model_call_count": at_limits["metered_usage"]["core"]["model_call_count"],
            "total_tokens": 2_000_000,
            "max_total_tokens": 2_000_000,
        },
        "operational_funnel": {
            "model_call_count": at_limits["metered_usage"]["operational_funnel"]["model_call_count"],
            "total_tokens": 1_200_000,
            "max_total_tokens": 1_200_000,
        },
        "total_tokens": 3_200_000,
        "model_call_count": at_limits["metered_usage"]["model_call_count"],
    }

    artifact["operational_funnel_scenarios"][0]["steps"][0]["response"]["debug"][
        "llm_usage_summary"
    ]["total_tokens"] = 1_200_001
    attach_artifact_integrity(artifact)

    above_operational_limit = score_release_candidate(artifact)

    assert "operational_funnel_token_budget:1200001>1200000" in above_operational_limit[
        "blockers"
    ]


def test_technical_health_rolls_up_runtime_and_tool_latency() -> None:
    report = score_release_candidate(_artifact())
    technical = report["technical"]

    assert technical["runtime_phase_latency_ms"]["handler_total"] == {
        "count": 3,
        "p50": 1100,
        "p95": 1100,
        "max": 1100,
    }
    assert technical["client_transport_overhead_ms"]["p95"] == 100
    assert technical["tool_latency_ms"]["by_tool"]["answer_order_faq"]["p95"] == 25


def test_missing_runtime_phase_or_tool_latency_blocks_promotion() -> None:
    artifact = _artifact()
    artifact["single_turn_cases"][0]["response"]["debug"].pop(
        "runtime_phase_timings_ms"
    )
    artifact["single_turn_cases"][1]["response"]["debug"]["tool_calls"][0].pop(
        "latency_ms"
    )
    attach_artifact_integrity(artifact)

    report = score_release_candidate(artifact)

    assert "missing_runtime_phase_timing:1" in report["blockers"]
    assert "missing_tool_latency:1" in report["blockers"]
