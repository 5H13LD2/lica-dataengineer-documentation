"""
Runtime analytics schemas for BigQuery.

These schemas favor flexibility by using JSON fields for nested payloads.
"""

from __future__ import annotations

from typing import Dict, List


def _runtime_metadata_schema() -> List[Dict[str, str]]:
    return [
        {"name": "service_environment", "type": "STRING"},
        {"name": "runtime_host", "type": "STRING"},
        {"name": "release_version", "type": "STRING"},
        {"name": "git_sha", "type": "STRING"},
    ]


def assistant_log_schema() -> List[Dict[str, str]]:
    return [
        {"name": "row_id", "type": "STRING"},
        {"name": "request_id", "type": "STRING"},
        {"name": "ts", "type": "DATETIME"},
        {"name": "trace_id", "type": "STRING"},
        {"name": "session_id", "type": "STRING"},
        {"name": "user_id", "type": "STRING"},
        {"name": "channel", "type": "STRING"},
        {"name": "platform", "type": "STRING"},
        {"name": "business_unit", "type": "STRING"},
        {"name": "message", "type": "STRING"},
        {"name": "has_tools", "type": "BOOLEAN"},
        {"name": "delivery_suppressed", "type": "BOOLEAN"},
        {"name": "suppress_reason", "type": "STRING"},
        {"name": "elapsed_ms", "type": "INTEGER"},
        {"name": "llm_calls", "type": "INTEGER"},
        {"name": "tool_calls", "type": "INTEGER"},
        {"name": "tool_failures", "type": "INTEGER"},
        {"name": "tool_rounds", "type": "INTEGER"},
        {"name": "request_payload", "type": "JSON"},
        {"name": "llm_spans", "type": "JSON"},
        {"name": "tagging_error", "type": "STRING"},
        {"name": "tagging_error_label", "type": "STRING"},
    ]


def tool_output_log_schema() -> List[Dict[str, str]]:
    return [
        {"name": "row_id", "type": "STRING"},
        {"name": "request_id", "type": "STRING"},
        {"name": "ts", "type": "DATETIME"},
        {"name": "trace_id", "type": "STRING"},
        {"name": "session_id", "type": "STRING"},
        {"name": "user_id", "type": "STRING"},
        {"name": "tool_name", "type": "STRING"},
        {"name": "ok", "type": "BOOLEAN"},
        {"name": "error", "type": "STRING"},
        {"name": "args", "type": "JSON"},
        {"name": "data", "type": "JSON"},
    ]


def error_log_schema() -> List[Dict[str, str]]:
    return [
        {"name": "row_id", "type": "STRING"},
        {"name": "request_id", "type": "STRING"},
        {"name": "ts", "type": "DATETIME"},
        {"name": "trace_id", "type": "STRING"},
        {"name": "session_id", "type": "STRING"},
        {"name": "user_id", "type": "STRING"},
        {"name": "error", "type": "STRING"},
    ]


def slots_log_schema() -> List[Dict[str, str]]:
    return [
        {"name": "row_id", "type": "STRING"},
        {"name": "request_id", "type": "STRING"},
        {"name": "ts", "type": "DATETIME"},
        {"name": "trace_id", "type": "STRING"},
        {"name": "session_id", "type": "STRING"},
        {"name": "user_id", "type": "STRING"},
        {"name": "channel", "type": "STRING"},
        {"name": "business_unit", "type": "STRING"},
        {"name": "slots", "type": "JSON"},
        {"name": "slots_meta", "type": "JSON"},
    ]


def debug_log_schema() -> List[Dict[str, str]]:
    return [
        {"name": "row_id", "type": "STRING"},
        {"name": "request_id", "type": "STRING"},
        {"name": "ts", "type": "DATETIME"},
        {"name": "trace_id", "type": "STRING"},
        {"name": "session_id", "type": "STRING"},
        {"name": "user_id", "type": "STRING"},
        {"name": "channel", "type": "STRING"},
        {"name": "business_unit", "type": "STRING"},
        {"name": "debug_payload", "type": "JSON"},
    ]


