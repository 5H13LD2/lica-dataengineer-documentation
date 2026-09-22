"""Tests for the isolated Runtime V7 Firestore persistence benchmark."""

import pytest

from scripts.runtime_v7_firestore_persistence_benchmark import (
    _comparison,
    _latency_summary,
    _payload_profile,
    _write_candidate,
    _validate_isolated_targets,
)


def test_benchmark_target_guard_rejects_serving_collections() -> None:
    with pytest.raises(ValueError, match="contain 'benchmark'"):
        _validate_isolated_targets(
            source_users_collection="users_test",
            source_sessions_subcollection="sessions_test",
            target_users_collection="users",
            target_session_groups=("sessions_indexed", "sessions_exempt"),
        )


def test_benchmark_target_guard_accepts_distinct_isolated_groups() -> None:
    _validate_isolated_targets(
        source_users_collection="users_test",
        source_sessions_subcollection="sessions_test",
        target_users_collection="users_persistence_benchmark_v1",
        target_session_groups=(
            "sessions_persist_benchmark_indexed_v1",
            "sessions_persist_benchmark_state_exempt_v1",
        ),
    )


def test_payload_profile_attributes_nested_state_without_raw_values() -> None:
    payload = {
        "messages": [{"text": "hello"}],
        "strategy_state": {
            "runtime_v7": {
                "product_observations": [{"large": "x" * 100}],
                "recent_turns": [{"text": "hello"}],
            },
            "inbound_events_v1": [{"event_id": "evt-1"}],
        },
    }

    profile = _payload_profile(payload)

    assert profile["document_json_bytes"] > profile["strategy_state_json_bytes"]
    assert profile["strategy_state_fields"][0]["field"] == "runtime_v7"
    assert profile["runtime_v7_largest_fields"][0]["field"] == (
        "product_observations"
    )
    assert "large" not in profile


def test_latency_summary_and_comparison_use_nearest_rank_p95() -> None:
    indexed = {"measured": _latency_summary([100, 200, 300, 400])}
    exempt = {"measured": _latency_summary([50, 100, 150, 200])}

    assert indexed["measured"]["p50_ms"] == 250.0
    assert indexed["measured"]["p95_ms"] == 400.0
    assert _comparison(indexed, exempt) == {
        "p50_reduction_percent": 50.0,
        "p95_reduction_percent": 50.0,
        "indexed_to_exempt_p50_ratio": 2.0,
        "indexed_to_exempt_p95_ratio": 2.0,
    }


def test_strategy_leaf_toggle_forces_nested_changes_without_mutating_source() -> None:
    source = {
        "strategy_state": {
            "runtime_v7": {
                "text": "hello",
                "count": 2,
                "enabled": True,
                "items": ["one", None],
            }
        }
    }

    stable, stable_changes = _write_candidate(
        source,
        iteration=2,
        mutation_mode="strategy_leaf_toggle",
    )
    toggled, toggled_changes = _write_candidate(
        source,
        iteration=3,
        mutation_mode="strategy_leaf_toggle",
    )

    assert stable_changes == 0
    assert toggled_changes == 5
    assert toggled["strategy_state"]["runtime_v7"] == {
        "text": "hello~",
        "count": 3,
        "enabled": False,
        "items": ["one~", "~"],
    }
    assert source["strategy_state"]["runtime_v7"]["text"] == "hello"
