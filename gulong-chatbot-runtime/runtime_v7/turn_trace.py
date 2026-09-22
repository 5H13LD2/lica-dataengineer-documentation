"""Version-neutral turn trace helpers for Runtime V7.

The API still persists V7-owned state, but trace records should use stable
concepts such as component spans and state snapshots so later runtimes can
share the same analytics shape.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Dict, List, Mapping, Optional, Sequence

from runtime.utils.time_utils import now_manila_str


def build_inbound_event(
    *,
    request_id: str,
    trace_id: str,
    runtime_version: str,
    user_id: str,
    channel_user_id: str,
    channel: str,
    message_id: str,
    idempotency_key: str,
    message_id_source: str = "",
    raw_payload: Optional[Mapping[str, Any]] = None,
    normalized_payload: Optional[Mapping[str, Any]] = None,
    channel_event_id: str = "",
    channel_event_ts: str = "",
    flow_context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return the version-neutral inbound event trace shape."""

    normalized = dict(normalized_payload or {})
    raw = dict(raw_payload or {})
    event_key = build_inbound_event_key(
        user_id=user_id,
        channel=channel,
        channel_event_id=channel_event_id,
        message_id=message_id,
        message_id_source=message_id_source,
        normalized_payload=normalized,
        channel_event_ts=channel_event_ts,
        flow_context=flow_context,
    )
    return {
        "event_type": "inbound_message",
        "event_key": event_key,
        "request_id": request_id,
        "trace_id": trace_id,
        "runtime_version": runtime_version,
        "user_id": str(user_id or ""),
        "channel_user_id": str(channel_user_id or user_id or ""),
        "channel": str(channel or ""),
        "message_id": str(message_id or ""),
        "message_id_source": str(message_id_source or ""),
        "idempotency_key": str(idempotency_key or ""),
        "channel_event_id": str(channel_event_id or ""),
        "channel_event_ts": str(channel_event_ts or ""),
        "dedupe_eligible": bool(
            str(channel_event_id or "").strip()
            or _is_external_message_id_source(message_id_source)
            or str(channel_event_ts or "").strip()
        ),
        "received_at": now_manila_str(),
        "raw_payload": raw,
        "normalized_payload": normalized,
        "flow_context": dict(flow_context or {}),
        "status": "received",
    }


def build_inbound_event_key(
    *,
    user_id: str,
    channel: str,
    channel_event_id: str = "",
    message_id: str = "",
    message_id_source: str = "",
    normalized_payload: Optional[Mapping[str, Any]] = None,
    channel_event_ts: str = "",
    flow_context: Optional[Mapping[str, Any]] = None,
) -> str:
    """Return a stable event key, preferring provider event ids."""

    provider_id = str(channel_event_id or "").strip()
    if provider_id:
        basis = {
            "kind": "provider_event",
            "channel": str(channel or ""),
            "user_id": str(user_id or ""),
            "channel_event_id": provider_id,
        }
        return "evt_" + _short_hash(basis)
    if _is_external_message_id_source(message_id_source) and str(message_id or "").strip():
        basis = {
            "kind": "message_id",
            "channel": str(channel or ""),
            "user_id": str(user_id or ""),
            "message_id": str(message_id or ""),
        }
        return "evt_" + _short_hash(basis)
    payload = dict(normalized_payload or {})
    basis = {
        "kind": "derived_payload",
        "channel": str(channel or ""),
        "user_id": str(user_id or ""),
        "payload": payload,
        "time_bucket": short_time_bucket(channel_event_ts or payload.get("request_time") or ""),
        "flow_hash": flow_context_hash(flow_context),
    }
    return "evt_" + _short_hash(basis)