def request_state_log_schema() -> List[Dict[str, str]]:
    return [
        {"name": "row_id", "type": "STRING"},
        {"name": "request_id", "type": "STRING"},
        {"name": "ts", "type": "DATETIME"},
        {"name": "trace_id", "type": "STRING"},
        {"name": "session_id", "type": "STRING"},
        {"name": "user_id", "type": "STRING"},
        {"name": "channel", "type": "STRING"},
        {"name": "business_unit", "type": "STRING"},
        {"name": "runtime_version", "type": "STRING"},
        {"name": "message_id", "type": "STRING"},
        {"name": "idempotency_key", "type": "STRING"},
        {"name": "request_source", "type": "STRING"},
        {"name": "status", "type": "STRING"},
        {"name": "attempt_count", "type": "INTEGER"},
        {"name": "llm_executed", "type": "BOOLEAN"},
        {"name": "last_error_type", "type": "STRING"},
        {"name": "last_error_stage", "type": "STRING"},
        {"name": "tokens_in", "type": "INTEGER"},
        {"name": "tokens_out", "type": "INTEGER"},
        {"name": "flow_stage_after", "type": "STRING"},
        {"name": "delivery_status", "type": "STRING"},
        {"name": "request_payload", "type": "JSON"},
        {"name": "final_response", "type": "JSON"},
        {"name": "meta", "type": "JSON"},
    ] + _runtime_metadata_schema()


def request_attempt_log_schema() -> List[Dict[str, str]]:
    return [
        {"name": "row_id", "type": "STRING"},
        {"name": "request_id", "type": "STRING"},
        {"name": "ts", "type": "DATETIME"},
        {"name": "trace_id", "type": "STRING"},
        {"name": "session_id", "type": "STRING"},
        {"name": "user_id", "type": "STRING"},
        {"name": "channel", "type": "STRING"},
        {"name": "business_unit", "type": "STRING"},
        {"name": "runtime_version", "type": "STRING"},
        {"name": "attempt_no", "type": "INTEGER"},
        {"name": "stage", "type": "STRING"},
        {"name": "event_type", "type": "STRING"},
        {"name": "retryable", "type": "BOOLEAN"},
        {"name": "latency_ms", "type": "INTEGER"},
        {"name": "backoff_seconds", "type": "INTEGER"},
        {"name": "session_locked", "type": "BOOLEAN"},
        {"name": "llm_executed", "type": "BOOLEAN"},
        {"name": "tokens_in", "type": "INTEGER"},
        {"name": "tokens_out", "type": "INTEGER"},
        {"name": "error_type", "type": "STRING"},
        {"name": "error_message", "type": "STRING"},
        {"name": "model", "type": "STRING"},
        {"name": "meta", "type": "JSON"},
    ] + _runtime_metadata_schema()


def turn_trace_log_schema() -> List[Dict[str, str]]:
    return [
        {"name": "row_id", "type": "STRING"},
        {"name": "request_id", "type": "STRING"},
        {"name": "ts", "type": "DATETIME"},
        {"name": "trace_id", "type": "STRING"},
        {"name": "session_id", "type": "STRING"},
        {"name": "user_id", "type": "STRING"},
        {"name": "channel_user_id", "type": "STRING"},
        {"name": "user_id_source", "type": "STRING"},
        {"name": "channel", "type": "STRING"},
        {"name": "business_unit", "type": "STRING"},
        {"name": "runtime_version", "type": "STRING"},
        {"name": "request_source", "type": "STRING"},
        {"name": "orchestration_mode", "type": "STRING"},
        {"name": "flow_stage_after", "type": "STRING"},
        {"name": "turn_latency_ms", "type": "INTEGER"},
        {"name": "llm_calls", "type": "INTEGER"},
        {"name": "tool_calls", "type": "INTEGER"},
        {"name": "tool_failures", "type": "INTEGER"},
        {"name": "request_payload", "type": "JSON"},
        {"name": "channel_context", "type": "JSON"},
        {"name": "llm_spans", "type": "JSON"},
        {"name": "tool_call_records", "type": "JSON"},
        {"name": "active_agents", "type": "JSON"},
        {"name": "agent_graph", "type": "JSON"},
        {"name": "memory_bank", "type": "JSON"},
        {"name": "slots", "type": "JSON"},
        {"name": "compatibility_state", "type": "JSON"},
        {"name": "canonical_state_snapshot", "type": "JSON"},
        {"name": "errors", "type": "JSON"},
        {"name": "final_response", "type": "JSON"},
        {"name": "tagging", "type": "JSON"},
    ] + _runtime_metadata_schema()


