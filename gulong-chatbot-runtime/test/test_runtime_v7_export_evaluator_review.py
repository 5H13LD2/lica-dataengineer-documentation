"""Tests for data-minimized external evaluator review bundles."""

from copy import deepcopy

import pytest

from runtime_v7.promotion_health_evaluator import (
    APPROVED_SCENARIO_DEFINITION_DIGESTS,
    DEFAULT_HEALTH_POLICY,
    SCENARIO_CONTRACT_SCHEMA_VERSION,
    SCENARIO_CONTRACT_VERSION,
    attach_artifact_integrity,
    score_release_candidate,
)
from scripts.runtime_v7_export_evaluator_review import (
    build_review_bundle,
    review_output_dir,
)


def _artifact() -> dict:
    response = {
        "request_id": "secret-request",
        "_probe_http_status": 200,
        "_probe_elapsed_ms": 100,
        "_probe_model_usage_expectation": "required",
        "status": "success",
        "release_version": "candidate",
        "git_sha": "abc123",
        "service_environment": "staging",
        "response": {"bubble1": "Available po."},
        "content_messages": [
            {
                "type": "buttons",
                "text": "Available po.",
                "buttons": [
                    {
                        "caption": "Select",
                        "actions": [
                            {
                                "type": "postback",
                                "value": "secret-action-token",
                                "url": "https://private.example",
                            }
                        ],
                    }
                ],
            }
        ],
        "debug": {
            "turn_trace": {"component_spans": [{"component_type": "model_call"}]},
            "tool_calls": [
                {
                    "name": "product_search",
                    "status": "ok",
                    "latency_ms": 25,
                    "args": {"secret": "do-not-export"},
                    "result": {"secret": "do-not-export"},
                }
            ],
            "llm_usage_summary": {
                "prompt_tokens": 10,
                "cache_read_input_tokens": 4,
                "uncached_prompt_tokens": 6,
                "completion_tokens": 5,
                "reasoning_tokens": 0,
                "total_tokens": 15,
            },
            "runtime_phase_timings_ms": {
                "harness_run": 60,
                "handler_total": 80,
            },
        },
    }
    rows = [
        {
            "case_id": case_id,
            "domain": "fixture",
            "message": "Customer prompt",
            "passed": True,
            "failures": [],
            "user_id": "secret-user",
            "response": deepcopy(response),
        }
        for case_id in (
            "business_contact_grounded",
            "delivery_policy_grounded",
            "payment_yokohama_home_credit",
        )
    ]
    artifact = {
        "schema_version": "runtime_v7_release_candidate_artifact_v1",
        "run_id": "run-1",
        "evaluation_profile": {
            "schema_version": "runtime_v7_release_candidate_matrix_v4",
            "tier": "smoke",
            "expected_release": "candidate",
            "expected_git_sha": "abc123",
            "expected_environment": "staging",
            "selected_case_ids": [row["case_id"] for row in rows],
            "selected_journey_ids": [],
            "feature_expectations": {},
            "health_policy": dict(DEFAULT_HEALTH_POLICY),
        },
        "scenario_contract": {
            "schema_version": SCENARIO_CONTRACT_SCHEMA_VERSION,
            "contract_version": SCENARIO_CONTRACT_VERSION,
            "definition_digest": APPROVED_SCENARIO_DEFINITION_DIGESTS["smoke"],
            "required_case_ids": [row["case_id"] for row in rows],
            "required_journey_ids": [],
        },
        "single_turn_cases": rows,
        "journeys": [],
    }
    attach_artifact_integrity(artifact)
    artifact["promotion_health"] = score_release_candidate(artifact)
    return artifact


def test_review_bundle_retains_visible_evidence_but_removes_private_debug() -> None:
    bundle = build_review_bundle(_artifact())
    serialized = str(bundle)

    assert bundle["single_turn_cases"][0]["customer_message"] == "Customer prompt"
    assert bundle["single_turn_cases"][0]["response"]["bubbles"] == ["Available po."]
    assert bundle["single_turn_cases"][0]["response"]["tools"] == [
        {"name": "product_search", "status": "ok"}
    ]
    assert "secret-user" not in serialized
    assert "secret-request" not in serialized
    assert "do-not-export" not in serialized
    assert "secret-action-token" not in serialized
    assert "private.example" not in serialized


def test_review_bundle_recomputes_instead_of_copying_stored_green() -> None:
    artifact = _artifact()
    artifact["promotion_health"] = {
        "grade": "green",
        "promotion_status": "ready_for_promotion",
    }

    bundle = build_review_bundle(artifact)

    assert bundle["promotion_health"]["promotion_status"] == "diagnostic_pass"


def test_review_bundle_includes_redacted_operational_funnel_evidence() -> None:
    artifact = _artifact()
    response = deepcopy(artifact["single_turn_cases"][0]["response"])
    artifact["operational_funnel_scenarios"] = [
        {
            "case_id": "synthetic_funnel_fixture",
            "domain": "size_brand_operational_funnel",
            "variation_tags": ["typed_location"],
            "expected_contract": {"provenance": "privacy_safe_fixture"},
            "passed": True,
            "failures": [],
            "funnel_stages": {
                "canonical_location_captured": {
                    "applicable": True,
                    "passed": True,
                    "evidence": {
                        "signal_evidence": {
                            "ledger_present": True,
                            "keys": ["location"],
                            "sources_by_key": {"location": ["latest_user_message"]},
                            "raw_value": "secret-location-value",
                        }
                    },
                }
            },
            "steps": [
                {
                    "action": "chat",
                    "message": "Synthetic customer input",
                    "response": response,
                }
            ],
        }
    ]
    attach_artifact_integrity(artifact)

    bundle = build_review_bundle(artifact)
    serialized = str(bundle)

    row = bundle["operational_funnel_scenarios"][0]
    assert row["funnel_stages"]["canonical_location_captured"]["passed"] is True
    assert row["steps"][0]["response"]["bubbles"] == ["Available po."]
    assert "secret-location-value" not in serialized


def test_review_bundle_rejects_modified_source_artifact() -> None:
    artifact = _artifact()
    artifact["single_turn_cases"][0]["response"]["response"]["bubble1"] = "changed"

    with pytest.raises(ValueError, match="integrity"):
        build_review_bundle(artifact)


def test_review_output_dir_rejects_path_escape(tmp_path) -> None:
    with pytest.raises(ValueError, match="unsafe run_id"):
        review_output_dir(tmp_path, "../escaped")