def short_time_bucket(value: str, *, bucket_seconds: int = 5) -> str:
    """Return a coarse timestamp bucket for weak fallback dedupe."""

    text = str(value or "").strip()
    if not text:
        return ""
    # Keep this intentionally parser-light: callers only need a stable coarse
    # bucket, not a source of truth for scheduling.
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 14:
        second = int(digits[12:14])
        bucket = second - (second % max(1, int(bucket_seconds or 5)))
        return f"{digits[:12]}{bucket:02d}"
    return text[:16]


def flow_context_hash(flow_context: Optional[Mapping[str, Any]]) -> str:
    """Return a compact hash for ManyChat flow or request context."""

    context = dict(flow_context or {})
    if not context:
        return ""
    return _short_hash(context)


def _is_external_message_id_source(value: str) -> bool:
    source = str(value or "").strip().lower()
    return source in {"provided", "manychat_load_messages", "channel_history_cache"}


def build_turn_trace(
    *,
    inbound_event: Mapping[str, Any],
    turn_record: Mapping[str, Any],
    delivery_result: Mapping[str, Any],
    tagging_result: Mapping[str, Any],
    state_saved: bool,
) -> Dict[str, Any]:
    """Build a compact, version-neutral trace from the V7 turn record."""

    component_spans = _component_spans_from_turn(turn_record, delivery_result=delivery_result, tagging_result=tagging_result)
    state_snapshots = _state_snapshots_from_turn(turn_record, tagging_result=tagging_result)
    return {
        "trace_id": inbound_event.get("trace_id") or "",
        "request_id": inbound_event.get("request_id") or "",
        "runtime_version": inbound_event.get("runtime_version") or "v7",
        "turn_id": turn_record.get("turn_id") or "",
        "inbound_event": dict(inbound_event or {}),
        "component_spans": component_spans,
        "state_snapshots": state_snapshots,
        "delivery_events": [
            {
                "component_type": "delivery",
                "component_name": "manychat_send_content",
                "status": delivery_result.get("status") or "",
                "output": dict(delivery_result or {}),
            }
        ],
        "status": "completed" if state_saved else "completed_state_not_saved",
    }