def turn_fact_log_schema() -> List[Dict[str, str]]:
    return [
        {"name": "row_id", "type": "STRING"},
        {"name": "request_id", "type": "STRING"},
        {"name": "ts", "type": "DATETIME"},
        {"name": "trace_id", "type": "STRING"},
        {"name": "session_id", "type": "STRING"},
        {"name": "user_id", "type": "STRING"},
        {"name": "channel", "type": "STRING"},
        {"name": "business_unit", "type": "STRING"},
        {"name": "runtime_version", "type": "STRING"},
        {"name": "request_source", "type": "STRING"},
        {"name": "orchestration_mode", "type": "STRING"},
        {"name": "flow_stage_after", "type": "STRING"},
        {"name": "turn_latency_ms", "type": "INTEGER"},
        {"name": "tokens_in", "type": "INTEGER"},
        {"name": "tokens_out", "type": "INTEGER"},
        {"name": "tokens_total", "type": "INTEGER"},
        {"name": "llm_calls", "type": "INTEGER"},
        {"name": "tool_calls", "type": "INTEGER"},
        {"name": "tool_failures", "type": "INTEGER"},
        {"name": "has_tools", "type": "BOOLEAN"},
        {"name": "out_of_flow_signal", "type": "STRING"},
        {"name": "response_bubble_count", "type": "INTEGER"},
        {"name": "request_payload", "type": "JSON"},
    ] + _runtime_metadata_schema()


def interaction_event_log_schema() -> List[Dict[str, str]]:
    """Normalized interactive discovery impression and choice events."""

    return [
        {"name": "row_id", "type": "STRING"},
        {"name": "request_id", "type": "STRING"},
        {"name": "ts", "type": "DATETIME"},
        {"name": "trace_id", "type": "STRING"},
        {"name": "session_id", "type": "STRING"},
        {"name": "user_id", "type": "STRING"},
        {"name": "channel", "type": "STRING"},
        {"name": "business_unit", "type": "STRING"},
        {"name": "runtime_version", "type": "STRING"},
        {"name": "event_type", "type": "STRING"},
        {"name": "surface_type", "type": "STRING"},
        {"name": "surface_ref", "type": "STRING"},
        {"name": "catalog_version_id", "type": "STRING"},
        {"name": "choice_type", "type": "STRING"},
        {"name": "choice_ref", "type": "STRING"},
        {"name": "promo_id", "type": "STRING"},
        {"name": "card_id", "type": "STRING"},
        {"name": "brand", "type": "STRING"},
        {"name": "category", "type": "STRING"},
        {"name": "tire_size", "type": "STRING"},
        {"name": "position", "type": "INTEGER"},
        {"name": "idempotency_key", "type": "STRING"},
        {"name": "delivery_status", "type": "STRING"},
        {"name": "details", "type": "JSON"},
    ] + _runtime_metadata_schema()


