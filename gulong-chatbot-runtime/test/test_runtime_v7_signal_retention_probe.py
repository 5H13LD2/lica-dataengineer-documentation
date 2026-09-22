"""Focused offline checks for the fixed-corpus signal-retention probe."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime_v7.state_signal_model import BACKGROUND_SIGNAL_EXTRACTOR_SYSTEM_PROMPT
from scripts.runtime_v7_signal_retention_probe import (
    REQUIRED_COVERAGE_DIMENSIONS,
    SignalRetentionPackError,
    build_arg_parser,
    evaluate_expectations,
    load_pack,
    render_markdown,
    run_probe,
    validate_pack,
    write_artifacts,
)


PACK_PATH = Path(__file__).resolve().parents[1] / "test_packs" / "runtime_v7_signal_retention_probe.json"


class _FakeSignalClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def extract_background_signals(self, *, system_prompt, user_prompt, metadata=None):
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt, "metadata": metadata or {}})
        response = self.responses.pop(0) if self.responses else {"candidates": []}
        return {
            "content": json.dumps(response, ensure_ascii=False),
            "usage": {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16},
            "cache_usage": {"cache_read_input_tokens": 0},
            "latency_ms": 3,
        }


def _candidate(key, value, *, relation="asserted"):
    return {
        "key": key,
        "value": value,
        "source": "latest_user_message",
        "confidence": "high",
        "relation": relation,
        "evidence": str(value),
    }


def _small_pack():
    return {
        "pack_id": "offline_signal_retention_fixture",
        "coverage_dimensions": sorted(REQUIRED_COVERAGE_DIMENSIONS),
        "scenarios": [
            {
                "id": "offline_one",
                "title": "offline",
                "tags": ["offline"],
                "min_interruptions": 1,
                "variation_dimensions": {"tire_size": "175/65R14", "brand": "Yokohama"},
                "turns": [
                    {
                        "id": "t1",
                        "message": "175/65R14 Yokohama",
                        "required_durable_signals": [
                            {"key": "tire_size", "value": "175/65R14"},
                            {"key": "preferred_brands", "value": "YOKOHAMA"},
                        ],
                    },
                    {
                        "id": "t2",
                        "message": "May BPI installment ba?",
                        "forbidden_durable_signals": [{"key": "bank", "value": "BPI"}],
                    },
                ],
                "final_required_durable_signals": [{"key": "tire_size", "value": "175/65R14"}],
            }
        ],
    }


def test_pack_loads_and_declares_all_required_dimensions():
    pack = load_pack(PACK_PATH)

    assert pack["pack_id"] == "runtime_v7_signal_retention_probe_v1"
    assert {item["id"] for item in pack["scenarios"]} == {
        "sr01_honda_yokohama",
        "sr02_toyota_bridgestone",
        "sr03_xpander_delivery",
        "sr04_navara_home_service",
        "sr05_partial_size_correction",
        "sr06_payment_document_boundary",
        "sr07_generic_payment_and_receipt",
    }
    assert set(pack["coverage_dimensions"]) >= REQUIRED_COVERAGE_DIMENSIONS
    assert all(len(item["turns"]) - 1 >= item["min_interruptions"] for item in pack["scenarios"])


def test_partial_size_reconstruction_contract_is_narrow_and_ambiguity_safe():
    prompt = " ".join(BACKGROUND_SIGNAL_EXTRACTOR_SYSTEM_PROMPT.split())

    assert "exactly one current complete tire_size" in prompt
    assert "multiple prior tire sizes are current" in prompt
    assert "emit no reconstructed tire_size" in prompt
    assert "Do not generalize component-splicing" in prompt


def test_explicit_service_survives_unknown_size_location_or_address():
    prompt = " ".join(BACKGROUND_SIGNAL_EXTRACTOR_SYSTEM_PROMPT.split())

    assert "installation-coverage inquiry still emits service_type=installation" in prompt
    assert "omit the unknown tire_size/location" in prompt
    assert "service_type=delivery without inventing a location or delivery_address" in prompt


def test_pack_validator_rejects_missing_turn_message_and_coverage():
    pack = _small_pack()
    pack["coverage_dimensions"] = ["tire_size"]
    with pytest.raises(SignalRetentionPackError, match="coverage dimensions"):
        validate_pack(pack)

    pack = _small_pack()
    pack["scenarios"][0]["turns"][0].pop("message")
    with pytest.raises(SignalRetentionPackError, match="requires message"):
        validate_pack(pack)


def test_expectation_report_distinguishes_required_and_forbidden_values():
    state = [
        {"key": "tire_size", "value": "175/65R14"},
        {"key": "preferred_brands", "value": "YOKOHAMA, MICHELIN"},
    ]

    result = evaluate_expectations(
        state,
        required=["tire_size=175/65R14", {"key": "preferred_brands", "value": "MICHELIN"}],
        forbidden=["tire_size=195/65R15"],
    )

    assert result["passed"] is True
    assert all(item["passed"] for item in result["required"])
    assert result["forbidden"][0]["passed"] is True


def test_expectation_report_does_not_split_composite_location_on_comma():
    result = evaluate_expectations(
        [{"key": "location", "value": "Imus, Cavite"}],
        required=[{"key": "location", "value": "Imus, Cavite"}],
        forbidden=[{"key": "location", "value": "Cavite"}],
    )

    assert result["passed"] is True


def test_offline_probe_writes_artifact_first_and_records_usage_latency_state(tmp_path):
    pack = _small_pack()
    fake = _FakeSignalClient(
        [
            {"candidates": [_candidate("tire_size", "175/65R14"), _candidate("preferred_brands", "Yokohama")]},
            {
                "candidates": [
                    _candidate("bank", "BPI", relation="question_only"),
                ]
            },
        ]
    )

    payload = run_probe(
        pack,
        model_client=fake,
        max_model_calls_run=2,
        model_retry_attempts=0,
    )
    artifacts = write_artifacts(payload, tmp_path)

    assert payload["aborted"] is False
    assert payload["guard"]["model_calls_run"] == 2
    assert payload["scenarios"][0]["passed"] is True
    assert payload["scenarios"][0]["final_durable_state"]
    turn = payload["scenarios"][0]["turns"][0]
    assert turn["extraction"]["status"] == "ok"
    assert turn["extraction"]["attempts"] == 1
    assert turn["extraction"]["usage"]["total_tokens"] == 16
    assert turn["extraction"]["model_latency_ms"] == 3
    assert artifacts["json"].exists()
    assert artifacts["markdown"].exists()
    loaded = json.loads(artifacts["json"].read_text(encoding="utf-8"))
    assert loaded["scenarios"][0]["final_durable_state"] == payload["scenarios"][0]["final_durable_state"]
    assert "Final durable state" in artifacts["markdown"].read_text(encoding="utf-8")


def test_probe_hard_call_cap_preserves_completed_turns_and_marks_abort():
    pack = _small_pack()
    fake = _FakeSignalClient(
        [
            {"candidates": [_candidate("tire_size", "175/65R14")]},
            {"candidates": []},
        ]
    )

    payload = run_probe(pack, model_client=fake, max_model_calls_run=1)

    assert payload["aborted"] is True
    assert payload["guard"]["model_calls_run"] == 1
    assert payload["scenario_count"] == 1
    assert payload["scenarios"][0]["aborted"] is True
    assert payload["scenarios"][0]["turn_count"] == 1
    assert payload["scenarios"][0]["final_durable_state"][0]["value"] == "175/65R14"


def test_default_retry_attempts_is_zero_and_markdown_is_concise():
    args = build_arg_parser().parse_args([])

    assert args.model_retry_attempts == 0
    assert args.max_model_calls_run == 60
    markdown = render_markdown(
        {
            "pack_id": "fixture",
            "run_id": "run",
            "scenario_count": 0,
            "guard": {"model_calls_run": 0, "max_model_calls_run": 1},
            "scenarios": [],
            "aborted": False,
        }
    )
    assert "Background Signal Retention Probe" in markdown
    assert "| Scenario | Turns | Calls | Result | Failures |" in markdown