def _component_spans_from_turn(
    turn_record: Mapping[str, Any],
    *,
    delivery_result: Mapping[str, Any],
    tagging_result: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    spans: List[Dict[str, Any]] = []
    bse = turn_record.get("background_signal_extraction")
    if isinstance(bse, Mapping):
        spans.append(
            {
                "component_type": "state_extraction",
                "component_name": "background_signal_extractor",
                "status": bse.get("status") or "",
                "latency_ms": bse.get("model_latency_ms") or bse.get("latency_ms"),
                "usage": deepcopy(bse.get("model_usage") or bse.get("usage") or {}),
                "cache_usage": deepcopy(bse.get("model_cache_usage") or {}),
                "model_used": bool(bse.get("model_used")),
                "model": bse.get("model") or "",
                "provider_call_count": bse.get("model_attempts") or 0,
                "metered_provider_call_count": bse.get(
                    "model_metered_attempts"
                ),
                "output_ref": "state:signals:before_turn",
            }
        )
    for call in turn_record.get("llm_calls") or []:
        if not isinstance(call, Mapping):
            continue
        spans.append(
            {
                "component_type": "model_call",
                "component_name": call.get("component") or "main_tool_loop",
                "round": call.get("round"),
                "status": call.get("finish_reason") or "",
                "latency_ms": call.get("latency_ms"),
                "usage": deepcopy(call.get("usage_summary") or call.get("usage") or {}),
                "tool_calls": deepcopy(call.get("tool_calls") or []),
                "provider_call_count": call.get("provider_call_count") or 1,
            }
        )
    for call in turn_record.get("supplemental_llm_calls") or []:
        if not isinstance(call, Mapping):
            continue
        if call.get("component") == "background_signal_extraction":
            # The dedicated state_extraction span above already owns this
            # component's latency and usage; do not duplicate it as a second
            # model span.
            continue
        spans.append(
            {
                "component_type": "model_call",
                "component_name": call.get("component") or "supplemental_model_call",
                "round": call.get("round"),
                "status": call.get("finish_reason") or "",
                "latency_ms": call.get("latency_ms"),
                "usage": deepcopy(call.get("usage_summary") or call.get("usage") or {}),
                "provider_call_count": call.get("provider_call_count") or 1,
                "supplemental_usage_record": True,
            }
        )
    for result in turn_record.get("tool_results") or []:
        if not isinstance(result, Mapping):
            continue
        full = result.get("full_result") or result.get("result") or {}
        spans.append(
            {
                "component_type": "tool_call",
                "component_name": result.get("name") or "",
                "status": full.get("status") if isinstance(full, Mapping) else "",
                "latency_ms": result.get("latency_ms"),
                "input": deepcopy(result.get("args") or {}),
                "output_ref": _tool_output_ref(result),
            }
        )
    composer = turn_record.get("final_composer")
    if isinstance(composer, Mapping):
        spans.append(
            {
                "component_type": "composer",
                "component_name": "final_composer",
                "status": composer.get("status") or "",
                "usage": deepcopy(composer.get("usage_summary") or {}),
            }
        )
    spans.append(
        {
            "component_type": "tagging",
            "component_name": "runtime_v7_tagging",
            "status": tagging_result.get("apply_status") or "",
            "output": deepcopy(tagging_result or {}),
        }
    )
    spans.append(
        {
            "component_type": "delivery",
            "component_name": "manychat_send_content",
            "status": delivery_result.get("status") or "",
        }
    )
    return spans


def _state_snapshots_from_turn(
    turn_record: Mapping[str, Any],
    *,
    tagging_result: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    snapshots: List[Dict[str, Any]] = []
    mappings = [
        ("memory", "before_turn", "active_working_memory_before_turn"),
        ("memory", "after_turn", "active_working_memory_after_turn"),
        ("signals", "before_turn", "background_signals_before_turn"),
        ("signals", "after_turn", "background_signal_ledger_after_turn"),
        ("readiness", "before_turn", "order_readiness_before_turn"),
        ("capabilities", "model_facing", "capability_profile"),
        ("presentation_context", "after_turn", "observation_headers_after_turn"),
        ("service_context", "after_turn", "service_observation_headers_after_turn"),
        ("order_state", "after_turn", "latest_order_summary_snapshot_after_turn"),
        ("order_state", "after_turn", "latest_selected_product_context_after_turn"),
        ("payment_state", "after_turn", "payment_request_refs_after_turn"),
    ]
    for state_type, stage, key in mappings:
        value = turn_record.get(key)
        if value in (None, "", [], {}):
            continue
        snapshots.append(
            {
                "state_type": state_type,
                "state_name": key,
                "stage": stage,
                "state_json": deepcopy(value),
            }
        )
    if tagging_result:
        snapshots.append(
            {
                "state_type": "tag_state",
                "state_name": "tagging_result",
                "stage": "after_turn",
                "state_json": deepcopy(tagging_result),
            }
        )
    return snapshots


def _tool_output_ref(result: Mapping[str, Any]) -> str:
    for key in ["observation_ref", "presentation_ref", "payment_request_ref", "order_payload_ref"]:
        value = result.get(key)
        if value:
            return str(value)
    full = result.get("full_result") or result.get("result") or {}
    if isinstance(full, Mapping):
        for key in ["observation_ref", "presentation_ref", "payment_request_ref", "order_payload_ref"]:
            value = full.get(key)
            if value:
                return str(value)
    return ""


def _small_dict(source: Mapping[str, Any], keys: Sequence[str]) -> Dict[str, Any]:
    return {key: deepcopy(source.get(key)) for key in keys if source.get(key) not in (None, "", [], {})}


def _short_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


__all__ = [
    "build_inbound_event",
    "build_inbound_event_key",
    "build_turn_trace",
    "flow_context_hash",
    "short_time_bucket",
]