def llm_span_log_schema() -> List[Dict[str, str]]:
    return [
        {"name": "row_id", "type": "STRING"},
        {"name": "request_id", "type": "STRING"},
        {"name": "ts", "type": "DATETIME"},
        {"name": "trace_id", "type": "STRING"},
        {"name": "session_id", "type": "STRING"},
        {"name": "user_id", "type": "STRING"},
        {"name": "channel", "type": "STRING"},
        {"name": "business_unit", "type": "STRING"},
        {"name": "runtime_version", "type": "STRING"},
        {"name": "span_index", "type": "INTEGER"},
        {"name": "component", "type": "STRING"},
        {"name": "agent_id", "type": "STRING"},
        {"name": "agent_role", "type": "STRING"},
        {"name": "parent_span_id", "type": "STRING"},
        {"name": "model", "type": "STRING"},
        {"name": "provider", "type": "STRING"},
        {"name": "tokens_in", "type": "INTEGER"},
        {"name": "tokens_out", "type": "INTEGER"},
        {"name": "latency_ms", "type": "INTEGER"},
        {"name": "meta", "type": "JSON"},
    ] + _runtime_metadata_schema()


def tool_call_log_schema() -> List[Dict[str, str]]:
    return [
        {"name": "row_id", "type": "STRING"},
        {"name": "request_id", "type": "STRING"},
        {"name": "ts", "type": "DATETIME"},
        {"name": "trace_id", "type": "STRING"},
        {"name": "session_id", "type": "STRING"},
        {"name": "user_id", "type": "STRING"},
        {"name": "channel", "type": "STRING"},
        {"name": "business_unit", "type": "STRING"},
        {"name": "runtime_version", "type": "STRING"},
        {"name": "call_index", "type": "INTEGER"},
        {"name": "tool_call_id", "type": "STRING"},
        {"name": "tool_name", "type": "STRING"},
        {"name": "component", "type": "STRING"},
        {"name": "agent_id", "type": "STRING"},
        {"name": "agent_role", "type": "STRING"},
        {"name": "ok", "type": "BOOLEAN"},
        {"name": "error", "type": "STRING"},
        {"name": "latency_ms", "type": "INTEGER"},
        {"name": "artifact_id", "type": "STRING"},
        {"name": "args", "type": "JSON"},
        {"name": "summary_context", "type": "JSON"},
        {"name": "presentation", "type": "JSON"},
    ] + _runtime_metadata_schema()


def followup_event_log_schema() -> List[Dict[str, str]]:
    """Normalized proactive follow-up and customer-recovery event schema."""

    return [
        {"name": "row_id", "type": "STRING"},
        {"name": "request_id", "type": "STRING"},
        {"name": "ts", "type": "DATETIME"},
        {"name": "trace_id", "type": "STRING"},
        {"name": "session_id", "type": "STRING"},
        {"name": "user_id", "type": "STRING"},
        {"name": "channel", "type": "STRING"},
        {"name": "business_unit", "type": "STRING"},
        {"name": "runtime_version", "type": "STRING"},
        {"name": "route", "type": "STRING"},
        {"name": "cadence", "type": "STRING"},
        {"name": "action", "type": "STRING"},
        {"name": "stance", "type": "STRING"},
        {"name": "focus_field", "type": "STRING"},
        {"name": "validation_status", "type": "STRING"},
        {"name": "validation_reasons", "type": "JSON"},
        {"name": "evidence_refs", "type": "JSON"},
        {"name": "attempt_status", "type": "STRING"},
        {"name": "delivery_status", "type": "STRING"},
        {"name": "delivery_reason", "type": "STRING"},
        {"name": "tokens_in", "type": "INTEGER"},
        {"name": "tokens_out", "type": "INTEGER"},
        {"name": "tokens_total", "type": "INTEGER"},
        {"name": "latency_ms", "type": "INTEGER"},
        {"name": "context_fingerprint", "type": "STRING"},
        {"name": "conversation_anchor_id", "type": "STRING"},
        {"name": "release_sha", "type": "STRING"},
        {"name": "meta", "type": "JSON"},
    ] + _runtime_metadata_schema()
