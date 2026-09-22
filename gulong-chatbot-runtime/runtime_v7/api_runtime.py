"""Deployable API wrapper for Runtime V7.

This module keeps Cloud Run/API concerns outside the tool-loop harness:
session loading, profile hydration, channel rendering, optional ManyChat
delivery, passive tag application, and compact state persistence.
"""

from __future__ import annotations

import hashlib
import asyncio
import json
import os
import re
import time
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

from channels.manychat.api_client import ManyChatAPI
from configs.log_utils import get_logger
from runtime.gateways.analytics_gateway import AnalyticsGateway
from runtime.gateways.sessions_gateway import SessionsGateway
from runtime.shared.types import MessageTurn, UserDoc
from runtime.utils.time_utils import now_manila_str
from runtime_v7.canonical_values import RuntimeV7CanonicalValuesProvider
from runtime_v7.brand_knowledge import (
    BrandKnowledgeRepository,
    BrandKnowledgeService,
    brand_knowledge_enabled,
)
from runtime_v7.channel_renderer import RuntimeV7ChannelRender, render_turn_for_channel
from runtime_v7.commercial_claim_contract import (
    dedupe_payment_policies as _dedupe_payment_policies,
    payment_claim,
    payment_claim_contract_violations,
    payment_policies_from_tool_results,
    payment_policy_identity as _payment_policy_identity,
)
from runtime_v7.conversation_hydrator import (
    CHANNEL_CONVERSATION_HISTORY_STATE_KEY,
    ConversationHydrationResult,
    append_current_turn_to_channel_history,
    build_channel_history_cache,
    build_conversation_hydration_result,
)
from runtime_v7.followup import redact_followup_pricing_context
from runtime_v7.faq_tools import answer_order_faq
from runtime_v7.followup_v2 import (
    build_attempt_record,
    build_followup_case,
    build_followup_plan_messages,
    build_followup_plan_response_model,
    customer_recovery_gate,
    followup_stop_reason,
    is_retryable_evaluation_reason,
    load_current_promo_brands,
    parse_followup_plan,
    proactive_followup_gate,
    upsert_attempt,
    validate_and_render_followup,
)
from runtime_v7.image_evidence import (
    ImageEvidenceExtractor,
    RuntimeV7ImageEvidenceModelClient,
    normalize_visible_tire_size,
)
from runtime_v7.interaction_resolution import (
    compile_interaction_packet,
    event_for_id,
)
from runtime_v7.llm_gateway import (
    RuntimeV7LLMGateway,
    RuntimeV7LLMGatewayConfig,
    RuntimeV7ProviderCallGuard,
)
from runtime_v7.location_quality import usable_lead_location
from runtime_v7.location_choices import ServiceableLocationChoicesProvider
from runtime_v7.manychat_cloudsql_reader import (
    compare_manychat_message_sets,
    load_manychat_messages_from_cloudsql,
)
from runtime_v7.manychat_message_loader import load_manychat_messages_fast
from runtime_v7.memory import (
    ActiveWorkingMemory,
    HybridActiveWorkingMemoryGenerator,
    RuntimeV7ActiveWorkingMemoryModelClient,
    compact_active_working_memory_for_persistence,
)
from runtime_v7.order_canonicalization import (
    checkout_metadata,
    normalize_payment_option,
    payment_option_label,
)
from runtime_v7.order_state import build_order_readiness, calculate_order_quote
from runtime_v7.product_observations import ProductObservation, ProductObservationStore, ProductToolHarness
from runtime_v7.product_search import ProductSearchRunner
from runtime_v7.promo_catalog import (
    PROMO_SELECTION_ACTIONS,
    PromoCatalogRepository,
    PromoCatalogService,
    product_card_matches_promo_types,
    promo_catalog_enabled_for_user,
)
from runtime_v7.runtime_harness import RuntimeV7Harness, final_composer_output_accepted
from runtime_v7.service_observations import ServiceObservation, ServiceObservationStore
from runtime_v7.service_tools import RuntimeV7ServiceTools
from runtime_v7.state_signal_model import RuntimeV7BackgroundSignalModelClient
from runtime_v7.tagging import (
    enrich_runtime_v7_analytical_qualifications,
    mark_runtime_v7_tags_applied,
)
from runtime_v7.turn_trace import build_inbound_event, build_turn_trace
from runtime_v7.transaction_choices import (
    build_payment_method_surface,
    build_payment_option_surface,
    signal_authority,
)


V7_STATE_KEY = "runtime_v7"
DEFAULT_DELIVERY_MODE = "return_only"
DEFAULT_MANYCHAT_BUBBLE_DELAY_MS = 1200
DEFAULT_MANYCHAT_BUBBLE_DELAY_MAX_MESSAGES = 6
logger = get_logger(__name__, level="INFO")


def _manychat_recipient_id(request: "RuntimeV7APIRequest") -> str:
    """Return the real channel recipient without changing session identity."""

    return str(request.channel_user_id or request.user_id).strip()


@dataclass
class RuntimeV7APIRequest:
    """Deployable Runtime V7 request shape."""

    user_id: str
    user_text: str
    channel_user_id: str = ""
    channel: str = "manychat"
    channel_subtype: str = ""
    full_name: str = ""
    first_name: str = ""
    last_name: str = ""
    assigned_agent: str = ""
    profile_fields: Dict[str, Any] = field(default_factory=dict)
    message_id: str = ""
    message_id_source: str = ""
    idempotency_key: str = ""
    user_id_source: str = "manychat"
    reset: bool = False
    return_logs: bool = False
    tester: bool = False
    delivery_mode: str = DEFAULT_DELIVERY_MODE
    request_time: str = ""
    channel_event_id: str = ""
    channel_event_ts: str = ""
    flow_context: Dict[str, Any] = field(default_factory=dict)
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    normalized_payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeV7APIResult:
    """Runtime V7 API result with channel-safe output and diagnostics."""

    response: Dict[str, str]
    content_messages: List[Dict[str, Any]]
    images: List[Dict[str, str]]
    payment: Dict[str, Any]
    delivery_result: Dict[str, Any]
    tagging_result: Dict[str, Any]
    turn_record: Dict[str, Any]
    session_id: str
    trace_id: str
    request_id: str
    message_id: str
    idempotency_key: str
    state_saved: bool
    status: str = "success"
    turn_trace: Dict[str, Any] = field(default_factory=dict)
    promo_presentation: Dict[str, Any] = field(default_factory=dict)
    choice_presentations: List[Dict[str, Any]] = field(default_factory=list)
    product_presentations: List[Dict[str, Any]] = field(default_factory=list)

    def to_payload(self, *, include_debug: bool = False) -> Dict[str, Any]:
        """Serialize the customer result and optional bounded turn diagnostics."""

        payload: Dict[str, Any] = {
            "status": self.status,
            "response": self.response,
            "content_messages": self.content_messages,
            "images": self.images,
            "payment": self.payment,
            "promo_presentation": self.promo_presentation,
            "choice_presentations": self.choice_presentations,
            "product_presentations": self.product_presentations,
            "delivery_result": self.delivery_result,
            "tagging_result": self.tagging_result,
            "request_id": self.request_id,
            "message_id": self.message_id,
            "idempotency_key": self.idempotency_key,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "state_saved": self.state_saved,
            "save_analytics": 1,
        }
        if self.turn_trace:
            payload["turn_trace_summary"] = _compact_turn_trace_summary(self.turn_trace)
        choice_validation = self.turn_record.get("choice_action_validation")
        if isinstance(choice_validation, dict) and choice_validation:
            payload["choice_action_validation"] = deepcopy(choice_validation)
        if include_debug:
            payload["debug"] = {
                "turn_id": self.turn_record.get("turn_id"),
                "tool_calls": _debug_tool_calls(self.turn_record.get("tool_results") or []),
                "tool_dedupe_events": _debug_tool_dedupe_events(
                    self.turn_record.get("tool_dedupe_events") or []
                ),
                "llm_usage_summary": self.turn_record.get("llm_usage_summary") or {},
                "runtime_phase_timings_ms": _debug_runtime_phase_timings(
                    self.turn_record.get("runtime_phase_timings_ms")
                ),
                "session_store_diagnostics": _debug_session_store_diagnostics(
                    self.turn_record.get("session_store_diagnostics")
                ),
                "context_cache_summary": self.turn_record.get("context_cache_summary") or {},
                "capability_profile": self.turn_record.get("capability_profile") or {},
                "order_readiness_before_turn": self.turn_record.get("order_readiness_before_turn") or {},
                "checkout_choice_surface_status": self.turn_record.get(
                    "checkout_choice_surface_status"
                )
                or {},
                "active_working_memory_after_turn": self.turn_record.get("active_working_memory_after_turn") or {},
                "promo_provider_truth_guard": self.turn_record.get(
                    "promo_provider_truth_guard"
                )
                or {},
                "location_progression_guard": self.turn_record.get(
                    "location_progression_guard"
                )
                or {},
                "payment_policy_truth_guard": self.turn_record.get(
                    "payment_policy_truth_guard"
                )
                or {},
                "commercial_payment_claims": self.turn_record.get(
                    "commercial_payment_claims"
                )
                or [],
                "semantic_answer_goal_audits": self.turn_record.get(
                    "semantic_answer_goal_audits"
                )
                or [],
                "promo_fact_scope_audits": self.turn_record.get(
                    "promo_fact_scope_audits"
                )
                or [],
                "final_composer_status": (
                    self.turn_record.get("final_composer") or {}
                ).get("status"),
                "response_guard_events": self.turn_record.get(
                    "response_guard_events"
                )
                or [],
                "suppressed_channel_surface_tools": self.turn_record.get(
                    "suppressed_channel_surface_tools"
                )
                or [],
                "followup": self.turn_record.get("followup") or {},
                "turn_trace": _debug_turn_trace(self.turn_trace),
            }
        return payload


def _record_runtime_phase(
    timings: Dict[str, float],
    name: str,
    started: float,
) -> None:
    """Record one bounded monotonic runtime phase without customer data."""

    elapsed_ms = max((time.perf_counter() - started) * 1000.0, 0.0)
    timings[str(name)] = round(elapsed_ms, 3)


def _debug_runtime_phase_timings(value: Any) -> Dict[str, float]:
    """Expose only bounded phase names and non-negative numeric durations."""

    if not isinstance(value, Mapping):
        return {}
    timings: Dict[str, float] = {}
    for key, duration in list(value.items())[:32]:
        if not isinstance(key, str) or type(duration) not in (int, float):
            continue
        timings[key[:80]] = round(max(float(duration), 0.0), 3)
    return timings


def _debug_session_store_diagnostics(value: Any) -> Dict[str, Any]:
    """Expose only content-free Firestore timing, retry, and size fields."""

    if not isinstance(value, Mapping):
        return {}
    output: Dict[str, Any] = {}
    for key in (
        "storage_kind",
        "write_mode",
        "saved",
        "error_type",
        "expected_revision",
        "attempt_count",
        "total_ms",
        "commit_retry_overhead_ms",
        "rpc_observer_status",
        "begin_rpc_attempt_count",
        "commit_rpc_attempt_count",
        "rpc_unattributed_ms",
        "observation_id",
        "process_id",
        "instance_id_hash",
        "revision",
        "process_uptime_ms",
        "active_saves_at_start",
        "active_saves_before_end",
        "process_peak_active_saves",
        "process_cpu_ms",
        "process_cpu_to_wall_percent",
        "payload_sizes_measured",
        "payload_json_bytes",
        "strategy_state_json_bytes",
        "diagnostic_overhead_ms",
        "instrumented_call_total_ms",
    ):
        field_value = value.get(key)
        if isinstance(field_value, (str, bool, int, float)):
            output[key] = field_value
    for key in (
        "read_ms",
        "transaction_body_ms",
        "begin_rpc_attempt_ms",
        "commit_rpc_attempt_ms",
        "commit_rpc_process_cpu_ms",
        "commit_rpc_thread_cpu_ms",
        "commit_rpc_other_threads_cpu_ms",
        "commit_rpc_user_cpu_ms",
        "commit_rpc_system_cpu_ms",
        "commit_rpc_minor_page_faults",
        "commit_rpc_major_page_faults",
        "commit_rpc_voluntary_context_switches",
        "commit_rpc_involuntary_context_switches",
    ):
        field_value = value.get(key)
        if isinstance(field_value, list):
            output[key] = [
                round(max(float(item), 0.0), 3)
                for item in field_value[:10]
                if type(item) in (int, float)
            ]
    for key in (
        "begin_rpc_outcomes",
        "begin_rpc_status_codes",
        "commit_rpc_outcomes",
        "commit_rpc_error_types",
        "commit_rpc_status_codes",
    ):
        field_value = value.get(key)
        if isinstance(field_value, list):
            output[key] = [
                str(item)[:80]
                for item in field_value[:10]
                if isinstance(item, str)
            ]
    for key in (
        "commit_rpc_gapic_retryable",
        "commit_rpc_transactional_retryable",
    ):
        field_value = value.get(key)
        if isinstance(field_value, list):
            output[key] = [
                item for item in field_value[:10] if isinstance(item, bool)
            ]
    for key in (
        "commit_rpc_gc_collections",
        "commit_rpc_gc_collected",
    ):
        field_value = value.get(key)
        if isinstance(field_value, list):
            output[key] = [
                [max(int(item), 0) for item in generation[:3] if type(item) is int]
                for generation in field_value[:10]
                if isinstance(generation, list)
            ]
    return output


def _debug_tool_calls(tool_results: List[Any]) -> List[Dict[str, Any]]:
    """Expose both raw and model-visible tool statuses for turn debugging."""

    calls: List[Dict[str, Any]] = []
    for item in tool_results:
        if not isinstance(item, dict):
            continue
        full_result = item.get("full_result") if isinstance(item.get("full_result"), dict) else {}
        compact_result = item.get("result") if isinstance(item.get("result"), dict) else {}
        raw_status = full_result.get("status")
        model_visible_status = compact_result.get("status")
        call = {
            "name": item.get("name"),
            "status": raw_status or model_visible_status,
            "raw_status": raw_status,
            "model_visible_status": model_visible_status,
        }
        if isinstance(item.get("latency_ms"), (int, float)):
            call["latency_ms"] = item.get("latency_ms")
        if item.get("tool_call_id") not in (None, ""):
            call["tool_call_id"] = item.get("tool_call_id")
        safe_args = _debug_tool_args(item.get("args"))
        if safe_args:
            call["args"] = safe_args
        safe_model_args = _debug_tool_args(item.get("model_args"))
        if safe_model_args:
            call["model_args"] = safe_model_args
        for key in ("error_type", "reason", "message"):
            value = full_result.get(key)
            if value in (None, "", [], {}):
                value = compact_result.get(key)
            if value not in (None, "", [], {}):
                call[key] = value
        if item.get("name") == "search_promo_catalog":
            call["commercial_scope"] = {
                "requested_brands": list(
                    full_result.get("requested_brands") or []
                ),
                "matched_requested_brands": list(
                    full_result.get("matched_requested_brands") or []
                ),
                "unmatched_requested_brands": list(
                    full_result.get("unmatched_requested_brands") or []
                ),
                "allowed_promo_refs": list(
                    full_result.get("allowed_promo_refs") or []
                ),
                "published_candidate_count": full_result.get(
                    "published_candidate_count"
                ),
                "current_candidate_count": full_result.get(
                    "current_candidate_count"
                ),
                "expired_candidate_count": full_result.get(
                    "expired_candidate_count"
                ),
            }
        if item.get("name") == "answer_order_faq":
            payment_policy = (
                full_result.get("payment_policy")
                if isinstance(full_result.get("payment_policy"), dict)
                else {}
            )
            if payment_policy:
                call["payment_scope"] = {
                    "requested_method": (
                        payment_policy.get("requested_payment_name")
                        or payment_policy.get("requested_payment_method")
                    ),
                    "requested_status": payment_policy.get(
                        "requested_payment_status"
                    ),
                    "brand": payment_policy.get("requested_product_brand"),
                    "brand_eligibility": payment_policy.get(
                        "requested_brand_eligibility"
                    ),
                    "payment_option": payment_policy.get("payment_option"),
                }
        authority = {
            "source": full_result.get("source") or compact_result.get("source") or item.get("source"),
            "evidence_ref": full_result.get("evidence_ref") or compact_result.get("evidence_ref"),
            "faq_id": full_result.get("faq_id") or compact_result.get("faq_id"),
            "presentation_ref": full_result.get("presentation_ref") or compact_result.get("presentation_ref"),
        }
        authority = {
            key: value
            for key, value in authority.items()
            if value not in (None, "", [], {})
        }
        if authority:
            call["authority"] = authority
        if item.get("round") not in (None, ""):
            call["round"] = item.get("round")
        calls.append({key: value for key, value in call.items() if value not in (None, "", [], {})})
    return calls


def _debug_tool_dedupe_events(events: List[Any]) -> List[Dict[str, Any]]:
    """Expose bounded same-turn reuse evidence without raw cache keys or questions."""

    rows: List[Dict[str, Any]] = []
    allowed = {
        "round",
        "type",
        "name",
        "tool_call_id",
        "first_round",
        "first_tool_call_id",
        "cache_match_type",
        "observation_ref",
        "presentation_ref",
    }
    for item in events:
        if not isinstance(item, Mapping):
            continue
        row = {
            str(key): deepcopy(value)
            for key, value in item.items()
            if str(key) in allowed and value not in (None, "", [], {})
        }
        safe_args = _debug_tool_args(item.get("args"))
        if safe_args:
            row["args"] = safe_args
        if row:
            rows.append(row)
    return rows


def _debug_turn_trace(value: Any) -> Dict[str, Any]:
    """Keep trace structure and usage while bounding embedded tool arguments."""

    if not isinstance(value, Mapping):
        return {}
    trace = deepcopy(dict(value))
    for span in trace.get("component_spans") or []:
        if not isinstance(span, dict):
            continue
        if span.get("component_type") == "model_call":
            safe_calls = []
            for call in span.get("tool_calls") or []:
                if not isinstance(call, Mapping):
                    continue
                safe_call = {
                    key: deepcopy(call.get(key))
                    for key in ("id", "tool_call_id", "name")
                    if call.get(key) not in (None, "", [], {})
                }
                safe_args = _debug_tool_args(call.get("args"))
                if safe_args:
                    safe_call["args"] = safe_args
                safe_calls.append(safe_call)
            span["tool_calls"] = safe_calls
        elif span.get("component_type") == "tool_call":
            span["input"] = _debug_tool_args(span.get("input"))
    return trace


def _debug_tool_args(value: Any) -> Dict[str, Any]:
    """Expose only bounded canonical/routing arguments in tester diagnostics."""

    if not isinstance(value, Mapping):
        return {}
    allowed = {
        "faq_id",
        "question_topics",
        "requested_payment_method",
        "requested_payment_category",
        "requested_product_brand",
        "payment_option",
        "section_width",
        "aspect_ratio",
        "rim_size",
        "required_brands",
        "brand_match_mode",
        "preferred_brands",
        "excluded_brands",
        "terrain_types",
        "tire_categories",
        "excluded_tire_categories",
        "origins",
        "excluded_origins",
        "promo_types",
        "model_or_pattern",
        "brands",
        "brand",
        "province",
        "city",
        "location",
        "service_type",
        "quantity",
        "product_id",
        "sku",
    }
    return {
        str(key): deepcopy(item)
        for key, item in value.items()
        if str(key) in allowed and item not in (None, "", [], {})
    }


class RuntimeV7APIService:
    """Stateful API boundary around the Runtime V7 harness."""

    def __init__(
        self,
        *,
        sessions_gateway: SessionsGateway,
        harness_factory: Optional[Callable[[str, Dict[str, Any], str], RuntimeV7Harness]] = None,
        profile_loader: Optional[Callable[[RuntimeV7APIRequest], Dict[str, Any]]] = None,
        conversation_history_loader: Optional[Callable[[RuntimeV7APIRequest], Any]] = None,
        delivery_client_factory: Optional[Callable[[RuntimeV7APIRequest], Any]] = None,
        analytics_gateway: Optional[AnalyticsGateway] = None,
        followup_model_client: Optional[Any] = None,
        delivery_mode: str = DEFAULT_DELIVERY_MODE,
        fetch_manychat_profile: Optional[bool] = None,
        fetch_manychat_messages: Optional[bool] = None,
        apply_manychat_tags: Optional[bool] = None,
        location_choices_provider: Optional[Any] = None,
    ) -> None:
        self.sessions_gateway = sessions_gateway
        self.harness_factory = harness_factory or build_runtime_v7_harness
        self.profile_loader = profile_loader
        self.conversation_history_loader = conversation_history_loader
        self.delivery_client_factory = delivery_client_factory
        self.analytics_gateway = analytics_gateway
        self.followup_model_client = followup_model_client
        self._followup_provider_call_guard: Optional[RuntimeV7ProviderCallGuard] = None
        self.location_choices_provider = (
            location_choices_provider or ServiceableLocationChoicesProvider()
        )
        self.delivery_mode = _normalize_delivery_mode(delivery_mode)
        self.fetch_manychat_profile = (
            bool(fetch_manychat_profile)
            if fetch_manychat_profile is not None
            else str(os.getenv("RUNTIME_V7_FETCH_MANYCHAT_PROFILE", "0")).strip().lower() in {"1", "true", "yes", "on"}
        )
        self.fetch_manychat_messages = (
            bool(fetch_manychat_messages)
            if fetch_manychat_messages is not None
            else str(os.getenv("RUNTIME_V7_FETCH_MANYCHAT_MESSAGES", "1")).strip().lower() in {"1", "true", "yes", "on"}
        )
        self.apply_manychat_tags = (
            bool(apply_manychat_tags)
            if apply_manychat_tags is not None
            else str(os.getenv("RUNTIME_V7_APPLY_MANYCHAT_TAGS", "1")).strip().lower() in {"1", "true", "yes", "on"}
        )

    async def handle(self, request: RuntimeV7APIRequest, *, request_id: str = "") -> RuntimeV7APIResult:
        """Run one locked customer turn and attach bounded phase telemetry."""

        handler_started = time.perf_counter()
        phase_timings: Dict[str, float] = {}
        user_id = _required_user_id(request)
        channel_user_id = str(request.channel_user_id or user_id).strip()
        request_id = request_id or f"req_{uuid.uuid4().hex}"
        trace_id = f"runtime_v7_api_{request_id}"
        if not request.request_time:
            request.request_time = now_manila_str()
        phase_started = time.perf_counter()
        session_load = self.sessions_gateway.load(
            user_id=user_id,
            channel_user_id=channel_user_id,
            user_id_source=request.user_id_source or request.channel or "manychat",
            reset=bool(request.reset),
        )
        _record_runtime_phase(phase_timings, "session_load", phase_started)
        session_doc = session_load.session_doc
        if (
            _interaction_batching_enabled()
            and _is_tracked_interaction_request(request)
        ):
            phase_started = time.perf_counter()
            self._record_prelock_interaction_event(
                request,
                user_id=user_id,
                session_id=session_doc.session_id,
                request_id=request_id,
            )
            _record_runtime_phase(
                phase_timings,
                "prelock_interaction_record",
                phase_started,
            )
        lock_owner = request_id
        lock_acquired = False
        if _runtime_v7_session_lock_enabled():
            phase_started = time.perf_counter()
            lock_acquired, _lock_waited = await self._acquire_turn_lock(
                user_id=user_id,
                session_id=session_doc.session_id,
                owner=lock_owner,
            )
            _record_runtime_phase(phase_timings, "session_lock_acquire", phase_started)
            if not lock_acquired:
                return await self._recover_chat_turn_after_busy_lock(
                    request,
                    request_id=request_id,
                    trace_id=trace_id,
                    user_id=user_id,
                    channel_user_id=channel_user_id,
                    session_id=session_doc.session_id,
                    lock_owner=lock_owner,
                )
            if not request.reset:
                # load() must run before lock acquisition so we can resolve the
                # session id. A preceding turn can commit after that read but
                # before this request acquires the just-released lock, even when
                # acquire_lock succeeds on its first poll. Always re-read while
                # holding the lock so click allowlists and service state match
                # the customer-visible response that produced this request.
                phase_started = time.perf_counter()
                refreshed_session = self.sessions_gateway.reload_session(
                    user_id=user_id,
                    session_id=session_doc.session_id,
                )
                if refreshed_session is not None:
                    session_doc = refreshed_session
                _record_runtime_phase(phase_timings, "session_reload", phase_started)
        result: Optional[RuntimeV7APIResult] = None
        try:
            result = await self._handle_locked_turn(
                request,
                request_id=request_id,
                trace_id=trace_id,
                user_id=user_id,
                channel_user_id=channel_user_id,
                session_doc=session_doc,
                phase_timings=phase_timings,
            )
        finally:
            if lock_acquired:
                phase_started = time.perf_counter()
                try:
                    self.sessions_gateway.release_lock(
                        user_id=user_id,
                        session_id=session_doc.session_id,
                        owner=lock_owner,
                    )
                except Exception as exc:
                    logger.warning(
                        "Runtime V7 session lock release failed request_id=%s session_id=%s error=%s",
                        request_id,
                        session_doc.session_id,
                        exc,
                    )
                finally:
                    _record_runtime_phase(
                        phase_timings,
                        "session_lock_release",
                        phase_started,
                    )
            _record_runtime_phase(phase_timings, "handler_total", handler_started)
            if result is not None:
                result.turn_record["runtime_phase_timings_ms"] = dict(
                    phase_timings
                )
        assert result is not None
        return result

    async def handle_followup(
        self,
        request: RuntimeV7APIRequest,
        *,
        request_id: str = "",
        force: bool = False,
    ) -> RuntimeV7APIResult:
        """Evaluate, compose, and optionally send one proactive follow-up."""

        user_id = _required_user_id(request)
        channel_user_id = str(request.channel_user_id or user_id).strip()
        request_id = request_id or f"req_{uuid.uuid4().hex}"
        trace_id = f"runtime_v7_followup_{request_id}"
        if not request.request_time:
            request.request_time = now_manila_str()
        request.flow_context = {
            **dict(request.flow_context or {}),
            "trigger": "followup_endpoint",
            "force": bool(force),
        }
        self._followup_provider_call_guard = _tester_provider_call_guard(request)
        session_load = self.sessions_gateway.load(
            user_id=user_id,
            channel_user_id=channel_user_id,
            user_id_source=request.user_id_source or request.channel or "manychat",
            reset=False,
        )
        session_doc = session_load.session_doc
        lock_owner = request_id
        lock_acquired = False
        lock_waited = False
        if _runtime_v7_session_lock_enabled():
            lock_acquired, lock_waited = await self._acquire_turn_lock(
                user_id=user_id,
                session_id=session_doc.session_id,
                owner=lock_owner,
            )
            if not lock_acquired:
                recovery = {
                    "enabled": _runtime_v7_session_lock_recovery_enabled(),
                    "phase": "followup",
                    "initial_wait_exhausted": True,
                }
                if recovery["enabled"]:
                    lock_acquired, _recovery_waited = await self._acquire_turn_lock(
                        user_id=user_id,
                        session_id=session_doc.session_id,
                        owner=lock_owner,
                        wait_s=_runtime_v7_session_lock_recovery_wait_s(),
                    )
                    recovery["secondary_wait_s"] = _runtime_v7_session_lock_recovery_wait_s()
                    recovery["status"] = "lock_acquired" if lock_acquired else "lock_wait_exhausted"
                    request.flow_context = _session_lock_recovery_flow_context(request.flow_context, recovery)
                if not lock_acquired:
                    return self._persist_session_busy_result(
                        request=request,
                        request_id=request_id,
                        trace_id=trace_id,
                        session_id=session_doc.session_id,
                        user_id=user_id,
                        recovery=recovery,
                    )
                session_load = self.sessions_gateway.load(
                    user_id=user_id,
                    channel_user_id=channel_user_id,
                    user_id_source=request.user_id_source or request.channel or "manychat",
                    reset=False,
                )
                session_doc = session_load.session_doc
            if lock_waited:
                session_load = self.sessions_gateway.load(
                    user_id=user_id,
                    channel_user_id=channel_user_id,
                    user_id_source=request.user_id_source or request.channel or "manychat",
                    reset=False,
                )
                session_doc = session_load.session_doc
        try:
            return await self._handle_locked_followup(
                request,
                request_id=request_id,
                trace_id=trace_id,
                user_id=user_id,
                channel_user_id=channel_user_id,
                session_doc=session_doc,
                force=force,
            )
        finally:
            if lock_acquired:
                try:
                    self.sessions_gateway.release_lock(
                        user_id=user_id,
                        session_id=session_doc.session_id,
                        owner=lock_owner,
                    )
                except Exception as exc:
                    logger.warning(
                        "Runtime V7 follow-up session lock release failed request_id=%s session_id=%s error=%s",
                        request_id,
                        session_doc.session_id,
                        exc,
                    )
            self._followup_provider_call_guard = None

    async def _recover_chat_turn_after_busy_lock(
        self,
        request: RuntimeV7APIRequest,
        *,
        request_id: str,
        trace_id: str,
        user_id: str,
        channel_user_id: str,
        session_id: str,
        lock_owner: str,
    ) -> RuntimeV7APIResult:
        """Wait once more after a busy lock and run against the latest visible customer turn."""

        recovery: Dict[str, Any] = {
            "enabled": _runtime_v7_session_lock_recovery_enabled(),
            "phase": "chat",
            "initial_wait_exhausted": True,
        }
        if not recovery["enabled"]:
            recovery["status"] = "disabled"
            return self._persist_session_busy_result(
                request=request,
                request_id=request_id,
                trace_id=trace_id,
                session_id=session_id,
                user_id=user_id,
                recovery=recovery,
            )

        recovery_request, request_recovery = await self._request_with_latest_customer_message_for_lock_recovery(
            request
        )
        recovery.update(request_recovery)
        secondary_wait_s = _runtime_v7_session_lock_recovery_wait_s()
        recovery["secondary_wait_s"] = secondary_wait_s
        lock_acquired, _recovery_waited = await self._acquire_turn_lock(
            user_id=user_id,
            session_id=session_id,
            owner=lock_owner,
            wait_s=secondary_wait_s,
        )
        recovery["status"] = "lock_acquired" if lock_acquired else "lock_wait_exhausted"
        recovery_request.flow_context = _session_lock_recovery_flow_context(recovery_request.flow_context, recovery)
        if not lock_acquired:
            return self._persist_session_busy_result(
                request=recovery_request,
                request_id=request_id,
                trace_id=trace_id,
                session_id=session_id,
                user_id=user_id,
                recovery=recovery,
            )

        session_load = self.sessions_gateway.load(
            user_id=user_id,
            channel_user_id=channel_user_id,
            user_id_source=recovery_request.user_id_source or recovery_request.channel or "manychat",
            reset=False,
        )
        recovered_session_doc = session_load.session_doc
        recovery_request, post_lock_recovery = await self._request_with_latest_customer_message_for_lock_recovery(
            recovery_request,
            processed_message_ids=_processed_inbound_message_ids(
                recovered_session_doc.strategy_state
            ),
        )
        if post_lock_recovery.get("message_selection") == "latest_user_message":
            recovery["post_lock_message_selection"] = "latest_user_message"
            recovery["post_lock_selected_message_id"] = post_lock_recovery.get("selected_message_id") or ""
            recovery["post_lock_selected_message_datetime"] = post_lock_recovery.get("selected_message_datetime") or ""
        recovery_request.flow_context = _session_lock_recovery_flow_context(recovery_request.flow_context, recovery)
        try:
            return await self._handle_locked_turn(
                recovery_request,
                request_id=request_id,
                trace_id=trace_id,
                user_id=user_id,
                channel_user_id=channel_user_id,
                session_doc=recovered_session_doc,
            )
        finally:
            try:
                self.sessions_gateway.release_lock(
                    user_id=user_id,
                    session_id=recovered_session_doc.session_id,
                    owner=lock_owner,
                )
            except Exception as exc:
                logger.warning(
                    "Runtime V7 recovered session lock release failed request_id=%s session_id=%s error=%s",
                    request_id,
                    recovered_session_doc.session_id,
                    exc,
                )

    async def _request_with_latest_customer_message_for_lock_recovery(
        self,
        request: RuntimeV7APIRequest,
        *,
        processed_message_ids: Optional[set[str]] = None,
    ) -> tuple[RuntimeV7APIRequest, Dict[str, Any]]:
        recovery: Dict[str, Any] = {"history_refresh_attempted": False}
        if _is_choice_action_request(request):
            # Button payloads are synthetic, session-authoritative events. They
            # are not guaranteed to appear as customer text in ManyChat, so a
            # transcript refresh could replace a valid click with an older
            # visible customer message.
            recovery["history_refresh_status"] = "skipped_choice_action"
            recovery["message_selection"] = "original_request"
            return self._request_with_session_lock_recovery_context(request, recovery), recovery
        if str(request.channel or "").strip().lower() != "manychat":
            recovery["history_refresh_status"] = "skipped_unsupported_channel"
            return self._request_with_session_lock_recovery_context(request, recovery), recovery

        recovery["history_refresh_attempted"] = True
        loader_result = await asyncio.to_thread(self._load_channel_history_sync, request)
        messages = _messages_from_history_loader_result(loader_result)
        recovery["history_refresh_status"] = (
            str(loader_result.get("status") or "unknown") if isinstance(loader_result, dict) else "unknown"
        )
        recovery["history_message_count"] = len(messages)
        processed_ids = {
            str(value or "").strip()
            for value in (processed_message_ids or set())
            if str(value or "").strip()
        }
        latest = _latest_unprocessed_user_message(
            messages,
            processed_message_ids=processed_ids,
        )
        if not latest:
            latest = _latest_channel_message(messages)
            if processed_ids:
                recovery["all_visible_user_messages_processed"] = True
        if latest:
            recovery["latest_message"] = _compact_channel_message(latest)
        if str(latest.get("role") or "").strip() != "user":
            recovery["message_selection"] = "original_request"
            return self._request_with_session_lock_recovery_context(request, recovery), recovery

        latest_text = _channel_message_text(latest)
        if not latest_text:
            recovery["message_selection"] = "original_request_empty_latest_user_text"
            return self._request_with_session_lock_recovery_context(request, recovery), recovery

        if _same_channel_message(
            latest,
            message_id=str(request.message_id or ""),
            content=request.user_text,
        ):
            recovery["message_selection"] = "original_request_is_latest_user"
            return self._request_with_session_lock_recovery_context(request, recovery), recovery

        latest_message_id = str(latest.get("message_id") or "").strip()
        latest_datetime = str(latest.get("datetime") or "").strip()
        recovery["message_selection"] = "latest_user_message"
        recovery["original_message_id"] = str(request.message_id or "")
        recovery["selected_message_id"] = latest_message_id
        recovery["selected_message_datetime"] = latest_datetime
        latest_channel_event_id = str(latest.get("channel_event_id") or latest.get("event_id") or "").strip()
        recovered_request = replace(
            request,
            user_text=latest_text,
            message_id=latest_message_id,
            message_id_source="session_lock_recovery_latest_user",
            idempotency_key="",
            channel_event_id=latest_channel_event_id,
            request_time=latest_datetime or request.request_time,
            channel_event_ts=latest_datetime,
            conversation_history=[dict(item) for item in (request.conversation_history or []) if isinstance(item, dict)],
            flow_context=_session_lock_recovery_flow_context(request.flow_context, recovery),
            raw_payload=dict(request.raw_payload or {}),
            normalized_payload=_session_lock_recovered_normalized_payload(
                request.normalized_payload,
                latest_text=latest_text,
                latest_message_id=latest_message_id,
                latest_channel_event_id=latest_channel_event_id,
                latest_datetime=latest_datetime,
            ),
        )
        return recovered_request, recovery

    def _request_with_session_lock_recovery_context(
        self,
        request: RuntimeV7APIRequest,
        recovery: Dict[str, Any],
    ) -> RuntimeV7APIRequest:
        return replace(
            request,
            conversation_history=[dict(item) for item in (request.conversation_history or []) if isinstance(item, dict)],
            flow_context=_session_lock_recovery_flow_context(request.flow_context, recovery),
            raw_payload=dict(request.raw_payload or {}),
            normalized_payload=dict(request.normalized_payload or {}),
        )

    def _persist_session_busy_result(
        self,
        *,
        request: RuntimeV7APIRequest,
        request_id: str,
        trace_id: str,
        session_id: str,
        user_id: str,
        recovery: Optional[Dict[str, Any]] = None,
    ) -> RuntimeV7APIResult:
        result = _session_busy_result(
            request=request,
            request_id=request_id,
            trace_id=trace_id,
            session_id=session_id,
            user_id=user_id,
            recovery=recovery,
        )
        self._persist_turn_trace(
            request=request,
            turn=result.turn_record,
            rendered=RuntimeV7ChannelRender(response={}, content_messages=[]),
            turn_trace=result.turn_trace,
            delivery_result=result.delivery_result,
            tagging_result=result.tagging_result,
            session_id=session_id,
            request_id=request_id,
            trace_id=trace_id,
            user_id=user_id,
        )
        return result

    async def _handle_locked_followup(
        self,
        request: RuntimeV7APIRequest,
        *,
        request_id: str,
        trace_id: str,
        user_id: str,
        channel_user_id: str,
        session_doc: Any,
        force: bool,
    ) -> RuntimeV7APIResult:
        state = _runtime_v7_state_from_session(session_doc.strategy_state)
        hydration = await self._hydrate_conversation_for_turn(
            request,
            session_doc=session_doc,
            state=state,
        )
        profile_fields, profile_status = self._fresh_followup_profile_fields(request)
        cadence = str((request.flow_context or {}).get("cadence") or "first").strip().lower()
        case = build_followup_case(
            request_time=request.request_time or now_manila_str(),
            recent_messages=hydration.messages,
            v7_state=state,
            profile_fields=profile_fields,
            cadence=cadence,
        )
        case["profile_load_status"] = profile_status
        context: Dict[str, Any] = {
            "followup_case": case,
            "conversation_hydration": _conversation_hydration_metadata(hydration),
            "route_contract_version": 2,
        }
        context_fingerprint = _followup_case_fingerprint(case)
        request.message_id = str(request.message_id or f"followup_{context_fingerprint}").strip()
        request.message_id_source = str(request.message_id_source or "followup_context").strip()
        request.idempotency_key = str(request.idempotency_key or request.message_id).strip()
        delivery_mode = _normalize_delivery_mode(request.delivery_mode or self.delivery_mode)
        request.delivery_mode = delivery_mode
        inbound_event = _followup_trigger_event(
            request=request,
            request_id=request_id,
            trace_id=trace_id,
            user_id=user_id,
            channel_user_id=channel_user_id,
            context_fingerprint=context_fingerprint,
        )
        turn_id = f"followup_{uuid.uuid4().hex[:12]}"
        llm_calls: List[Dict[str, Any]] = []
        if self.fetch_manychat_messages and hydration.loader_status not in {"success", "loaded", "ok"}:
            return self._finalize_followup_result(
                request=request,
                request_id=request_id,
                trace_id=trace_id,
                user_id=user_id,
                channel_user_id=channel_user_id,
                session_doc=session_doc,
                hydration=hydration,
                inbound_event=inbound_event,
                turn_id=turn_id,
                context=context,
                context_fingerprint=context_fingerprint,
                llm_calls=llm_calls,
                decision={"action": "suppress", "reason": "manychat_transcript_unavailable"},
                composer={},
                rendered=RuntimeV7ChannelRender(response={}, content_messages=[]),
                delivery_result={
                    "status": "suppressed",
                    "reason": "manychat_transcript_unavailable",
                    "delivery_mode": delivery_mode,
                },
                status="suppressed",
            )
        if not hydration.messages:
            return self._finalize_followup_result(
                request=request,
                request_id=request_id,
                trace_id=trace_id,
                user_id=user_id,
                channel_user_id=channel_user_id,
                session_doc=session_doc,
                hydration=hydration,
                inbound_event=inbound_event,
                turn_id=turn_id,
                context=context,
                context_fingerprint=context_fingerprint,
                llm_calls=llm_calls,
                decision={"action": "suppress", "reason": "no_recent_messages"},
                composer={},
                rendered=RuntimeV7ChannelRender(response={}, content_messages=[]),
                delivery_result={"status": "suppressed", "reason": "no_recent_messages", "delivery_mode": delivery_mode},
                status="suppressed",
            )
        stop_reason = followup_stop_reason(
            profile_fields=profile_fields,
            recent_messages=hydration.messages,
        )
        runtime_handoff_stop = _runtime_handoff_stop_reason(state)
        if runtime_handoff_stop:
            stop_reason = runtime_handoff_stop
        if profile_status == "unavailable":
            stop_reason = "manychat_profile_unavailable"
        if stop_reason:
            return self._finalize_followup_result(
                request=request,
                request_id=request_id,
                trace_id=trace_id,
                user_id=user_id,
                channel_user_id=channel_user_id,
                session_doc=session_doc,
                hydration=hydration,
                inbound_event=inbound_event,
                turn_id=turn_id,
                context=context,
                context_fingerprint=context_fingerprint,
                llm_calls=llm_calls,
                decision={"action": "suppress", "reason": stop_reason},
                composer={},
                rendered=RuntimeV7ChannelRender(response={}, content_messages=[]),
                delivery_result={"status": "suppressed", "reason": stop_reason, "delivery_mode": delivery_mode},
                status="suppressed",
            )

        latest = case.get("latest_message") if isinstance(case.get("latest_message"), dict) else {}
        if str(latest.get("role") or "") == "user":
            gate = customer_recovery_gate(case)
            context["followup_gate"] = gate
            if gate.get("status") != "allow":
                reason = str(gate.get("reason") or "customer_turn_recovery_suppressed")
                return self._finalize_followup_result(
                    request=request,
                    request_id=request_id,
                    trace_id=trace_id,
                    user_id=user_id,
                    channel_user_id=channel_user_id,
                    session_doc=session_doc,
                    hydration=hydration,
                    inbound_event=inbound_event,
                    turn_id=turn_id,
                    context=context,
                    context_fingerprint=context_fingerprint,
                    llm_calls=llm_calls,
                    decision={"action": "suppress", "reason": reason},
                    composer={},
                    rendered=RuntimeV7ChannelRender(response={}, content_messages=[]),
                    delivery_result={"status": "suppressed", "reason": reason, "delivery_mode": delivery_mode},
                    status="suppressed",
                )
            return await self._handle_followup_latest_customer_message(
                request,
                request_id=request_id,
                trace_id=trace_id,
                user_id=user_id,
                channel_user_id=channel_user_id,
                session_doc=session_doc,
                latest_customer_message=dict(case.get("latest_customer_message") or {}),
            )

        reconciled_attempts = [
            dict(item)
            for item in case.get("prior_attempts") or []
            if isinstance(item, Mapping) and bool(item.get("reconciliation_pending_persist"))
        ]
        reconciliation_persisted = True
        for reconciled_attempt in reconciled_attempts:
            reconciled_attempt.pop("reconciliation_pending_persist", None)
            reconciled_attempt["updated_at"] = request.request_time or now_manila_str()
            if not self._persist_followup_attempt(
                request=request,
                request_id=request_id,
                user_id=user_id,
                channel_user_id=channel_user_id,
                session_doc=session_doc,
                attempt=reconciled_attempt,
            ):
                reconciliation_persisted = False
                break
        if not reconciliation_persisted:
            return self._finalize_followup_result(
                request=request,
                request_id=request_id,
                trace_id=trace_id,
                user_id=user_id,
                channel_user_id=channel_user_id,
                session_doc=session_doc,
                hydration=hydration,
                inbound_event=inbound_event,
                turn_id=turn_id,
                context=context,
                context_fingerprint=context_fingerprint,
                llm_calls=llm_calls,
                decision={"action": "suppress", "reason": "followup_reconciliation_not_persisted"},
                composer={},
                rendered=RuntimeV7ChannelRender(response={}, content_messages=[]),
                delivery_result={
                    "status": "suppressed",
                    "reason": "followup_reconciliation_not_persisted",
                    "delivery_mode": delivery_mode,
                },
                status="suppressed",
            )

        gate = proactive_followup_gate(case)
        context["followup_gate"] = gate
        if gate.get("status") != "allow":
            reason = str(gate.get("reason") or "proactive_followup_suppressed")
            return self._finalize_followup_result(
                request=request,
                request_id=request_id,
                trace_id=trace_id,
                user_id=user_id,
                channel_user_id=channel_user_id,
                session_doc=session_doc,
                hydration=hydration,
                inbound_event=inbound_event,
                turn_id=turn_id,
                context=context,
                context_fingerprint=context_fingerprint,
                llm_calls=llm_calls,
                decision={"action": "suppress", "reason": reason, "gate": gate},
                composer={},
                rendered=RuntimeV7ChannelRender(response={}, content_messages=[]),
                delivery_result={
                    "status": "suppressed",
                    "reason": reason,
                    "delivery_mode": delivery_mode,
                    "followup_gate": gate,
                },
                status="suppressed",
            )

        promo_brand_result = await asyncio.to_thread(load_current_promo_brands)
        case = build_followup_case(
            request_time=request.request_time or now_manila_str(),
            recent_messages=hydration.messages,
            v7_state=state,
            profile_fields=profile_fields,
            cadence=cadence,
            promo_brand_result=promo_brand_result,
        )
        case["profile_load_status"] = profile_status
        context["followup_case"] = case
        context_fingerprint = _followup_case_fingerprint(case)

        try:
            plan_response = await self._run_followup_model(
                component="followup_generation",
                messages=build_followup_plan_messages(case),
                response_format=build_followup_plan_response_model(case),
                trace_id=trace_id,
                max_tokens=_followup_generation_max_tokens(),
            )
            llm_calls.append(
                _followup_llm_call_record(
                    plan_response,
                    component="followup_generation",
                    round_name="followup_generation",
                )
            )
            decision = parse_followup_plan(str(plan_response.get("content") or ""))
        except Exception as exc:
            decision = {
                "action": "suppress",
                "customer_stance": "unclear",
                "focus_field": None,
                "reason": "followup_generation_model_error",
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
            }
        action = str(decision.get("action") or "suppress")
        validation = validate_and_render_followup(case, decision)
        if action != "send":
            reason = str(decision.get("reason") or f"model_{action}")
            return self._finalize_followup_result(
                request=request,
                request_id=request_id,
                trace_id=trace_id,
                user_id=user_id,
                channel_user_id=channel_user_id,
                session_doc=session_doc,
                hydration=hydration,
                inbound_event=inbound_event,
                turn_id=turn_id,
                context=context,
                context_fingerprint=context_fingerprint,
                llm_calls=llm_calls,
                decision=decision,
                composer=validation,
                rendered=RuntimeV7ChannelRender(response={}, content_messages=[]),
                delivery_result={"status": action, "reason": reason, "delivery_mode": delivery_mode},
                status="deferred" if action == "defer" else "suppressed",
            )
        if validation.get("status") != "valid":
            reason = ",".join(str(item) for item in validation.get("validation_reasons") or []) or "followup_validation_failed"
            return self._finalize_followup_result(
                request=request,
                request_id=request_id,
                trace_id=trace_id,
                user_id=user_id,
                channel_user_id=channel_user_id,
                session_doc=session_doc,
                hydration=hydration,
                inbound_event=inbound_event,
                turn_id=turn_id,
                context=context,
                context_fingerprint=context_fingerprint,
                llm_calls=llm_calls,
                decision=decision,
                composer=validation,
                rendered=RuntimeV7ChannelRender(response={}, content_messages=[]),
                delivery_result={"status": "suppressed", "reason": reason, "delivery_mode": delivery_mode},
                status="validation_failed",
            )

        message = str(validation.get("message") or "").strip()
        rendered = render_turn_for_channel({"runtime_final_response": message, "tool_results": []})
        freshness = await self._freshness_check_before_delivery(
            request,
            hydration=hydration,
            delivery_mode=delivery_mode,
        )
        if freshness.get("status") in {"stale", "fresh_with_newer_user_message", "no_history"}:
            reason = freshness.get("reason") or "newer_channel_message_seen"
            if freshness.get("status") == "no_history":
                reason = "pre_delivery_transcript_unavailable"
            return self._finalize_followup_result(
                request=request,
                request_id=request_id,
                trace_id=trace_id,
                user_id=user_id,
                channel_user_id=channel_user_id,
                session_doc=session_doc,
                hydration=hydration,
                inbound_event=inbound_event,
                turn_id=turn_id,
                context=context,
                context_fingerprint=context_fingerprint,
                llm_calls=llm_calls,
                decision=decision,
                composer=validation,
                rendered=RuntimeV7ChannelRender(response={}, content_messages=[]),
                delivery_result={
                    "status": "suppressed",
                    "reason": reason,
                    "delivery_mode": delivery_mode,
                    "freshness_check": freshness,
                },
                status="suppressed",
            )
        attempt = build_attempt_record(
            case=case,
            plan=decision,
            validation=validation,
            status="sending" if delivery_mode != "return_only" else "evaluated",
            request_id=request_id,
        )
        context["attempt_id"] = attempt.get("attempt_id")
        attempt_persisted = self._persist_followup_attempt(
            request=request,
            request_id=request_id,
            user_id=user_id,
            channel_user_id=channel_user_id,
            session_doc=session_doc,
            attempt=attempt,
        )
        if delivery_mode != "return_only" and not attempt_persisted:
            return self._finalize_followup_result(
                request=request,
                request_id=request_id,
                trace_id=trace_id,
                user_id=user_id,
                channel_user_id=channel_user_id,
                session_doc=session_doc,
                hydration=hydration,
                inbound_event=inbound_event,
                turn_id=turn_id,
                context=context,
                context_fingerprint=context_fingerprint,
                llm_calls=llm_calls,
                decision=decision,
                composer=validation,
                rendered=RuntimeV7ChannelRender(response={}, content_messages=[]),
                delivery_result={
                    "status": "suppressed",
                    "reason": "followup_sending_state_not_persisted",
                    "delivery_mode": delivery_mode,
                },
                status="suppressed",
            )
        delivery_result = await self._deliver_followup_safely(
            request,
            rendered,
            delivery_mode=delivery_mode,
            route="proactive_followup",
        )
        delivery_result["freshness_check"] = freshness
        status = _followup_result_status(delivery_result)
        return self._finalize_followup_result(
            request=request,
            request_id=request_id,
            trace_id=trace_id,
            user_id=user_id,
            channel_user_id=channel_user_id,
            session_doc=session_doc,
            hydration=hydration,
            inbound_event=inbound_event,
            turn_id=turn_id,
            context=context,
            context_fingerprint=context_fingerprint,
            llm_calls=llm_calls,
            decision=decision,
            composer=validation,
            rendered=rendered,
            delivery_result=delivery_result,
            status=status,
        )

    async def _handle_followup_latest_customer_message(
        self,
        request: RuntimeV7APIRequest,
        *,
        request_id: str,
        trace_id: str,
        user_id: str,
        channel_user_id: str,
        session_doc: Any,
        latest_customer_message: Dict[str, Any],
    ) -> RuntimeV7APIResult:
        """Route latest customer messages from follow-up triggers to normal chat."""

        latest_text = str(latest_customer_message.get("content") or "").strip()
        if not latest_text:
            return RuntimeV7APIResult(
                response={},
                content_messages=[],
                images=[],
                payment={},
                delivery_result={
                    "status": "suppressed",
                    "reason": "latest_customer_message_empty",
                    "delivery_mode": request.delivery_mode,
                },
                tagging_result={"tags_to_add": []},
                turn_record={
                    "turn_id": f"followup_{uuid.uuid4().hex[:12]}",
                    "turn_type": "followup",
                    "user_message": "",
                    "runtime_final_response": "",
                    "tool_results": [],
                    "llm_calls": [],
                    "followup": {"status": "suppressed", "decision": {"reason": "latest_customer_message_empty"}},
                    "flow_stage_after": "followup_suppressed",
                },
                session_id=session_doc.session_id,
                trace_id=trace_id,
                request_id=request_id,
                message_id=request.message_id,
                idempotency_key=request.idempotency_key,
                state_saved=False,
                status="suppressed",
            )
        latest_message_id = str(latest_customer_message.get("message_id") or "").strip()
        request.user_text = latest_text
        if latest_message_id:
            request.message_id = latest_message_id
            request.message_id_source = "followup_latest_customer_message"
        else:
            request.message_id = _synthetic_customer_message_id(
                user_id=user_id,
                timestamp=str(latest_customer_message.get("datetime") or request.channel_event_ts or ""),
                content=latest_text,
            )
            request.message_id_source = "followup_latest_customer_message_synthetic"
        request.idempotency_key = request.message_id
        request.channel_event_ts = str(latest_customer_message.get("datetime") or request.channel_event_ts or "").strip()
        request.flow_context = {
            **dict(request.flow_context or {}),
            "trigger": "followup_endpoint_latest_customer_message",
            "routed_to": "runtime_v7_chat",
            "route": "customer_turn_recovery",
            "late_reply_apology_required": True,
        }
        request.normalized_payload = {
            **dict(request.normalized_payload or {}),
            "trigger": "followup_endpoint_latest_customer_message",
            "user_text": latest_text,
            "message_id": request.message_id,
            "message_id_source": request.message_id_source,
        }
        request.raw_payload = {
            **dict(request.raw_payload or {}),
            "followup_latest_customer_message": dict(latest_customer_message),
        }
        return await self._handle_locked_turn(
            request,
            request_id=request_id,
            trace_id=trace_id,
            user_id=user_id,
            channel_user_id=channel_user_id,
            session_doc=session_doc,
        )

    async def _run_followup_model(
        self,
        *,
        component: str,
        messages: Sequence[Dict[str, Any]],
        response_format: Any,
        trace_id: str,
        max_tokens: int,
    ) -> Dict[str, Any]:
        client = self._get_followup_model_client(trace_id=trace_id)
        metadata = _metadata(trace_id, component)
        if component == "followup_generation":
            metadata["prompt_version"] = "runtime_v7_followup_generation_v2"
        acomplete = getattr(client, "acomplete", None)
        if callable(acomplete):
            return dict(
                await acomplete(
                    messages=messages,
                    tools=None,
                    tool_choice="none",
                    metadata=metadata,
                    response_format=response_format,
                    max_tokens=max_tokens,
                )
            )
        complete = getattr(client, "complete", None)
        if not callable(complete):
            raise TypeError(f"{component}_client_missing_complete")
        return dict(
            await asyncio.to_thread(
                complete,
                messages=messages,
                tools=[],
                tool_choice="none",
                metadata=metadata,
                response_format=response_format,
                max_tokens=max_tokens,
            )
        )

    def _get_followup_model_client(self, *, trace_id: str) -> Any:
        if self.followup_model_client is None:
            self.followup_model_client = _build_followup_model_client(
                trace_id=trace_id,
                provider_call_guard=self._followup_provider_call_guard,
            )
        return self.followup_model_client

    def _fresh_followup_profile_fields(self, request: RuntimeV7APIRequest) -> tuple[Dict[str, Any], str]:
        """Load authoritative profile/tag state for the follow-up route."""

        if self.profile_loader is not None:
            try:
                fetched = self.profile_loader(request)
            except Exception:
                return {}, "unavailable"
            return (dict(fetched or {}), "loaded") if isinstance(fetched, dict) else ({}, "unavailable")
        if self.fetch_manychat_profile:
            fetched = _load_manychat_profile(request)
            return (dict(fetched), "loaded") if fetched else ({}, "unavailable")
        # Direct unit/harness callers may inject a trusted snapshot while the
        # production router always forces a fresh ManyChat profile read.
        return dict(request.profile_fields or {}), "injected"

    def _persist_followup_attempt(
        self,
        *,
        request: RuntimeV7APIRequest,
        request_id: str,
        user_id: str,
        channel_user_id: str,
        session_doc: Any,
        attempt: Mapping[str, Any],
    ) -> bool:
        """Persist an attempt transition while the session lock is held."""

        strategy_state = dict(session_doc.strategy_state or {})
        v7_state = _runtime_v7_state_from_session(strategy_state)
        previous = v7_state.get("followup") if isinstance(v7_state.get("followup"), dict) else {}
        v7_state["followup"] = upsert_attempt(previous, attempt)
        v7_state["updated_at"] = now_manila_str()
        strategy_state[V7_STATE_KEY] = v7_state
        session_doc.strategy_state = strategy_state
        return self.sessions_gateway.save(
            user_doc=UserDoc(
                user_id=user_id,
                channel_user_id=channel_user_id or user_id,
                active_session_id=session_doc.session_id,
                updated_at=now_manila_str(),
                user_id_source=request.user_id_source or request.channel or "manychat",
            ),
            session_doc=session_doc,
            expected_revision=getattr(session_doc, "revision", None),
            request_id=request_id,
            use_cas=True,
        )

    def _finalize_followup_result(
        self,
        *,
        request: RuntimeV7APIRequest,
        request_id: str,
        trace_id: str,
        user_id: str,
        channel_user_id: str,
        session_doc: Any,
        hydration: ConversationHydrationResult,
        inbound_event: Dict[str, Any],
        turn_id: str,
        context: Dict[str, Any],
        context_fingerprint: str,
        llm_calls: Sequence[Dict[str, Any]],
        decision: Dict[str, Any],
        composer: Dict[str, Any],
        rendered: RuntimeV7ChannelRender,
        delivery_result: Dict[str, Any],
        status: str,
    ) -> RuntimeV7APIResult:
        tagging_result = {"tags_to_add": []}
        sent = bool(status == "success" and rendered.text)
        logged_decision = _followup_log_payload(decision)
        logged_composer = _followup_log_payload(composer)
        turn = _followup_turn_record(
            turn_id=turn_id,
            context=context,
            context_fingerprint=context_fingerprint,
            llm_calls=llm_calls,
            decision=logged_decision,
            composer=logged_composer,
            rendered=rendered,
            delivery_result=delivery_result,
            status=status,
        )
        state_saved = self._save_followup_state(
            user_id=user_id,
            channel_user_id=channel_user_id,
            user_id_source=request.user_id_source or request.channel or "manychat",
            request_id=request_id,
            session_doc=session_doc,
            hydration=hydration,
            rendered=rendered,
            turn=turn,
            context=context,
            context_fingerprint=context_fingerprint,
            sent=sent,
            delivery_result=delivery_result,
            decision=logged_decision,
            composer=logged_composer,
            trace_id=trace_id,
        )
        if sent and not state_saved:
            delivery_result = {
                **delivery_result,
                "original_status": str(delivery_result.get("status") or "success"),
                "status": "delivery_unknown",
                "reason": "followup_post_delivery_state_not_persisted",
            }
            status = "delivery_unknown"
            sent = False
            turn["flow_stage_after"] = "followup_evaluated"
            turn["followup"]["status"] = status
            turn["followup"]["delivery_status"] = "delivery_unknown"
            turn["followup"]["delivery_reason"] = delivery_result["reason"]
        turn_trace = build_turn_trace(
            inbound_event=inbound_event,
            turn_record=turn,
            delivery_result=delivery_result,
            tagging_result=tagging_result,
            state_saved=state_saved,
        )
        self._persist_turn_trace(
            request=request,
            turn=turn,
            rendered=rendered,
            turn_trace=turn_trace,
            delivery_result=delivery_result,
            tagging_result=tagging_result,
            session_id=session_doc.session_id,
            request_id=request_id,
            trace_id=trace_id,
            user_id=user_id,
        )
        self._persist_followup_event(
            request=request,
            request_id=request_id,
            trace_id=trace_id,
            session_id=session_doc.session_id,
            user_id=user_id,
            context=context,
            context_fingerprint=context_fingerprint,
            llm_calls=llm_calls,
            decision=logged_decision,
            validation=logged_composer,
            delivery_result=delivery_result,
            sent=sent,
        )
        return RuntimeV7APIResult(
            response=rendered.response,
            content_messages=rendered.content_messages,
            images=rendered.images,
            payment=rendered.payment,
            delivery_result=delivery_result,
            tagging_result=tagging_result,
            turn_record=turn,
            session_id=session_doc.session_id,
            trace_id=trace_id,
            request_id=request_id,
            message_id=request.message_id,
            idempotency_key=request.idempotency_key,
            state_saved=state_saved,
            status=status,
            turn_trace=turn_trace,
        )

    def _persist_followup_event(
        self,
        *,
        request: RuntimeV7APIRequest,
        request_id: str,
        trace_id: str,
        session_id: str,
        user_id: str,
        context: Mapping[str, Any],
        context_fingerprint: str,
        llm_calls: Sequence[Mapping[str, Any]],
        decision: Mapping[str, Any],
        validation: Mapping[str, Any],
        delivery_result: Mapping[str, Any],
        sent: bool,
    ) -> None:
        if self.analytics_gateway is None:
            return
        case = context.get("followup_case") if isinstance(context.get("followup_case"), Mapping) else {}
        usage = _aggregate_followup_llm_usage(llm_calls)
        attempt_status = _followup_attempt_status(
            sent=sent,
            decision=decision,
            validation=validation,
            delivery_result=delivery_result,
        )
        payload = {
            "request_id": request_id,
            "ts": now_manila_str(),
            "trace_id": trace_id,
            "session_id": session_id,
            "user_id": user_id,
            "channel": request.channel,
            "business_unit": "gulong",
            "runtime_version": "v7",
            "route": str(case.get("route") or "proactive_followup"),
            "cadence": str(case.get("cadence") or ""),
            "action": str(decision.get("action") or "suppress"),
            "stance": str(decision.get("customer_stance") or "unclear"),
            "focus_field": str(validation.get("focus_field") or decision.get("focus_field") or ""),
            "validation_status": str(validation.get("status") or "not_applicable"),
            "validation_reasons": list(validation.get("validation_reasons") or []),
            "evidence_refs": list(validation.get("evidence_refs") or []),
            "attempt_status": attempt_status,
            "delivery_status": str(delivery_result.get("status") or ""),
            "delivery_reason": str(delivery_result.get("reason") or ""),
            "tokens_in": int(usage.get("prompt_tokens") or 0),
            "tokens_out": int(usage.get("completion_tokens") or 0),
            "tokens_total": int(usage.get("total_tokens") or 0),
            "latency_ms": int(usage.get("latency_ms") or 0),
            "context_fingerprint": context_fingerprint,
            "conversation_anchor_id": str(case.get("conversation_anchor_id") or ""),
            "release_sha": os.getenv("GIT_SHA", ""),
            "meta": {
                "profile_load_status": case.get("profile_load_status"),
                "gate": context.get("followup_gate") or {},
                "next_step_candidates": case.get("next_step_candidates") or [],
                "benefit_refs": validation.get("benefit_refs") or [],
                "transport_retry_count": sum(
                    len(call.get("transport_retry_events") or [])
                    for call in llm_calls
                    if isinstance(call, Mapping)
                ),
                "prior_sent_same_cadence": any(
                    isinstance(item, Mapping)
                    and str(item.get("status") or "") == "sent"
                    and str(item.get("cadence") or "") == str(case.get("cadence") or "")
                    for item in case.get("prior_attempts") or []
                ),
            },
        }
        try:
            _safe_enqueue_analytics(self.analytics_gateway, "enqueue_followup_event_log", payload)
        except Exception as exc:
            logger.warning("Follow-up event analytics enqueue failed request_id=%s error=%s", request_id, exc)
        _emit_followup_alerts(payload)

    def _save_followup_state(
        self,
        *,
        user_id: str,
        channel_user_id: str,
        user_id_source: str,
        request_id: str,
        session_doc: Any,
        hydration: ConversationHydrationResult,
        rendered: RuntimeV7ChannelRender,
        turn: Dict[str, Any],
        context: Dict[str, Any],
        context_fingerprint: str,
        sent: bool,
        delivery_result: Dict[str, Any],
        decision: Dict[str, Any],
        composer: Dict[str, Any],
        trace_id: str,
    ) -> bool:
        now = now_manila_str()
        strategy_state = dict(session_doc.strategy_state or {})
        v7_state = _runtime_v7_state_from_session(strategy_state)
        previous = v7_state.get("followup") if isinstance(v7_state.get("followup"), dict) else {}
        case = context.get("followup_case") if isinstance(context.get("followup_case"), dict) else {}
        validation = dict(composer or {})
        if not validation.get("message") and rendered.text:
            validation["message"] = rendered.text
        attempt_status = _followup_attempt_status(
            sent=sent,
            decision=decision,
            validation=validation,
            delivery_result=delivery_result,
        )
        attempt = build_attempt_record(
            case=case,
            plan=decision,
            validation=validation,
            status=attempt_status,
            request_id=request_id,
            delivery_result=delivery_result,
            existing_attempt_id=str(context.get("attempt_id") or ""),
        )
        attempt["updated_at"] = now
        followup_state = upsert_attempt(previous, attempt)
        followup_state.update(
            {
                "last_evaluated_at": now,
                "last_decision": str(decision.get("action") or "suppress"),
                "last_decision_reason": str(decision.get("reason") or ""),
                "last_context_fingerprint": context_fingerprint,
                "last_delivery_status": str(delivery_result.get("status") or ""),
                "last_delivery_reason": str(delivery_result.get("reason") or ""),
                "last_request_id": request_id,
                "last_trace_id": trace_id,
            }
        )
        if sent:
            followup_state["last_sent_context_fingerprint"] = context_fingerprint
            followup_state["last_message_preview"] = str(rendered.text or "")[:240]
            session_doc.messages.append(MessageTurn(role="assistant", text=str(rendered.text or ""), ts=now))
            session_doc.messages = session_doc.messages[-40:]
            base_messages = hydration.channel_messages or hydration.messages
            messages = append_current_turn_to_channel_history(
                base_messages,
                user_text="",
                assistant_text=str(rendered.text or ""),
                user_message_id="",
                assistant_message_id=f"assistant_followup_{context_fingerprint}",
                timestamp=now,
            )
            strategy_state[CHANNEL_CONVERSATION_HISTORY_STATE_KEY] = build_channel_history_cache(
                messages,
                source="firestore_runtime_cache",
                refresh_status=hydration.cache_status,
                metadata=_conversation_hydration_metadata(hydration),
            )
        v7_state["followup"] = followup_state
        v7_state["updated_at"] = now
        strategy_state[V7_STATE_KEY] = v7_state
        session_doc.strategy_state = strategy_state
        return self.sessions_gateway.save(
            user_doc=UserDoc(
                user_id=user_id,
                channel_user_id=channel_user_id or user_id,
                active_session_id=session_doc.session_id,
                updated_at=now,
                user_id_source=user_id_source or "manychat",
            ),
            session_doc=session_doc,
            expected_revision=getattr(session_doc, "revision", None),
            request_id=request_id,
            use_cas=True,
        )

    async def _handle_locked_turn(
        self,
        request: RuntimeV7APIRequest,
        *,
        request_id: str,
        trace_id: str,
        user_id: str,
        channel_user_id: str,
        session_doc: Any,
        phase_timings: Optional[Dict[str, float]] = None,
    ) -> RuntimeV7APIResult:
        phase_timings = phase_timings if phase_timings is not None else {}
        phase_started = time.perf_counter()
        state = _runtime_v7_state_from_session(session_doc.strategy_state)
        _apply_promo_action_runtime_context(request, state)
        conversation_hydration = await self._hydrate_conversation_for_turn(
            request,
            session_doc=session_doc,
            state=state,
        )
        _record_runtime_phase(
            phase_timings,
            "conversation_hydration",
            phase_started,
        )
        message_identity = _resolve_message_identity(
            request,
            hydration=conversation_hydration,
            user_id=user_id,
        )
        message_id = message_identity["message_id"]
        message_id_source = message_identity["message_id_source"]
        idempotency_key = str(request.idempotency_key or message_id).strip()
        inbound_event = build_inbound_event(
            request_id=request_id,
            trace_id=trace_id,
            runtime_version="v7",
            user_id=user_id,
            channel_user_id=channel_user_id,
            channel=request.channel,
            message_id=message_id,
            message_id_source=message_id_source,
            idempotency_key=idempotency_key,
            raw_payload=request.raw_payload,
            normalized_payload=request.normalized_payload,
            channel_event_id=request.channel_event_id,
            channel_event_ts=request.channel_event_ts or str(conversation_hydration.current_message.get("datetime") or ""),
            flow_context=request.flow_context,
        )
        replay = _inbound_event_replay(session_doc.strategy_state, inbound_event)
        if replay:
            if _is_customer_turn_recovery(request):
                return await self._handle_customer_recovery_replay(
                    request=request,
                    request_id=request_id,
                    trace_id=trace_id,
                    user_id=user_id,
                    channel_user_id=channel_user_id,
                    session_doc=session_doc,
                    hydration=conversation_hydration,
                    inbound_event=inbound_event,
                    replay=replay,
                )
            replay_turn = {
                "turn_id": replay.get("turn_id") or "replayed_turn",
                "user_message": request.user_text,
                "runtime_final_response": replay.get("response_text") or "",
                "tool_results": [],
                "llm_calls": [],
                "tagging": dict(replay.get("tagging_result") or {}),
                "inbound_event": inbound_event,
                "replayed_from_inbound_event": True,
            }
            replay_delivery = {
                "status": "replayed",
                "reason": "duplicate_inbound_event",
                "event_key": inbound_event.get("event_key"),
            }
            replay_trace = build_turn_trace(
                inbound_event={**inbound_event, "status": "replayed"},
                turn_record=replay_turn,
                delivery_result=replay_delivery,
                tagging_result=dict(replay.get("tagging_result") or {}),
                state_saved=True,
            )
            replay_rendered = RuntimeV7ChannelRender(
                response=dict(replay.get("response") or {}),
                content_messages=[
                    dict(item)
                    for item in replay.get("content_messages") or []
                    if isinstance(item, dict)
                ],
                images=[
                    dict(item)
                    for item in replay.get("images") or []
                    if isinstance(item, dict)
                ],
                payment=dict(replay.get("payment") or {}),
                text=str(replay.get("response_text") or ""),
            )
            self._persist_turn_trace(
                request=request,
                turn=replay_turn,
                rendered=replay_rendered,
                turn_trace=replay_trace,
                delivery_result=replay_delivery,
                tagging_result=dict(replay.get("tagging_result") or {}),
                session_id=session_doc.session_id,
                request_id=request_id,
                trace_id=trace_id,
                user_id=user_id,
            )
            return RuntimeV7APIResult(
                response=dict(replay_rendered.response),
                content_messages=list(replay_rendered.content_messages),
                images=[dict(item) for item in replay.get("images") or [] if isinstance(item, dict)],
                payment=dict(replay.get("payment") or {}),
                delivery_result=replay_delivery,
                tagging_result=dict(replay.get("tagging_result") or {}),
                turn_record=replay_turn,
                session_id=session_doc.session_id,
                trace_id=trace_id,
                request_id=request_id,
                message_id=message_id,
                idempotency_key=idempotency_key,
                state_saved=True,
                turn_trace=replay_trace,
            )
        phase_started = time.perf_counter()
        profile_fields = self._profile_fields(request)
        if self.harness_factory is build_runtime_v7_harness:
            harness = build_runtime_v7_harness(
                session_doc.session_id,
                profile_fields,
                trace_id,
                user_id=user_id,
                provider_call_guard=_tester_provider_call_guard(request),
            )
        else:
            harness = self.harness_factory(session_doc.session_id, profile_fields, trace_id)
        _hydrate_harness(harness, state)
        _record_runtime_phase(
            phase_timings,
            "profile_and_harness_hydration",
            phase_started,
        )
        handoff_stop_reason = _runtime_handoff_stop_reason(state)
        if handoff_stop_reason:
            delivery_result = {
                "status": "suppressed",
                "reason": handoff_stop_reason,
                "delivery_mode": _normalize_delivery_mode(
                    request.delivery_mode or self.delivery_mode
                ),
            }
            turn = {
                "turn_id": "turn_handoff_suppressed_" + uuid.uuid4().hex[:16],
                "user_message": request.user_text,
                "runtime_final_response": "",
                "tool_results": [],
                "llm_calls": [],
                "tagging": {
                    "tags_to_add": [],
                    "tag_apply_skipped": True,
                    "tag_apply_skip_reason": handoff_stop_reason,
                },
                "human_handoff_state_after_turn": deepcopy(
                    harness.human_handoff_state
                ),
                "inbound_event": inbound_event,
            }
            turn_trace = build_turn_trace(
                inbound_event=inbound_event,
                turn_record=turn,
                delivery_result=delivery_result,
                tagging_result=dict(turn["tagging"]),
                state_saved=False,
            )
            self._persist_turn_trace(
                request=request,
                turn=turn,
                rendered=RuntimeV7ChannelRender(
                    response={},
                    content_messages=[],
                ),
                turn_trace=turn_trace,
                delivery_result=delivery_result,
                tagging_result=dict(turn["tagging"]),
                session_id=session_doc.session_id,
                request_id=request_id,
                trace_id=trace_id,
                user_id=user_id,
            )
            return RuntimeV7APIResult(
                response={},
                content_messages=[],
                images=[],
                payment={},
                delivery_result=delivery_result,
                tagging_result=dict(turn["tagging"]),
                turn_record=turn,
                session_id=session_doc.session_id,
                trace_id=trace_id,
                request_id=request_id,
                message_id=message_id,
                idempotency_key=idempotency_key,
                state_saved=False,
                status="suppressed",
                turn_trace=turn_trace,
            )
        tracked_interaction = (
            _interaction_batching_enabled()
            and _is_tracked_interaction_request(request)
        )
        interaction_resolution_turn = (
            tracked_interaction
            or (
                _interaction_batching_enabled()
                and _has_unresolved_interaction_history(harness)
            )
        )
        pre_interaction_harness_state = (
            _export_harness_state(harness)
            if interaction_resolution_turn
            else {}
        )
        interaction_state_snapshot = (
            _snapshot_interaction_transition_state(harness)
            if interaction_resolution_turn
            else {}
        )
        _remember_promo_action_attempt(harness, request)
        _remember_choice_action_attempt(harness, request)
        choice_action_validation = _public_choice_action_validation(
            getattr(harness, "latest_choice_action", {}),
            request=request,
        )
        if choice_action_validation.get("status") == "duplicate":
            turn = {
                "turn_id": "turn_duplicate_choice_" + uuid.uuid4().hex[:16],
                "user_message": request.user_text,
                "runtime_final_response": "",
                "tool_results": [],
                "llm_calls": [],
                "tagging": {"tags_to_add": [], "tag_apply_skipped": True},
                "choice_action_validation": choice_action_validation,
                "inbound_event": inbound_event,
                "semantic_duplicate_choice_suppressed": True,
            }
            delivery_result = {
                "status": "suppressed",
                "reason": "duplicate_choice_action",
                "delivery_mode": _normalize_delivery_mode(
                    request.delivery_mode or self.delivery_mode
                ),
            }
            tagging_result = dict(turn["tagging"])
            turn_trace = build_turn_trace(
                inbound_event=inbound_event,
                turn_record=turn,
                delivery_result=delivery_result,
                tagging_result=tagging_result,
                state_saved=False,
            )
            self._persist_turn_trace(
                request=request,
                turn=turn,
                rendered=RuntimeV7ChannelRender(
                    response={},
                    content_messages=[],
                ),
                turn_trace=turn_trace,
                delivery_result=delivery_result,
                tagging_result=tagging_result,
                session_id=session_doc.session_id,
                request_id=request_id,
                trace_id=trace_id,
                user_id=user_id,
            )
            return RuntimeV7APIResult(
                response={},
                content_messages=[],
                images=[],
                payment={},
                delivery_result=delivery_result,
                tagging_result=tagging_result,
                turn_record=turn,
                session_id=session_doc.session_id,
                trace_id=trace_id,
                request_id=request_id,
                message_id=message_id,
                idempotency_key=idempotency_key,
                state_saved=False,
                status="suppressed",
                turn_trace=turn_trace,
            )
        interaction_packet = _compile_current_interaction_packet(
            harness,
            request=request,
        )
        if tracked_interaction:
            interaction_packet = (
                _apply_button_only_ambiguity_envelope(
                    interaction_packet
                )
            )
        if (
            interaction_packet
            and _interaction_batching_enabled()
            and _current_interaction_is_valid(harness, request)
        ):
            phase_started = time.perf_counter()
            settle_freshness = await self._settle_tracked_interaction(
                request,
                hydration=conversation_hydration,
                session_id=session_doc.session_id,
            )
            _record_runtime_phase(
                phase_timings,
                "interaction_settle",
                phase_started,
            )
            if settle_freshness.get("status") == "fresh_with_newer_user_message":
                _restore_interaction_transition_state(
                    harness,
                    interaction_state_snapshot,
                )
                _mark_current_interaction_delivery_status(
                    harness,
                    request=request,
                    status="superseded_before_composition",
                )
                delivery_result = {
                    "status": "suppressed",
                    "reason": "interaction_turn_superseded",
                    "delivery_mode": _normalize_delivery_mode(
                        request.delivery_mode or self.delivery_mode
                    ),
                    "freshness_check": settle_freshness,
                }
                turn = {
                    "turn_id": "turn_interaction_superseded_"
                    + uuid.uuid4().hex[:16],
                    "user_message": request.user_text,
                    "runtime_final_response": "",
                    "tool_results": [],
                    "llm_calls": [],
                    "tagging": {
                        "tags_to_add": [],
                        "tag_apply_skipped": True,
                    },
                    "interaction_packet": interaction_packet,
                    "interaction_turn_superseded": True,
                    "inbound_event": inbound_event,
                }
                state_saved = self._save_provisional_interaction_state(
                    user_id=user_id,
                    channel_user_id=channel_user_id,
                    user_id_source=(
                        request.user_id_source
                        or request.channel
                        or "manychat"
                    ),
                    request_id=request_id,
                    session_doc=session_doc,
                    harness=harness,
                    turn=turn,
                    inbound_event=inbound_event,
                    delivery_result=delivery_result,
                )
                turn_trace = build_turn_trace(
                    inbound_event=inbound_event,
                    turn_record=turn,
                    delivery_result=delivery_result,
                    tagging_result=dict(turn["tagging"]),
                    state_saved=state_saved,
                )
                self._persist_turn_trace(
                    request=request,
                    turn=turn,
                    rendered=RuntimeV7ChannelRender(
                        response={},
                        content_messages=[],
                    ),
                    turn_trace=turn_trace,
                    delivery_result=delivery_result,
                    tagging_result=dict(turn["tagging"]),
                    session_id=session_doc.session_id,
                    request_id=request_id,
                    trace_id=trace_id,
                    user_id=user_id,
                )
                return RuntimeV7APIResult(
                    response={},
                    content_messages=[],
                    images=[],
                    payment={},
                    delivery_result=delivery_result,
                    tagging_result=dict(turn["tagging"]),
                    turn_record=turn,
                    session_id=session_doc.session_id,
                    trace_id=trace_id,
                    request_id=request_id,
                    message_id=message_id,
                    idempotency_key=idempotency_key,
                    state_saved=state_saved,
                    status="suppressed",
                    turn_trace=turn_trace,
                )
        if (
            tracked_interaction
            and interaction_packet.get("state_commit_deferred")
        ):
            _restore_interaction_transition_state(
                harness,
                interaction_state_snapshot,
            )
        if _conversation_messages_include_product_inclusions(conversation_hydration.messages):
            harness.product_inclusions_sent = True
        product_inclusions_previously_sent = bool(harness.product_inclusions_sent)
        service_policy_note_ids_previously_sent = list(
            dict.fromkeys(
                getattr(harness, "service_policy_note_ids_sent", []) or []
            )
        )
        existing_tags = _existing_tag_names(profile_fields)
        model_led_interaction = bool(
            interaction_packet and _interaction_batching_enabled()
        )
        harness.turn_surface_planner = (
            lambda partial_turn: _plan_customer_turn_surfaces(
                partial_turn,
                request=request,
                harness=harness,
                provider=self.location_choices_provider,
            )
        )
        harness.location_plan_executor = (
            lambda args: _execute_location_choice_plan(
                args,
                request=request,
                harness=harness,
                provider=self.location_choices_provider,
            )
        )
        phase_started = time.perf_counter()
        turn = await asyncio.to_thread(
            harness.run_turn,
            request.user_text,
            image_urls=_extract_image_urls_from_text(request.user_text),
            conversation_history=conversation_hydration.messages,
            request_time_override=request.request_time or now_manila_str(),
            existing_tags=existing_tags,
            response_seed_overrides=_response_seed_overrides_for_flow(request.flow_context),
            validated_choice_context=(
                request.flow_context.get("choice_action_runtime_context")
                if isinstance(request.flow_context, dict)
                else None
            ),
            interaction_packet=interaction_packet,
        )
        _record_runtime_phase(phase_timings, "harness_run", phase_started)
        phase_started = time.perf_counter()
        if interaction_packet.get("state_commit_deferred"):
            _restore_interaction_transition_state(
                harness,
                interaction_state_snapshot,
                restore_service_observations=False,
            )
            _commit_validated_interaction_decision(
                harness,
                packet=interaction_packet,
                turn=turn,
            )
            _refresh_turn_state_after_interaction_decision(
                harness,
                packet=interaction_packet,
                turn=turn,
                pre_interaction_state=pre_interaction_harness_state,
            )
        else:
            _commit_nonbatched_location_choice_state(
                harness,
                request=request,
                turn=turn,
            )
        if choice_action_validation:
            turn["choice_action_validation"] = choice_action_validation
        turn["product_inclusions_previously_sent"] = product_inclusions_previously_sent
        turn["product_price_list_delivery_fingerprints"] = (
            _delivered_product_price_list_fingerprints(
                getattr(harness, "product_presentation_history", [])
            )
        )
        turn["service_policy_note_ids_previously_sent"] = (
            service_policy_note_ids_previously_sent
        )
        turn["ingress_conversation_history"] = conversation_hydration.messages
        turn["conversation_hydration"] = _conversation_hydration_metadata(conversation_hydration)
        turn["inbound_event"] = inbound_event
        model_composed_complete_turn = final_composer_output_accepted(turn)
        # The final composer owns natural connective prose and surface choice,
        # not commercial source authority. Promo-provider evidence therefore
        # remains a deterministic boundary for both composer and fallback paths.
        _apply_promo_provider_truth_guard(turn)
        if not model_composed_complete_turn:
            _apply_payment_policy_truth_guard(
                turn,
                request=request,
                harness=harness,
            )
        # Typed commercial claims are provider-derived observability, not
        # model-authored prose. Preserve them even when the validated final
        # composer owns the visible answer and legacy truth rewrites are
        # intentionally skipped.
        _record_commercial_payment_claims(turn)
        _apply_submit_authorization_truth_guard(turn)
        _apply_single_product_location_progression_guard(turn)
        rendered = render_turn_for_channel(turn, profile_fields=profile_fields)
        _record_runtime_phase(
            phase_timings,
            "post_model_state_and_render",
            phase_started,
        )
        delivery_mode = _normalize_delivery_mode(request.delivery_mode or self.delivery_mode)
        phase_started = time.perf_counter()
        freshness = await self._freshness_check_before_delivery(
            request,
            hydration=conversation_hydration,
            delivery_mode=delivery_mode,
            session_id=session_doc.session_id,
        )
        _record_runtime_phase(
            phase_timings,
            "pre_delivery_freshness",
            phase_started,
        )
        turn["pre_delivery_freshness_check"] = freshness
        recovery_freshness_blocked = _is_customer_turn_recovery(request) and freshness.get("status") in {
            "fresh_with_newer_user_message",
            "no_history",
        }
        interaction_freshness_blocked = (
            model_led_interaction
            and tracked_interaction
            and freshness.get("status") == "fresh_with_newer_user_message"
            and not _turn_contains_authorized_side_effect(turn)
        )
        if (
            freshness.get("status") == "stale"
            or recovery_freshness_blocked
            or interaction_freshness_blocked
        ):
            reason = freshness.get("reason") or "newer_channel_message_seen"
            if freshness.get("status") == "fresh_with_newer_user_message":
                reason = (
                    "interaction_turn_superseded"
                    if interaction_freshness_blocked
                    else "newer_user_message_seen_recovery_suppressed"
                )
            if freshness.get("status") == "no_history":
                reason = "pre_delivery_transcript_unavailable"
            delivery_result = {
                "status": "suppressed",
                "reason": reason,
                "delivery_mode": delivery_mode,
                "freshness_check": freshness,
            }
            tagging_result = dict(turn.get("tagging") or {})
            tagging_result["tag_apply_skipped"] = True
            tagging_result["tag_apply_skip_reason"] = "stale_turn_delivery_suppressed"
            turn["tagging"] = tagging_result
            if interaction_freshness_blocked:
                _restore_harness_for_superseded_interaction(
                    harness,
                    pre_interaction_harness_state,
                )
                _mark_current_interaction_delivery_status(
                    harness,
                    request=request,
                    status="superseded_before_delivery",
                )
                turn["interaction_turn_superseded"] = True
                state_saved = self._save_provisional_interaction_state(
                    user_id=user_id,
                    channel_user_id=channel_user_id,
                    user_id_source=(
                        request.user_id_source
                        or request.channel
                        or "manychat"
                    ),
                    request_id=request_id,
                    session_doc=session_doc,
                    harness=harness,
                    turn=turn,
                    inbound_event=inbound_event,
                    delivery_result=delivery_result,
                )
            else:
                state_saved = False
        else:
            recovery_attempt: Dict[str, Any] = {}
            if _is_customer_turn_recovery(request):
                recovery_case = {
                    "request_time": request.request_time or now_manila_str(),
                    "conversation_anchor_id": str(inbound_event.get("message_id") or ""),
                    "cadence": str((request.flow_context or {}).get("cadence") or "first"),
                    "route": "customer_turn_recovery",
                }
                recovery_validation = {
                    "status": "valid",
                    "action": "send",
                    "message": rendered.text,
                    "focus_field": None,
                    "evidence_refs": [str(inbound_event.get("message_id") or "")],
                    "benefit_refs": [],
                    "validation_reasons": [],
                }
                recovery_attempt = build_attempt_record(
                    case=recovery_case,
                    plan={"action": "send", "customer_stance": "active", "focus_field": None},
                    validation=recovery_validation,
                    status="sending" if delivery_mode != "return_only" else "evaluated",
                    request_id=request_id,
                )
                persisted = self._persist_followup_attempt(
                    request=request,
                    request_id=request_id,
                    user_id=user_id,
                    channel_user_id=channel_user_id,
                    session_doc=session_doc,
                    attempt=recovery_attempt,
                )
                if not persisted:
                    delivery_result = {
                        "status": "suppressed",
                        "reason": "customer_recovery_sending_state_not_persisted",
                        "delivery_mode": delivery_mode,
                    }
                    tagging_result = {"tags_to_add": [], "tag_apply_skipped": True}
                    turn["tagging"] = tagging_result
                    turn_trace = build_turn_trace(
                        inbound_event=inbound_event,
                        turn_record=turn,
                        delivery_result=delivery_result,
                        tagging_result=tagging_result,
                        state_saved=False,
                    )
                    return RuntimeV7APIResult(
                        response={},
                        content_messages=[],
                        images=[],
                        payment={},
                        delivery_result=delivery_result,
                        tagging_result=tagging_result,
                        turn_record=turn,
                        session_id=session_doc.session_id,
                        trace_id=trace_id,
                        request_id=request_id,
                        message_id=message_id,
                        idempotency_key=idempotency_key,
                        state_saved=False,
                        status="suppressed",
                        turn_trace=turn_trace,
                    )
            if recovery_attempt:
                phase_started = time.perf_counter()
                delivery_result = await self._deliver_followup_safely(
                    request,
                    rendered,
                    delivery_mode=delivery_mode,
                    route="customer_turn_recovery",
                )
            else:
                phase_started = time.perf_counter()
                delivery_result = await self._deliver(request, rendered, delivery_mode=delivery_mode)
            _record_runtime_phase(phase_timings, "delivery", phase_started)
            if recovery_attempt:
                recovery_attempt["status"] = _customer_recovery_attempt_status(delivery_result)
                recovery_attempt["updated_at"] = now_manila_str()
                recovery_attempt["delivery_result"] = _compact_delivery_result_for_state(delivery_result)
                self._persist_followup_attempt(
                    request=request,
                    request_id=request_id,
                    user_id=user_id,
                    channel_user_id=channel_user_id,
                    session_doc=session_doc,
                    attempt=recovery_attempt,
                )
            _remember_promo_delivery_result(harness, rendered, delivery_result)
            _remember_promo_action_delivery_result(harness, request, delivery_result)
            _remember_choice_delivery_result(harness, rendered, delivery_result)
            _remember_choice_action_delivery_result(harness, request, rendered, delivery_result)
            _remember_interaction_batch_delivery_result(
                harness,
                turn=turn,
                delivery_result=delivery_result,
            )
            _remember_product_delivery_result(harness, rendered, delivery_result)
            if recovery_attempt and not _delivery_result_means_customer_visible(delivery_result):
                tagging_result = dict(turn.get("tagging") or {})
                tagging_result["tag_apply_skipped"] = True
                tagging_result["tag_apply_skip_reason"] = "customer_recovery_not_delivered"
            else:
                phase_started = time.perf_counter()
                tagging_result = await self._apply_tags(
                    request,
                    turn.get("tagging") or {},
                    delivery_mode=delivery_mode,
                    turn=turn,
                )
                _record_runtime_phase(phase_timings, "tag_application", phase_started)
            turn["tagging"] = tagging_result
            if _rendered_product_inclusions_visible(rendered) and (
                _delivery_result_means_customer_visible(delivery_result)
                or (
                    request.tester
                    and str(delivery_mode or "").strip().lower()
                    == "return_only"
                )
            ):
                harness.product_inclusions_sent = True
                turn["product_inclusions_sent_after_turn"] = True
            if rendered.service_policy_note_ids and _delivery_result_means_customer_visible(
                delivery_result
            ):
                harness.service_policy_note_ids_sent = list(
                    dict.fromkeys(
                        [
                            *(
                                getattr(
                                    harness,
                                    "service_policy_note_ids_sent",
                                    [],
                                )
                                or []
                            ),
                            *rendered.service_policy_note_ids,
                        ]
                    )
                )[-20:]
                turn["service_policy_note_ids_sent_after_turn"] = list(
                    harness.service_policy_note_ids_sent
                )
            if recovery_attempt and not _delivery_result_means_customer_visible(delivery_result):
                state_saved = self._save_customer_recovery_render_state(
                    user_id=user_id,
                    channel_user_id=channel_user_id,
                    user_id_source=request.user_id_source or request.channel or "manychat",
                    request_id=request_id,
                    session_doc=session_doc,
                    turn=turn,
                    response_text=rendered.text or turn.get("runtime_final_response") or "",
                    inbound_event=inbound_event,
                    rendered=rendered,
                    delivery_result=delivery_result,
                    tagging_result=tagging_result,
                )
            else:
                phase_started = time.perf_counter()
                state_saved = self._save_session_state(
                    user_id=user_id,
                    channel_user_id=channel_user_id,
                    user_id_source=request.user_id_source or request.channel or "manychat",
                    request_id=request_id,
                    session_doc=session_doc,
                    harness=harness,
                    turn=turn,
                    response_text=rendered.text or turn.get("runtime_final_response") or "",
                    inbound_event=inbound_event,
                    conversation_hydration=conversation_hydration,
                    rendered=rendered,
                    delivery_result=delivery_result,
                    tagging_result=tagging_result,
                    phase_timings=phase_timings,
                )
                _record_runtime_phase(
                    phase_timings,
                    "session_persistence",
                    phase_started,
                )
            if recovery_attempt and _delivery_result_means_customer_visible(delivery_result) and not state_saved:
                delivery_result = {
                    **delivery_result,
                    "original_status": str(delivery_result.get("status") or "success"),
                    "status": "delivery_unknown",
                    "reason": "customer_recovery_post_delivery_state_not_persisted",
                }
        if state_saved:
            phase_started = time.perf_counter()
            self._clear_resolved_interaction_inbox(
                user_id=user_id,
                session_id=session_doc.session_id,
                turn=turn,
                delivery_result=delivery_result,
            )
            _record_runtime_phase(
                phase_timings,
                "interaction_inbox_cleanup",
                phase_started,
            )
        turn_trace = build_turn_trace(
            inbound_event=inbound_event,
            turn_record=turn,
            delivery_result=delivery_result,
            tagging_result=tagging_result,
            state_saved=state_saved,
        )
        phase_started = time.perf_counter()
        self._persist_turn_trace(
            request=request,
            turn=turn,
            rendered=rendered,
            turn_trace=turn_trace,
            delivery_result=delivery_result,
            tagging_result=tagging_result,
            session_id=session_doc.session_id,
            request_id=request_id,
            trace_id=trace_id,
            user_id=user_id,
        )
        _record_runtime_phase(
            phase_timings,
            "trace_persistence",
            phase_started,
        )
        if _is_customer_turn_recovery(request):
            recovery_case = {
                "request_time": request.request_time or now_manila_str(),
                "conversation_anchor_id": str(inbound_event.get("message_id") or ""),
                "cadence": str((request.flow_context or {}).get("cadence") or "first"),
                "route": "customer_turn_recovery",
            }
            recovery_validation = {
                "status": "valid" if rendered.text else "invalid",
                "focus_field": None,
                "evidence_refs": [str(inbound_event.get("message_id") or "")],
                "benefit_refs": [],
                "validation_reasons": [] if rendered.text else ["customer_recovery_response_empty"],
            }
            self._persist_followup_event(
                request=request,
                request_id=request_id,
                trace_id=trace_id,
                session_id=session_doc.session_id,
                user_id=user_id,
                context={"followup_case": recovery_case, "route_contract_version": 2},
                context_fingerprint=_followup_case_fingerprint(recovery_case),
                llm_calls=[dict(item) for item in turn.get("llm_calls") or [] if isinstance(item, Mapping)],
                decision={
                    "action": "send",
                    "customer_stance": "active",
                    "focus_field": None,
                    "reason": "customer_turn_recovery",
                },
                validation=recovery_validation,
                delivery_result=delivery_result,
                sent=_delivery_result_means_customer_visible(delivery_result),
            )
        return RuntimeV7APIResult(
            response=rendered.response,
            content_messages=rendered.content_messages,
            images=rendered.images,
            payment=rendered.payment,
            promo_presentation=rendered.promo_presentation,
            choice_presentations=rendered.choice_presentations,
            product_presentations=rendered.product_presentations,
            delivery_result=delivery_result,
            tagging_result=tagging_result,
            turn_record=turn,
            session_id=session_doc.session_id,
            trace_id=trace_id,
            request_id=request_id,
            message_id=message_id,
            idempotency_key=idempotency_key,
            state_saved=state_saved,
            turn_trace=turn_trace,
        )

    async def _handle_customer_recovery_replay(
        self,
        *,
        request: RuntimeV7APIRequest,
        request_id: str,
        trace_id: str,
        user_id: str,
        channel_user_id: str,
        session_doc: Any,
        hydration: ConversationHydrationResult,
        inbound_event: Dict[str, Any],
        replay: Dict[str, Any],
    ) -> RuntimeV7APIResult:
        """Resolve a previously rendered customer turn without regenerating it."""

        ledger_status = str(replay.get("_ledger_status") or "completed")
        prior_delivery = replay.get("delivery_result") if isinstance(replay.get("delivery_result"), dict) else {}
        response_text = str(replay.get("response_text") or "").strip()
        recovery_case = {
            "request_time": request.request_time or now_manila_str(),
            "conversation_anchor_id": str(inbound_event.get("message_id") or ""),
            "cadence": str((request.flow_context or {}).get("cadence") or "first"),
            "route": "customer_turn_recovery",
        }
        recovery_context = {"followup_case": recovery_case, "route_contract_version": 2}
        recovery_fingerprint = _followup_case_fingerprint(recovery_case)

        def finish(
            *,
            status: str,
            delivery_result: Dict[str, Any],
            action: str = "suppress",
            validation: Optional[Mapping[str, Any]] = None,
        ) -> RuntimeV7APIResult:
            validation_payload = dict(validation or {})
            self._persist_followup_event(
                request=request,
                request_id=request_id,
                trace_id=trace_id,
                session_id=session_doc.session_id,
                user_id=user_id,
                context=recovery_context,
                context_fingerprint=recovery_fingerprint,
                llm_calls=[],
                decision={
                    "action": action,
                    "customer_stance": "active" if action == "send" else "unclear",
                    "focus_field": None,
                    "reason": str(delivery_result.get("reason") or "customer_turn_recovery_replay"),
                },
                validation=validation_payload,
                delivery_result=delivery_result,
                sent=status == "success",
            )
            return _customer_recovery_replay_result(
                request=request,
                request_id=request_id,
                trace_id=trace_id,
                session_id=session_doc.session_id,
                inbound_event=inbound_event,
                replay=replay,
                status=status,
                delivery_result=delivery_result,
            )

        seen = _response_text_seen_in_transcript(response_text, hydration.channel_messages or hydration.messages)
        prior_delivery_status = str(prior_delivery.get("status") or "").strip().lower()
        confirmed_delivered = ledger_status == "delivered" or prior_delivery_status == "success"
        if confirmed_delivered or seen:
            reason = "customer_turn_already_handled" if confirmed_delivered else "customer_turn_delivery_reconciled"
            return finish(
                status="suppressed",
                delivery_result={"status": "suppressed", "reason": reason, "prior_delivery": prior_delivery},
            )
        effective_ledger_status = ledger_status
        if ledger_status == "completed":
            if prior_delivery_status in {"error", "failed", "failure"}:
                effective_ledger_status = "delivery_failed"
            elif prior_delivery_status == "skipped" and str(prior_delivery.get("reason") or "") == "return_only":
                effective_ledger_status = "rendered"
            else:
                logger.error(
                    "customer_turn_recovery_legacy_delivery_ambiguous request_id=%s user_id=%s event_key=%s",
                    request_id,
                    user_id,
                    inbound_event.get("event_key"),
                )
                return finish(
                    status="suppressed",
                    delivery_result={"status": "suppressed", "reason": "customer_turn_delivery_ambiguous"},
                )
        if effective_ledger_status == "delivery_unknown" and hydration.loader_status not in {"success", "loaded", "ok"}:
            logger.error(
                "customer_turn_recovery_delivery_ambiguous request_id=%s user_id=%s event_key=%s",
                request_id,
                user_id,
                inbound_event.get("event_key"),
            )
            return finish(
                status="suppressed",
                delivery_result={"status": "suppressed", "reason": "customer_turn_delivery_ambiguous"},
            )
        if effective_ledger_status not in {"rendered", "delivery_failed", "delivery_unknown"} or not response_text:
            return finish(
                status="suppressed",
                delivery_result={"status": "suppressed", "reason": "customer_turn_replay_not_redeliverable"},
            )

        rendered = RuntimeV7ChannelRender(
            response=dict(replay.get("response") or {}),
            content_messages=[dict(item) for item in replay.get("content_messages") or [] if isinstance(item, dict)],
            images=[dict(item) for item in replay.get("images") or [] if isinstance(item, dict)],
            payment=dict(replay.get("payment") or {}),
            text=response_text,
        )
        freshness = await self._freshness_check_before_delivery(
            request,
            hydration=hydration,
            delivery_mode=request.delivery_mode,
        )
        if freshness.get("status") in {"stale", "fresh_with_newer_user_message"}:
            return finish(
                status="suppressed",
                delivery_result={
                    "status": "suppressed",
                    "reason": freshness.get("reason") or "newer_channel_message_seen",
                    "freshness_check": freshness,
                },
            )

        recovery_validation = {
            "status": "valid",
            "action": "send",
            "message": response_text,
            "focus_field": None,
            "evidence_refs": [str(inbound_event.get("message_id") or "")],
            "benefit_refs": [],
            "validation_reasons": [],
        }
        followup_state = _runtime_v7_state_from_session(session_doc.strategy_state).get("followup") or {}
        prior_attempt = next(
            (
                item
                for item in reversed(followup_state.get("attempts") or [])
                if isinstance(item, Mapping)
                and str(item.get("route") or "") == "customer_turn_recovery"
                and str(item.get("conversation_anchor_id") or "") == recovery_case["conversation_anchor_id"]
            ),
            {},
        )
        attempt = build_attempt_record(
            case=recovery_case,
            plan={"action": "send", "customer_stance": "active", "focus_field": None},
            validation=recovery_validation,
            status="sending" if request.delivery_mode != "return_only" else "evaluated",
            request_id=request_id,
            existing_attempt_id=str(prior_attempt.get("attempt_id") or ""),
        )
        if not self._persist_followup_attempt(
            request=request,
            request_id=request_id,
            user_id=user_id,
            channel_user_id=channel_user_id,
            session_doc=session_doc,
            attempt=attempt,
        ):
            return finish(
                status="suppressed",
                delivery_result={"status": "suppressed", "reason": "customer_recovery_sending_state_not_persisted"},
                action="send",
                validation=recovery_validation,
            )

        delivery_result = await self._deliver_followup_safely(
            request,
            rendered,
            delivery_mode=request.delivery_mode,
            route="customer_turn_recovery",
        )
        delivery_result["reason"] = (
            "customer_turn_stored_response_redelivered"
            if str(delivery_result.get("status") or "").lower() == "success"
            else str(delivery_result.get("reason") or "customer_turn_stored_response_redelivery_failed")
        )
        delivery_result["freshness_check"] = freshness
        _update_inbound_event_delivery(
            session_doc.strategy_state,
            event_key=str(inbound_event.get("event_key") or ""),
            delivery_result=delivery_result,
        )
        attempt["status"] = _customer_recovery_attempt_status(delivery_result)
        attempt["updated_at"] = now_manila_str()
        attempt["delivery_result"] = _compact_delivery_result_for_state(delivery_result)
        persisted = self._persist_followup_attempt(
            request=request,
            request_id=request_id,
            user_id=user_id,
            channel_user_id=channel_user_id,
            session_doc=session_doc,
            attempt=attempt,
        )
        if not persisted and _delivery_result_means_customer_visible(delivery_result):
            delivery_result = {
                **delivery_result,
                "status": "delivery_unknown",
                "reason": "customer_recovery_post_delivery_state_not_persisted",
            }
        result_status = _followup_result_status(delivery_result)
        return finish(
            status=result_status,
            delivery_result=delivery_result,
            action="send",
            validation=recovery_validation,
        )

    async def _acquire_turn_lock(
        self,
        *,
        user_id: str,
        session_id: str,
        owner: str,
        wait_s: Optional[float] = None,
    ) -> tuple[bool, bool]:
        wait_s = max(0.0, float(os.getenv("RUNTIME_V7_SESSION_LOCK_WAIT_S", "25") or "25") if wait_s is None else wait_s)
        poll_s = max(0.05, float(os.getenv("RUNTIME_V7_SESSION_LOCK_POLL_S", "0.35") or "0.35"))
        ttl_s = max(5, int(os.getenv("RUNTIME_V7_SESSION_LOCK_TTL_S", "90") or "90"))
        deadline = time.monotonic() + wait_s
        waited = False
        while True:
            ok, _lock_until = self.sessions_gateway.acquire_lock(
                user_id=user_id,
                session_id=session_id,
                owner=owner,
                ttl_seconds=ttl_s,
            )
            if ok:
                return True, waited
            if time.monotonic() >= deadline:
                return False, waited
            waited = True
            await asyncio.sleep(poll_s)

    def _record_prelock_interaction_event(
        self,
        request: RuntimeV7APIRequest,
        *,
        user_id: str,
        session_id: str,
        request_id: str,
    ) -> None:
        """Publish a click before lock wait so an older turn can yield."""

        recorder = getattr(
            self.sessions_gateway,
            "record_interaction_event",
            None,
        )
        if not callable(recorder):
            return
        event = _prelock_interaction_event(
            request,
            request_id=request_id,
        )
        if not event:
            return
        try:
            recorder(
                user_id=user_id,
                session_id=session_id,
                event=event,
                max_events=max(10, _interaction_max_events() * 2),
            )
        except Exception as exc:
            logger.warning(
                "Runtime V7 pre-lock interaction record failed "
                "request_id=%s session_id=%s error=%s",
                request_id,
                session_id,
                exc,
            )

    def _clear_resolved_interaction_inbox(
        self,
        *,
        user_id: str,
        session_id: str,
        turn: Mapping[str, Any],
        delivery_result: Dict[str, Any],
    ) -> None:
        """Acknowledge an inbox batch only after durable resolution."""

        packet = (
            turn.get("interaction_packet")
            if isinstance(turn.get("interaction_packet"), dict)
            else {}
        )
        decision = (
            turn.get("interaction_decision_validation")
            if isinstance(
                turn.get("interaction_decision_validation"),
                dict,
            )
            else {}
        )
        if (
            not packet
            or decision.get("status") != "valid"
            or _interaction_delivery_status(delivery_result)
            not in {"success", "evaluated"}
        ):
            return
        event_ids = [
            str(event.get("event_id") or "").strip()
            for event in packet.get("events") or []
            if isinstance(event, dict)
            and str(event.get("event_id") or "").strip()
        ]
        remover = getattr(
            self.sessions_gateway,
            "remove_interaction_events",
            None,
        )
        if not callable(remover) or not event_ids:
            return
        try:
            remover(
                user_id=user_id,
                session_id=session_id,
                event_ids=event_ids,
            )
        except Exception as exc:
            logger.warning(
                "Runtime V7 interaction inbox cleanup failed "
                "session_id=%s error=%s",
                session_id,
                exc,
            )

    def _newer_prelock_interaction(
        self,
        request: RuntimeV7APIRequest,
        *,
        session_id: str,
    ) -> Dict[str, Any]:
        """Return a newer tracked event that arrived while this turn ran."""

        loader = getattr(
            self.sessions_gateway,
            "load_interaction_events",
            None,
        )
        if not callable(loader) or not session_id:
            return {}
        try:
            events = loader(
                user_id=_required_user_id(request),
                session_id=session_id,
            )
        except Exception as exc:
            logger.warning(
                "Runtime V7 pre-lock interaction read failed "
                "session_id=%s error=%s",
                session_id,
                exc,
            )
            return {}
        return _latest_newer_prelock_interaction(
            events,
            current=_prelock_interaction_event(request),
        )

    async def _freshness_check_before_delivery(
        self,
        request: RuntimeV7APIRequest,
        *,
        hydration: ConversationHydrationResult,
        delivery_mode: str,
        allow_return_only: bool = False,
        allow_disabled: bool = False,
        session_id: str = "",
    ) -> Dict[str, Any]:
        if (
            _normalize_delivery_mode(delivery_mode) == "return_only"
            and not allow_return_only
        ):
            return {"status": "skipped", "reason": "return_only"}
        if str(request.channel or "").strip().lower() != "manychat":
            return {"status": "skipped", "reason": "unsupported_channel"}
        if (
            not _runtime_v7_delivery_freshness_enabled()
            and not allow_disabled
        ):
            return {"status": "skipped", "reason": "disabled"}
        if _is_tracked_interaction_request(request):
            newer_interaction = self._newer_prelock_interaction(
                request,
                session_id=session_id,
            )
            if newer_interaction:
                return {
                    "status": "fresh_with_newer_user_message",
                    "reason": "newer_tracked_interaction_seen",
                    "latest_interaction": newer_interaction,
                    "current_interaction": _prelock_interaction_event(request),
                }
        loader_result = await asyncio.to_thread(_load_manychat_messages_for_freshness, request)
        messages = _messages_from_history_loader_result(loader_result)
        if not messages:
            return {
                "status": "no_history",
                "loader_status": loader_result.get("status") if isinstance(loader_result, dict) else "",
            }
        latest = messages[-1]
        current_id = str((hydration.current_message or {}).get("message_id") or request.message_id or "").strip()
        current_text = str(request.user_text or "").strip()
        if _same_channel_message(latest, message_id=current_id, content=current_text):
            return {"status": "fresh", "latest_message": _compact_channel_message(latest)}
        latest_role = str(latest.get("role") or "").strip()
        latest_dt = _parse_datetime(str(latest.get("datetime") or ""))
        current_dt = _parse_datetime(str((hydration.current_message or {}).get("datetime") or request.request_time or ""))
        if latest_role == "human_agent" and latest_dt and current_dt and latest_dt > current_dt:
            return {
                "status": "stale",
                "reason": "newer_human_agent_message_seen",
                "latest_message": _compact_channel_message(latest),
                "current_message_id": current_id,
                "current_message_datetime": str((hydration.current_message or {}).get("datetime") or request.request_time or ""),
            }
        if latest_role == "user" and latest_dt and current_dt and latest_dt > current_dt:
            return {
                "status": "fresh_with_newer_user_message",
                "reason": "newer_user_message_seen_delivery_not_suppressed",
                "latest_message": _compact_channel_message(latest),
                "current_message_id": current_id,
                "current_message_datetime": str((hydration.current_message or {}).get("datetime") or request.request_time or ""),
            }
        return {"status": "fresh", "latest_message": _compact_channel_message(latest)}

    async def _settle_tracked_interaction(
        self,
        request: RuntimeV7APIRequest,
        *,
        hydration: ConversationHydrationResult,
        session_id: str = "",
    ) -> Dict[str, Any]:
        """Give a newer tracked click a bounded chance to join this batch."""

        settle_ms = _interaction_settle_ms()
        max_wait_ms = _interaction_max_wait_ms()
        intentional_wait_ms = min(settle_ms, max_wait_ms)
        if intentional_wait_ms > 0:
            await asyncio.sleep(intentional_wait_ms / 1000.0)
        result = await self._freshness_check_before_delivery(
            request,
            hydration=hydration,
            delivery_mode=(
                request.delivery_mode or self.delivery_mode
            ),
            allow_return_only=True,
            allow_disabled=True,
            session_id=session_id,
        )
        return {
            **result,
            "intentional_wait_ms": intentional_wait_ms,
        }

    def _persist_turn_trace(
        self,
        *,
        request: RuntimeV7APIRequest,
        turn: Dict[str, Any],
        rendered: RuntimeV7ChannelRender,
        turn_trace: Dict[str, Any],
        delivery_result: Dict[str, Any],
        tagging_result: Dict[str, Any],
        session_id: str,
        request_id: str,
        trace_id: str,
        user_id: str,
    ) -> None:
        enriched_tagging = enrich_runtime_v7_analytical_qualifications(
            tagging_result,
            event_id=str(request.channel_event_id or request.message_id or ""),
            channel_event_id=str(request.channel_event_id or ""),
            message_id=str(request.message_id or ""),
            idempotency_key=str(request.idempotency_key or ""),
            request_id=request_id,
            user_id=user_id,
            channel_user_id=str(request.channel_user_id or user_id or ""),
            session_id=session_id,
            trace_id=trace_id,
            turn_id=str(turn.get("turn_id") or ""),
            channel=str(request.channel or ""),
            occurred_at=str(request.channel_event_ts or request.request_time or ""),
            service_environment=os.getenv("SERVICE_ENVIRONMENT", ""),
            runtime_host=os.getenv("RUNTIME_HOST", os.getenv("K_SERVICE", "")),
            release_version=os.getenv("RELEASE_VERSION", ""),
            git_sha=os.getenv("GIT_SHA", ""),
            interaction_context=_qualification_interaction_context(request, turn),
        )
        # Callers reuse this object for session persistence and the API result,
        # so enrich in place before any trace/log representation is produced.
        tagging_result.clear()
        tagging_result.update(enriched_tagging)
        if isinstance(turn, dict):
            turn["tagging"] = dict(tagging_result)
        inbound_event = (
            turn_trace.get("inbound_event")
            if isinstance(turn_trace.get("inbound_event"), Mapping)
            else {}
        )
        if inbound_event:
            refreshed_trace = build_turn_trace(
                inbound_event=inbound_event,
                turn_record=turn,
                delivery_result=delivery_result,
                tagging_result=tagging_result,
                state_saved=str(turn_trace.get("status") or "") == "completed",
            )
            turn_trace.clear()
            turn_trace.update(refreshed_trace)
        payload = _turn_trace_debug_payload(
            request=request,
            turn=turn,
            rendered=rendered,
            turn_trace=turn_trace,
            delivery_result=delivery_result,
            tagging_result=tagging_result,
        )
        if self.analytics_gateway is not None:
            try:
                self.analytics_gateway.enqueue_debug_log(
                    {
                        "request_id": request_id,
                        "trace_id": trace_id,
                        "session_id": session_id,
                        "user_id": user_id,
                        "ts": now_manila_str(),
                        "channel": request.channel,
                        "business_unit": "gulong",
                        "debug_payload": payload,
                    }
                )
            except Exception as exc:
                logger.warning(
                    "Runtime V7 trace BigQuery enqueue failed request_id=%s trace_id=%s error=%s",
                    request_id,
                    trace_id,
                    exc,
                )
            try:
                _emit_normalized_turn_logs(
                    self.analytics_gateway,
                    request=request,
                    turn=turn,
                    rendered=rendered,
                    turn_trace=turn_trace,
                    delivery_result=delivery_result,
                    tagging_result=tagging_result,
                    session_id=session_id,
                    request_id=request_id,
                    trace_id=trace_id,
                    user_id=user_id,
                )
            except Exception as exc:
                logger.warning(
                    "Runtime V7 normalized analytics enqueue failed request_id=%s trace_id=%s error=%s",
                    request_id,
                    trace_id,
                    exc,
                )
        try:
            logger.info(
                "runtime_v7_turn_trace request_id=%s trace_id=%s session_id=%s user_id=%s summary=%s",
                request_id,
                trace_id,
                session_id,
                user_id,
                json.dumps(_compact_trace_log_payload(payload), ensure_ascii=False, default=str),
            )
        except Exception:
            pass

    async def _hydrate_conversation_for_turn(
        self,
        request: RuntimeV7APIRequest,
        *,
        session_doc: Any,
        state: Dict[str, Any],
    ) -> ConversationHydrationResult:
        strategy_state = session_doc.strategy_state if isinstance(session_doc.strategy_state, dict) else {}
        channel_cache = _channel_history_cache_from_strategy_state(strategy_state)
        loaded_history: List[Dict[str, Any]] = []
        refresh_attempted = False
        loader_status = "not_attempted"
        message_age_days = int(os.getenv("RUNTIME_V7_MANYCHAT_MESSAGE_AGE_DAYS", "30") or "30")
        if self._should_refresh_channel_history(request, channel_cache):
            refresh_attempted = True
            loader_result = await asyncio.to_thread(self._load_channel_history_sync, request)
            loaded_history = _messages_from_history_loader_result(loader_result)
            loader_status = str(loader_result.get("status") or "unknown") if isinstance(loader_result, dict) else "unknown"
        hydration = build_conversation_hydration_result(
            session_messages=session_doc.messages,
            request_history=request.conversation_history,
            stored_v7_history=state.get("conversation_history") if isinstance(state, dict) else [],
            cached_channel_history=channel_cache,
            loaded_channel_history=loaded_history,
            current_message_id=str(request.message_id or "").strip(),
            current_user_text=request.user_text,
            current_message_datetime=request.request_time or now_manila_str(),
            message_age_days=max(1, message_age_days),
            reset_requested=bool(request.reset),
            refresh_attempted=refresh_attempted,
            loader_status=loader_status,
        )
        await self._maybe_compare_manychat_cloudsql_history(
            request,
            hydration=hydration,
            message_age_days=max(1, message_age_days),
        )
        return hydration

    def _should_refresh_channel_history(self, request: RuntimeV7APIRequest, channel_cache: Dict[str, Any]) -> bool:
        if bool(request.reset):
            return False
        if request.conversation_history:
            return False
        if str(request.channel or "").strip().lower() != "manychat":
            return False
        if _is_choice_action_request(request):
            return False
        if not self.fetch_manychat_messages and self.conversation_history_loader is None:
            return False
        messages = channel_cache.get("messages") if isinstance(channel_cache, dict) else []
        if not messages:
            return True
        flow_context = request.flow_context if isinstance(request.flow_context, dict) else {}
        trigger = str(flow_context.get("trigger") or "").strip().lower()
        message_source = str(request.message_id_source or "").strip().lower()
        if trigger.startswith("followup_endpoint") or message_source.startswith("followup"):
            return True
        current = str(request.user_text or "").strip()
        if not current:
            return False
        request_message_id = str(request.message_id or request.channel_event_id or "").strip()
        if not request_message_id:
            # Text alone cannot distinguish a new repeated reply ("yes",
            # "proceed", etc.) from an earlier ManyChat message.
            return True
        # If Firestore already has the current inbound message, do not pay the
        # loadMessages cost again; this also enables fast duplicate replay. A
        # provider message ID is authoritative here: falling back to equal text
        # would incorrectly treat a new repeated reply as the cached event.
        return not any(
            str(message.get("message_id") or "").strip() == request_message_id
            for message in messages
            if isinstance(message, dict)
        )

    def _load_channel_history_sync(self, request: RuntimeV7APIRequest) -> Dict[str, Any]:
        if self.conversation_history_loader is not None:
            try:
                loaded = self.conversation_history_loader(request)
                if isinstance(loaded, dict):
                    return dict(loaded)
                if isinstance(loaded, list):
                    return {"status": "success", "data": [dict(item) for item in loaded if isinstance(item, dict)]}
                return {"status": "error", "message": "conversation_history_loader_returned_invalid_shape", "data": []}
            except Exception as exc:
                return {"status": "error", "message": f"{type(exc).__name__}: {exc}", "data": []}
        if not self.fetch_manychat_messages:
            return {"status": "skipped", "message": "manychat_message_fetch_disabled", "data": []}
        return _load_manychat_messages(request)

    async def _maybe_compare_manychat_cloudsql_history(
        self,
        request: RuntimeV7APIRequest,
        *,
        hydration: ConversationHydrationResult,
        message_age_days: int,
    ) -> None:
        if not _manychat_cloudsql_compare_enabled():
            return
        if bool(request.reset) or str(request.channel or "").strip().lower() != "manychat":
            return
        if request.conversation_history:
            return
        if not _manychat_cloudsql_compare_sample_allows(request):
            return
        try:
            result = await asyncio.to_thread(
                load_manychat_messages_from_cloudsql,
                user_id=str(request.user_id),
                user_name=str(request.full_name or ""),
                limit=_manychat_cloudsql_compare_limit(),
                message_age_days=max(1, int(message_age_days or 30)),
            )
            summary: Dict[str, Any] = {
                "enabled": True,
                "cloudsql_status": str(result.get("status") or "unknown"),
                "cloudsql_latency_ms": int(result.get("latency_ms") or 0),
                "cloudsql_row_count": int(result.get("row_count") or 0),
                "hydration_source": hydration.source,
                "hydration_cache_status": hydration.cache_status,
            }
            cloudsql_messages = _messages_from_history_loader_result(result)
            if cloudsql_messages:
                summary.update(
                    compare_manychat_message_sets(
                        hydration.channel_messages or hydration.messages,
                        cloudsql_messages,
                        current_message_id=str(request.message_id or ""),
                        current_user_text=str(request.user_text or ""),
                    )
                )
            else:
                summary["match_status"] = "cloudsql_empty" if summary["cloudsql_status"] == "success" else "cloudsql_unavailable"
            hydration.metadata["cloudsql_read_compare"] = summary
            logger.info(
                "runtime_v7_manychat_cloudsql_compare user_id=%s status=%s match_status=%s summary=%s",
                request.user_id,
                summary.get("cloudsql_status"),
                summary.get("match_status"),
                json.dumps(summary, ensure_ascii=False, default=str),
            )
        except Exception as exc:
            hydration.metadata["cloudsql_read_compare"] = {
                "enabled": True,
                "cloudsql_status": "error",
                "error_type": type(exc).__name__,
                "match_status": "cloudsql_unavailable",
            }
            logger.warning(
                "Runtime V7 ManyChat Cloud SQL compare failed user_id=%s error=%s",
                request.user_id,
                exc,
            )

    def _profile_fields(self, request: RuntimeV7APIRequest) -> Dict[str, Any]:
        profile = dict(request.profile_fields or {})
        for key, value in {
            "user_id": request.user_id,
            "channel_user_id": request.channel_user_id or request.user_id,
            "full_name": request.full_name,
            "first_name": request.first_name,
            "last_name": request.last_name,
            "assigned_agent": request.assigned_agent,
            "agent_assigned": request.assigned_agent,
            "channel": request.channel,
            "channel_subtype": request.channel_subtype,
            "many_chat_id": request.channel_user_id or request.user_id,
        }.items():
            if value not in (None, "", [], {}):
                profile.setdefault(key, value)
        if self.profile_loader is not None:
            fetched = self.profile_loader(request)
        elif self.fetch_manychat_profile:
            fetched = _load_manychat_profile(request)
        else:
            fetched = {}
        for key, value in (fetched or {}).items():
            if value not in (None, "", [], {}):
                profile.setdefault(key, value)
        return profile

    async def _deliver(
        self,
        request: RuntimeV7APIRequest,
        rendered: RuntimeV7ChannelRender,
        *,
        delivery_mode: str,
    ) -> Dict[str, Any]:
        if delivery_mode == "return_only":
            return {"status": "skipped", "reason": "return_only"}
        if str(request.channel or "").lower() != "manychat":
            return {"status": "skipped", "reason": "unsupported_channel", "channel": request.channel}
        client = (
            self.delivery_client_factory(request)
            if self.delivery_client_factory
            else ManyChatAPI(psid=_manychat_recipient_id(request))
        )
        delay_ms = _manychat_bubble_delay_ms()
        max_delayed_messages = _manychat_bubble_delay_max_messages()
        has_cards = any(
            str(message.get("type") or "").strip().lower() == "cards"
            for message in rendered.content_messages
            if isinstance(message, dict)
        )
        if not rendered.contact_actions and not has_cards and _should_deliver_manychat_messages_sequentially(
            rendered.content_messages,
            delay_ms=delay_ms,
            max_delayed_messages=max_delayed_messages,
        ):
            result = await _send_manychat_content_with_bubble_delay(
                client,
                rendered.content_messages,
                channel_subtype=request.channel_subtype or None,
                delay_ms=delay_ms,
                max_delayed_messages=max_delayed_messages,
            )
            result.setdefault("delivery_mode", delivery_mode)
            return result
        if rendered.contact_actions:
            result = await client.send_content(
                rendered.content_messages,
                channel_subtype=request.channel_subtype or None,
                actions=rendered.contact_actions,
            )
        else:
            result = await client.send_content(rendered.content_messages, channel_subtype=request.channel_subtype or None)
        result = dict(result or {})
        result.setdefault("delivery_mode", delivery_mode)
        return result

    async def _deliver_followup_safely(
        self,
        request: RuntimeV7APIRequest,
        rendered: RuntimeV7ChannelRender,
        *,
        delivery_mode: str,
        route: str,
    ) -> Dict[str, Any]:
        """Convert delivery exceptions into durable follow-up failure results."""

        try:
            return await self._deliver(request, rendered, delivery_mode=delivery_mode)
        except Exception as exc:
            logger.exception(
                "Follow-up delivery raised route=%s user_id=%s error_type=%s",
                route,
                request.user_id,
                type(exc).__name__,
            )
            return {
                "status": "error",
                "reason": "followup_delivery_exception",
                "error_type": type(exc).__name__,
                "delivery_mode": delivery_mode,
                "route": route,
            }

    async def _apply_tags(
        self,
        request: RuntimeV7APIRequest,
        tagging_result: Dict[str, Any],
        *,
        delivery_mode: str,
        turn: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        actions = [item for item in tagging_result.get("tags_to_add") or [] if isinstance(item, dict)]
        if not actions or str(request.channel or "").lower() != "manychat":
            return dict(tagging_result or {})
        if not self.apply_manychat_tags or _normalize_delivery_mode(delivery_mode) == "return_only":
            result = dict(tagging_result or {})
            result["tag_apply_skipped"] = True
            result["tag_apply_skip_reason"] = "return_only" if _normalize_delivery_mode(delivery_mode) == "return_only" else "disabled"
            return result
        applied: List[str] = []
        failed: List[Dict[str, Any]] = []
        client = ManyChatAPI(psid=_manychat_recipient_id(request))
        for action in actions:
            tag = str(action.get("tag") or "").strip()
            if not tag:
                continue
            try:
                result = await client.add_tag_by_name(tag)
            except Exception as exc:  # pragma: no cover - defensive delivery boundary
                failed.append({"tag": tag, "error": f"{type(exc).__name__}: {exc}"})
                continue
            if str(result.get("status") or "").lower() == "success":
                applied.append(tag)
            else:
                failed.append({"tag": tag, "error": result.get("message") or result.get("error") or result})
        result = mark_runtime_v7_tags_applied(tagging_result, applied_tags=applied, failed_tags=failed)
        handoff_tag = _handoff_tag_to_note(applied)
        if handoff_tag:
            note = _build_manychat_handoff_note(
                handoff_tag,
                request=request,
                turn=turn or {},
                tagging_result=result,
            )
            if note:
                try:
                    note_result = await client.create_note(note)
                except Exception as exc:  # pragma: no cover - defensive note boundary
                    note_result = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
                result["handoff_note"] = {
                    "tag": handoff_tag,
                    "status": str((note_result or {}).get("status") or "unknown"),
                    "result": note_result,
                    "preview": note[:500],
                }
        return result

    def _save_customer_recovery_render_state(
        self,
        *,
        user_id: str,
        channel_user_id: str,
        user_id_source: str,
        request_id: str,
        session_doc: Any,
        turn: Dict[str, Any],
        response_text: str,
        inbound_event: Dict[str, Any],
        rendered: RuntimeV7ChannelRender,
        delivery_result: Dict[str, Any],
        tagging_result: Dict[str, Any],
    ) -> bool:
        """Persist a replayable recovery result without claiming it was visible."""

        strategy_state = dict(session_doc.strategy_state or {})
        _remember_inbound_event(
            strategy_state,
            inbound_event=inbound_event,
            turn=turn,
            rendered=rendered,
            delivery_result=delivery_result,
            tagging_result=tagging_result,
            response_text=response_text,
        )
        session_doc.strategy_state = strategy_state
        return self.sessions_gateway.save(
            user_doc=UserDoc(
                user_id=user_id,
                channel_user_id=channel_user_id or user_id,
                active_session_id=session_doc.session_id,
                updated_at=now_manila_str(),
                user_id_source=user_id_source or "manychat",
            ),
            session_doc=session_doc,
            expected_revision=getattr(session_doc, "revision", None),
            request_id=request_id,
            use_cas=True,
        )

    def _save_session_state(
        self,
        *,
        user_id: str,
        channel_user_id: str,
        user_id_source: str,
        request_id: str,
        session_doc: Any,
        harness: RuntimeV7Harness,
        turn: Dict[str, Any],
        response_text: str,
        inbound_event: Dict[str, Any],
        conversation_hydration: ConversationHydrationResult,
        rendered: RuntimeV7ChannelRender,
        delivery_result: Dict[str, Any],
        tagging_result: Dict[str, Any],
        phase_timings: Optional[Dict[str, float]] = None,
    ) -> bool:
        phase_timings = phase_timings if phase_timings is not None else {}
        assembly_started = time.perf_counter()
        now = now_manila_str()
        session_doc.last_user_message_at = now
        session_doc.messages.append(MessageTurn(role="user", text=str(turn.get("user_message") or ""), ts=now))
        session_doc.messages.append(MessageTurn(role="assistant", text=str(response_text or ""), ts=now))
        session_doc.messages = session_doc.messages[-40:]
        strategy_state = dict(session_doc.strategy_state or {})
        previous_v7 = _runtime_v7_state_from_session(strategy_state)
        exported_v7 = _export_harness_state(harness)
        if isinstance(previous_v7.get("followup"), dict):
            exported_v7["followup"] = deepcopy(previous_v7["followup"])
        strategy_state[V7_STATE_KEY] = exported_v7
        _remember_channel_conversation_history(
            strategy_state,
            hydration=conversation_hydration,
            user_text=str(turn.get("user_message") or ""),
            assistant_text=str(response_text or ""),
            user_message_id=str(inbound_event.get("message_id") or ""),
            assistant_message_id=f"assistant_{inbound_event.get('event_key') or uuid.uuid4().hex}",
            timestamp=now,
        )
        _remember_inbound_event(
            strategy_state,
            inbound_event=inbound_event,
            turn=turn,
            rendered=rendered,
            delivery_result=delivery_result,
            tagging_result=tagging_result,
            response_text=response_text,
        )
        session_doc.strategy_state = strategy_state
        _record_runtime_phase(
            phase_timings,
            "session_state_assembly",
            assembly_started,
        )
        store_started = time.perf_counter()
        saved = self.sessions_gateway.save(
            user_doc=UserDoc(
                user_id=user_id,
                channel_user_id=channel_user_id or user_id,
                active_session_id=session_doc.session_id,
                updated_at=now,
                user_id_source=user_id_source or "manychat",
            ),
            session_doc=session_doc,
            expected_revision=getattr(session_doc, "revision", None),
            request_id=request_id,
            use_cas=True,
        )
        diagnostics_loader = getattr(
            self.sessions_gateway,
            "last_save_diagnostics",
            None,
        )
        if callable(diagnostics_loader):
            diagnostics = diagnostics_loader()
            if isinstance(diagnostics, dict) and diagnostics:
                turn["session_store_diagnostics"] = diagnostics
        _record_runtime_phase(
            phase_timings,
            "session_store_save",
            store_started,
        )
        return saved

    def _save_provisional_interaction_state(
        self,
        *,
        user_id: str,
        channel_user_id: str,
        user_id_source: str,
        request_id: str,
        session_doc: Any,
        harness: RuntimeV7Harness,
        turn: Dict[str, Any],
        inbound_event: Dict[str, Any],
        delivery_result: Dict[str, Any],
    ) -> bool:
        """Persist a joined click without inventing an assistant conversation turn."""

        now = now_manila_str()
        strategy_state = dict(session_doc.strategy_state or {})
        previous_v7 = _runtime_v7_state_from_session(strategy_state)
        exported_v7 = _export_harness_state(harness)
        if isinstance(previous_v7.get("followup"), dict):
            exported_v7["followup"] = deepcopy(previous_v7["followup"])
        strategy_state[V7_STATE_KEY] = exported_v7
        _remember_inbound_event(
            strategy_state,
            inbound_event=inbound_event,
            turn=turn,
            rendered=RuntimeV7ChannelRender(
                response={},
                content_messages=[],
            ),
            delivery_result=delivery_result,
            tagging_result=dict(turn.get("tagging") or {}),
            response_text="",
        )
        session_doc.strategy_state = strategy_state
        session_doc.last_user_message_at = now
        return self.sessions_gateway.save(
            user_doc=UserDoc(
                user_id=user_id,
                channel_user_id=channel_user_id or user_id,
                active_session_id=session_doc.session_id,
                updated_at=now,
                user_id_source=user_id_source or "manychat",
            ),
            session_doc=session_doc,
            expected_revision=getattr(session_doc, "revision", None),
            request_id=request_id,
            use_cas=True,
        )


def _handoff_tag_to_note(applied_tags: Sequence[str]) -> str:
    tags = {str(tag or "").strip() for tag in applied_tags or [] if str(tag or "").strip()}
    if "Stop Chatbot" in tags:
        return "Human Handoff Requested"
    if "High Intent" in tags:
        return "High Intent"
    if "Moderate Intent" in tags:
        return "Moderate Intent"
    return ""


def _runtime_handoff_stop_reason(state: Mapping[str, Any]) -> str:
    """Suppress proactive bot follow-ups after a durable handoff request."""

    handoff_state = (
        state.get("human_handoff_state")
        if isinstance(state.get("human_handoff_state"), Mapping)
        else {}
    )
    if str(handoff_state.get("status") or "").strip().lower() == "requested":
        return "runtime_human_handoff_requested"
    return ""


def _build_manychat_handoff_note(
    handoff_tag: str,
    *,
    request: RuntimeV7APIRequest,
    turn: Dict[str, Any],
    tagging_result: Dict[str, Any],
) -> str:
    del request  # Notes summarize trusted state, not synthetic click text.
    lines = [f"Gulong.ph CS Handoff | {handoff_tag}"]
    for label, value in _handoff_summary_facts(turn):
        cleaned = _handoff_value(value)
        if cleaned:
            lines.append(f"{label}: {cleaned}")
    pending = _handoff_pending_items(turn, tagging_result)
    lines.append("Pending: " + (", ".join(pending[:5]) if pending else "None"))
    return "\n".join(lines).strip()


def _handoff_summary_facts(turn: Dict[str, Any]) -> List[tuple[str, str]]:
    """Return compact, trusted sales facts for a human CS handoff."""

    lead = turn.get("lead_qualification") if isinstance(turn.get("lead_qualification"), dict) else {}
    present = lead.get("present") if isinstance(lead.get("present"), dict) else {}
    readiness = _handoff_order_readiness(turn)
    collected = readiness.get("collected") if isinstance(readiness.get("collected"), dict) else {}
    selected = (
        turn.get("latest_selected_product_context_after_turn")
        if isinstance(turn.get("latest_selected_product_context_after_turn"), dict)
        else {}
    )
    brand = str(present.get("tire_brand") or selected.get("brand") or "").strip()
    tire_size = str(
        present.get("tire_size")
        or selected.get("tire_size")
        or selected.get("size")
        or ""
    ).strip()
    tire = " | ".join(value for value in (tire_size, brand) if value)
    product = str(
        collected.get("Product")
        or selected.get("label")
        or selected.get("sku_model")
        or ""
    ).strip()
    quantity = str(collected.get("Quantity") or "").replace(" (assumed default)", "").strip()
    total = str(collected.get("Trusted total") or "").strip()
    quantity_total = " | ".join(value for value in (quantity, total) if value)
    location = usable_lead_location(present.get("location"))
    service_location = str(
        collected.get("Installation area")
        or collected.get("Delivery address")
        or collected.get("Delivery area")
        or location
        or ""
    ).strip()
    service = " | ".join(
        value
        for value in (_handoff_fulfillment(collected), service_location)
        if value
    )
    partner = str(collected.get("Installation partner") or "").strip()
    schedule = _handoff_compact_schedule(
        collected.get("Installation schedule")
        or collected.get("Preferred installation schedule")
        or ""
    )
    payment = _handoff_payment_summary(collected)
    full_name = " ".join(
        value
        for value in (
            str(collected.get("First name") or "").strip(),
            str(collected.get("Last name") or "").strip(),
        )
        if value
    )
    contact = " | ".join(
        value
        for value in (
            full_name,
            str(collected.get("Contact number") or "").strip(),
            str(collected.get("Email address") or "").strip(),
        )
        if value
    )
    return [
        ("Tire", tire),
        ("Product", product),
        ("Qty / total", quantity_total),
        ("Service", service),
        ("Partner", partner),
        ("Schedule", schedule),
        ("Payment", payment),
        ("Customer", contact),
    ]


def _handoff_order_readiness(turn: Dict[str, Any]) -> Dict[str, Any]:
    for key in ("order_readiness_after_tools", "order_readiness_before_turn"):
        value = turn.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _handoff_pending_items(
    turn: Dict[str, Any],
    tagging_result: Dict[str, Any],
) -> List[str]:
    readiness = _handoff_order_readiness(turn)
    collected = readiness.get("collected") if isinstance(readiness.get("collected"), dict) else {}
    missing = [
        str(value or "").strip()
        for value in readiness.get("missing") or []
        if str(value or "").strip()
    ]
    lead = turn.get("lead_qualification") if isinstance(turn.get("lead_qualification"), dict) else {}
    present = lead.get("present") if isinstance(lead.get("present"), dict) else {}
    lead_missing = [
        *list(lead.get("missing") or []),
        *list(lead.get("optional_missing") or []),
    ]
    for field_name in lead_missing:
        normalized_field = str(field_name or "").strip()
        if not normalized_field or normalized_field in missing:
            continue
        present_value = (
            present.get(normalized_field)
            or _handoff_collected_lead_value(collected, normalized_field)
        )
        if normalized_field == "location":
            present_value = usable_lead_location(present_value)
        if not present_value:
            missing.append(normalized_field)
    if (
        present.get("location")
        and not usable_lead_location(present.get("location"))
        and "location" not in missing
    ):
        missing.append("location")
    synthetic = (
        tagging_result.get("synthetic_signals")
        if isinstance(tagging_result.get("synthetic_signals"), dict)
        else {}
    )
    if (
        _handoff_has_selected_product(turn)
        and synthetic.get("has_location_or_partner")
        and not synthetic.get("has_schedule_or_payment")
        and not _handoff_has_schedule_or_payment(collected)
        and not any("schedule" in value.casefold() for value in missing)
    ):
        missing.append("Preferred schedule")
    labels = {
        "tire_size": "tire size",
        "tire_brand": "brand or budget",
        "location": "location",
        "contact_number": "contact number",
        "selected_product": "product choice",
        "selected_product_sku": "product choice",
        "Selected product/SKU": "product choice",
        "Trusted customer-facing price/total": "price or total",
        "Fulfillment path or delivery/installation area": "service choice",
        "Complete delivery address": "delivery address",
        "Delivery area/address": "delivery address",
        "Installation area/location": "location",
        "Selected installation schedule": "schedule",
        "Validated installation schedule": "schedule confirmation",
        "Contact number": "contact number",
        "First name": "customer name",
        "Last name": "customer name",
        "Email address": "email",
        "Payment option (Pay Now or Pay Later)": "Pay Now or Pay Later",
        "Reservation payment method": "reservation payment method",
        "Installment bank": "installment bank",
        "Installment term": "installment term",
        "Preferred schedule": "schedule",
    }
    human_labels = [
        _human_handoff_pending_label(value, labels=labels)
        for value in missing
    ]
    return list(dict.fromkeys(value for value in human_labels if value))


def _human_handoff_pending_label(
    value: Any,
    *,
    labels: Mapping[str, str],
) -> str:
    """Return a compact human label for internal readiness field names."""

    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw in labels:
        return labels[raw]
    normalized = " ".join(
        token
        for token in re.split(r"[_/\s]+", raw.casefold())
        if token
    )
    normalized_aliases = {
        "selected product": "product choice",
        "selected product sku": "product choice",
        "product sku": "product choice",
        "tire size": "tire size",
        "tire brand": "brand or budget",
        "contact number": "contact number",
        "first name": "customer name",
        "last name": "customer name",
        "email address": "email",
        "installation area": "location",
        "installation location": "location",
        "selected installation schedule": "schedule",
        "validated installation schedule": "schedule confirmation",
        "payment option": "Pay Now or Pay Later",
        "payment method": "payment method",
    }
    return normalized_aliases.get(normalized, normalized)


def _handoff_collected_lead_value(
    collected: Mapping[str, Any],
    field_name: str,
) -> Any:
    keys = {
        "tire_size": ("Product",),
        "tire_brand": ("Product",),
        "location": (
            "Installation area",
            "Delivery address",
            "Delivery area",
        ),
        "contact_number": ("Contact number",),
    }.get(field_name, ())
    return next(
        (
            collected.get(key)
            for key in keys
            if collected.get(key) not in (None, "", [], {})
        ),
        None,
    )


def _handoff_has_schedule_or_payment(collected: Mapping[str, Any]) -> bool:
    return any(
        collected.get(key) not in (None, "", [], {})
        for key in (
            "Installation schedule",
            "Preferred installation schedule",
            "Payment option",
            "Payment method",
            "Reservation payment method",
            "Balance payment method",
        )
    )


def _handoff_has_selected_product(turn: Dict[str, Any]) -> bool:
    readiness = _handoff_order_readiness(turn)
    collected = readiness.get("collected") if isinstance(readiness.get("collected"), dict) else {}
    return bool(
        collected.get("Product")
        or turn.get("latest_selected_product_context_after_turn")
    )


def _handoff_fulfillment(collected: Mapping[str, Any]) -> str:
    value = str(collected.get("Fulfillment") or "").strip()
    basis = " ".join(
        str(collected.get(key) or "")
        for key in (
            "Fulfillment",
            "Installation area",
            "Installation partner",
            "Delivery address",
            "Delivery area",
        )
    ).casefold()
    if "installation" in basis:
        return "Installation"
    if "delivery" in basis:
        return "Delivery"
    return value


def _handoff_payment_summary(collected: Mapping[str, Any]) -> str:
    option = str(collected.get("Payment option") or "").strip()
    if option == "Pay Later / Pay After Service":
        option = "Pay Later"
    method = str(collected.get("Payment method") or "").strip()
    reservation = str(collected.get("Reservation payment method") or "").strip()
    balance = str(collected.get("Balance payment method") or "").strip()
    bank = str(collected.get("Payment bank") or "").strip()
    term = str(collected.get("Installment term") or "").strip()
    values = [option]
    if method:
        values.append(method)
    if reservation:
        values.append(f"Reservation: {reservation}")
    if balance:
        values.append(f"Balance: {balance}")
    if bank and not any(bank.casefold() in value.casefold() for value in values):
        values.append(bank)
    if term and not any(term.casefold() in value.casefold() for value in values):
        values.append(term)
    return " | ".join(dict.fromkeys(value for value in values if value))


def _handoff_compact_schedule(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    text = re.sub(
        r"\b(\d{4})-(\d{2})-(\d{2})\b",
        lambda match: datetime(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        ).strftime("%b %d").replace(" 0", " "),
        text,
    )
    text = re.sub(r"\b([A-Z][a-z]{2}) (\d{1,2}), \d{4}\b", r"\1 \2", text)
    return text.replace(" (flexible preference)", " (preferred)")


def _handoff_value(value: Any, *, max_chars: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().strip("|").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _build_followup_model_client(
    *,
    trace_id: str,
    provider_call_guard: Optional[RuntimeV7ProviderCallGuard] = None,
) -> RuntimeV7LLMGateway:
    """Build the single structured-plan model client for follow-up evaluation."""

    timeout_s = float(os.getenv("RUNTIME_V7_FOLLOWUP_TIMEOUT_S", os.getenv("RUNTIME_V7_TIMEOUT_S", "20")) or "20")
    cache_enabled = str(os.getenv("RUNTIME_V7_FOLLOWUP_ENABLE_CONTEXT_CACHE", "0")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    model = os.getenv(
        "RUNTIME_V7_FOLLOWUP_MODEL",
        os.getenv("RUNTIME_V7_FOLLOWUP_COMPOSER_MODEL", "gemini/gemini-2.5-flash-lite"),
    )
    return RuntimeV7LLMGateway(
        config=RuntimeV7LLMGatewayConfig(
            model=model,
            temperature=float(os.getenv("RUNTIME_V7_FOLLOWUP_TEMPERATURE", "0.1")),
            max_tokens=_followup_generation_max_tokens(),
            timeout_s=timeout_s,
            max_transport_retries=_int_env_clamped(
                "RUNTIME_V7_FOLLOWUP_TRANSPORT_RETRIES",
                default=1,
                minimum=0,
                maximum=2,
            ),
            transport_retry_backoff_s=float(
                os.getenv("RUNTIME_V7_FOLLOWUP_TRANSPORT_RETRY_BACKOFF_S", "0.75") or "0.75"
            ),
            enable_context_cache=cache_enabled,
            context_cache_ttl=_runtime_v7_context_cache_ttl(),
            reasoning_effort=_followup_reasoning_effort(
                "RUNTIME_V7_FOLLOWUP_REASONING_EFFORT",
                model,
                default="disable",
            ),
            provider_call_guard=provider_call_guard,
        )
    )


def _followup_generation_max_tokens() -> int:
    return _int_env_clamped("RUNTIME_V7_FOLLOWUP_MAX_TOKENS", default=700, minimum=160, maximum=1200)


def _followup_reasoning_effort(env_name: str, model: str, *, default: str = "") -> Optional[str]:
    raw_value = os.getenv(env_name)
    configured = _empty_to_none(raw_value) if raw_value is not None else _empty_to_none(default)
    if not configured:
        return None
    normalized_model = str(model or "").lower()
    if "gemini-2.0" in normalized_model:
        return None
    return configured


def _response_seed_overrides_for_flow(flow_context: Mapping[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(flow_context, Mapping):
        return []
    seeds: List[Dict[str, Any]] = []
    if bool(flow_context.get("late_reply_apology_required")):
        seeds.append(
            {
                "type": "late_reply_apology",
                "priority": "high",
                "guidance": (
                    "The latest customer message was found by a follow-up trigger, so treat it as a normal inbound chat "
                    "turn and start the first customer-visible text with a brief apology for the late reply, such as "
                    "'Sorry po sa late reply.' Then answer the latest customer message normally using Runtime V7 tools "
                    "and policies. Do not mention automation, follow-up triggers, logs, or internal routing."
                ),
            }
        )
    promo_context = flow_context.get("promo_action_context")
    if isinstance(promo_context, Mapping):
        if str(promo_context.get("status") or "") == "stale":
            guidance = (
                "The customer clicked an old or expired promo card. State briefly that the selected promo is no longer "
                "current and offer the current reviewed catalog. Do not apply or quote stale mechanics."
            )
        else:
            runtime_context = flow_context.get("promo_action_runtime_context")
            runtime_context = dict(runtime_context) if isinstance(runtime_context, Mapping) else {}
            action = str(promo_context.get("action") or runtime_context.get("action") or "").strip().lower()
            brand = str(runtime_context.get("selected_brand") or promo_context.get("selected_brand") or "").strip()
            tire_size = str(runtime_context.get("trusted_tire_size") or "").strip()
            reviewed_context = json.dumps(
                dict(promo_context),
                ensure_ascii=False,
                default=str,
            )
            if action == "choose_brand" and not brand:
                guidance = (
                    "This is a validated navigation request to choose a tire brand; no brand or product has been "
                    "selected yet. Ask only for the exact tire size if it is still missing. If the exact size is "
                    "already known, show the grounded brand or price-category choices available for that size. "
                    "Do not treat the promo title as a product model or brand selection. Use the reviewed promo "
                    f"context only for supporting promo facts: {reviewed_context}"
                )
            elif action in {"check_price", "choose_brand"} and tire_size:
                guidance = (
                    "This is a validated promo-card price-selection action. The customer's confirmed tire size is "
                    f"{tire_size} and the selected brand is {brand or 'the reviewed promo brand'}. Call product_search "
                    "now with that exact tire size and selected brand. Do not ask the customer to repeat either value. "
                    "After presenting grounded eligible products, advance qualification by asking exactly one missing "
                    "field: prefer location, then contact number; if neither is missing, offer the next purchase or "
                    "installation step. Do not repeat the gallery summary before searching. Use only this reviewed promo "
                    f"context for promo facts: {reviewed_context}"
                )
            elif action in {"check_price", "choose_brand"}:
                guidance = (
                    "This is a validated promo-card price-selection action. Preserve the selected brand "
                    f"{brand or 'from the reviewed card'} and ask only for the exact tire size needed for product_search. "
                    "Do not repeat the promo summary or ask for the brand again. Use only this reviewed promo context for "
                    f"promo facts: {reviewed_context}"
                )
            elif action == "promo_details":
                guidance = (
                    "Answer only the requested promo mechanics using the reviewed context below. This informational "
                    "action is not a brand, product, quantity, fulfillment, or purchase selection. Do not advance "
                    "qualification or ask for location, contact, schedule, payment, tire size, or product confirmation. "
                    "Offer only to check eligible products/prices or compare another promo as an optional next step. "
                    f"Reviewed context: {reviewed_context}"
                )
            elif action == "about_brand":
                brand_profile = (
                    promo_context.get("brand_profile")
                    if isinstance(
                        promo_context.get("brand_profile"), Mapping
                    )
                    else {}
                )
                source_backed_profile = bool(
                    brand_profile.get("profile_ref")
                    and brand_profile.get("about_brand")
                )
                brand_context = {
                    "action": action,
                    "selected_brand": promo_context.get("selected_brand"),
                    "profile_scope": (
                        "gulong_brand_knowledge"
                        if source_backed_profile
                        else "promo_catalog_offer_summary_only"
                    ),
                    "reviewed_background_available": (
                        source_backed_profile
                    ),
                    "brand_profile": {
                        key: deepcopy(brand_profile.get(key))
                        for key in (
                            "profile_ref",
                            "brand",
                            "about_brand",
                            "origin_country",
                            "market_segment",
                            "manufacturer_warranty",
                            "gulong_guarantee",
                            "warranty_policy",
                            "source_updated_at",
                            "source_urls",
                            "evidence_refs",
                        )
                        if brand_profile.get(key) not in (None, "", [], {})
                    },
                }
                if source_backed_profile:
                    guidance = (
                        "The customer's current validated action is About Brand "
                        "for the named tire brand. Answer that action even if "
                        "older conversation history discussed another topic. "
                        "This is not a request to submit a customer review or "
                        "feedback. "
                        "Answer the customer's About Brand request using the "
                        "published Gulong.ph brand profile below. Give a friendly, "
                        "natural summary of useful background, origin, and market "
                        "positioning. This general About Brand action is not a "
                        "warranty question: if useful, mention only the published "
                        "manufacturer or Gulong.ph warranty duration briefly. Do "
                        "not summarize warranty coverage, eligibility, exclusions, "
                        "or claim conditions unless the customer explicitly asks "
                        "about warranty or protection. Keep manufacturer/product "
                        "warranty separate "
                        "from the Gulong.ph unconditional-damage warranty and its "
                        "conditions. For manufacturer warranty, state only the "
                        "fields actually present; do not borrow the Gulong.ph "
                        "policy's purchase-date start, coverage, or conditions. "
                        "This informational action is not a brand, "
                        "product, quantity, fulfillment, or purchase selection, "
                        "so it has no selection effect. Do not advance "
                        "qualification or ask for location, schedule, payment, "
                        "contact details, or tire size. Offer one light next step "
                        "such as comparing brands or viewing available products. "
                        "Continue the customer's recent natural language; the "
                        "English button label is not a language preference. Do "
                        "not mention or restate any current offer unless the "
                        "customer separately asks about promos. Do not mention "
                        "records, embeddings, refs, or internal review mechanics. "
                        "Published brand context: "
                        + json.dumps(
                            brand_context,
                            ensure_ascii=False,
                            default=str,
                        )
                    )
                else:
                    guidance = (
                        "This About Brand source is marked "
                        "promo_catalog_offer_summary_only and does not contain "
                        "reviewed general background. This informational action "
                        "is not a brand, product, quantity, fulfillment, or "
                        "purchase selection. Do not advance qualification or "
                        "ask for location, schedule, payment, contact details, "
                        "or tire size. Do not mention or restate any current "
                        "offer. Say briefly and naturally that the background "
                        "is not available, then offer a comparison or product "
                        "next step. Context: "
                        + json.dumps(
                            brand_context,
                            ensure_ascii=False,
                            default=str,
                        )
                    )
            else:
                guidance = (
                    "This is a validated promo-card action. Use only the following reviewed action context for promo or "
                    "brand facts, then continue the requested qualification step: "
                    + reviewed_context
                )
        seeds.append(
            {
                "type": "promo_action",
                "priority": "high",
                "guidance": guidance,
                "evidence": dict(promo_context),
            }
        )
    choice_context = flow_context.get("choice_action_runtime_context")
    if isinstance(choice_context, Mapping):
        choice_type = str(choice_context.get("choice_type") or "").strip()
        if (
            str(choice_context.get("validation_status") or "").strip()
            == "valid"
            and choice_type == "serviceable_city"
            and not bool(choice_context.get("selected_product_ready"))
        ):
            seeds.append(
                {
                    "type": "validated_location_before_product",
                    "priority": "high",
                    "guidance": (
                        "The customer's serviceable city choice is validated and must be retained, but no trusted "
                        "product has been selected. Resume the unresolved product layer before schedule or order "
                        "progression. If an exact tire size is already known, call product_search or "
                        "discover_brand_buckets and render the resulting product/category choices. If a current "
                        "product result exists but was not shown, render that product surface now. Do not repeat a "
                        "broad promo gallery unless the customer explicitly asked about promos, and do not ask for "
                        "the city again. The model still owns the natural acknowledgement and CTA."
                    ),
                    "evidence": {
                        "choice_type": choice_type,
                        "location": str(choice_context.get("label") or ""),
                        "province": str(
                            choice_context.get("province_label") or ""
                        ),
                    },
                }
            )
    return seeds


def _apply_promo_action_runtime_context(request: RuntimeV7APIRequest, state: Mapping[str, Any]) -> None:
    """Bridge a validated promo click to trusted qualification context.

    A generic ``choose_brand`` action is navigation, not a product selection.
    Its next qualification step therefore remains model-resolved from the
    current conversation state: use an already known exact size for discovery,
    or ask for it only when it is genuinely missing.  Transactional promo
    selections continue to reuse only the stricter selected-product size.
    """

    flow_context = request.flow_context if isinstance(request.flow_context, dict) else {}
    promo_context = flow_context.get("promo_action_context")
    if not isinstance(promo_context, Mapping) or str(promo_context.get("status") or "") != "valid":
        return

    action = str(promo_context.get("action") or "").strip().lower()
    selected_brand = str(promo_context.get("selected_brand") or "").strip()
    selection_action = action in PROMO_SELECTION_ACTIONS and bool(
        selected_brand
    )
    tire_size = _trusted_selected_product_tire_size(state) if selection_action else ""

    profile_fields = dict(request.profile_fields or {})
    if selection_action and selected_brand:
        # A tracked card button is an explicit current preference and must beat
        # an older brand value loaded from the ManyChat profile.
        profile_fields["tire_brand"] = selected_brand
    if selection_action and tire_size:
        profile_fields["tire_size"] = tire_size
    request.profile_fields = profile_fields

    runtime_context = {
        "action": action,
        "selected_brand": selected_brand,
        "trusted_tire_size": tire_size,
        "tire_size_source": "latest_selected_product_context" if tire_size else "",
        "interaction_mode": (
            "selection"
            if selection_action
            else "navigation"
            if action == "choose_brand"
            else "informational"
        ),
        "selection_effect": "query_preference" if selection_action else "none",
        "qualification_effect": (
            "advance_after_grounded_results"
            if selection_action
            else "model_resolve_from_current_state"
            if action == "choose_brand"
            else "none"
        ),
    }
    request.flow_context = {**flow_context, "promo_action_runtime_context": runtime_context}

    if action not in {"check_price", "choose_brand"} or not tire_size:
        return
    promo = promo_context.get("promo") if isinstance(promo_context.get("promo"), Mapping) else {}
    title = str(promo.get("title") or "this promo").strip()
    selection = selected_brand or title
    request.user_text = (
        f"I selected {selection} from the promo gallery. My current tire size is already confirmed as {tire_size}. "
        "Show eligible promo tire prices now. Do not ask me to repeat my brand or tire size."
    )


def _trusted_selected_product_tire_size(state: Mapping[str, Any]) -> str:
    """Read a canonical size only from the persisted selected-product record."""

    selected = state.get("latest_selected_product_context")
    if not isinstance(selected, Mapping):
        return ""
    summary = selected.get("product_summary")
    if not isinstance(summary, Mapping):
        return ""
    for key in ("tire_size", "size", "sku_model", "model", "title"):
        tire_size = normalize_visible_tire_size(summary.get(key))
        if tire_size:
            return tire_size
    return ""


def _turn_has_successful_tool(turn: Mapping[str, Any], tool_name: str) -> bool:
    return any(
        str(result.get("name") or "") == tool_name
        and str((result.get("result") or {}).get("status") or "").lower() in {"ok", "success"}
        for result in turn.get("tool_results") or []
        if isinstance(result, Mapping) and isinstance(result.get("result"), Mapping)
    )


def _turn_contains_authorized_side_effect(turn: Mapping[str, Any]) -> bool:
    """Do not hide the customer result of an action that already happened."""

    return any(
        str(result.get("name") or "") in {
            "submit_order",
            "prepare_payment_request",
        }
        and not _tool_failed(result)
        for result in turn.get("tool_results") or []
        if isinstance(result, Mapping)
    )


def _followup_trigger_event(
    *,
    request: RuntimeV7APIRequest,
    request_id: str,
    trace_id: str,
    user_id: str,
    channel_user_id: str,
    context_fingerprint: str,
) -> Dict[str, Any]:
    return {
        "event_type": "followup_trigger",
        "event_key": f"followup_{context_fingerprint}",
        "request_id": request_id,
        "trace_id": trace_id,
        "runtime_version": "v7",
        "user_id": user_id,
        "channel_user_id": channel_user_id or user_id,
        "channel": request.channel,
        "message_id": request.message_id,
        "message_id_source": request.message_id_source,
        "idempotency_key": request.idempotency_key,
        "channel_event_id": request.channel_event_id,
        "channel_event_ts": request.channel_event_ts,
        "dedupe_eligible": bool(context_fingerprint),
        "received_at": now_manila_str(),
        "raw_payload": dict(request.raw_payload or {}),
        "normalized_payload": dict(request.normalized_payload or {}),
        "flow_context": dict(request.flow_context or {}),
        "status": "received",
    }


def _followup_llm_call_record(
    response: Dict[str, Any],
    *,
    component: str,
    round_name: str,
) -> Dict[str, Any]:
    usage_summary = _followup_llm_usage_summary(response)
    request_debug = response.get("request_debug") if isinstance(response.get("request_debug"), Mapping) else {}
    transport_retry_events = [
        dict(item)
        for item in response.get("transport_retry_events") or []
        if isinstance(item, Mapping)
    ]
    return {
        "round": round_name,
        "component": component,
        "model": response.get("model"),
        "provider": response.get("provider"),
        "finish_reason": response.get("finish_reason"),
        "latency_ms": response.get("latency_ms"),
        "usage_summary": usage_summary,
        "tool_calls": [],
        "tool_choice": "none",
        "response_format": "RuntimeV7FollowupCasePlanModel",
        "request_cache": response.get("request_cache"),
        "cache_guard_events": response.get("cache_guard_events"),
        "transport_attempt_count": int(request_debug.get("transport_attempt_count") or 1),
        "transport_retry_events": transport_retry_events,
        "model_output": {
            "model": response.get("model"),
            "provider": response.get("provider"),
            "finish_reason": response.get("finish_reason"),
        },
    }


def _followup_log_payload(value: Mapping[str, Any]) -> Dict[str, Any]:
    redacted = redact_followup_pricing_context(dict(value or {}))
    if isinstance(redacted, Mapping):
        return dict(redacted)
    return {}


def _followup_turn_record(
    *,
    turn_id: str,
    context: Dict[str, Any],
    context_fingerprint: str,
    llm_calls: Sequence[Dict[str, Any]],
    decision: Dict[str, Any],
    composer: Dict[str, Any],
    rendered: RuntimeV7ChannelRender,
    delivery_result: Dict[str, Any],
    status: str,
) -> Dict[str, Any]:
    case = context.get("followup_case") if isinstance(context.get("followup_case"), dict) else {}
    return {
        "turn_id": turn_id,
        "turn_type": "followup",
        "user_message": "",
        "runtime_final_response": rendered.text,
        "tool_results": [],
        "llm_calls": [dict(item) for item in llm_calls if isinstance(item, dict)],
        "llm_usage_summary": _aggregate_followup_llm_usage(llm_calls),
        "tagging": {"tags_to_add": []},
        "followup": {
            "status": status,
            "route": case.get("route"),
            "cadence": case.get("cadence"),
            "conversation_anchor_id": case.get("conversation_anchor_id"),
            "context_fingerprint": context_fingerprint,
            "gate": dict(context.get("followup_gate") or {}),
            "decision": dict(decision or {}),
            "validation": {key: value for key, value in dict(composer or {}).items() if key != "message"},
            "message_preview": str(rendered.text or "")[:240],
            "delivery_status": delivery_result.get("status"),
            "delivery_reason": delivery_result.get("reason"),
        },
        "conversation_hydration": context.get("conversation_hydration") if isinstance(context, dict) else {},
        "ingress_conversation_history": case.get("recent_messages") if isinstance(case, dict) else [],
        "active_working_memory_after_turn": "",
        "background_signal_ledger_after_turn": [],
        "flow_stage_after": (
            "followup_sent"
            if status == "success"
            else "followup_deferred"
            if status == "deferred"
            else "followup_evaluated"
            if status == "evaluated"
            else "followup_suppressed"
        ),
    }


def _followup_llm_usage_summary(response: Dict[str, Any]) -> Dict[str, Any]:
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    prompt_tokens = _int_or_zero(usage.get("prompt_tokens"))
    completion_tokens = _int_or_zero(usage.get("completion_tokens"))
    total_tokens = _int_or_zero(usage.get("total_tokens"))
    cache_usage = response.get("cache_usage") if isinstance(response.get("cache_usage"), dict) else {}
    cache_read_input_tokens = _int_or_zero(
        cache_usage.get("cache_read_input_tokens")
        or usage.get("cache_read_input_tokens")
        or _nested_get(usage, "prompt_tokens_details", "cached_tokens")
    )
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cache_read_input_tokens": cache_read_input_tokens,
        "uncached_prompt_tokens": max(prompt_tokens - cache_read_input_tokens, 0),
        "cache_hit_rate": _ratio(cache_read_input_tokens, prompt_tokens),
        "latency_ms": _int_or_zero(response.get("latency_ms")),
        "reasoning_tokens": _int_or_zero(
            cache_usage.get("reasoning_tokens")
            or usage.get("reasoning_tokens")
            or _nested_get(usage, "completion_tokens_details", "reasoning_tokens")
        ),
    }


def _aggregate_followup_llm_usage(calls: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    summary = {
        "llm_call_count": len([item for item in calls or [] if isinstance(item, dict)]),
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cache_read_input_tokens": 0,
        "uncached_prompt_tokens": 0,
        "reasoning_tokens": 0,
        "latency_ms": 0,
    }
    for call in calls or []:
        if not isinstance(call, dict):
            continue
        usage = call.get("usage_summary") if isinstance(call.get("usage_summary"), dict) else {}
        for key in [
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "cache_read_input_tokens",
            "uncached_prompt_tokens",
            "reasoning_tokens",
            "latency_ms",
        ]:
            summary[key] += _int_or_zero(usage.get(key))
    summary["cache_hit_rate"] = _ratio(summary["cache_read_input_tokens"], summary["prompt_tokens"])
    return summary


def _env_bool(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _runtime_v7_context_cache_ttl() -> str:
    return os.getenv("RUNTIME_V7_CONTEXT_CACHE_TTL", "300s")


def _runtime_v7_main_context_cache_enabled() -> bool:
    if os.getenv("RUNTIME_V7_MAIN_ENABLE_CONTEXT_CACHE") is not None:
        return _env_bool("RUNTIME_V7_MAIN_ENABLE_CONTEXT_CACHE", default=False)
    return _env_bool("RUNTIME_V7_ENABLE_CONTEXT_CACHE", default=False)


def _runtime_v7_component_context_cache_enabled(env_name: str) -> bool:
    return _env_bool(env_name, default=False)


def _tester_provider_call_guard(
    request: RuntimeV7APIRequest,
) -> Optional[RuntimeV7ProviderCallGuard]:
    """Build the tester-only provider-call budget for one server request."""

    if not request.tester:
        return None
    max_provider_calls = _int_env_clamped(
        "RUNTIME_V7_TESTER_MAX_PROVIDER_CALLS",
        default=10,
        minimum=0,
        maximum=100,
    )
    return RuntimeV7ProviderCallGuard(
        max_provider_calls=max_provider_calls or None,
    )


def build_runtime_v7_harness(
    session_id: str,
    profile_fields: Dict[str, Any],
    trace_id: str,
    *,
    user_id: str = "",
    provider_call_guard: Optional[RuntimeV7ProviderCallGuard] = None,
) -> RuntimeV7Harness:
    """Build the production Runtime V7 harness with live read tools."""

    main_context_cache_enabled = _runtime_v7_main_context_cache_enabled()
    memory_context_cache_enabled = _runtime_v7_component_context_cache_enabled("RUNTIME_V7_MEMORY_ENABLE_CONTEXT_CACHE")
    background_context_cache_enabled = _runtime_v7_component_context_cache_enabled(
        "RUNTIME_V7_BACKGROUND_SIGNAL_ENABLE_CONTEXT_CACHE"
    )
    cache_ttl = _runtime_v7_context_cache_ttl()
    timeout_s = float(os.getenv("RUNTIME_V7_TIMEOUT_S", "30"))
    canonical_values_provider = RuntimeV7CanonicalValuesProvider()
    product_tools = ProductToolHarness(
        runner=ProductSearchRunner(
            canonical_values_provider=canonical_values_provider,
            max_api_calls=int(os.getenv("RUNTIME_V7_PRODUCT_MAX_API_CALLS", "12")),
            max_pages_per_attempt=int(os.getenv("RUNTIME_V7_PRODUCT_MAX_PAGES_PER_ATTEMPT", "1")),
        ),
        canonical_values_provider=canonical_values_provider,
    )
    service_tools = RuntimeV7ServiceTools(
        canonical_values_provider=canonical_values_provider,
        geocode_api_key=os.getenv("GMAPS_API_KEY", ""),
    )
    model_client = RuntimeV7LLMGateway(
        config=RuntimeV7LLMGatewayConfig(
            model=os.getenv("RUNTIME_V7_MAIN_MODEL", "gemini/gemini-2.5-flash"),
            temperature=float(os.getenv("RUNTIME_V7_MAIN_TEMPERATURE", "0.3")),
            max_tokens=int(os.getenv("RUNTIME_V7_MAIN_MAX_TOKENS", "1800")),
            timeout_s=timeout_s,
            max_transport_retries=_int_env_clamped(
                "RUNTIME_V7_MAIN_TRANSPORT_RETRIES",
                default=1,
                minimum=0,
                maximum=2,
            ),
            transport_retry_backoff_s=float(
                os.getenv(
                    "RUNTIME_V7_MAIN_TRANSPORT_RETRY_BACKOFF_S",
                    "0.75",
                )
                or "0.75"
            ),
            enable_context_cache=main_context_cache_enabled,
            context_cache_ttl=cache_ttl,
            reasoning_effort=_empty_to_none(os.getenv("RUNTIME_V7_MAIN_REASONING_EFFORT", "low")),
            provider_call_guard=provider_call_guard,
        )
    )
    memory_generator = HybridActiveWorkingMemoryGenerator(
        model_client=RuntimeV7ActiveWorkingMemoryModelClient(
            model=os.getenv("RUNTIME_V7_MEMORY_MODEL", "gemini/gemini-2.5-flash-lite"),
            timeout_s=timeout_s,
            enable_context_cache=memory_context_cache_enabled,
            context_cache_ttl=cache_ttl,
            metadata=_metadata(trace_id, "memory"),
            provider_call_guard=provider_call_guard,
        )
    )
    background_signal_model_client = RuntimeV7BackgroundSignalModelClient(
        model=os.getenv("RUNTIME_V7_BACKGROUND_SIGNAL_MODEL", "gemini/gemini-2.5-flash-lite"),
        timeout_s=timeout_s,
        enable_context_cache=background_context_cache_enabled,
        context_cache_ttl=cache_ttl,
        reasoning_effort=_empty_to_none(os.getenv("RUNTIME_V7_BACKGROUND_SIGNAL_REASONING_EFFORT", "low")),
            metadata=_metadata(trace_id, "background_signals"),
            provider_call_guard=provider_call_guard,
    )
    image_extractor = ImageEvidenceExtractor(
        model_client=RuntimeV7ImageEvidenceModelClient(
            model=os.getenv("RUNTIME_V7_IMAGE_MODEL", "gemini/gemini-2.5-flash"),
            timeout_s=timeout_s,
            metadata=_metadata(trace_id, "image_evidence"),
            provider_call_guard=provider_call_guard,
        )
    )
    brand_knowledge = None
    if brand_knowledge_enabled():
        brand_knowledge = BrandKnowledgeService(
            BrandKnowledgeRepository(
                project_id=os.getenv(
                    "GOOGLE_CLOUD_PROJECT",
                    "gulong-chatbot-459723",
                ),
                profiles_collection=os.getenv(
                    "BRAND_KNOWLEDGE_PROFILES_COLLECTION",
                    "brand_knowledge_profiles",
                ),
                chunks_collection=os.getenv(
                    "BRAND_KNOWLEDGE_CHUNKS_COLLECTION",
                    "brand_knowledge_chunks",
                ),
                config_collection=os.getenv(
                    "BRAND_KNOWLEDGE_CONFIG_COLLECTION",
                    "brand_knowledge_config",
                ),
                provider_call_guard=provider_call_guard,
            )
        )
    promo_catalog = None
    if promo_catalog_enabled_for_user(user_id):
        promo_catalog = PromoCatalogService(
            PromoCatalogRepository(
                project_id=os.getenv("GOOGLE_CLOUD_PROJECT", "gulong-chatbot-459723"),
                cards_collection=os.getenv("PROMO_CATALOG_CARDS_COLLECTION", "promo_catalog_cards"),
                mechanics_collection=os.getenv("PROMO_CATALOG_MECHANICS_COLLECTION", "promo_catalog_mechanics"),
                brand_profiles_collection=os.getenv("PROMO_BRAND_PROFILES_COLLECTION", "promo_brand_profiles"),
                config_collection=os.getenv("PROMO_CATALOG_CONFIG_COLLECTION", "promo_catalog_config"),
                provider_call_guard=provider_call_guard,
            ),
            product_lookup=lambda tire_size, brands: _promo_exact_size_products(
                product_tools,
                tire_size=tire_size,
                brands=brands,
            ),
            brand_knowledge=brand_knowledge,
        )
    return RuntimeV7Harness(
        model_client=model_client,
        tools=product_tools,
        service_tools=service_tools,
        session_id=session_id,
        memory_generator=memory_generator,
        background_signal_model_client=background_signal_model_client,
        background_signal_model_policy=os.getenv("RUNTIME_V7_BACKGROUND_SIGNAL_POLICY", "auto"),
        image_evidence_extractor=image_extractor,
        max_tool_rounds=int(os.getenv("RUNTIME_V7_MAX_TOOL_ROUNDS", "5")),
        # Production uses signal/ref-driven domain projection. Ambiguous turns
        # retain the general request_capability recovery tool instead of paying
        # for the entire product policy and schema surface on every request.
        default_domains=(),
        canonical_values_provider=canonical_values_provider,
        thought_signature_mode=os.getenv("RUNTIME_V7_THOUGHT_SIGNATURE_MODE", "preserve"),
        profile_fields=dict(profile_fields or {}),
        promo_catalog=promo_catalog,
        brand_knowledge=brand_knowledge,
    )


def _promo_exact_size_products(
    product_tools: ProductToolHarness,
    *,
    tire_size: str,
    brands: Sequence[str],
) -> List[Dict[str, Any]]:
    """Run one hidden exact-size inventory lookup for promo applicability."""

    match = re.fullmatch(r"(\d{3})/(\d{2})(ZR|R)(\d{2})", str(tire_size or "").upper())
    if not match:
        return []
    result = product_tools.runner.run(
        {
            "section_width": match.group(1),
            "aspect_ratio": match.group(2),
            "rim_size": f"{match.group(3)}{match.group(4)}",
            "preferred_brands": list(brands or []),
            "top_k": 12,
        }
    )
    rows = [
        dict(row)
        for row in [*(result.get("best_products") or []), *(result.get("presented_products") or [])]
        if isinstance(row, dict)
    ]
    seen = set()
    output = []
    for row in rows:
        key = str(row.get("item_ref") or row.get("product_id") or row.get("slug") or json.dumps(row, sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output


def _runtime_v7_state_from_session(strategy_state: Any) -> Dict[str, Any]:
    if not isinstance(strategy_state, dict):
        return {}
    state = strategy_state.get(V7_STATE_KEY)
    return deepcopy(state) if isinstance(state, dict) else {}


def _channel_history_cache_from_strategy_state(strategy_state: Any) -> Dict[str, Any]:
    if not isinstance(strategy_state, dict):
        return {}
    cache = strategy_state.get(CHANNEL_CONVERSATION_HISTORY_STATE_KEY)
    return deepcopy(cache) if isinstance(cache, dict) else {}


def _messages_from_history_loader_result(result: Any) -> List[Dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    data = result.get("data")
    if isinstance(data, list):
        return [dict(item) for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        messages = data.get("messages")
        if isinstance(messages, list):
            return [dict(item) for item in messages if isinstance(item, dict)]
    messages = result.get("messages")
    if isinstance(messages, list):
        return [dict(item) for item in messages if isinstance(item, dict)]
    return []


def _resolve_message_identity(
    request: RuntimeV7APIRequest,
    *,
    hydration: ConversationHydrationResult,
    user_id: str,
) -> Dict[str, str]:
    provided = str(request.message_id or "").strip()
    if provided and str(request.message_id_source or "").strip().lower() == "provided":
        return {"message_id": provided, "message_id_source": "provided"}
    current = hydration.current_message if isinstance(hydration.current_message, dict) else {}
    current_id = str(current.get("message_id") or "").strip()
    if current_id:
        source = str(current.get("source") or hydration.source or "").strip()
        if source == "channel_history_cache":
            source = "channel_history_cache"
        elif source == "manychat_load_messages":
            source = "manychat_load_messages"
        else:
            source = "channel_history_cache" if hydration.source == "channel_history_cache" else "manychat_load_messages"
        return {"message_id": current_id, "message_id_source": source}
    derived = str(provided or _stable_message_id(request, user_id=user_id)).strip()
    return {"message_id": derived, "message_id_source": "derived"}


def _conversation_hydration_metadata(hydration: ConversationHydrationResult) -> Dict[str, Any]:
    return {
        "source": hydration.source,
        "cache_status": hydration.cache_status,
        "refresh_attempted": hydration.refresh_attempted,
        "loader_status": hydration.loader_status,
        "current_message_id": (hydration.current_message or {}).get("message_id") or "",
        "latest_cached_message_id": (hydration.latest_cached_message or {}).get("message_id") or "",
        "latest_loaded_message_id": (hydration.latest_loaded_message or {}).get("message_id") or "",
        "metadata": dict(hydration.metadata or {}),
    }


def _remember_channel_conversation_history(
    strategy_state: Dict[str, Any],
    *,
    hydration: ConversationHydrationResult,
    user_text: str,
    assistant_text: str,
    user_message_id: str,
    assistant_message_id: str,
    timestamp: str,
) -> None:
    messages = append_current_turn_to_channel_history(
        hydration.channel_messages,
        user_text=user_text,
        assistant_text=assistant_text,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        timestamp=timestamp,
    )
    strategy_state[CHANNEL_CONVERSATION_HISTORY_STATE_KEY] = build_channel_history_cache(
        messages,
        source="firestore_runtime_cache",
        refresh_status=hydration.cache_status,
        metadata=_conversation_hydration_metadata(hydration),
    )


def _compact_turn_trace_summary(turn_trace: Dict[str, Any]) -> Dict[str, Any]:
    """Return a payload-safe summary of the full version-neutral trace."""

    inbound = turn_trace.get("inbound_event") if isinstance(turn_trace.get("inbound_event"), dict) else {}
    spans = [span for span in turn_trace.get("component_spans") or [] if isinstance(span, dict)]
    snapshots = [item for item in turn_trace.get("state_snapshots") or [] if isinstance(item, dict)]
    return {
        "trace_id": turn_trace.get("trace_id"),
        "turn_id": turn_trace.get("turn_id"),
        "event_key": inbound.get("event_key"),
        "message_id": inbound.get("message_id"),
        "component_span_count": len(spans),
        "state_snapshot_count": len(snapshots),
        "component_types": sorted({str(span.get("component_type") or "") for span in spans if span.get("component_type")}),
        "state_types": sorted({str(item.get("state_type") or "") for item in snapshots if item.get("state_type")}),
        "status": turn_trace.get("status"),
    }


def _inbound_event_replay(strategy_state: Any, inbound_event: Dict[str, Any]) -> Dict[str, Any]:
    """Return a prior event result plus its delivery-aware ledger status."""

    if not isinstance(strategy_state, dict):
        return {}
    event_key = str(inbound_event.get("event_key") or "").strip()
    if not event_key:
        return {}
    for event in reversed(strategy_state.get("inbound_events_v1") or []):
        if not isinstance(event, dict):
            continue
        if str(event.get("event_key") or "") != event_key:
            continue
        status = str(event.get("status") or "")
        if status not in {"completed", "delivered", "delivery_failed", "delivery_unknown", "rendered"}:
            return {}
        result = dict(event.get("result") or {})
        result["_ledger_status"] = status
        return result
    return {}


def _processed_inbound_message_ids(strategy_state: Any) -> set[str]:
    """Return provider message ids already represented in the event ledger."""

    if not isinstance(strategy_state, dict):
        return set()
    return {
        str(event.get("message_id") or "").strip()
        for event in strategy_state.get("inbound_events_v1") or []
        if isinstance(event, dict)
        and str(event.get("message_id") or "").strip()
        and str(event.get("status") or "").strip()
        in {"completed", "delivered", "delivery_failed", "delivery_unknown", "rendered"}
    }


def _is_customer_turn_recovery(request: RuntimeV7APIRequest) -> bool:
    flow = request.flow_context if isinstance(request.flow_context, dict) else {}
    return str(flow.get("route") or "") == "customer_turn_recovery"


def _is_choice_action_request(request: RuntimeV7APIRequest) -> bool:
    """Return whether the request is a validated interactive-control event."""

    flow = request.flow_context if isinstance(request.flow_context, dict) else {}
    return bool(
        str(flow.get("trigger") or "").strip().casefold() == "choice_action"
        or isinstance(flow.get("choice_action_context"), dict)
        or isinstance(flow.get("choice_action_runtime_context"), dict)
    )


def _response_text_seen_in_transcript(response_text: str, messages: Sequence[Mapping[str, Any]]) -> bool:
    expected = _compact_text(response_text)
    if not expected:
        return False
    return any(
        str(message.get("role") or "") in {"assistant", "chatbot", "bot"}
        and _compact_text(message.get("content") or message.get("text")) == expected
        for message in messages or []
        if isinstance(message, Mapping)
    )


def _update_inbound_event_delivery(
    strategy_state: Any,
    *,
    event_key: str,
    delivery_result: Mapping[str, Any],
) -> None:
    if not isinstance(strategy_state, dict) or not event_key:
        return
    status = str(delivery_result.get("status") or "").strip().lower()
    event_status = "delivered" if status == "success" else "delivery_failed" if status in {"error", "failed", "failure"} else "delivery_unknown"
    for event in reversed(strategy_state.get("inbound_events_v1") or []):
        if not isinstance(event, dict) or str(event.get("event_key") or "") != event_key:
            continue
        event["status"] = event_status
        event["updated_at"] = now_manila_str()
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        result["delivery_result"] = _compact_delivery_result_for_state(dict(delivery_result or {}))
        event["result"] = result
        return


def _customer_recovery_replay_result(
    *,
    request: RuntimeV7APIRequest,
    request_id: str,
    trace_id: str,
    session_id: str,
    inbound_event: Dict[str, Any],
    replay: Dict[str, Any],
    status: str,
    delivery_result: Dict[str, Any],
) -> RuntimeV7APIResult:
    turn = {
        "turn_id": replay.get("turn_id") or "customer_turn_recovery_replay",
        "turn_type": "customer_turn_recovery",
        "user_message": request.user_text,
        "runtime_final_response": replay.get("response_text") or "",
        "tool_results": [],
        "llm_calls": [],
        "replayed_from_inbound_event": True,
        "flow_stage_after": "customer_turn_recovery_replayed" if status == "success" else "customer_turn_recovery_suppressed",
    }
    turn_trace = build_turn_trace(
        inbound_event={**inbound_event, "status": status},
        turn_record=turn,
        delivery_result=delivery_result,
        tagging_result=dict(replay.get("tagging_result") or {}),
        state_saved=True,
    )
    include_content = status in {"success", "evaluated"}
    return RuntimeV7APIResult(
        response=dict(replay.get("response") or {}) if include_content else {},
        content_messages=(
            [dict(item) for item in replay.get("content_messages") or [] if isinstance(item, dict)]
            if include_content
            else []
        ),
        images=[dict(item) for item in replay.get("images") or [] if isinstance(item, dict)] if include_content else [],
        payment=dict(replay.get("payment") or {}) if include_content else {},
        delivery_result=delivery_result,
        tagging_result=dict(replay.get("tagging_result") or {}),
        turn_record=turn,
        session_id=session_id,
        trace_id=trace_id,
        request_id=request_id,
        message_id=request.message_id,
        idempotency_key=request.idempotency_key,
        state_saved=True,
        status=status,
        turn_trace=turn_trace,
    )


def _remember_inbound_event(
    strategy_state: Dict[str, Any],
    *,
    inbound_event: Dict[str, Any],
    turn: Dict[str, Any],
    rendered: RuntimeV7ChannelRender,
    delivery_result: Dict[str, Any],
    tagging_result: Dict[str, Any],
    response_text: str,
) -> None:
    """Append a compact inbound-event entry with delivery-aware status."""

    event_key = str(inbound_event.get("event_key") or "").strip()
    if not event_key:
        return
    entries = [dict(item) for item in strategy_state.get("inbound_events_v1") or [] if isinstance(item, dict)]
    entries = [entry for entry in entries if str(entry.get("event_key") or "") != event_key]
    delivery_status = str(delivery_result.get("status") or "").strip().lower()
    delivery_reason = str(delivery_result.get("reason") or "").strip().lower()
    if delivery_status == "success":
        event_status = "delivered"
    elif delivery_status in {"error", "failed", "failure"}:
        event_status = "delivery_failed"
    elif delivery_status == "skipped" and delivery_reason == "return_only":
        event_status = "rendered"
    else:
        event_status = "delivery_unknown"
    entries.append(
        {
            "event_key": event_key,
            "status": event_status,
            "message_id": inbound_event.get("message_id") or "",
            "message_id_source": inbound_event.get("message_id_source") or "",
            "channel_event_id": inbound_event.get("channel_event_id") or "",
            "dedupe_eligible": bool(inbound_event.get("dedupe_eligible")),
            "received_at": inbound_event.get("received_at") or "",
            "completed_at": now_manila_str(),
            "result": _compact_inbound_event_result(
                turn=turn,
                rendered=rendered,
                delivery_result=delivery_result,
                tagging_result=tagging_result,
                response_text=response_text,
            ),
        }
    )
    strategy_state["inbound_events_v1"] = entries[-20:]


def _compact_inbound_event_result(
    *,
    turn: Dict[str, Any],
    rendered: RuntimeV7ChannelRender,
    delivery_result: Dict[str, Any],
    tagging_result: Dict[str, Any],
    response_text: str,
) -> Dict[str, Any]:
    return {
        "turn_id": str(turn.get("turn_id") or ""),
        "response": _compact_json(dict(rendered.response or {}), max_depth=2, max_list_items=8, max_dict_items=12, max_string_chars=1900),
        "content_messages": _compact_json(
            [dict(item) for item in rendered.content_messages or [] if isinstance(item, dict)],
            max_depth=3,
            max_list_items=12,
            max_dict_items=20,
            max_string_chars=1900,
        ),
        "images": _compact_json(
            [dict(item) for item in rendered.images or [] if isinstance(item, dict)],
            max_depth=3,
            max_list_items=12,
            max_dict_items=20,
            max_string_chars=1200,
        ),
        "payment": _compact_json(dict(rendered.payment or {}), max_depth=3, max_list_items=10, max_dict_items=20, max_string_chars=1200),
        "delivery_result": _compact_delivery_result_for_state(delivery_result),
        "tagging_result": _compact_tagging_result_for_state(tagging_result),
        "response_text": _truncate_state_text(response_text, 6000),
    }


def _compact_delivery_result_for_state(delivery_result: Dict[str, Any]) -> Dict[str, Any]:
    result = delivery_result if isinstance(delivery_result, dict) else {}
    return _compact_json(result, max_depth=3, max_list_items=12, max_dict_items=32, max_string_chars=1000)


def _compact_tagging_result_for_state(tagging_result: Dict[str, Any]) -> Dict[str, Any]:
    result = tagging_result if isinstance(tagging_result, dict) else {}
    compact = _compact_json(result, max_depth=3, max_list_items=24, max_dict_items=48, max_string_chars=1000)
    if not isinstance(compact, dict):
        return {}
    handoff_note = result.get("handoff_note") if isinstance(result.get("handoff_note"), dict) else {}
    if handoff_note:
        compact["handoff_note"] = {
            "tag": str(handoff_note.get("tag") or ""),
            "status": str(handoff_note.get("status") or ""),
            "preview": _truncate_state_text(handoff_note.get("preview") or "", 500),
        }
    return compact


def _truncate_state_text(value: Any, max_chars: int) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 12)] + "...[truncated]"


def _hydrate_harness(harness: RuntimeV7Harness, state: Dict[str, Any]) -> None:
    if not state:
        return
    harness.recent_turns = [dict(item) for item in state.get("recent_turns") or [] if isinstance(item, dict)]
    harness.conversation_history = [dict(item) for item in state.get("conversation_history") or [] if isinstance(item, dict)]
    harness.product_inclusions_sent = bool(state.get("product_inclusions_sent"))
    harness.service_policy_note_ids_sent = [
        str(value)
        for value in state.get("service_policy_note_ids_sent") or []
        if str(value).strip()
    ][-20:]
    turn_count = int(state.get("turn_count") or 0)
    harness.turn_records = [{"turn_id": f"historical_{index + 1}"} for index in range(max(0, turn_count))]
    memory_payload = state.get("active_working_memory") if isinstance(state.get("active_working_memory"), dict) else {}
    restored_memory = ActiveWorkingMemory.from_dict(memory_payload)
    legacy_memory_note = str(state.get("memory_note") or "").strip()
    if not restored_memory.text.strip() and legacy_memory_note:
        restored_memory = ActiveWorkingMemory.from_text(
            legacy_memory_note,
            source="legacy_memory_note_migration",
            metadata={"migration": "memory_note_to_active_working_memory"},
        )
    harness.memory_store.save(harness.session_id, restored_memory)
    signals = [dict(item) for item in state.get("background_signals") or [] if isinstance(item, dict)]
    if signals:
        harness.signal_ledger._items[str(harness.session_id)] = deepcopy(signals)
    _restore_product_store(harness.tools.store, state.get("product_observations") or {})
    _restore_service_store(harness.service_tools.store, state.get("service_observations") or {})
    for attr in [
        "latest_order_summary_snapshot",
        "latest_selected_product_context",
        "order_payload_store",
        "latest_order_payload_ref",
        "latest_submitted_order_context",
        "latest_order_details_context",
        "payment_request_store",
        "latest_payment_request_ref",
        "external_evidence_store",
        "latest_fitment_observation",
        "tag_ledger",
        "human_handoff_state",
        "latest_promo_presentation",
        "promo_presentation_history",
        "latest_promo_action",
        "promo_action_history",
        "latest_choice_presentation",
        "choice_presentation_history",
        "latest_choice_action",
        "choice_action_history",
        "latest_product_presentation",
        "product_presentation_history",
    ]:
        if attr in state:
            setattr(harness, attr, deepcopy(state.get(attr)))


def _conversation_messages_include_product_inclusions(messages: Sequence[Dict[str, Any]]) -> bool:
    return any(
        _text_contains_product_inclusions(message.get("content") or message.get("text") or "")
        for message in messages or []
        if isinstance(message, dict)
    )


def _rendered_product_inclusions_visible(rendered: RuntimeV7ChannelRender) -> bool:
    legacy_text_visible = any(
        _text_contains_product_inclusions(message.get("text") or "")
        for message in rendered.content_messages or []
        if isinstance(message, dict) and str(message.get("type") or "") == "text"
    )
    promo_refs = {
        str(value or "").strip().casefold()
        for value in (rendered.promo_presentation or {}).get("promo_refs") or []
        if str(value or "").strip()
    }
    warranty_visual_visible = (
        "promo:the-gulong-double-warranty" in promo_refs
    )
    return legacy_text_visible or warranty_visual_visible


def _text_contains_product_inclusions(value: Any) -> bool:
    text = " ".join(str(value or "").lower().split())
    return "warranty and inclusions:" in text


def _delivery_result_means_customer_visible(delivery_result: Dict[str, Any]) -> bool:
    status = str((delivery_result or {}).get("status") or "").strip().lower()
    return status == "success"


def _followup_result_status(delivery_result: Mapping[str, Any]) -> str:
    status = str((delivery_result or {}).get("status") or "").strip().lower()
    reason = str((delivery_result or {}).get("reason") or "").strip().lower()
    if status == "success":
        return "success"
    if status in {"suppress", "suppressed", "defer", "deferred"}:
        return "deferred" if status in {"defer", "deferred"} else "suppressed"
    if status == "skipped" and reason == "return_only":
        return "evaluated"
    if status in {"error", "failed", "failure"}:
        return "delivery_failed"
    return "delivery_unknown"


def _customer_recovery_attempt_status(delivery_result: Mapping[str, Any]) -> str:
    result = _followup_result_status(delivery_result)
    return "sent" if result == "success" else result


def _followup_attempt_status(
    *,
    sent: bool,
    decision: Mapping[str, Any],
    validation: Mapping[str, Any],
    delivery_result: Mapping[str, Any],
) -> str:
    if sent:
        return "sent"
    action = str(decision.get("action") or "suppress").strip().lower()
    if action == "defer":
        return "deferred"
    reason = str(delivery_result.get("reason") or decision.get("reason") or "").strip().lower()
    if is_retryable_evaluation_reason(reason):
        return "evaluated"
    if action != "send":
        return "suppressed"
    if str(validation.get("status") or "") == "invalid":
        return "validation_failed"
    result_status = _followup_result_status(delivery_result)
    if result_status in {"delivery_failed", "delivery_unknown", "evaluated"}:
        return result_status
    return "suppressed"


def _emit_followup_alerts(event: Mapping[str, Any]) -> None:
    reasons = {str(item) for item in event.get("validation_reasons") or []}
    meta = event.get("meta") if isinstance(event.get("meta"), Mapping) else {}
    gate = meta.get("gate") if isinstance(meta.get("gate"), Mapping) else {}
    gate_reason = str(gate.get("reason") or "")
    delivered = str(event.get("delivery_status") or "").lower() == "success"
    alerts = []
    if "benefit_ref_not_allowed" in reasons:
        alerts.append("unsupported_commercial_claim_blocked")
    if str(event.get("validation_status") or "") == "invalid":
        alerts.append("followup_semantic_validation_failed")
    if str(event.get("delivery_status") or "").lower() in {"error", "failed", "failure"}:
        alerts.append("followup_delivery_failed")
    if str(event.get("attempt_status") or "").lower() == "delivery_unknown" or str(
        event.get("delivery_status") or ""
    ).lower() == "delivery_unknown":
        alerts.append("followup_delivery_unknown")
    if delivered and gate_reason.startswith("stop_tag"):
        alerts.append("followup_stop_tag_send_violation")
    if delivered and "human_agent" in gate_reason:
        alerts.append("followup_human_takeover_send_violation")
    if delivered and bool(meta.get("prior_sent_same_cadence")):
        alerts.append("followup_duplicate_send_violation")
    if (
        str(event.get("route") or "") == "customer_turn_recovery"
        and str(event.get("delivery_reason") or "") == "customer_turn_already_handled"
    ):
        alerts.append("customer_recovery_already_delivered_event")
    if (
        str(event.get("route") or "") == "customer_turn_recovery"
        and str(event.get("delivery_reason") or "") == "customer_turn_delivery_ambiguous"
    ):
        alerts.append("customer_recovery_delivery_ambiguous")
    for alert in alerts:
        logger.error(
            "followup_alert alert=%s request_id=%s user_id=%s route=%s details=%s",
            alert,
            event.get("request_id"),
            event.get("user_id"),
            event.get("route"),
            json.dumps(
                {
                    "focus_field": event.get("focus_field"),
                    "validation_reasons": list(reasons),
                    "delivery_reason": event.get("delivery_reason"),
                    "release_sha": os.getenv("GIT_SHA", ""),
                    "runtime_host": os.getenv("RUNTIME_HOST", os.getenv("K_SERVICE", "")),
                },
                ensure_ascii=True,
                default=str,
            ),
        )


def _followup_case_fingerprint(case: Mapping[str, Any]) -> str:
    stable = json.dumps(dict(case or {}), sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]


def _synthetic_customer_message_id(*, user_id: str, timestamp: str, content: str) -> str:
    normalized = " ".join(str(content or "").casefold().split())
    stable = f"{user_id}|{timestamp}|{normalized}"
    return "synthetic_customer_" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]


def _remember_promo_delivery_result(
    harness: RuntimeV7Harness,
    rendered: RuntimeV7ChannelRender,
    delivery_result: Dict[str, Any],
) -> None:
    """Finalize the authoritative promo presentation ledger after delivery."""

    if not rendered.promo_presentation or not harness.latest_promo_presentation:
        return
    status = str(delivery_result.get("status") or "unknown").strip().lower()
    entry = deepcopy(harness.latest_promo_presentation)
    entry["delivery_status"] = status
    entry["delivery_result"] = {
        key: deepcopy(value)
        for key, value in delivery_result.items()
        if key in {"status", "status_code", "message", "error", "delivery_mode", "reason"}
    }
    if status == "success":
        entry["delivered_at"] = now_manila_str()
    harness.latest_promo_presentation = entry
    if harness.promo_presentation_history:
        harness.promo_presentation_history[-1] = deepcopy(entry)
    else:
        harness.promo_presentation_history = [deepcopy(entry)]


def _remember_promo_action_attempt(harness: RuntimeV7Harness, request: RuntimeV7APIRequest) -> None:
    """Record a compact validated click with durable correlation identifiers."""

    flow_context = request.flow_context if isinstance(request.flow_context, dict) else {}
    validation = flow_context.get("promo_action_context")
    if not isinstance(validation, dict):
        return
    promo = validation.get("promo") if isinstance(validation.get("promo"), dict) else {}
    received_at = now_manila_str()
    tracking = _promo_action_tracking_context(harness, validation)
    entry = {
        **tracking,
        "catalog_version_id": str(validation.get("catalog_version_id") or ""),
        "promo_id": str(promo.get("promo_id") or ""),
        "promo_ref": str(promo.get("promo_ref") or ""),
        "card_id": str(validation.get("card_id") or ""),
        "action": str(validation.get("action") or ""),
        "selected_brand": str(validation.get("selected_brand") or ""),
        "validation_status": str(validation.get("status") or ""),
        "message_id": str(request.message_id or ""),
        "event_id": str(request.channel_event_id or ""),
        "idempotency_key": str(request.idempotency_key or ""),
        "click_timestamp": str(request.channel_event_ts or ""),
        "delivery_status": "pending",
        "received_at": received_at,
        "processed_at": received_at,
        "attempted_at": received_at,
    }
    harness.latest_promo_action = entry
    history = [
        deepcopy(item)
        for item in harness.promo_action_history
        if str(item.get("idempotency_key") or "") != entry["idempotency_key"]
    ]
    harness.promo_action_history = [*history[-19:], deepcopy(entry)]
    request.flow_context = {
        **flow_context,
        "promo_action_tracking_context": tracking,
    }


def _promo_action_tracking_context(
    harness: RuntimeV7Harness,
    validation: Mapping[str, Any],
) -> Dict[str, str]:
    """Resolve a promo click to its delivered surface when that evidence exists.

    Card id, catalog version, and action remain useful correlation keys when a
    legacy session lacks the original gallery record. A fallback surface ref is
    explicitly labeled as catalog-card correlation, never as proof that a
    particular gallery layout was delivered.
    """

    catalog_version_id = str(validation.get("catalog_version_id") or "").strip()
    card_ref = str(validation.get("card_id") or "").strip()
    promo = validation.get("promo") if isinstance(validation.get("promo"), Mapping) else {}
    promo_id = str(promo.get("promo_id") or "").strip()
    promo_ref = str(promo.get("promo_ref") or promo_id).strip()
    action = str(validation.get("action") or "").strip()
    presentation_ref = ""
    for presentation in [
        getattr(harness, "latest_promo_presentation", {}),
        *reversed(getattr(harness, "promo_presentation_history", []) or []),
    ]:
        if not isinstance(presentation, Mapping):
            continue
        if catalog_version_id and str(presentation.get("catalog_version_id") or "") != catalog_version_id:
            continue
        if card_ref and card_ref not in {
            str(value or "") for value in presentation.get("card_refs") or []
        }:
            continue
        candidate = str(presentation.get("presentation_ref") or "").strip()
        if candidate:
            presentation_ref = candidate
            break
    surface_ref = presentation_ref or ":".join(
        value
        for value in ("promo_card", catalog_version_id, promo_id, card_ref)
        if value
    )
    return {
        "surface_type": "promo_gallery",
        "surface_ref": surface_ref,
        "presentation_ref": presentation_ref,
        "presentation_ref_source": (
            "delivered_promo_presentation"
            if presentation_ref
            else "catalog_card_correlation"
        ),
        "card_ref": card_ref,
        "choice_type": "promo_action",
        "choice_ref": ":".join(
            value for value in ("promo_action", promo_ref, action) if value
        ),
        "promo_id": promo_id,
        "promo_ref": promo_ref,
        "action": action,
        "validation_status": str(validation.get("status") or "").strip(),
    }


def _remember_promo_action_delivery_result(
    harness: RuntimeV7Harness,
    request: RuntimeV7APIRequest,
    delivery_result: Dict[str, Any],
) -> None:
    """Finalize the authoritative promo click ledger after delivery."""

    entry = deepcopy(getattr(harness, "latest_promo_action", {}))
    if not entry or str(entry.get("idempotency_key") or "") != str(request.idempotency_key or ""):
        return
    status = str(delivery_result.get("status") or "unknown").strip().lower()
    entry["delivery_status"] = status
    entry["delivery_result"] = {
        key: deepcopy(value)
        for key, value in delivery_result.items()
        if key in {"status", "status_code", "message", "error", "delivery_mode", "reason"}
    }
    if status == "success":
        entry["delivered_at"] = now_manila_str()
    harness.latest_promo_action = entry
    if harness.promo_action_history:
        harness.promo_action_history[-1] = deepcopy(entry)
    else:
        harness.promo_action_history = [deepcopy(entry)]


def _remember_choice_delivery_result(
    harness: RuntimeV7Harness,
    rendered: RuntimeV7ChannelRender,
    delivery_result: Dict[str, Any],
) -> None:
    """Persist delivered category-choice surfaces as the validation allowlist."""

    if not rendered.choice_presentations:
        return
    status = _interaction_delivery_status(delivery_result)
    now = now_manila_str()
    history = list(harness.choice_presentation_history or [])
    new_refs = {
        str(item.get("presentation_ref") or "").strip()
        for item in rendered.choice_presentations
        if isinstance(item, dict)
        and str(item.get("presentation_ref") or "").strip()
    }
    if status in {"success", "evaluated"} and new_refs:
        superseding_ref = next(iter(new_refs))
        for prior in history:
            if not isinstance(prior, dict):
                continue
            prior_ref = str(prior.get("presentation_ref") or "").strip()
            if (
                prior_ref
                and prior_ref not in new_refs
                and not prior.get("superseded_at")
            ):
                prior["superseded_at"] = now
                prior["superseded_by_ref"] = superseding_ref
    for presentation in rendered.choice_presentations:
        entry = deepcopy(presentation)
        entry["delivery_status"] = status
        entry["created_at"] = now
        entry["expires_at"] = _presentation_expiry(now)
        entry["delivery_result"] = _compact_delivery_result_for_state(delivery_result)
        if status == "success":
            entry["delivered_at"] = now
        history.append(entry)
        harness.latest_choice_presentation = deepcopy(entry)
    harness.choice_presentation_history = history[-10:]


def _apply_promo_provider_truth_guard(turn: Dict[str, Any]) -> None:
    """Never turn a promo-provider failure into a factual no-promo answer."""

    unavailable = False
    validated_product_promo = False
    provider_reasons: List[str] = []
    unmatched_requested_brands: List[str] = []
    active_alternative_brands: List[str] = []
    api_verified_promo_brands: List[str] = []
    validated_product_promo_brands: List[str] = []
    scoped_partial_product_brands: List[str] = []
    grounded_alternative_product_surface = False
    grounded_alternative_promo_surface = False
    requested_promo_types = {
        str(value or "").strip().casefold()
        for item in turn.get("tool_results") or []
        if isinstance(item, dict)
        and item.get("name") in {"product_search", "search_promo_catalog"}
        and isinstance(item.get("args"), dict)
        for value in (item.get("args") or {}).get("promo_types") or []
        if str(value or "").strip()
    }
    partial_product_surface = False
    nonexact_product_result = False
    for item in turn.get("tool_results") or []:
        if not isinstance(item, dict):
            continue
        full = (
            item.get("full_result")
            if isinstance(item.get("full_result"), dict)
            else {}
        )
        if item.get("name") == "search_promo_catalog":
            status = str(full.get("status") or "").strip().casefold()
            if status in {"unavailable", "error"}:
                unavailable = True
                reason = str(full.get("reason") or status).strip()
                if reason:
                    provider_reasons.append(reason)
            unmatched = [
                str(value or "").strip()
                for value in full.get("unmatched_requested_brands") or []
                if str(value or "").strip()
            ]
            if (
                not unmatched
                and full.get("exact_requested_brand_match") is False
            ):
                unmatched = [
                    str(value or "").strip()
                    for value in full.get("requested_brands") or []
                    if str(value or "").strip()
                ]
            unmatched_requested_brands.extend(unmatched)
            allowed_refs = {
                str(value or "").strip()
                for value in full.get("allowed_promo_refs") or []
                if str(value or "").strip()
            }
            alternative_refs = {
                str(value or "").strip()
                for value in full.get("alternative_promo_refs") or []
                if str(value or "").strip()
            }
            for candidate in full.get("candidates") or []:
                if not isinstance(candidate, dict):
                    continue
                candidate_ref = str(candidate.get("promo_ref") or "").strip()
                if candidate_ref not in allowed_refs:
                    continue
                if (
                    candidate.get("query_constraint_match") is not True
                    and candidate_ref not in alternative_refs
                ):
                    continue
                active_alternative_brands.extend(
                    str(value or "").strip()
                    for value in candidate.get("brands") or []
                    if str(value or "").strip()
                )
        if item.get("name") == "product_search":
            promo_evidence = (
                full.get("promo_evidence")
                if isinstance(full.get("promo_evidence"), dict)
                else {}
            )
            api_verified_promo_brands.extend(
                str(value or "").strip()
                for value in promo_evidence.get("verified_brands") or []
                if str(value or "").strip()
            )
            product_status = str(full.get("status") or "").strip().casefold()
            product_result_level = str(full.get("result_level") or "").strip().casefold()
            query_basis = (
                full.get("query_basis")
                if isinstance(full.get("query_basis"), dict)
                else {}
            )
            if product_status == "partial_match":
                partial_product_surface = True
            if (
                product_status == "partial_match"
                or product_result_level in {"near_exact", "partial", "alternate"}
                or query_basis.get("exact_base_query_verified") is False
            ):
                nonexact_product_result = True
            for card in full.get("product_cards") or []:
                if not isinstance(card, dict):
                    continue
                pricing_facts = (
                    card.get("pricing_facts")
                    if isinstance(card.get("pricing_facts"), dict)
                    else {}
                )
                card_has_promo = bool(
                    card.get("promo_savings_line") not in (None, "", [], {})
                    or pricing_facts.get("included_promos")
                )
                if card_has_promo:
                    validated_product_promo = True
                    if str(full.get("status") or "").strip() == "ok":
                        grounded_alternative_product_surface = True
                if product_card_matches_promo_types(
                    card,
                    requested_promo_types=requested_promo_types,
                ):
                    brand = str(card.get("brand") or "").strip()
                    if brand:
                        validated_product_promo_brands.append(brand)
                missing_filters = {
                    str(value or "").strip().casefold()
                    for value in card.get("missing_requested_filters") or []
                    if str(value or "").strip()
                }
                if (
                    product_status == "partial_match"
                    and requested_promo_types
                    and missing_filters.intersection({"promo_only", "promo_type"})
                    and query_basis.get("exact_base_query_verified") is not False
                ):
                    brand = str(card.get("brand") or "").strip()
                    if brand:
                        scoped_partial_product_brands.append(brand)
        if item.get("name") == "present_promo_gallery":
            if str(full.get("status") or "").strip().casefold() == "ok":
                presentation_ref = str(
                    full.get("presentation_ref")
                    or full.get("surface_ref")
                    or ""
                ).strip()
                presented_refs = {
                    str(value or "").strip()
                    for value in full.get("promo_refs") or []
                    if str(value or "").strip()
                }
                grounded_alternative_promo_surface = bool(
                    presented_refs
                    and presentation_ref
                    and full.get("cards")
                    and any(
                        presented_refs.intersection(
                            {
                                str(value or "").strip()
                                for value in (
                                    search_item.get("full_result") or {}
                                ).get("alternative_promo_refs")
                                or []
                                if str(value or "").strip()
                            }
                        )
                        for search_item in turn.get("tool_results") or []
                        if isinstance(search_item, dict)
                        and search_item.get("name") == "search_promo_catalog"
                        and isinstance(search_item.get("full_result"), dict)
                    )
                )
    unmatched_requested_brands = list(
        dict.fromkeys(unmatched_requested_brands)
    )
    # Generic API promo authority proves that a brand has at least one current
    # offer. It does not prove the specific mechanic the customer requested.
    # When a mechanic is explicit, only a product card matching that mechanic
    # may clear a catalog-level unmatched-brand result.
    api_verified = {
        brand.casefold()
        for brand in (
            validated_product_promo_brands
            if requested_promo_types
            else [
                *api_verified_promo_brands,
                *validated_product_promo_brands,
            ]
        )
        if brand
    }
    unmatched_requested_brands = [
        brand
        for brand in unmatched_requested_brands
        if brand.casefold() not in api_verified
    ]
    active_alternative_brands = [
        brand
        for brand in dict.fromkeys(active_alternative_brands)
        if brand.casefold()
        not in {value.casefold() for value in unmatched_requested_brands}
    ]
    if unmatched_requested_brands:
        scoped_partial_brands = {
            brand.casefold()
            for brand in scoped_partial_product_brands
            if brand
        }
        if (
            requested_promo_types
            and all(
                brand.casefold() in scoped_partial_brands
                for brand in unmatched_requested_brands
            )
        ):
            # The provider-owned partial-match surface already states that the
            # exact-size requested-brand card misses the requested promo. Keep
            # that useful fitment result and its separately verified promo
            # alternatives instead of suppressing or replacing the surface.
            turn["promo_provider_truth_guard"] = {
                "status": "validated",
                "reason": "unmatched_promo_brand_scoped_by_product_disclosure",
                "unmatched_requested_brands": unmatched_requested_brands,
                "requested_promo_types": sorted(requested_promo_types),
                "partial_product_surface_suppressed": False,
            }
            return
        suppress_partial_product_surface = bool(
            partial_product_surface
            and not grounded_alternative_product_surface
        )
        if suppress_partial_product_surface:
            suppressed = {
                str(value or "").strip()
                for value in turn.get("suppressed_channel_surface_tools") or []
                if str(value or "").strip()
            }
            suppressed.add("product_search")
            turn["suppressed_channel_surface_tools"] = sorted(suppressed)
        requires_exact_product_confirmation = bool(
            final_composer_output_accepted(turn) and nonexact_product_result
        )
        if requires_exact_product_confirmation:
            brand_text = ", ".join(unmatched_requested_brands)
            requested_size = next(
                (
                    str((item.get("full_result") or {}).get("tire_size") or "").strip()
                    for item in turn.get("tool_results") or []
                    if isinstance(item, dict)
                    and item.get("name") == "search_promo_catalog"
                    and isinstance(item.get("full_result"), dict)
                    and str((item.get("full_result") or {}).get("tire_size") or "").strip()
                ),
                "",
            )
            if grounded_alternative_promo_surface:
                response = (
                    "Wala akong na-verify na exact "
                    f"{brand_text}{f' {requested_size}' if requested_size else ''} "
                    "option para sa requested promo. Narito ang current verified "
                    "promo alternatives na maaari ninyong i-check."
                )
            elif requested_size:
                response = (
                    "Wala akong na-verify na exact "
                    f"{brand_text} {requested_size} option para sa requested promo. "
                    "Wala ring verified applicable promo alternative na bumalik "
                    "sa current check."
                )
            else:
                response = (
                    "Sa current reviewed promos, wala pang confirmed exact "
                    "matching tire product para "
                    f"sa requested {brand_text} promo. Ano po ang exact tire size "
                    "at model na gusto ninyong i-check?"
                )
            _set_runtime_turn_response(
                turn,
                response,
                owner="runtime_commercial_truth_guard",
                preserve_validated_promo_surfaces=True,
            )
            turn["promo_provider_truth_guard"] = {
                "status": "rewritten",
                "reason": "unmatched_promo_brand_requires_exact_product_match",
                "unmatched_requested_brands": unmatched_requested_brands,
                "partial_product_surface_suppressed": (
                    suppress_partial_product_surface
                ),
            }
            return
        has_negative_promo_fact = _response_has_negative_promo_fact(
            turn,
            unmatched_requested_brands,
        )
        has_scoped_negative_promo_fact = (
            has_negative_promo_fact
            and _response_has_reviewed_promo_scope(turn)
        )
        if not has_scoped_negative_promo_fact:
            brand_text = ", ".join(unmatched_requested_brands)
            alternative_text = ", ".join(active_alternative_brands)
            if grounded_alternative_promo_surface:
                response = (
                    "Sa current reviewed promos namin, wala pong promo na "
                    f"tugma para sa {brand_text}. Narito ang current verified "
                    "promo alternatives na maaari ninyong i-check."
                )
            elif alternative_text:
                response = (
                    "Sa current reviewed promos namin, wala pong promo na "
                    f"tugma para sa {brand_text}. May active promo options "
                    f"po para sa {alternative_text}; puwede ko pong ipakita "
                    "ang details para makapag-compare kayo."
                )
            else:
                response = (
                    "Sa current reviewed promos namin, wala pong promo na "
                    f"tugma para sa {brand_text}. Puwede ko pong i-check ang "
                    "ibang active promo options para sa inyo."
                )
            _set_runtime_turn_response(
                turn,
                response,
                owner="runtime_commercial_truth_guard",
                preserve_validated_promo_surfaces=True,
            )
            turn["promo_provider_truth_guard"] = {
                "status": "rewritten",
                "reason": (
                    "unmatched_requested_promo_brand_requires_scoped_answer"
                    if has_negative_promo_fact
                    else "unmatched_requested_promo_brand_requires_answer"
                ),
                "unmatched_requested_brands": unmatched_requested_brands,
                "partial_product_surface_suppressed": (
                    suppress_partial_product_surface
                ),
            }
            return
        turn["promo_provider_truth_guard"] = {
            "status": "validated",
            "reason": "unmatched_requested_promo_brand_scoped_answer",
            "unmatched_requested_brands": unmatched_requested_brands,
            "partial_product_surface_suppressed": (
                suppress_partial_product_surface
            ),
        }
    if not unavailable or validated_product_promo:
        return
    response = (
        "Sorry po, hindi ko ma-verify ang current promo list right now, kaya "
        "ayokong magsabi na walang promo nang walang validated source. Pwede "
        "kong i-retry ang promo check or continue with the exact current "
        "product and price options."
    )
    _set_runtime_turn_response(turn, response)
    turn["promo_provider_truth_guard"] = {
        "status": "rewritten",
        "reason": "promo_provider_unavailable_is_not_negative_evidence",
        "provider_reasons": list(dict.fromkeys(provider_reasons)),
    }


def _response_has_negative_promo_fact(
    turn: Dict[str, Any],
    brands: Sequence[str],
) -> bool:
    """Return whether prose answers each reviewed unmatched-brand result."""

    response = " ".join(
        re.sub(
            r"[^a-z0-9+]+",
            " ",
            _runtime_turn_response_text(turn).casefold(),
        ).split()
    )
    if not response or not any(
        cue in response
        for cue in (
            "no current",
            "no verified",
            "not available",
            "does not have",
            "doesn t have",
            "hindi available",
            "walang",
            "wala",
        )
    ):
        return False
    if not any(token in response for token in ("promo", "3+1", "3 1")):
        return False
    for brand in brands:
        normalized = " ".join(
            re.findall(r"[a-z0-9]+", str(brand or "").casefold())
        )
        if not normalized or not re.search(
            rf"(?:^|\s){re.escape(normalized)}(?:\s|$)",
            response,
        ):
            return False
    return True


def _response_has_reviewed_promo_scope(turn: Dict[str, Any]) -> bool:
    """Require prose to identify a bounded reviewed or verified promo scope."""

    response = " ".join(
        re.sub(
            r"[^a-z0-9]+",
            " ",
            _runtime_turn_response_text(turn).casefold(),
        ).split()
    )
    tokens = set(response.split())
    return bool(
        "promo" in tokens
        and (
            "verified" in tokens
            or "reviewed" in tokens
            or (
                "current" in tokens
                and ("catalog" in tokens or "list" in tokens)
            )
        )
    )










def _complete_customer_payment_queries(
    turn: Dict[str, Any],
    policies: List[Dict[str, Any]],
    *,
    request: RuntimeV7APIRequest,
    harness: RuntimeV7Harness,
) -> None:
    """Resolve only typed payment-query scopes selected by the semantic model."""

    provider = getattr(harness, "canonical_values_provider", None)
    if provider is None:
        return
    plans = _semantic_customer_payment_query_plans(turn, request=request)
    if not plans:
        return

    # A model-proposed result can carry the right method identity without a
    # claimable checkout outcome. It is not resolved authority and must not
    # prevent Runtime from executing the customer-backed plan again.
    known = {
        _payment_policy_identity(policy)
        for policy in policies
        if payment_claim(policy)
    }
    known_unsupported_methods = {
        " ".join(
            re.findall(
                r"[a-z0-9]+",
                str(
                    policy.get("requested_payment_name")
                    or policy.get("requested_payment_method")
                    or ""
                ).casefold(),
            )
        )
        for policy in policies
        if str(policy.get("requested_payment_status") or "").strip()
        == "unsupported"
    }
    known_categories = {
        (
            str(policy.get("requested_payment_category") or ""),
            str(policy.get("payment_option") or ""),
        )
        for policy in policies
        if str(policy.get("requested_payment_category") or "")
    }
    added = 0
    for lookup_args in plans:
        category_identity = (
            str(lookup_args.get("requested_payment_category") or ""),
            str(lookup_args.get("payment_option") or ""),
        )
        if category_identity[0] and category_identity in known_categories:
            continue
        proposed_method = " ".join(
            re.findall(
                r"[a-z0-9]+",
                str(
                    lookup_args.get("requested_payment_method") or ""
                ).casefold(),
            )
        )
        if proposed_method and proposed_method in known_unsupported_methods:
            continue
        result = answer_order_faq(
            lookup_args,
            canonical_values_provider=provider,
        )
        candidate = (
            result.get("payment_policy")
            if isinstance(result.get("payment_policy"), dict)
            else {}
        )
        identity = _payment_policy_identity(candidate)
        if category_identity[0]:
            if not candidate:
                continue
            policies.append(candidate)
            known_categories.add(category_identity)
            turn.setdefault("tool_results", []).append(
                {
                    "name": "answer_order_faq",
                    "args": deepcopy(lookup_args),
                    "result": {
                        "status": str(result.get("status") or ""),
                        "source": str(result.get("source") or ""),
                    },
                    "full_result": result,
                    "source": "runtime_required_payment_category_lookup",
                }
            )
            added += 1
            continue
        if not candidate or not any(identity) or identity in known:
            continue
        policies.append(candidate)
        known.add(identity)
        turn.setdefault("tool_results", []).append(
            {
                "name": "answer_order_faq",
                "args": deepcopy(lookup_args),
                "result": {
                    "status": str(result.get("status") or ""),
                    "source": str(result.get("source") or ""),
                },
                "full_result": result,
                "source": "runtime_required_payment_policy_lookup",
            }
        )
        added += 1
    if added:
        turn["payment_policy_lookup"] = {
            "status": "runtime_required",
            "reason": "model_omitted_compound_payment_policy_lookup",
            "lookup_count": added,
        }


def _semantic_customer_payment_query_plans(
    turn: Dict[str, Any],
    *,
    request: RuntimeV7APIRequest,
) -> List[Dict[str, Any]]:
    """Compile isolated bounded scopes without deciding payment truth."""

    decision = (
        turn.get("payment_query_decision")
        if isinstance(turn.get("payment_query_decision"), dict)
        else {}
    )
    if str(decision.get("decision") or "") in {
        "no_payment_request",
        "unclear",
    }:
        return []
    output: List[Dict[str, Any]] = []
    for query in decision.get("payment_queries") or []:
        if not isinstance(query, dict):
            continue
        scope_kind = str(query.get("scope_kind") or "named_method")
        method = " ".join(
            str(query.get("requested_payment_method") or "").split()
        )
        brand = " ".join(
            str(query.get("requested_product_brand") or "").split()
        )
        payment_option = " ".join(
            str(query.get("payment_option") or "").split()
        )
        if scope_kind == "method_category":
            method_category = str(query.get("method_category") or "").strip()
            if method_category not in {
                "e_wallet",
                "card",
                "installment",
                "bank_transfer",
                "financing",
                "all_methods",
            }:
                continue
            plan = {
                "question": "How do I Pay?",
                "requested_payment_category": method_category,
            }
            if payment_option:
                plan["payment_option"] = payment_option
            output.append(plan)
            continue
        if not method or len(method) > 60 or len(method.split()) > 8:
            continue
        if brand and (len(brand) > 40 or len(brand.split()) > 5):
            continue
        if payment_option and (
            len(payment_option) > 40 or len(payment_option.split()) > 6
        ):
            continue
        plan: Dict[str, Any] = {
            # Canonicalize this independent scope without letting a bank or
            # installment term from a sibling clause bleed into it. The full
            # customer turn was already interpreted by the typed decision.
            "question": method,
            "requested_payment_method": method,
        }
        if brand:
            plan["requested_product_brand"] = brand
        if payment_option:
            plan["payment_option"] = payment_option
        output.append(plan)
    unique: Dict[tuple[str, str, str, str], Dict[str, Any]] = {}
    for plan in output:
        key = (
            str(plan.get("requested_payment_method") or "").casefold(),
            str(plan.get("requested_product_brand") or "").casefold(),
            str(plan.get("payment_option") or "").casefold(),
            str(plan.get("requested_payment_category") or "").casefold(),
        )
        unique.setdefault(key, plan)
    return list(unique.values())


def _typed_payment_query_requested(turn: Dict[str, Any]) -> bool:
    """Return whether the semantic payment decision authorized lookup."""

    decision = (
        turn.get("payment_query_decision")
        if isinstance(turn.get("payment_query_decision"), dict)
        else {}
    )
    return bool(
        str(decision.get("decision") or "")
        not in {"", "no_payment_request", "unclear"}
        and any(
            isinstance(query, dict) and query
            for query in decision.get("payment_queries") or []
        )
    )


def _record_commercial_payment_claims(turn: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Attach deduplicated provider-backed payment claims to turn telemetry.

    The claims describe authoritative payment tool results already used to
    validate the visible response. They do not infer customer intent and do
    not rewrite composer-owned text.
    """

    claims = [
        claim
        for policy in payment_policies_from_tool_results(
            turn.get("tool_results") or []
        )
        if (claim := payment_claim(policy))
    ]
    turn["commercial_payment_claims"] = claims
    return claims


def _apply_payment_policy_truth_guard(
    turn: Dict[str, Any],
    *,
    request: Optional[RuntimeV7APIRequest] = None,
    harness: Optional[RuntimeV7Harness] = None,
) -> None:
    """Enforce payment support and brand eligibility from checkout metadata."""

    policies: List[Dict[str, Any]] = []
    policy: Dict[str, Any] = {}
    for item in turn.get("tool_results") or []:
        if not isinstance(item, dict) or item.get("name") != "answer_order_faq":
            continue
        full = (
            item.get("full_result")
            if isinstance(item.get("full_result"), dict)
            else {}
        )
        candidate = (
            full.get("payment_policy")
            if isinstance(full.get("payment_policy"), dict)
            else {}
        )
        if candidate:
            policies.append(candidate)
            policy = candidate
    if request is not None and harness is not None:
        _complete_customer_payment_queries(
            turn,
            policies,
            request=request,
            harness=harness,
        )
    policies = _dedupe_payment_policies(policies)
    if policies:
        policy = policies[-1]
    fact_policies = [
        candidate
        for candidate in policies
        if str(candidate.get("requested_payment_status") or "").strip()
        == "unsupported"
        or str(candidate.get("requested_brand_eligibility") or "").strip()
        in {"eligible", "not_eligible", "not_brand_restricted"}
    ]
    claimable_fact_policies = [
        candidate for candidate in fact_policies if payment_claim(candidate)
    ]
    _record_commercial_payment_claims(turn)
    commercial_claim_violations = payment_claim_contract_violations(
        str(turn.get("runtime_final_response") or ""),
        turn.get("tool_results") or [],
    )
    if claimable_fact_policies and not commercial_claim_violations:
        return
    if len(claimable_fact_policies) > 1:
        if commercial_claim_violations:
            facts = list(
                dict.fromkeys(
                    fact
                    for candidate in claimable_fact_policies
                    if (fact := _validated_payment_policy_fact(candidate))
                )
            )
            if facts:
                _set_runtime_turn_responses(
                    turn,
                    facts,
                    owner="runtime_commercial_truth_guard",
                )
                turn["payment_policy_truth_guard"] = {
                    "status": "rewritten",
                    "reason": "multi_claim_payment_facts_use_checkout_authority",
                    "sources": list(
                        dict.fromkeys(
                            str(candidate.get("source") or "")
                            for candidate in claimable_fact_policies
                            if str(candidate.get("source") or "")
                        )
                    ),
                    "claim_count": len(claimable_fact_policies),
                }
                return
    requested_status = str(
        policy.get("requested_payment_status") or ""
    ).strip()
    eligibility = str(
        policy.get("requested_brand_eligibility") or ""
    ).strip()
    if requested_status == "unsupported":
        method = str(policy.get("requested_payment_method") or "").strip()
        # Pay Now / Pay Later describe payment timing, not a checkout method.
        # A model-proposed policy lookup can still send customer wording such
        # as "full payment" as requested_payment_method.  Do not let that
        # malformed query plan contradict a separately validated payment
        # option and its rendered method surface.
        if normalize_payment_option(method):
            turn["payment_policy_truth_guard"] = {
                "status": "ignored",
                "reason": "payment_option_is_not_a_payment_method",
                "source": str(policy.get("source") or ""),
                "requested_payment_method": method or None,
            }
            return
        alternatives = _active_payment_method_names(policy, limit=3)
        alternative_text = (
            " Current options include "
            + ", ".join(alternatives)
            + "."
            if alternatives else ""
        )
        _set_runtime_turn_response(
            turn,
            f"{method or 'Yung payment method na iyon'} wala po sa current payment options."
            f"{alternative_text}",
            owner="runtime_commercial_truth_guard",
        )
        turn["payment_policy_truth_guard"] = {
            "status": "rewritten",
            "reason": "unsupported_method_uses_checkout_authority",
            "source": str(policy.get("source") or ""),
            "requested_payment_method": method or None,
        }
        return
    if eligibility == "not_eligible":
        method = str(policy.get("requested_payment_method") or "").strip()
        brand = str(policy.get("requested_product_brand") or "").strip()
        _set_runtime_turn_response(
            turn,
            (
                f"{method or 'That payment method'} is not currently available "
                f"for {brand or 'that brand'} under the active checkout options."
            ),
            owner="runtime_commercial_truth_guard",
        )
        turn["payment_policy_truth_guard"] = {
            "status": "rewritten",
            "reason": "brand_excluded_by_checkout_allowlist",
            "source": str(policy.get("source") or ""),
            "requested_payment_method": method or None,
            "requested_product_brand": brand or None,
        }
        return
    # A grounded positive fact that the composer omitted is a quality issue,
    # not a safety violation. The model-owned composer must answer it during
    # its normal repair loop; this post-composition guard does not inject a
    # fixed answer or CTA.
    missing_policy_for_inquiry = (
        not policy
        and request is not None
        and _typed_payment_query_requested(turn)
    )
    if eligibility != "needs_product_validation" and not missing_policy_for_inquiry:
        return
    method = str(policy.get("requested_payment_method") or "").strip()
    brand = str(policy.get("requested_product_brand") or "").strip()
    readiness = (
        turn.get("order_readiness_after_tools")
        if isinstance(turn.get("order_readiness_after_tools"), dict)
        else turn.get("order_readiness_before_turn")
        if isinstance(turn.get("order_readiness_before_turn"), dict)
        else {}
    )
    collected = (
        readiness.get("collected")
        if isinstance(readiness.get("collected"), dict)
        else {}
    )
    selected_product = str(collected.get("Product") or "").strip()
    if selected_product:
        fact_response = (
            (
                f"Available po ang {method or 'requested payment method'} as a "
                "payment method, pero hindi pa confirmed sa current checkout "
                f"options ang compatibility nito with the selected "
                f"{brand or 'product'}."
            )
            if policy
            else (
                "Hindi ko pa ma-confirm from the current checkout options "
                "whether the requested payment method applies to the selected "
                "product."
            )
        )
        fact_response += (
            " Iche-check natin ito before finalizing the order. Wala pa pong "
            "payment choice na na-set."
        )
        _set_runtime_turn_response(
            turn,
            fact_response,
            owner="runtime_commercial_truth_guard",
        )
    else:
        fact_response = (
            (
                f"Available po ang {method or 'requested payment method'} as a "
                "payment method, pero product-specific compatibility still "
                "depends on the exact tire."
            )
            if policy
            else (
                "Hindi ko pa ma-confirm from the current checkout options "
                "whether the requested payment method applies to a specific "
                "tire."
            )
        )
        _set_runtime_turn_response(
            turn,
            fact_response,
            owner="runtime_commercial_truth_guard",
        )
    turn["payment_policy_truth_guard"] = {
        "status": "rewritten",
        "reason": "general_brand_absence_is_not_negative_evidence",
        "source": str(policy.get("source") or ""),
        "requested_payment_method": method or None,
        "requested_product_brand": brand or None,
    }






def _restrictive_payment_policy_fact(policy: Dict[str, Any]) -> str:
    """Return a safe fallback fact for a validated negative payment claim."""

    method = _customer_payment_method_label(policy)
    brand = _customer_brand_label(
        policy.get("requested_product_brand")
    )
    if str(policy.get("requested_payment_status") or "").strip() == "unsupported":
        return (
            f"Hindi po available ang {method or 'payment method na iyon'} "
            "bilang payment method."
        )
    if (
        str(policy.get("requested_brand_eligibility") or "").strip()
        == "not_eligible"
    ):
        return (
            f"Hindi po available ang {method or 'payment method na iyon'} "
            f"para sa {brand or 'brand na iyon'}."
        )
    return ""


def _active_payment_method_names(
    policy: Mapping[str, Any],
    *,
    limit: int,
) -> List[str]:
    """Return a short deduplicated alternative list from checkout authority."""

    by_option = (
        policy.get("active_methods_by_option")
        if isinstance(policy.get("active_methods_by_option"), Mapping)
        else {}
    )
    names: List[str] = []
    for values in by_option.values():
        for value in values if isinstance(values, list) else []:
            name = str(value or "").strip()
            if name and name not in names:
                names.append(name)
            if len(names) >= max(1, limit):
                return names
    return names


def _validated_payment_policy_fact(policy: Dict[str, Any]) -> str:
    """Return a safe factual sentence for one checkout-backed payment claim."""

    restrictive = _restrictive_payment_policy_fact(policy)
    if restrictive:
        return restrictive
    eligibility = str(
        policy.get("requested_brand_eligibility") or ""
    ).strip()
    if eligibility not in {"eligible", "not_brand_restricted"}:
        return ""
    method = _customer_payment_method_label(policy)
    brand = _customer_brand_label(
        policy.get("requested_product_brand")
    )
    payment_option = payment_option_label(
        policy.get("payment_option")
    )
    scope = f" under {payment_option}" if payment_option else ""
    if brand:
        return (
            f"Available po ang {method or 'payment method na iyon'} para sa "
            f"{brand}{scope}."
        )
    return f"Supported po ang {method or 'payment method na iyon'}{scope}."


def _customer_payment_method_label(policy: Dict[str, Any]) -> str:
    """Turn an exact checkout method name into natural fallback copy."""

    label = str(
        policy.get("requested_payment_name")
        or policy.get("requested_payment_method")
        or ""
    ).strip()
    label = re.sub(
        r"\b(\d+)\s*-\s*(?:mos?|months?)\b",
        r"\1-month",
        label,
        flags=re.IGNORECASE,
    )
    label = re.sub(
        r"\(\s*(0%\s*interest)\s*\)",
        r"\1",
        label,
        flags=re.IGNORECASE,
    )
    label = re.sub(
        r"\bInstallment\b",
        "installment",
        label,
        flags=re.IGNORECASE,
    )
    return " ".join(label.split())


def _customer_brand_label(value: Any) -> str:
    """Use readable title casing for canonical all-caps brand labels."""

    label = str(value or "").strip()
    return label.title() if label.isupper() else label


def _response_has_restrictive_payment_fact(
    turn: Dict[str, Any],
    policy: Dict[str, Any],
) -> bool:
    """Check that the composer covered each validated negative payment claim."""

    raw_response = _runtime_turn_response_text(turn).casefold()
    segments = [
        " ".join(re.sub(r"[^a-z0-9]+", " ", segment).split())
        for segment in re.split(
            r"(?:[.!?;\n]+|\bbut\b|\bhowever\b|\bpero\b|\bsubalit\b)",
            raw_response,
        )
    ]
    segments = [segment for segment in segments if segment]
    if not segments:
        return False
    anchors = [
        token
        for token in re.findall(
            r"[a-z0-9]+",
            str(policy.get("requested_payment_method") or "").casefold(),
        )
        if token
        not in {
            "payment",
            "method",
            "credit",
            "card",
            "interest",
            "zero",
            "0",
            "months",
            "month",
            "mos",
            "installment",
        }
    ]
    brand = re.sub(
        r"[^a-z0-9]+",
        " ",
        str(policy.get("requested_product_brand") or "").casefold(),
    ).strip()
    if brand:
        anchors.extend(brand.split())
    anchors = list(dict.fromkeys(anchors))
    negative_patterns = (
        r"\bnot(?:\s+currently)?\s+supported\b",
        r"\bunsupported\b",
        r"\bnot(?:\s+currently)?\s+available\b",
        r"\bunavailable\b",
        r"\bnot(?:\s+currently)?\s+eligible\b",
        r"\bhindi(?:\s+\w+){0,2}\s+available\b",
        r"\bhindi(?:\s+\w+){0,2}\s+supported\b",
        r"\bhindi(?:\s+\w+){0,2}\s+eligible\b",
        r"\bwala\b",
    )
    return bool(anchors) and any(
        any(re.search(pattern, segment) for pattern in negative_patterns)
        and all(
            re.search(rf"\b{re.escape(token)}\b", segment)
            for token in anchors
        )
        for segment in segments
    )


def _recommend_serviceable_cities(
    args: Dict[str, Any],
    *,
    request: RuntimeV7APIRequest,
    harness: RuntimeV7Harness,
    provider: Any,
) -> Dict[str, Any]:
    """Rank serviceable cities from isolated read-only slot previews."""

    action = (
        request.flow_context.get("choice_action_runtime_context")
        if isinstance(request.flow_context, dict)
        else {}
    )
    province_label = str(
        (action or {}).get("label")
        or args.get("location")
        or ""
    ).strip()
    turn_id = str(
        request.message_id
        or request.idempotency_key
        or "turn_city_recommendation"
    )
    resolve_surface = getattr(
        provider,
        "city_surface_for_province_label",
        None,
    )
    surface = (
        resolve_surface(
            province_label=province_label,
            turn_id=turn_id,
        )
        if callable(resolve_surface)
        else {}
    )
    if not surface:
        return {
            "status": "no_serviceable_city_choices",
            "recommendation_mode": "serviceable_city",
            "read_only": True,
        }

    shared = harness.service_tools
    preview_tools = RuntimeV7ServiceTools(
        store=ServiceObservationStore(),
        canonical_values_provider=getattr(
            shared,
            "canonical_values_provider",
            None,
        ),
        installation_partner_tool=getattr(
            shared,
            "installation_partner_tool",
            None,
        ),
        installation_slot_lookup=getattr(
            shared,
            "installation_slot_lookup",
            None,
        ),
    )
    choices = []
    preview_refs = []
    for choice in surface.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        city_label = str(choice.get("label") or "").strip()
        province = str(
            choice.get("province_label")
            or surface.get("parent_label")
            or province_label
        ).strip()
        city_args = {
            key: deepcopy(args.get(key))
            for key in (
                "preferred_date",
                "preferred_date_start",
                "preferred_date_end",
                "preferred_time_window",
                "source_schedule_phrase",
                "preferred_schedule_candidates",
                "request_time",
                "section_width",
                "aspect_ratio",
                "rim_size",
                "model_query",
                "tire_brand",
                "quantity",
                "trusted_order_total",
            )
            if args.get(key) not in (None, "", [], {})
        }
        city_args.update(
            {
                "location": ", ".join(
                    value for value in [city_label, province] if value
                ),
                "service_type": "installation",
                "partner_detail_level": "availability_summary",
                "top_k": 1,
                "slots_per_partner": 1,
                "max_days": min(int(args.get("max_days") or 7), 7),
            }
        )
        result = preview_tools.find_installation_slots(city_args)
        preview = _earliest_city_slot_preview(result)
        item = deepcopy(choice)
        if preview:
            item["earliest_slot_preview"] = preview
            item["earliest_slot_sort_key"] = str(
                preview.get("start") or ""
            )
        observation_ref = str(result.get("observation_ref") or "").strip()
        if observation_ref:
            preview_refs.append(observation_ref)
        choices.append(item)

    choices.sort(
        key=lambda item: (
            0 if item.get("earliest_slot_sort_key") else 1,
            str(item.get("earliest_slot_sort_key") or "9999"),
            -int(item.get("partner_count") or 0),
            str(item.get("label") or ""),
        )
    )
    surface = deepcopy(surface)
    surface["choices"] = choices
    surface["recommendation_mode"] = "earliest_availability_then_partner_count"
    surface["preview_observation_refs"] = preview_refs
    surface["preview_is_selection"] = False
    return {
        "status": "ok",
        "recommendation_mode": "serviceable_city",
        "location_choice_surface": surface,
        "preview_observation_refs": preview_refs,
        "read_only": True,
        "can_confirm_booking": False,
    }


def _execute_location_choice_plan(
    args: Dict[str, Any],
    *,
    request: RuntimeV7APIRequest,
    harness: RuntimeV7Harness,
    provider: Any,
) -> Dict[str, Any]:
    """Execute a model-proposed location plan without granting factual authority.

    The model owns whether a location-choice surface is useful for the current
    conversational goal. This executor owns the finite plan modes and returns
    only provider-backed routing surfaces; it cannot infer a customer location,
    prove serviceability, choose a branch, or confirm a schedule.
    """

    mode = str(args.get("discovery_mode") or "").strip()
    if mode == "recommend_serviceable_cities":
        return _recommend_serviceable_cities(
            args,
            request=request,
            harness=harness,
            provider=provider,
        )
    if mode != "serviceable_provinces":
        return {
            "status": "invalid_plan",
            "reason": "unsupported_location_choice_plan",
            "routing_only": True,
            "read_only": True,
        }
    turn_id = str(
        request.message_id
        or request.idempotency_key
        or "turn_serviceable_provinces"
    )
    surface = provider.province_surface(turn_id=turn_id)
    if not surface:
        return {
            "status": "unavailable",
            "reason": "serviceable_province_choices_unavailable",
            "routing_only": True,
            "read_only": True,
        }
    return {
        "status": "ok",
        "choice_level": "province",
        "location_choice_surface": surface,
        "routing_only": True,
        "read_only": True,
        "can_confirm_serviceability": False,
        "can_select_location": False,
        "can_confirm_booking": False,
    }


def _earliest_city_slot_preview(result: Dict[str, Any]) -> Dict[str, Any]:
    """Return the earliest compact slot without exposing it as selectable."""

    slots = [
        slot
        for group in result.get("slot_groups") or []
        if isinstance(group, dict)
        for slot in group.get("slots") or []
        if isinstance(slot, dict)
    ]
    slots.sort(
        key=lambda slot: (
            str(slot.get("start") or ""),
            str(slot.get("date") or ""),
            str(slot.get("time_text") or ""),
        )
    )
    if not slots:
        return {}
    slot = slots[0]
    return {
        "date": str(slot.get("date") or ""),
        "weekday": str(slot.get("weekday") or ""),
        "time_text": str(slot.get("time_text") or ""),
        "start": str(slot.get("start") or ""),
    }


def _plan_customer_turn_surfaces(
    partial_turn: Dict[str, Any],
    *,
    request: RuntimeV7APIRequest,
    harness: RuntimeV7Harness,
    provider: Any,
) -> Dict[str, Any]:
    """Plan renderer-owned choice surfaces before final composition."""

    planned = deepcopy(partial_turn)
    recommendation_surface = next(
        (
            item.get("full_result", {}).get("location_choice_surface")
            for item in reversed(planned.get("tool_results") or [])
            if isinstance(item, dict)
            and item.get("name") == "find_installation_slots"
            and isinstance(item.get("full_result"), dict)
            and isinstance(
                item.get("full_result", {}).get(
                    "location_choice_surface"
                ),
                dict,
            )
        ),
        {},
    )
    if recommendation_surface:
        planned["location_choice_surface"] = deepcopy(
            recommendation_surface
        )
        planned["location_choice_surface_status"] = {
            "status": "attached",
            "reason": "customer_unsure_city_ranked_preview",
            "slots_authorized": False,
        }
    model_requested_surface = next(
        (
            item.get("full_result", {}).get("location_choice_surface")
            for item in reversed(planned.get("tool_results") or [])
            if isinstance(item, dict)
            and item.get("name")
            == "present_serviceable_location_choices"
            and isinstance(item.get("full_result"), dict)
            and item.get("full_result", {}).get("status") == "ok"
            and item.get("full_result", {}).get("routing_only") is True
            and isinstance(
                item.get("full_result", {}).get(
                    "location_choice_surface"
                ),
                dict,
            )
        ),
        {},
    )
    if model_requested_surface and _model_requested_location_surface_allowed(
        planned,
        request=request,
    ):
        planned["location_choice_surface"] = deepcopy(
            model_requested_surface
        )
        planned["location_choice_surface_status"] = {
            "status": "attached",
            "reason": "model_requested_serviceable_location_choices",
            "routing_only": True,
            "slots_authorized": False,
        }
    _attach_location_choice_surface(
        planned,
        request=request,
        provider=provider,
    )
    _attach_checkout_choice_surface(
        planned,
        request=request,
        harness=harness,
    )
    return {
        key: deepcopy(planned[key])
        for key in (
            "location_choice_surface",
            "location_choice_surface_status",
            "checkout_choice_surface",
            "checkout_choice_surface_status",
        )
        if planned.get(key) not in (None, "", [], {})
    }


def _model_requested_location_surface_allowed(
    turn: Mapping[str, Any],
    *,
    request: RuntimeV7APIRequest,
) -> bool:
    """Validate that a model-requested province surface is context-compatible.

    This guard validates structured state only. It deliberately does not
    reinterpret raw customer language or second-guess the model with keywords.
    """

    readiness = (
        turn.get("order_readiness_after_tools")
        if isinstance(turn.get("order_readiness_after_tools"), Mapping)
        else turn.get("order_readiness_before_turn")
        if isinstance(turn.get("order_readiness_before_turn"), Mapping)
        else {}
    )
    collected = (
        readiness.get("collected")
        if isinstance(readiness.get("collected"), Mapping)
        else {}
    )
    if (
        str(collected.get("Fulfillment") or "").strip().casefold()
        == "delivery"
        or str(collected.get("Delivery address") or "").strip()
    ):
        return False
    flow = request.flow_context if isinstance(request.flow_context, dict) else {}
    action = flow.get("choice_action_runtime_context")
    if (
        isinstance(action, Mapping)
        and action.get("validation_status") == "valid"
        and action.get("choice_type") == "serviceable_city"
    ):
        return False
    return True


def _attach_location_choice_surface(
    turn: Dict[str, Any],
    *,
    request: RuntimeV7APIRequest,
    provider: Any,
) -> None:
    """Attach a trusted location surface without making the renderer call APIs."""

    if isinstance(turn.get("location_choice_surface"), dict):
        return
    if not _model_requested_location_surface_allowed(turn, request=request):
        turn["location_choice_surface_status"] = {
            "status": "not_attached",
            "reason": "delivery_or_resolved_city_guard",
            "slots_authorized": False,
        }
        return
    flow = request.flow_context if isinstance(request.flow_context, dict) else {}
    action = flow.get("choice_action_runtime_context")
    turn_id = str(turn.get("turn_id") or request.message_id or request.idempotency_key or "turn")
    try:
        if (
            isinstance(action, dict)
            and action.get("validation_status") == "valid"
            and action.get("choice_type") == "serviceable_province"
            and str(action.get("choice_code") or "") != "other"
        ):
            surface = provider.city_surface(
                province_code=str(action.get("choice_code") or ""),
                turn_id=turn_id,
            )
            if surface:
                turn["location_choice_surface"] = surface
            return
        province_label = _province_only_location_label(turn)
        resolve_surface = getattr(
            provider,
            "city_surface_for_province_label",
            None,
        )
        if province_label and callable(resolve_surface):
            surface = resolve_surface(
                province_label=province_label,
                turn_id=turn_id,
            )
            if surface:
                turn["location_choice_surface"] = surface
                turn["location_choice_surface_status"] = {
                    "status": "attached",
                    "reason": "province_only_free_text",
                    "location_precision": "province_only",
                    "slots_authorized": False,
                }
                return
        readiness = (
            turn.get("order_readiness_after_tools")
            if isinstance(turn.get("order_readiness_after_tools"), dict)
            else turn.get("order_readiness_before_turn")
            if isinstance(turn.get("order_readiness_before_turn"), dict)
            else {}
        )
        collected = (
            readiness.get("collected")
            if isinstance(readiness.get("collected"), dict)
            else {}
        )
        fulfillment = str(collected.get("Fulfillment") or "").strip().casefold()
        if fulfillment == "delivery" or str(collected.get("Delivery address") or "").strip():
            # Serviceable province/city controls qualify installation coverage.
            # They are contradictory after a customer chooses delivery and
            # supplies a delivery address, even if the lead CTA still carries
            # an older optional installation-location focus.
            return
    except Exception as exc:
        # Location buttons are progressive enhancement. The existing typed CTA
        # remains valid if the current branch/catalog lookup is unavailable.
        turn["location_choice_surface_status"] = {
            "status": "not_attached",
            "reason": "provider_unavailable",
            "slots_authorized": False,
        }
        logger.warning(
            "Runtime V7 location choice surface unavailable turn_id=%s error=%s",
            turn_id,
            exc.__class__.__name__,
        )


def _province_only_location_label(turn: Dict[str, Any]) -> str:
    """Return a latest-message province only when no city was resolved."""

    for signal in reversed(turn.get("background_signals_before_turn") or []):
        if not isinstance(signal, dict):
            continue
        if str(signal.get("key") or "").strip() != "location":
            continue
        if str(signal.get("source") or "").strip() not in {
            "latest_user_message",
            "validated_choice_action",
            "signal_ledger",
        }:
            continue
        resolution = (
            signal.get("resolution")
            if isinstance(signal.get("resolution"), dict)
            else {}
        )
        metadata = (
            signal.get("metadata")
            if isinstance(signal.get("metadata"), dict)
            else {}
        )
        normalization = (
            metadata.get("normalization")
            if isinstance(metadata.get("normalization"), dict)
            else {}
        )
        normalized_resolution = (
            normalization.get("location_resolution")
            if isinstance(
                normalization.get("location_resolution"),
                dict,
            )
            else {}
        )
        city = str(
            resolution.get("city_hint")
            or normalized_resolution.get("city_hint")
            or ""
        ).strip()
        province = str(
            resolution.get("province_hint")
            or normalized_resolution.get("province_hint")
            or ""
        ).strip()
        precision = str(
            resolution.get("location_precision")
            or normalized_resolution.get("location_precision")
            or ""
        ).strip()
        if (
            province
            and not city
            and precision
            in {"", "province", "province_only", "province_or_region"}
        ):
            return province
        return ""
    return ""


def _attach_checkout_choice_surface(
    turn: Dict[str, Any],
    *,
    request: RuntimeV7APIRequest,
    harness: RuntimeV7Harness,
) -> None:
    """Attach checkout controls without making delivery depend on the UI."""

    if isinstance(turn.get("checkout_choice_surface"), dict):
        return
    turn_id = str(
        turn.get("turn_id")
        or request.message_id
        or request.idempotency_key
        or "turn"
    )
    try:
        _attach_checkout_choice_surface_unchecked(
            turn,
            request=request,
            harness=harness,
        )
    except Exception as exc:
        logger.warning(
            "Runtime V7 checkout choice surface unavailable turn_id=%s error=%s",
            turn_id,
            exc.__class__.__name__,
        )


def _apply_submit_authorization_truth_guard(turn: Dict[str, Any]) -> None:
    """Render a safe confirmation request when submit authorization is absent."""

    denied = next(
        (
            item.get("full_result")
            for item in reversed(turn.get("tool_results") or [])
            if isinstance(item, dict)
            and item.get("name") == "submit_order"
            and isinstance(item.get("full_result"), dict)
            and item["full_result"].get("status")
            == "needs_explicit_order_confirmation"
        ),
        None,
    )
    if not isinstance(denied, dict):
        return
    _set_runtime_turn_response(
        turn,
        (
            "Naka-ready na po ang order details, pero hindi pa na-submit ang "
            "order. Pakiconfirm po kung tama ang summary at gusto ninyong "
            "i-submit ang order."
        ),
        owner="runtime_submit_authorization_guard",
    )
    turn["submit_authorization_truth_guard"] = {
        "status": "blocked",
        "reason": str(denied.get("reason") or ""),
        "order_payload_ref": str(denied.get("order_payload_ref") or ""),
    }


def _customer_date_label(value: Any) -> str:
    """Format an ISO choice date for a concise customer acknowledgement."""

    raw = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return raw or "the selected date"
    return f"{parsed.strftime('%b')} {parsed.day}"


def _set_runtime_turn_response(
    turn: Dict[str, Any],
    text: str,
    *,
    owner: str = "runtime_validated_choice_progression",
    preserve_validated_promo_surfaces: bool = False,
) -> None:
    """Set one structured runtime-owned response across renderer fallbacks."""

    _set_runtime_turn_responses(
        turn,
        [text],
        owner=owner,
        preserve_validated_promo_surfaces=(
            preserve_validated_promo_surfaces
        ),
    )


def _apply_single_product_location_progression_guard(
    turn: Dict[str, Any],
) -> None:
    """Ensure an exact size+brand result asks directly for customer area.

    This postcondition is deliberately typed and narrow. It runs only when the
    latest customer message supplied both size and brand, exactly one exact
    product card is ready, no location/contact is already known, and no other
    decision domain or tracked action owns the turn. The product and supporting
    promo surfaces remain unchanged; only trailing connective prose is replaced
    with one direct location question.
    """

    signals = [
        item
        for item in turn.get("background_signals_before_turn") or []
        if isinstance(item, Mapping)
    ]
    latest_signal_keys = {
        str(item.get("key") or "").strip()
        for item in signals
        if str(item.get("source") or "").strip() == "latest_user_message"
        and str(item.get("relation") or "asserted").strip()
        not in {"negated", "question_only"}
        and item.get("value") not in (None, "", [], {})
    }
    if "tire_size" not in latest_signal_keys or not latest_signal_keys.intersection(
        {"required_brands", "preferred_brands"}
    ):
        return
    if _turn_has_location_or_contact(turn, signals=signals):
        return
    choice_validation = turn.get("choice_action_validation")
    if (
        isinstance(choice_validation, Mapping)
        and choice_validation.get("validation_status") == "valid"
    ):
        return

    allowed_tools = {
        "product_search",
        "search_promo_catalog",
        "present_promo_gallery",
    }
    tool_results = [
        item for item in turn.get("tool_results") or [] if isinstance(item, Mapping)
    ]
    tool_names = {
        str(item.get("name") or "").strip()
        for item in tool_results
        if str(item.get("name") or "").strip()
    }
    if not tool_names or not tool_names.issubset(allowed_tools):
        return

    exact_product_results: List[Mapping[str, Any]] = []
    product_cards: List[Mapping[str, Any]] = []
    product_surface_refs: List[str] = []
    for item in tool_results:
        if item.get("name") != "product_search":
            continue
        full = item.get("full_result") if isinstance(item.get("full_result"), Mapping) else {}
        query_basis = full.get("query_basis") if isinstance(full.get("query_basis"), Mapping) else {}
        if (
            str(full.get("status") or "").strip().casefold() != "ok"
            or str(full.get("result_level") or "exact").strip().casefold()
            not in {"", "exact"}
            or query_basis.get("exact_base_query_verified") is False
        ):
            return
        cards = [
            card
            for card in full.get("product_cards") or []
            if isinstance(card, Mapping)
        ]
        exact_product_results.append(full)
        product_cards.extend(cards)
        surface_ref = str(full.get("presentation_ref") or "").strip()
        if surface_ref:
            product_surface_refs.append(surface_ref)
    if len(exact_product_results) != 1 or len(product_cards) != 1:
        return

    payload: Dict[str, Any] = {}
    for key in ("runtime_final_response", "assistant_text", "draft_assistant_text"):
        raw = str(turn.get(key) or "").strip()
        if not raw.startswith("{"):
            continue
        try:
            candidate = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(candidate, dict) and isinstance(candidate.get("response_units"), list):
            payload = candidate
            break
    if not payload:
        return
    units = [
        deepcopy(unit)
        for unit in payload.get("response_units") or []
        if isinstance(unit, Mapping)
    ]
    rendered_refs = [
        str((unit.get("content") or {}).get("surface_ref") or "").strip()
        for unit in units
        if str(unit.get("type") or "").strip() == "render_surface"
        and isinstance(unit.get("content"), Mapping)
    ]
    if not set(product_surface_refs).intersection(rendered_refs):
        return
    final_surface_index = max(
        index
        for index, unit in enumerate(units)
        if str(unit.get("type") or "").strip() == "render_surface"
    )
    retained_units = units[: final_surface_index + 1]
    retained_units.append(
        {
            "type": "text",
            "content": {
                "text": (
                    "Para ma-check ang installation o delivery options, "
                    "saang city o area po kayo?"
                )
            },
        }
    )
    payload["response_units"] = retained_units
    structured = json.dumps(payload, ensure_ascii=False)
    turn["assistant_text"] = structured
    turn["draft_assistant_text"] = structured
    turn["runtime_final_response"] = structured
    turn["response_owner"] = "runtime_single_product_location_progression"
    turn["location_progression_guard"] = {
        "status": "rewritten",
        "reason": "single_exact_size_brand_result_requires_location_question",
        "product_card_count": 1,
        "preserved_surface_refs": rendered_refs,
    }


def _turn_has_location_or_contact(
    turn: Mapping[str, Any],
    *,
    signals: Sequence[Mapping[str, Any]],
) -> bool:
    """Return whether trusted current state already has location or contact."""

    signal_keys = {
        str(item.get("key") or "").strip()
        for item in signals
        if item.get("value") not in (None, "", [], {})
        and str(item.get("relation") or "asserted").strip()
        not in {"negated", "question_only"}
    }
    if signal_keys.intersection(
        {"location", "city", "province", "contact_number", "phone_number", "mobile_number"}
    ):
        return True
    readiness = (
        turn.get("order_readiness_after_tools")
        if isinstance(turn.get("order_readiness_after_tools"), Mapping)
        else turn.get("order_readiness_before_turn")
        if isinstance(turn.get("order_readiness_before_turn"), Mapping)
        else {}
    )
    collected = readiness.get("collected") if isinstance(readiness.get("collected"), Mapping) else {}
    return any(
        collected.get(key) not in (None, "", [], {})
        for key in (
            "Location",
            "Installation location",
            "Delivery address",
            "Contact number",
            "Mobile number",
        )
    )


def _set_runtime_turn_responses(
    turn: Dict[str, Any],
    texts: Sequence[str],
    *,
    owner: str = "runtime_validated_choice_progression",
    preserve_validated_promo_surfaces: bool = False,
) -> None:
    """Set ordered runtime-owned text units without coupling answer and CTA."""

    response_units = [
        {
            "type": "text",
            "content": {"text": str(text or "").strip()},
        }
        for text in texts or []
        if str(text or "").strip()
    ]
    if preserve_validated_promo_surfaces:
        response_units.extend(
            {
                "type": "render_surface",
                "content": {"surface_ref": surface_ref},
            }
            for surface_ref in _validated_promo_surface_refs(turn)
        )
    structured = json.dumps(
        {
            "response_units": response_units,
        },
        ensure_ascii=False,
    )
    turn["assistant_text"] = structured
    turn["draft_assistant_text"] = structured
    turn["runtime_final_response"] = structured
    turn["response_owner"] = str(owner or "runtime_validated_choice_progression")


def _validated_promo_surface_refs(turn: Dict[str, Any]) -> List[str]:
    """Return current renderer-owned promo refs safe to retain in a fallback."""

    refs: List[str] = []
    for item in turn.get("tool_results") or []:
        if (
            not isinstance(item, dict)
            or item.get("name") != "present_promo_gallery"
        ):
            continue
        full = (
            item.get("full_result")
            if isinstance(item.get("full_result"), dict)
            else {}
        )
        status = str(full.get("status") or "").strip().casefold()
        ref = str(
            full.get("presentation_ref")
            or full.get("surface_ref")
            or ""
        ).strip()
        if (
            status not in {"error", "unavailable", "blocked"}
            and ref
            and full.get("cards")
            and ref not in refs
        ):
            refs.append(ref)
    return refs


def _runtime_turn_response_text(turn: Dict[str, Any]) -> str:
    """Read the runtime-owned structured text set by choice progression."""

    raw = str(turn.get("runtime_final_response") or "")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return raw.strip()
    units = payload.get("response_units") if isinstance(payload, dict) else []
    return "\n\n".join(
        str((unit.get("content") or {}).get("text") or "").strip()
        for unit in units or []
        if isinstance(unit, dict)
        and isinstance(unit.get("content"), dict)
        and str((unit.get("content") or {}).get("text") or "").strip()
    )


def _turn_location_label(turn: Dict[str, Any]) -> str:
    """Return the current lead location used to scope deferred service data."""

    lead = (
        turn.get("lead_qualification")
        if isinstance(turn.get("lead_qualification"), dict)
        else {}
    )
    present = lead.get("present") if isinstance(lead.get("present"), dict) else {}
    location = present.get("location")
    if isinstance(location, dict):
        location = (
            location.get("label")
            or location.get("value")
            or location.get("normalized")
        )
    if str(location or "").strip():
        return str(location).strip()
    for signal in reversed(turn.get("background_signals_before_turn") or []):
        if not isinstance(signal, dict):
            continue
        if str(signal.get("key") or "").strip() != "location":
            continue
        value = signal.get("value")
        if isinstance(value, dict):
            value = value.get("label") or value.get("value")
        if str(value or "").strip():
            return str(value).strip()
    return ""


def _attach_checkout_choice_surface_unchecked(
    turn: Dict[str, Any],
    *,
    request: RuntimeV7APIRequest,
    harness: RuntimeV7Harness,
) -> None:
    """Attach API-backed checkout controls after qualification is complete.

    For installation, an exact validated slot marks the end of the
    qualification decision sequence. Checkout controls are progressive
    enhancement: the customer may still type the payment option or method
    together with the remaining order form details.
    """

    def skip(reason: str, **details: Any) -> None:
        turn["checkout_choice_surface_status"] = {
            "status": "not_attached",
            "reason": reason,
            **details,
        }

    selected_value = getattr(harness, "latest_selected_product_context", {})
    selected = selected_value if isinstance(selected_value, dict) else {}
    if not selected:
        return skip("selected_product_context_missing")
    product_tools = getattr(harness, "tools", None)
    service_tools = getattr(harness, "service_tools", None)
    product_store = getattr(product_tools, "store", None)
    service_store = getattr(service_tools, "store", None)
    if product_store is None or service_store is None:
        return skip("observation_store_missing")
    action = (
        request.flow_context.get("choice_action_runtime_context")
        if isinstance(request.flow_context, dict)
        else {}
    )
    if not isinstance(action, dict):
        action = {}
    action_is_valid = action.get("validation_status") == "valid"
    action_type = str(action.get("choice_type") or "").strip()
    if action_is_valid and action_type in {
        "price_category",
        "product_selection",
        "serviceable_province",
        "serviceable_city",
    }:
        # A qualification click owns this turn. Even if an older checkout
        # context remains in the session, do not place payment controls beside
        # a product or location decision.
        return skip("qualification_choice_owns_turn", choice_type=action_type)
    readiness = (
        turn.get("order_readiness_after_tools")
        if isinstance(turn.get("order_readiness_after_tools"), dict)
        else turn.get("order_readiness_before_turn")
        if isinstance(turn.get("order_readiness_before_turn"), dict)
        else {}
    )
    collected = (
        readiness.get("collected")
        if isinstance(readiness.get("collected"), dict)
        else {}
    )
    signals = [
        item
        for item in turn.get("background_signals_before_turn") or []
        if isinstance(item, dict)
    ]
    payment_option = str(collected.get("Payment option") or "").strip()
    payment_method = str(collected.get("Payment method") or "").strip()
    reservation_payment_method = str(
        collected.get("Reservation payment method") or ""
    ).strip()
    balance_payment_method = str(
        collected.get("Balance payment method") or ""
    ).strip()
    latest_payment_option = _latest_trusted_payment_signal_value(
        signals,
        "payment_option",
    )
    if latest_payment_option:
        # Free-form "full payment"/"Pay Now" is a customer choice too. Let the
        # normalized latest-message signal override a stale readiness snapshot
        # before deciding which checkout layer to render.
        payment_option = str(latest_payment_option).strip()
    if action_is_valid and action_type == "payment_option_selection":
        payment_option = str(action.get("value") or "").strip()
        # A Pay Now/Pay Later click starts a new method layer. An older method
        # must not silently carry across a changed option.
        payment_method = ""
        reservation_payment_method = ""
        balance_payment_method = ""
    if action_is_valid and action_type == "payment_method_selection":
        payment_option = str(
            action.get("payment_option") or payment_option
        ).strip()
        selected_method = str(
            action.get("label") or action.get("value") or ""
        ).strip()
        selected_stage = str(action.get("payment_stage") or "").strip()
        if selected_stage == "reservation_fee":
            reservation_payment_method = selected_method
        elif selected_stage == "balance_payment":
            balance_payment_method = selected_method
        else:
            payment_method = selected_method
    # The selected product has already been validated against the delivered
    # product presentation. Bind the quote to those refs instead of asking the
    # quote compiler to rediscover the SKU from newer observations or signals.
    quote_payload = {
        key: selected.get(key)
        for key in (
            "product_observation_ref",
            "product_presentation_ref",
            "product_card_ref",
            "product_item_ref",
            "product_id",
            "slug",
        )
        if selected.get(key) not in (None, "")
    }
    if payment_option:
        quote_payload["payment_option"] = payment_option
    quote = calculate_order_quote(
        payload=quote_payload,
        current_user_message=request.user_text,
        background_signals=signals,
        product_observation_store=product_store,
        service_observation_store=service_store,
        order_readiness=readiness,
    )
    quote = _checkout_quote_with_current_order_summary_preview(turn, quote)
    service_path = str(quote.get("service_path") or "").strip()
    if not service_path:
        return skip("service_path_missing")
    if service_path in {"installation", "pickup"}:
        validated_slot = getattr(
            service_store,
            "latest_validated_slot_context",
            None,
        )
        exact_schedule_selected = bool(
            callable(validated_slot) and validated_slot()
        )
        serviceability_validated = _installation_serviceability_is_validated(
            turn,
            harness=harness,
            action=action,
        )
        flexible_schedule_selected = bool(
            (
                str(
                    collected.get("Preferred installation schedule") or ""
                ).strip()
                and serviceability_validated
            )
            or (
                action_is_valid
                and action_type == "schedule_selection"
                and action.get("selection_kind") == "afternoon_preference"
                and serviceability_validated
            )
        )
        if not serviceability_validated:
            return skip("installation_serviceability_not_validated")
        if (
            not exact_schedule_selected
            and not flexible_schedule_selected
            and action_type
            not in {"payment_option_selection", "payment_method_selection"}
        ):
            return skip("installation_schedule_not_selected")
    elif service_path == "delivery":
        # Delivery has no installation schedule gate. Do not advance checkout
        # from a partial/stale area alone; a complete address marks the end of
        # delivery qualification.
        if (
            not collected.get("Delivery address")
            and action_type
            not in {"payment_option_selection", "payment_method_selection"}
        ):
            return skip("complete_delivery_address_missing")
    else:
        return skip("unsupported_service_path", service_path=service_path)
    if not _payment_stage_is_confirmed(
        turn,
        action=action,
    ):
        return skip("model_or_guided_payment_progression_missing")
    metadata = checkout_metadata(
        getattr(harness, "canonical_values_provider", None)
    )
    turn_id = str(
        turn.get("turn_id")
        or request.message_id
        or request.idempotency_key
        or "turn"
    )
    if not payment_option:
        surface = build_payment_option_surface(
            quote=quote,
            metadata=metadata,
            turn_id=turn_id,
        )
    elif (
        payment_option == "Pay Later / Pay After Service"
        and balance_payment_method
        and not reservation_payment_method
    ):
        surface = build_payment_method_surface(
            metadata=metadata,
            payment_option=payment_option,
            product_brand=_selected_product_brand(selected),
            service_path=service_path,
            turn_id=turn_id,
            payment_stage="reservation_fee",
        )
    elif not (
        payment_method
        or reservation_payment_method
        or balance_payment_method
    ):
        surface = build_payment_method_surface(
            metadata=metadata,
            payment_option=payment_option,
            product_brand=_selected_product_brand(selected),
            service_path=service_path,
            turn_id=turn_id,
        )
    else:
        surface = {}
    if surface:
        turn["checkout_choice_surface"] = surface
        turn["checkout_choice_surface_status"] = {
            "status": "attached",
            "choice_type": str(surface.get("choice_type") or ""),
            "service_path": service_path,
            "source": str(surface.get("source") or ""),
        }
    else:
        skip(
            "surface_empty",
            service_path=service_path,
            payment_option=payment_option,
            payment_method=payment_method,
            reservation_payment_method=reservation_payment_method,
            balance_payment_method=balance_payment_method,
            payment_option_count=len(metadata.get("payment_options") or []),
            payment_method_count=len(metadata.get("payment_types") or []),
        )


def _latest_trusted_payment_signal_value(
    signals: Sequence[Dict[str, Any]],
    key: str,
) -> Any:
    """Return the newest action-safe customer/choice payment value."""

    for signal in reversed(list(signals or [])):
        if not isinstance(signal, dict):
            continue
        if str(signal.get("key") or "").strip() != key:
            continue
        if signal.get("value") in (None, "", []):
            continue
        if str(signal.get("source") or "").strip() != "latest_user_message":
            # This override is only for the current free-text choice. Persisted
            # signal-ledger values are already represented in readiness and
            # must not make an unrelated turn look like a new payment choice.
            continue
        source, status = signal_authority(signal)
        if source != "latest_user_message":
            continue
        if status in {
            "invalid",
            "rejected",
            "superseded",
            "mentioned_unconfirmed",
        }:
            continue
        return signal.get("value")
    return None


def _installation_serviceability_is_validated(
    turn: Dict[str, Any],
    *,
    harness: RuntimeV7Harness,
    action: Mapping[str, Any],
) -> bool:
    """Require a source-backed partner/slot observation for installation."""

    service_tools = getattr(harness, "service_tools", None)
    store = getattr(service_tools, "store", None)
    if store is None:
        return False
    validated_slot = getattr(store, "latest_validated_slot_context", None)
    if callable(validated_slot) and validated_slot():
        return True

    observation_ref = str(action.get("observation_ref") or "").strip()
    get_observation = getattr(store, "get_observation", None)
    if observation_ref and callable(get_observation):
        observation = get_observation(observation_ref)
        if _service_observation_proves_serviceability(observation):
            return True

    latest_slots = getattr(
        store,
        "latest_installation_slots_observation",
        None,
    )
    location_label = _turn_location_label(turn)
    observation = (
        latest_slots(
            location_label=location_label,
            max_age_seconds=3600,
        )
        if callable(latest_slots)
        else None
    )
    return _service_observation_proves_serviceability(observation)


def _service_observation_proves_serviceability(
    observation: Any,
) -> bool:
    """Return whether an observation contains usable partner/slot evidence."""

    if observation is None:
        return False
    service_locations = getattr(observation, "service_locations", None)
    slot_groups = getattr(observation, "slot_groups", None)
    availability = getattr(observation, "availability", None)
    if isinstance(observation, dict):
        service_locations = observation.get("service_locations")
        slot_groups = observation.get("slot_groups")
        availability = observation.get("availability")
    availability = availability if isinstance(availability, dict) else {}
    status = str(
        availability.get("availability_status")
        or availability.get("status")
        or ""
    ).strip().casefold()
    if status in {
        "no_match",
        "unserviceable",
        "not_serviceable",
        "not_applicable_for_delivery",
    }:
        return False
    return bool(service_locations and slot_groups)


def _payment_stage_is_confirmed(
    turn: Dict[str, Any],
    *,
    action: Mapping[str, Any],
) -> bool:
    """Authorize payment controls from typed model state or a validated click."""

    action_type = str(action.get("choice_type") or "").strip()
    if (
        action.get("validation_status") == "valid"
        and action_type
        in {
            "schedule_selection",
            "payment_option_selection",
            "payment_method_selection",
        }
    ):
        return True
    for result in turn.get("tool_results") or []:
        if not isinstance(result, dict) or result.get("name") != "build_order_summary":
            continue
        full_result = result.get("full_result") if isinstance(result.get("full_result"), dict) else {}
        if str(full_result.get("status") or "").strip().lower() not in {
            "",
            "error",
            "blocked",
            "unavailable",
        }:
            return True
    trusted_progression_keys = {
        "order_summary_review_confirmation",
        "payment_option",
        "payment_method",
        "reservation_payment_method",
        "balance_payment_method",
    }
    for signal in turn.get("background_signals_before_turn") or []:
        if not isinstance(signal, dict):
            continue
        if str(signal.get("key") or "").strip() not in trusted_progression_keys:
            continue
        if signal.get("value") in (None, "", []):
            continue
        source, status = signal_authority(signal)
        if source == "latest_user_message" and status not in {
            "invalid",
            "rejected",
            "superseded",
            "mentioned_unconfirmed",
        }:
            return True
    return False


def _checkout_quote_with_current_order_summary_preview(
    turn: Dict[str, Any],
    quote: Dict[str, Any],
) -> Dict[str, Any]:
    """Reuse the current source-backed order-summary payment comparison."""

    for tool_result in reversed(turn.get("tool_results") or []):
        if (
            not isinstance(tool_result, dict)
            or tool_result.get("name") != "build_order_summary"
        ):
            continue
        full = (
            tool_result.get("full_result")
            if isinstance(tool_result.get("full_result"), dict)
            else {}
        )
        summary = (
            full.get("quote_summary")
            if isinstance(full.get("quote_summary"), dict)
            else {}
        )
        preview = (
            summary.get("payment_options_preview")
            if isinstance(summary.get("payment_options_preview"), dict)
            else {}
        )
        if not preview:
            continue
        breakdown = (
            dict(quote.get("quote_breakdown") or {})
            if isinstance(quote.get("quote_breakdown"), dict)
            else {}
        )
        breakdown["payment_options_preview"] = deepcopy(preview)
        return {
            **quote,
            "quote_ref": str(
                quote.get("quote_ref")
                or full.get("order_summary_ref")
                or ""
            ),
            "quote_breakdown": breakdown,
        }
    return quote


def _selected_product_brand(context: Dict[str, Any]) -> str:
    summary = (
        context.get("product_summary")
        if isinstance(context.get("product_summary"), dict)
        else {}
    )
    return str(
        summary.get("brand")
        or context.get("brand")
        or ""
    ).strip()


def _remember_choice_action_attempt(harness: RuntimeV7Harness, request: RuntimeV7APIRequest) -> None:
    """Validate an interactive click against the delivered session allowlist."""

    flow = request.flow_context if isinstance(request.flow_context, dict) else {}
    context = flow.get("choice_action_context")
    if not isinstance(context, dict):
        return
    presentation_ref = str(context.get("presentation_ref") or "")
    category = str(context.get("category") or "").strip().casefold()
    choice_code = str(context.get("choice_code") or "").strip()
    choice_type = str(
        context.get("choice_type")
        or ("price_category" if category else "")
    ).strip().casefold()
    presentation = next(
        (
            item
            for item in reversed(harness.choice_presentation_history or [])
            if str(item.get("presentation_ref") or "") == presentation_ref
            and str(item.get("delivery_status") or "").strip().lower()
            in {
                "success",
                "pending",
                "unknown",
                "delivery_unknown",
                "evaluated",
            }
        ),
        None,
    )
    presentation_superseded = bool(
        str((presentation or {}).get("superseded_at") or "").strip()
    )
    choice = next(
        (
            item
            for item in (presentation or {}).get("choices") or []
            if (
                choice_type == "price_category"
                and str(item.get("category") or "").strip().casefold() == category
            )
            or (
                choice_type in {"serviceable_province", "serviceable_city"}
                and str(item.get("code") or "").strip() == choice_code
            )
            or (
                choice_type == "product_selection"
                and str(item.get("card_ref") or "").strip()
                == str(context.get("card_ref") or "").strip()
            )
            or (
                choice_type
                in {
                    "schedule_selection",
                    "payment_option_selection",
                    "payment_method_selection",
                }
                and str(item.get("choice_ref") or "").strip()
                == str(context.get("choice_ref") or "").strip()
            )
        ),
        None,
    )
    expires_at = _parse_datetime(str((presentation or {}).get("expires_at") or ""))
    expired = bool(expires_at and expires_at <= datetime.now(tz=expires_at.tzinfo))
    expected_size = str((presentation or {}).get("tire_size") or "").strip().upper()
    supplied_size = str(context.get("tire_size") or "").strip().upper()
    size_matches = (
        choice_type != "price_category"
        or not expected_size
        or expected_size == supplied_size
    )
    presentation_type = str(
        (presentation or {}).get("choice_type")
        or ("price_category" if (presentation or {}).get("tire_size") or category else "")
    ).strip().casefold()
    type_matches = presentation_type == choice_type
    validation_status = (
        "valid"
        if (
            presentation
            and choice
            and type_matches
            and not expired
            and size_matches
            and not presentation_superseded
        )
        else "stale"
    )
    runtime_context = {
        **context,
        "validation_status": validation_status,
        "choice_ref": str(
            (choice or {}).get("choice_ref")
            or (
                f"price_category:{category}"
                if choice_type == "price_category"
                else (
                    f"location:{choice_code}"
                    if choice_type
                    in {"serviceable_province", "serviceable_city"}
                    else ""
                )
            )
        ),
        "label": str((choice or {}).get("label") or context.get("label") or ""),
        "position": int((choice or {}).get("position") or 0),
        "source": str((presentation or {}).get("source") or ""),
        "source_version": str((presentation or {}).get("source_version") or ""),
        "parent_code": str((presentation or {}).get("parent_code") or context.get("parent_code") or ""),
        "province_code": str((choice or {}).get("province_code") or context.get("province_code") or ""),
        "province_label": str((choice or {}).get("province_label") or context.get("province_label") or ""),
        "card_ref": str((choice or {}).get("card_ref") or context.get("card_ref") or ""),
        "item_ref": str((choice or {}).get("item_ref") or ""),
        "product_id": str((choice or {}).get("product_id") or ""),
        "slug": str((choice or {}).get("slug") or ""),
        "brand": str((choice or {}).get("brand") or ""),
        "tire_size": str((choice or {}).get("tire_size") or context.get("tire_size") or ""),
        "deal_price_line": str((choice or {}).get("deal_price_line") or ""),
        "observation_ref": str(
            (presentation or {}).get("observation_ref")
            or (choice or {}).get("observation_ref")
            or ""
        ),
        "selection_kind": str((choice or {}).get("selection_kind") or ""),
        "slot_ref": str((choice or {}).get("slot_ref") or ""),
        "slot_refs": list((choice or {}).get("slot_refs") or []),
        "date": str((choice or {}).get("date") or ""),
        "time_text": str((choice or {}).get("time_text") or ""),
        "time_window": str((choice or {}).get("time_window") or ""),
        "availability_status": str(
            (choice or {}).get("availability_status") or ""
        ),
        "installation_partner_ref": str(
            (choice or {}).get("installation_partner_ref") or ""
        ),
        "service_location_ref": str(
            (choice or {}).get("service_location_ref") or ""
        ),
        "option_id": str((choice or {}).get("option_id") or ""),
        "payment_type_id": str((choice or {}).get("payment_type_id") or ""),
        "payment_option_id": str(
            (choice or {}).get("payment_option_id")
            or (presentation or {}).get("payment_option_id")
            or ""
        ),
        "payment_option": str(
            (presentation or {}).get("payment_option") or ""
        ),
        "value": str((choice or {}).get("value") or ""),
        "description": str((choice or {}).get("description") or ""),
        "is_installment": bool((choice or {}).get("is_installment")),
        "payment_stage": str((choice or {}).get("payment_stage") or ""),
        "installment_months": str(
            (choice or {}).get("installment_months") or ""
        ),
        "service_path": str((presentation or {}).get("service_path") or ""),
        "product_brand": str((presentation or {}).get("product_brand") or ""),
    }
    if choice_type in {"serviceable_province", "serviceable_city"}:
        runtime_context["selected_product_ready"] = bool(
            getattr(harness, "latest_selected_product_context", {})
        )
    if validation_status == "valid" and _is_recent_semantic_choice_duplicate(
        harness.choice_action_history,
        presentation_ref=presentation_ref,
        choice_ref=str(runtime_context.get("choice_ref") or ""),
    ):
        validation_status = "duplicate"
        runtime_context["validation_status"] = "duplicate"
        runtime_context["duplicate_reason"] = (
            "same_delivered_choice_recently_processed"
        )
    if (
        validation_status == "valid"
        and _choice_already_applied_to_runtime_state(
            harness,
            runtime_context,
        )
    ):
        validation_status = "duplicate"
        runtime_context["validation_status"] = "duplicate"
        runtime_context["duplicate_reason"] = (
            "choice_already_applied_to_current_state"
        )
    if (
        validation_status == "stale"
        and presentation_superseded
        and choice
        and type_matches
        and not expired
        and size_matches
        and _choice_already_applied_to_runtime_state(
            harness,
            runtime_context,
        )
    ):
        # ManyChat can deliver the same button event again after the first
        # click has already advanced to a new surface.  The old presentation
        # is superseded, but the exact choice is harmless when it is already
        # the current validated state.  Treat only that case as a no-op.
        validation_status = "duplicate"
        runtime_context["validation_status"] = "duplicate"
        runtime_context["duplicate_reason"] = (
            "choice_already_applied_to_current_state"
        )
    _remember_validated_commercial_choice_signals(
        harness,
        runtime_context,
    )
    if (
        validation_status == "valid"
        and choice_type in {"serviceable_province", "serviceable_city"}
    ):
        service_tools = getattr(harness, "service_tools", None)
        clear_location_dependent = getattr(
            getattr(service_tools, "store", None),
            "clear_location_dependent",
            None,
        )
        if callable(clear_location_dependent):
            clear_location_dependent()
    request.flow_context = {**flow, "choice_action_runtime_context": runtime_context}
    if validation_status == "duplicate":
        request.user_text = (
            "The same delivered choice was already processed recently."
        )
    elif validation_status == "stale":
        request.user_text = (
            "The choice I clicked is no longer current. Please show the current options."
        )
    elif choice_type == "serviceable_province":
        label = str(runtime_context.get("label") or "").strip()
        if choice_code == "other":
            runtime_context["recommended_service_path"] = "delivery"
            runtime_context["service_path_selected"] = False
            request.flow_context = {
                **flow,
                "choice_action_runtime_context": runtime_context,
            }
            request.user_text = (
                "My area is outside the current guided installation choices. "
                "Shift naturally toward delivery as the likely alternative, "
                "but do not say delivery is already selected or confirmed. "
                "Ask for the one delivery location detail needed next, or ask "
                "whether I want delivery when that choice is not yet clear. "
                "Do not restart installation location choices unless I ask to recheck installation."
            )
        else:
            request.user_text = (
                f"I selected {label}. Show only the current serviceable cities "
                "under this province."
            )
    elif choice_type == "serviceable_city":
        label = str(runtime_context.get("label") or "").strip()
        province_label = str(runtime_context.get("province_label") or "").strip()
        location_label = ", ".join(value for value in [label, province_label] if value)
        if runtime_context.get("selected_product_ready"):
            request.user_text = (
                f"My installation location is {location_label}. Continue "
                "naturally from this validated location choice using the current "
                "conversation and sales-progression state."
            )
        else:
            request.user_text = (
                f"My installation location is {location_label}. Keep this "
                "validated location, but I have not selected a tire product yet. "
                "Show the current product or price-category choices for my known "
                "tire size before checking schedules."
            )
    elif choice_type == "product_selection":
        remember_selection = getattr(
            harness,
            "_remember_selected_product_context_from_resolution",
            None,
        )
        resolution: Dict[str, Any] = {}
        tools = getattr(harness, "tools", None)
        resolve_reference = getattr(tools, "resolve_product_reference", None)
        if validation_status == "valid" and callable(resolve_reference):
            resolution = resolve_reference(
                {
                    "presentation_ref": presentation_ref,
                    "card_ref": runtime_context["card_ref"],
                }
            )
            if resolution.get("status") == "resolved" and callable(remember_selection):
                remember_selection(resolution)
            else:
                validation_status = "stale"
                runtime_context["validation_status"] = validation_status
                request.flow_context = {
                    **flow,
                    "choice_action_runtime_context": runtime_context,
                }
        if validation_status == "valid":
            label = str(runtime_context.get("label") or "the selected tire").strip()
            request.user_text = (
                f"I selected {label} from the shown product choices. "
                "Continue from this exact validated SKU."
            )
        else:
            request.user_text = (
                "The product choice I clicked is no longer current. "
                "Please show the current product options."
            )
    elif choice_type == "schedule_selection":
        if (
            validation_status == "valid"
            and runtime_context["selection_kind"] == "exact_slot"
        ):
            validation = harness.service_tools.validate_installation_slot(
                {
                    "observation_ref": runtime_context["observation_ref"],
                    "slot_ref": runtime_context["slot_ref"],
                    "installation_partner_ref": runtime_context[
                        "installation_partner_ref"
                    ],
                }
            )
            if validation.get("status") != "ok" or validation.get("valid") is not True:
                validation_status = "stale"
                runtime_context["validation_status"] = "stale"
                runtime_context["slot_validation"] = {
                    "status": validation.get("status"),
                    "reason": validation.get("reason"),
                }
                request.flow_context = {
                    **flow,
                    "choice_action_runtime_context": runtime_context,
                }
                request.user_text = (
                    "The exact schedule I clicked is no longer valid. "
                    "Please show the current schedule options."
                )
            else:
                runtime_context["validated_service_observation_ref"] = str(
                    validation.get("observation_ref") or ""
                )
                request.flow_context = {
                    **flow,
                    "choice_action_runtime_context": runtime_context,
                }
                request.user_text = (
                    f"I selected the validated {runtime_context['date']} "
                    f"{runtime_context['time_text']} installation slot from the "
                    "shown schedule controls. It is selected for order review "
                    "but is not booked or reserved yet. Continue to the order details."
                )
        elif (
            validation_status == "valid"
            and runtime_context["selection_kind"] == "afternoon_preference"
        ):
            preferred_slot_ref = str(
                runtime_context.get("slot_ref") or ""
            ).strip()
            if preferred_slot_ref:
                validation = harness.service_tools.validate_installation_slot(
                    {
                        "observation_ref": runtime_context["observation_ref"],
                        "slot_ref": preferred_slot_ref,
                        "installation_partner_ref": runtime_context.get(
                            "installation_partner_ref"
                        ),
                    }
                )
                if (
                    validation.get("status") != "ok"
                    or validation.get("valid") is not True
                ):
                    validation_status = "stale"
                    runtime_context["validation_status"] = "stale"
                    runtime_context["slot_validation"] = {
                        "status": validation.get("status"),
                        "reason": validation.get("reason"),
                    }
                    request.user_text = (
                        "The earliest afternoon schedule from the choice I "
                        "clicked is no longer current. Please show the current "
                        "schedule options."
                    )
                else:
                    selected_slot = (
                        validation.get("selected_slot")
                        if isinstance(
                            validation.get("selected_slot"),
                            dict,
                        )
                        else {}
                    )
                    runtime_context["afternoon_resolution_status"] = (
                        "earliest_available_slot_validated"
                    )
                    runtime_context["validated_service_observation_ref"] = str(
                        validation.get("observation_ref") or ""
                    )
                    runtime_context["resolved_time_text"] = str(
                        selected_slot.get("time_text")
                        or runtime_context.get("time_text")
                        or ""
                    ).strip()
                    request.user_text = (
                        "I selected Anytime in the afternoon from the shown "
                        "schedule controls. Runtime resolved this to the earliest "
                        f"validated afternoon slot on {runtime_context['date']} "
                        f"at {runtime_context['resolved_time_text']}. It is selected "
                        "for order review but is not booked or reserved yet. "
                        "Continue to the order details."
                    )
            else:
                runtime_context["time_text"] = "12:00 PM"
                runtime_context["afternoon_resolution_status"] = (
                    "default_noon_preference_unvalidated"
                )
                request.user_text = (
                    f"I prefer 12:00 PM on {runtime_context['date']} because no "
                    "current afternoon slot was present in the delivered schedule. "
                    "This is a customer preference, not an availability or booking "
                    "claim. Continue to the order details without treating it as "
                    "a validated slot."
                )
            request.flow_context = {
                **flow,
                "choice_action_runtime_context": runtime_context,
            }
        else:
            request.user_text = (
                "The schedule choice I clicked is no longer current. "
                "Please show the current schedule options."
            )
    elif choice_type == "payment_option_selection":
        if validation_status == "valid":
            request.user_text = (
                f"I selected {runtime_context['value']} from the shown "
                "API-backed checkout options. Treat this as my validated payment "
                "option and continue collecting or confirming the order details."
            )
        else:
            request.user_text = (
                "The payment option I clicked is no longer current. "
                "Please show the current Pay Now and Pay Later options."
            )
    elif choice_type == "payment_method_selection":
        if validation_status == "valid":
            method_label = str(
                runtime_context.get("label")
                or runtime_context.get("value")
                or ""
            ).strip()
            term = str(
                runtime_context.get("installment_months") or ""
            ).strip()
            payment_stage = str(
                runtime_context.get("payment_stage") or ""
            ).strip()
            payment_option = str(
                runtime_context.get("payment_option") or ""
            ).strip()
            if payment_stage == "reservation_fee":
                request.user_text = (
                    f"I selected {method_label} as the reservation payment "
                    f"method under {payment_option or 'Pay Later / Pay After Service'}. "
                    "This validated choice is not Pay Now and is not the balance "
                    "payment method."
                )
            elif payment_stage == "balance_payment":
                request.user_text = (
                    f"I selected {method_label} as the balance payment method "
                    f"under {payment_option or 'Pay Later / Pay After Service'}. "
                    "The separate reservation payment method is still required."
                    + (
                        f" The validated installment term is {term} months."
                        if term
                        else ""
                    )
                )
            else:
                request.user_text = (
                    f"I selected {method_label} as the full payment method "
                    f"under {payment_option or 'Pay Now'}. Treat this as my "
                    "validated checkout-compatible payment method."
                    + (
                        f" The validated installment term is {term} months."
                        if term
                        else ""
                    )
                )
        else:
            request.user_text = (
                "The payment method I clicked is no longer current. "
                "Please show the current compatible payment methods."
            )
    received_at = now_manila_str()
    entry = {
        **runtime_context,
        "event_id": str(request.channel_event_id or ""),
        "idempotency_key": str(request.idempotency_key or ""),
        "click_timestamp": str(request.channel_event_ts or ""),
        "delivery_status": "pending",
        "received_at": received_at,
        "processed_at": received_at,
        "attempted_at": received_at,
    }
    harness.latest_choice_action = entry
    history = [
        deepcopy(item)
        for item in harness.choice_action_history
        if str(item.get("idempotency_key") or "") != entry["idempotency_key"]
    ]
    harness.choice_action_history = [*history[-19:], deepcopy(entry)]


def _is_recent_semantic_choice_duplicate(
    history: Sequence[Dict[str, Any]],
    *,
    presentation_ref: str,
    choice_ref: str,
) -> bool:
    """Return whether the same delivered choice already produced a response."""

    ref = str(presentation_ref or "").strip()
    choice = str(choice_ref or "").strip()
    if not ref or not choice:
        return False
    try:
        ttl_seconds = int(
            os.getenv("RUNTIME_V7_CHOICE_DEDUPE_SECONDS", "90") or "90"
        )
    except (TypeError, ValueError):
        ttl_seconds = 90
    ttl_seconds = max(30, min(300, ttl_seconds))
    now = datetime.now().astimezone()
    for item in reversed(list(history or [])):
        if not isinstance(item, dict):
            continue
        if str(item.get("presentation_ref") or "").strip() != ref:
            continue
        if str(item.get("choice_ref") or "").strip() != choice:
            continue
        if str(item.get("validation_status") or "") != "valid":
            continue
        if str(item.get("delivery_status") or "").strip().lower() not in {
            "success",
            "evaluated",
        }:
            continue
        occurred = _parse_datetime(
            str(
                item.get("delivered_at")
                or item.get("attempted_at")
                or item.get("click_timestamp")
                or ""
            )
        )
        if occurred is None:
            continue
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=now.tzinfo)
        age_seconds = (now - occurred.astimezone(now.tzinfo)).total_seconds()
        if 0 <= age_seconds <= ttl_seconds:
            return True
    return False


def _choice_already_applied_to_runtime_state(
    harness: RuntimeV7Harness,
    context: Mapping[str, Any],
) -> bool:
    """Return whether a validated click would leave trusted state unchanged.

    ManyChat may create different event/idempotency IDs for repeated clicks on
    the same visible control. Event-level dedupe cannot catch those requests,
    so the runtime also compares the proposed transition with the authoritative
    state that was hydrated before this turn.
    """

    choice_type = str(context.get("choice_type") or "").strip()
    if choice_type == "product_selection":
        latest_action = getattr(harness, "latest_choice_action", {})
        latest_action = (
            latest_action if isinstance(latest_action, dict) else {}
        )
        if (
            str(latest_action.get("choice_type") or "")
            != "product_selection"
            or str(latest_action.get("validation_status") or "") != "valid"
            or str(latest_action.get("delivery_status") or "").strip().lower()
            not in {"success", "evaluated"}
        ):
            # A single-card search may bind a product context before the
            # customer explicitly clicks it. The first explicit confirmation
            # must remain conversationally visible.
            return False
        selected = getattr(harness, "latest_selected_product_context", {})
        selected = selected if isinstance(selected, dict) else {}
        stable_pairs = (
            ("product_id", "product_id"),
            ("slug", "slug"),
            ("item_ref", "product_item_ref"),
        )
        comparisons = [
            (
                str(context.get(choice_key) or "").strip().casefold(),
                str(selected.get(state_key) or "").strip().casefold(),
            )
            for choice_key, state_key in stable_pairs
            if context.get(choice_key) not in (None, "")
            and selected.get(state_key) not in (None, "")
        ]
        if comparisons:
            return any(
                proposed == applied
                for proposed, applied in comparisons
            )
        same_presentation = (
            str(context.get("presentation_ref") or "").strip()
            == str(
                selected.get("product_presentation_ref") or ""
            ).strip()
        )
        return bool(
            same_presentation
            and str(context.get("card_ref") or "").strip()
            and str(context.get("card_ref") or "").strip()
            == str(selected.get("product_card_ref") or "").strip()
        )

    if choice_type == "schedule_selection":
        service_tools = getattr(harness, "service_tools", None)
        store = getattr(service_tools, "store", None)
        getter = getattr(store, "latest_validated_slot_context", None)
        validated = getter() if callable(getter) else {}
        selected_slot = (
            validated.get("selected_slot")
            if isinstance(validated, dict)
            and isinstance(validated.get("selected_slot"), dict)
            else {}
        )
        proposed_ref = str(context.get("slot_ref") or "").strip()
        applied_ref = str(selected_slot.get("slot_ref") or "").strip()
        if proposed_ref and applied_ref:
            return proposed_ref == applied_ref
        proposed_date = str(context.get("date") or "").strip()
        proposed_time = str(
            context.get("resolved_time_text")
            or context.get("time_text")
            or ""
        ).strip().casefold()
        applied_date = str(
            selected_slot.get("date")
            or selected_slot.get("schedule_date")
            or ""
        ).strip()
        applied_time = str(
            selected_slot.get("time_text")
            or selected_slot.get("time")
            or ""
        ).strip().casefold()
        return bool(
            proposed_date
            and proposed_time
            and proposed_date == applied_date
            and proposed_time == applied_time
        )

    signal_values = _trusted_choice_state_signal_values(harness)
    if choice_type == "payment_option_selection":
        proposed = normalize_payment_option(
            context.get("value") or context.get("payment_option")
        )
        applied = normalize_payment_option(signal_values.get("payment_option"))
        return bool(proposed and applied and proposed == applied)
    if choice_type == "payment_method_selection":
        stage = str(context.get("payment_stage") or "").strip()
        key = {
            "reservation_fee": "reservation_payment_method",
            "balance_payment": "balance_payment_method",
            "full_payment": "payment_method",
        }.get(stage, "payment_method")
        proposed = _normalized_choice_state_value(
            context.get("label") or context.get("value")
        )
        applied = _normalized_choice_state_value(signal_values.get(key))
        return bool(proposed and applied and proposed == applied)
    return False


def _trusted_choice_state_signal_values(
    harness: RuntimeV7Harness,
) -> Dict[str, Any]:
    """Load action-safe commercial state used only for no-op comparison."""

    ledger = getattr(harness, "signal_ledger", None)
    if ledger is None or not callable(getattr(ledger, "load", None)):
        return {}
    output: Dict[str, Any] = {}
    for signal in ledger.load(harness.session_id):
        if not isinstance(signal, dict):
            continue
        key = str(signal.get("key") or "").strip()
        if not key or signal.get("value") in (None, "", []):
            continue
        source, status = signal_authority(signal)
        if source not in {"latest_user_message", "validated_choice_action"}:
            continue
        if status in {"invalid", "rejected", "superseded", "mentioned_unconfirmed"}:
            continue
        output[key] = signal.get("value")
    return output


def _normalized_choice_state_value(value: Any) -> str:
    """Normalize one human/API label for exact same-state comparison."""

    return " ".join(
        token
        for token in re.findall(r"[a-z0-9]+", str(value or "").casefold())
        if token
    )


def _remember_validated_commercial_choice_signals(
    harness: RuntimeV7Harness,
    context: Dict[str, Any],
) -> None:
    """Seed commercial state only from a validated delivered guided choice."""

    if context.get("validation_status") != "valid":
        return
    choice_type = str(context.get("choice_type") or "").strip()
    if choice_type not in {
        "price_category",
        "serviceable_province",
        "serviceable_city",
        "payment_option_selection",
        "payment_method_selection",
    }:
        return

    updates: Dict[str, str] = {}
    cleared: set[str] = set()
    if choice_type == "price_category":
        category = str(
            context.get("label") or context.get("category") or ""
        ).strip()
        if category:
            updates["tire_category_preference"] = category
    elif choice_type in {"serviceable_province", "serviceable_city"}:
        outside_installation_choices = (
            choice_type == "serviceable_province"
            and str(context.get("choice_code") or "").strip().casefold()
            == "other"
        )
        if outside_installation_choices:
            # "Other" is a validated navigation outcome, not a real location
            # and not consent to delivery. Remove stale installation-specific
            # state so the model can offer delivery without claiming it was
            # already selected.
            cleared.update(
                {
                    "location",
                    "city",
                    "selected_installation_partner",
                    "chosen_schedule_slot",
                    "preferred_schedule",
                    "service_location_ref",
                    "installation_partner_ref",
                }
            )
            current_service_type = _normalized_choice_state_value(
                _trusted_choice_state_signal_values(harness).get("service_type")
            )
            if "deliver" not in current_service_type:
                cleared.add("service_type")
        else:
            label = str(context.get("label") or "").strip()
            province_label = str(
                context.get("province_label")
                or (
                    label
                    if choice_type == "serviceable_province"
                    else ""
                )
                or ""
            ).strip()
            location = (
                ", ".join(
                    value
                    for value in [label, province_label]
                    if value
                )
                if choice_type == "serviceable_city"
                else province_label
            )
            if location:
                updates["location"] = location
            # This is not an inference from arbitrary location text. The
            # customer clicked a delivered, validated surface whose contract
            # is scoped to installation/service locations, so fulfillment
            # intent is part of the trusted choice semantics.
            updates["service_type"] = "installation"
            cleared.update(
                {
                    "selected_installation_partner",
                    "chosen_schedule_slot",
                    "preferred_schedule",
                    "service_location_ref",
                    "installation_partner_ref",
                }
            )
            if choice_type == "serviceable_province":
                cleared.add("city")
    else:
        payment_option = str(
            context.get("payment_option")
            or (
                context.get("value")
                if choice_type == "payment_option_selection"
                else ""
            )
            or ""
        ).strip()
        if payment_option:
            updates["payment_option"] = payment_option
        if choice_type == "payment_option_selection":
            # A newly selected timing layer supersedes a method from the previous
            # option. The compatible method will be selected from the new surface.
            cleared.update(
                {
                    "payment_method",
                    "reservation_payment_method",
                    "balance_payment_method",
                    "bank",
                    "installment_months",
                }
            )
        else:
            method = str(
                context.get("label") or context.get("value") or ""
            ).strip()
            if method:
                payment_stage = str(context.get("payment_stage") or "").strip()
                method_key = {
                    "reservation_fee": "reservation_payment_method",
                    "balance_payment": "balance_payment_method",
                    "full_payment": "payment_method",
                }.get(payment_stage, "payment_method")
                updates[method_key] = method
                # A newly validated method supersedes qualifiers from the
                # previously selected method. Re-add only qualifiers carried
                # by this validated choice below.
                cleared.update({"bank", "installment_months"})
            months = str(context.get("installment_months") or "").strip()
            if months:
                updates["installment_months"] = months

    ledger = getattr(harness, "signal_ledger", None)
    if ledger is None or not callable(getattr(ledger, "load", None)):
        return
    existing = [
        dict(signal)
        for signal in ledger.load(harness.session_id)
        if isinstance(signal, dict)
        and str(signal.get("key") or "") not in {*updates, *cleared}
    ]
    labels = {
        "tire_category_preference": "Tire category preference",
        "location": "Location",
        "service_type": "Service type",
        "payment_option": "Payment option",
        "payment_method": "Payment method",
        "reservation_payment_method": "Reservation payment method",
        "balance_payment_method": "Balance payment method",
        "installment_months": "Installment months",
    }
    validated = []
    for key, value in updates.items():
        entry = {
            "key": key,
            "value": value,
            "label": labels[key],
            "status": "tool_grounded",
            "source": "validated_choice_action",
            "confidence": "high",
            "safe_for_action": not (
                key == "location"
                and choice_type == "serviceable_province"
            ),
            "requires_validation": (
                key == "location"
                and choice_type == "serviceable_province"
            ),
            "relevance": "Validated checkout selection",
            "ask_timing": "current_order_step",
            "metadata": {
                "choice_ref": str(context.get("choice_ref") or ""),
                "presentation_ref": str(
                    context.get("presentation_ref") or ""
                ),
            },
        }
        if key == "location":
            province_label = str(
                context.get("province_label")
                or (
                    context.get("label")
                    if choice_type == "serviceable_province"
                    else ""
                )
                or ""
            ).strip()
            city_label = (
                str(context.get("label") or "").strip()
                if choice_type == "serviceable_city"
                else ""
            )
            entry["resolution"] = {
                "status": "resolved_location",
                "display_label": value,
                "city_hint": city_label or None,
                "province_hint": province_label or None,
                "location_precision": (
                    "city_or_area"
                    if city_label
                    else "province_or_region"
                ),
                "safe_for_action": bool(city_label),
            }
            entry["relevance"] = "Validated location selection"
        elif key == "tire_category_preference":
            entry["relation"] = "selected"
            entry["relevance"] = "Validated price-category selection"
        validated.append(entry)
    ledger.save(harness.session_id, [*existing, *validated])


def _public_choice_action_validation(
    entry: Any,
    *,
    request: RuntimeV7APIRequest,
) -> Dict[str, Any]:
    """Expose the runtime allowlist decision without trusting router parsing."""

    if not isinstance(entry, dict) or not entry:
        return {}
    if str(entry.get("idempotency_key") or "") != str(
        request.idempotency_key or ""
    ):
        return {}
    validation_status = str(entry.get("validation_status") or "").strip()
    payload = {
        "status": (
            "accepted"
            if validation_status == "valid"
            else "duplicate"
            if validation_status == "duplicate"
            else "stale"
        ),
        "validation_status": validation_status or "stale",
        "presentation_ref": str(entry.get("presentation_ref") or ""),
        "choice_type": str(entry.get("choice_type") or ""),
    }
    for key in ("choice_ref", "card_ref", "choice_code", "category"):
        value = entry.get(key)
        if value not in (None, ""):
            payload[key] = str(value)
    if validation_status == "duplicate":
        payload["reason"] = str(
            entry.get("duplicate_reason")
            or "same_delivered_choice_recently_processed"
        )
    elif validation_status != "valid":
        payload["reason"] = "choice_not_in_current_delivered_allowlist"
    return payload


def _remember_choice_action_delivery_result(
    harness: RuntimeV7Harness,
    request: RuntimeV7APIRequest,
    rendered: RuntimeV7ChannelRender,
    delivery_result: Dict[str, Any],
) -> None:
    """Finalize one category click and link its resulting product surface."""

    entry = deepcopy(getattr(harness, "latest_choice_action", {}))
    if not entry or str(entry.get("idempotency_key") or "") != str(request.idempotency_key or ""):
        return
    status = _interaction_delivery_status(delivery_result)
    entry["delivery_status"] = status
    entry["delivery_result"] = _compact_delivery_result_for_state(delivery_result)
    product_refs = [
        str(item.get("presentation_ref") or "")
        for item in rendered.product_presentations
        if isinstance(item, dict) and str(item.get("presentation_ref") or "")
    ]
    if product_refs:
        entry["resulting_product_presentation_refs"] = product_refs
    if status == "success":
        entry["delivered_at"] = now_manila_str()
    harness.latest_choice_action = entry
    if harness.choice_action_history:
        harness.choice_action_history[-1] = deepcopy(entry)
    else:
        harness.choice_action_history = [deepcopy(entry)]


def _remember_interaction_batch_delivery_result(
    harness: RuntimeV7Harness,
    *,
    turn: Mapping[str, Any],
    delivery_result: Dict[str, Any],
) -> None:
    """Close all provisional events after one resolved response is delivered."""

    packet = (
        turn.get("interaction_packet")
        if isinstance(turn.get("interaction_packet"), dict)
        else {}
    )
    decision = (
        turn.get("interaction_decision_validation")
        if isinstance(turn.get("interaction_decision_validation"), dict)
        else {}
    )
    status = _interaction_delivery_status(delivery_result)
    if (
        not packet
        or decision.get("status") != "valid"
        or status not in {"success", "evaluated"}
    ):
        return
    event_ids = {
        str(event.get("event_id") or "")
        for event in packet.get("events") or []
        if isinstance(event, dict) and str(event.get("event_id") or "")
    }
    if not event_ids:
        return
    processed_at = now_manila_str()
    interpretation = str(decision.get("interpretation") or "").strip()
    effective_event_ids = {
        str(value or "").strip()
        for value in decision.get("effective_event_ids") or []
        if str(value or "").strip()
    }

    def resolution_status(event_id: str) -> str:
        if interpretation == "clarify":
            return (
                "clarification_delivered"
                if status == "success"
                else "clarification_evaluated"
            )
        if interpretation == "compare":
            return (
                "comparison_delivered"
                if status == "success"
                else "comparison_evaluated"
            )
        if event_id in effective_event_ids:
            return (
                "effective_selection_delivered"
                if status == "success"
                else "effective_selection_evaluated"
            )
        return "superseded_by_resolution"

    for latest_name, history_name in (
        ("latest_choice_action", "choice_action_history"),
        ("latest_promo_action", "promo_action_history"),
    ):
        history = [
            {
                **deepcopy(item),
                "delivery_status": status,
                "batch_delivery_status": status,
                "resolution_interpretation": interpretation,
                "resolution_status": resolution_status(
                    str(
                        item.get("event_id")
                        or item.get("message_id")
                        or item.get("idempotency_key")
                        or ""
                    )
                ),
                "effective_for_state": str(
                    item.get("event_id")
                    or item.get("message_id")
                    or item.get("idempotency_key")
                    or ""
                )
                in effective_event_ids,
                "processed_at": processed_at,
                **(
                    {"delivered_at": processed_at}
                    if status == "success"
                    else {}
                ),
            }
            if isinstance(item, dict)
            and str(
                item.get("event_id")
                or item.get("message_id")
                or item.get("idempotency_key")
                or ""
            )
            in event_ids
            else deepcopy(item)
            for item in getattr(harness, history_name, []) or []
        ]
        setattr(harness, history_name, history)
        latest = getattr(harness, latest_name, {})
        latest_id = (
            str(
                latest.get("event_id")
                or latest.get("message_id")
                or latest.get("idempotency_key")
                or ""
            )
            if isinstance(latest, dict)
            else ""
        )
        if latest_id in event_ids:
            updated = next(
                (
                    deepcopy(item)
                    for item in reversed(history)
                    if isinstance(item, dict)
                    and str(
                        item.get("event_id")
                        or item.get("message_id")
                        or item.get("idempotency_key")
                        or ""
                    )
                    == latest_id
                ),
                latest,
            )
            setattr(harness, latest_name, updated)


def _interaction_delivery_status(delivery_result: Dict[str, Any]) -> str:
    """Distinguish safe return-only evaluation from a failed channel send."""

    status = str(delivery_result.get("status") or "unknown").strip().lower()
    reason = str(delivery_result.get("reason") or "").strip().lower()
    delivery_mode = str(
        delivery_result.get("delivery_mode") or ""
    ).strip().lower()
    if status == "skipped" and (
        reason == "return_only" or delivery_mode == "return_only"
    ):
        return "evaluated"
    return status


def _delivered_product_price_list_fingerprints(
    history: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return only v2 list-plus-gallery presentations safe to suppress once.

    Older ledger entries did not prove that the long-form price list was shown,
    so they are deliberately ignored. Failed sends are also excluded. Card
    identities are compacted to keep renderer input and persisted turn records
    small.
    """

    fingerprints: List[Dict[str, Any]] = []
    for entry in history or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("delivery_status") or "").strip().lower() not in {
            "success",
            "evaluated",
        }:
            continue
        expires_at = _parse_datetime(entry.get("expires_at"))
        if expires_at is not None and expires_at <= datetime.now():
            continue
        if (
            entry.get("renderer_variant")
            != "manychat_product_price_list_gallery_v2"
            or entry.get("price_list_included") is not True
            or entry.get("gallery_included") is not True
        ):
            continue
        presentation_ref = str(entry.get("presentation_ref") or "").strip()
        identities = [
            identity
            for card in entry.get("cards") or []
            if isinstance(card, dict)
            and (identity := _product_presentation_card_identity(card))
        ]
        commercial_fingerprints = [
            str(value or "").strip()
            for value in entry.get("commercial_fingerprints") or []
            if str(value or "").strip()
        ]
        if (
            presentation_ref
            and identities
            and len(commercial_fingerprints) == len(identities)
        ):
            fingerprints.append(
                {
                    "presentation_ref": presentation_ref,
                    "card_identities": identities,
                    "commercial_fingerprints": commercial_fingerprints,
                }
            )
    return fingerprints[-10:]


def _product_presentation_card_identity(card: Mapping[str, Any]) -> str:
    """Return the same stable identity order used by the channel renderer."""

    for key in ("item_ref", "product_id", "slug", "card_ref"):
        value = str(card.get(key) or "").strip()
        if value:
            return f"{key}:{value}"
    return ""


def _remember_product_delivery_result(
    harness: RuntimeV7Harness,
    rendered: RuntimeV7ChannelRender,
    delivery_result: Dict[str, Any],
) -> None:
    """Record exact product cards only after their delivery outcome is known."""

    visible_presentations = [
        presentation
        for presentation in rendered.product_presentations
        if isinstance(presentation, dict)
        and _rendered_product_presentation_visible(
            rendered,
            presentation,
        )
    ]
    if not visible_presentations:
        return
    status = _interaction_delivery_status(delivery_result)
    now = now_manila_str()
    history = list(harness.product_presentation_history or [])
    for presentation in visible_presentations:
        entry = deepcopy(presentation)
        entry["delivery_status"] = status
        entry["created_at"] = now
        entry["expires_at"] = _presentation_expiry(now)
        entry["delivery_result"] = {
            key: deepcopy(value)
            for key, value in delivery_result.items()
            if key in {"status", "status_code", "message", "error", "delivery_mode", "reason"}
        }
        if status == "success":
            entry["delivered_at"] = now
        history.append(entry)
        harness.latest_product_presentation = deepcopy(entry)
    harness.product_presentation_history = history[-10:]


def _rendered_product_presentation_visible(
    rendered: RuntimeV7ChannelRender,
    presentation: Mapping[str, Any],
) -> bool:
    """Return whether one product presentation reached customer-visible output."""

    presentation_ref = str(
        presentation.get("presentation_ref") or ""
    ).strip()
    tracked_values = [
        str(action.get("value") or "")
        for message in rendered.content_messages
        if isinstance(message, Mapping)
        for element in message.get("elements") or []
        if isinstance(element, Mapping)
        for button in element.get("buttons") or []
        if isinstance(button, Mapping)
        for action in button.get("actions") or []
        if isinstance(action, Mapping)
    ]
    if presentation_ref and any(
        value.startswith(f"ps1|{presentation_ref}|")
        for value in tracked_values
    ):
        return True

    visible_parts: List[str] = []
    for message in rendered.content_messages:
        if not isinstance(message, Mapping):
            continue
        visible_parts.append(str(message.get("text") or ""))
        for element in message.get("elements") or []:
            if not isinstance(element, Mapping):
                continue
            visible_parts.extend(
                [
                    str(element.get("title") or ""),
                    str(element.get("subtitle") or ""),
                ]
            )
    visible_text = re.sub(
        r"[^a-z0-9]+",
        " ",
        " ".join(visible_parts).casefold(),
    ).strip()
    for card in presentation.get("cards") or []:
        if not isinstance(card, Mapping):
            continue
        for key in ("sku_model", "model", "title", "slug"):
            candidate = re.sub(
                r"[^a-z0-9]+",
                " ",
                str(card.get(key) or "").casefold(),
            ).strip()
            if len(candidate) >= 5 and candidate in visible_text:
                return True
    return False


def _presentation_expiry(created_at: str) -> str:
    parsed = _parse_datetime(created_at)
    if parsed is None:
        return ""
    ttl_hours = max(1.0, float(os.getenv("RUNTIME_V7_FOLLOWUP_PRESENTATION_TTL_HOURS", "24") or "24"))
    return (parsed + timedelta(hours=ttl_hours)).isoformat()


def _export_harness_state(harness: RuntimeV7Harness) -> Dict[str, Any]:
    return {
        "version": 1,
        "session_id": harness.session_id,
        "turn_count": len(harness.turn_records),
        "active_working_memory": compact_active_working_memory_for_persistence(
            harness.memory_store.load(harness.session_id)
        ),
        "recent_turns": deepcopy(harness.recent_turns[-10:]),
        "conversation_history": deepcopy(harness.conversation_history[-20:]),
        "product_inclusions_sent": bool(harness.product_inclusions_sent),
        "service_policy_note_ids_sent": list(
            dict.fromkeys(
                getattr(harness, "service_policy_note_ids_sent", []) or []
            )
        )[-20:],
        "background_signals": harness.signal_ledger.load(harness.session_id),
        "product_observations": _export_product_store(
            harness.tools.store,
            pinned_observation_refs=(
                str(harness.latest_selected_product_context.get("product_observation_ref") or ""),
            ),
        ),
        "service_observations": _export_service_store(harness.service_tools.store),
        "latest_order_summary_snapshot": deepcopy(harness.latest_order_summary_snapshot),
        "latest_selected_product_context": deepcopy(harness.latest_selected_product_context),
        "order_payload_store": deepcopy(harness.order_payload_store),
        "latest_order_payload_ref": harness.latest_order_payload_ref,
        "latest_submitted_order_context": deepcopy(harness.latest_submitted_order_context),
        "latest_order_details_context": deepcopy(harness.latest_order_details_context),
        "payment_request_store": deepcopy(harness.payment_request_store),
        "latest_payment_request_ref": harness.latest_payment_request_ref,
        "external_evidence_store": deepcopy(harness.external_evidence_store),
        "latest_fitment_observation": deepcopy(harness.latest_fitment_observation),
        "tag_ledger": deepcopy(harness.tag_ledger),
        "human_handoff_state": deepcopy(harness.human_handoff_state),
        "latest_promo_presentation": deepcopy(harness.latest_promo_presentation),
        "promo_presentation_history": deepcopy(harness.promo_presentation_history[-10:]),
        "latest_promo_action": deepcopy(harness.latest_promo_action),
        "promo_action_history": deepcopy(harness.promo_action_history[-20:]),
        "latest_choice_presentation": deepcopy(harness.latest_choice_presentation),
        "choice_presentation_history": deepcopy(harness.choice_presentation_history[-10:]),
        "latest_choice_action": deepcopy(harness.latest_choice_action),
        "choice_action_history": deepcopy(harness.choice_action_history[-20:]),
        "latest_product_presentation": deepcopy(harness.latest_product_presentation),
        "product_presentation_history": deepcopy(harness.product_presentation_history[-10:]),
        "updated_at": now_manila_str(),
    }


def _snapshot_interaction_transition_state(
    harness: RuntimeV7Harness,
) -> Dict[str, Any]:
    """Capture only state a validated click can change before composition."""

    return {
        "latest_selected_product_context": deepcopy(
            harness.latest_selected_product_context
        ),
        "service_observations": _export_service_store(
            harness.service_tools.store
        ),
        "background_signals": deepcopy(
            harness.signal_ledger.load(harness.session_id)
        ),
    }


def _restore_interaction_transition_state(
    harness: RuntimeV7Harness,
    snapshot: Mapping[str, Any],
    *,
    restore_service_observations: bool = True,
) -> None:
    """Restore authoritative state while retaining the provisional event ledger."""

    harness.latest_selected_product_context = deepcopy(
        snapshot.get("latest_selected_product_context") or {}
    )
    if restore_service_observations:
        _restore_service_store(
            harness.service_tools.store,
            dict(snapshot.get("service_observations") or {}),
        )
    harness.signal_ledger.save(
        harness.session_id,
        [
            deepcopy(item)
            for item in snapshot.get("background_signals") or []
            if isinstance(item, dict)
        ],
    )


def _restore_harness_for_superseded_interaction(
    harness: RuntimeV7Harness,
    pre_interaction_state: Mapping[str, Any],
) -> None:
    """Discard an obsolete composed turn while retaining its provisional click."""

    choice_history = deepcopy(harness.choice_action_history)
    promo_history = deepcopy(harness.promo_action_history)
    latest_choice = deepcopy(harness.latest_choice_action)
    latest_promo = deepcopy(harness.latest_promo_action)
    _hydrate_harness(harness, dict(pre_interaction_state))
    harness.choice_action_history = choice_history
    harness.promo_action_history = promo_history
    harness.latest_choice_action = latest_choice
    harness.latest_promo_action = latest_promo


def _compile_current_interaction_packet(
    harness: RuntimeV7Harness,
    *,
    request: RuntimeV7APIRequest,
) -> Dict[str, Any]:
    """Build the bounded packet only when the rollout flag is enabled."""

    if not _interaction_batching_enabled():
        return {}
    event_id = str(
        request.channel_event_id
        or request.message_id
        or request.idempotency_key
        or ""
    ).strip()
    return compile_interaction_packet(
        choice_history=harness.choice_action_history,
        promo_history=harness.promo_action_history,
        current_event_id=event_id,
        max_events=_interaction_max_events(),
        max_chars=2500,
    )


def _apply_button_only_ambiguity_envelope(
    packet: Mapping[str, Any],
) -> Dict[str, Any]:
    """Treat the newest same-layer button as the customer's current choice.

    Tracked controls are exact, ordered customer actions. A button-only batch
    contains no customer-authored comparison request, so the newest validated
    action replaces the earlier action in that dimension. Free-text comparison
    requests remain model-owned in ordinary conversation turns.
    """

    output = deepcopy(dict(packet or {}))
    if output.get("runtime_relation") != "same_layer_distinct":
        return output
    output["allowed_model_interpretations"] = ["accept_latest"]
    output["requires_model_interpretation"] = False
    # Defer the mutation until the typed interaction decision is validated so
    # only the effective (latest) event is committed from a rapid batch.
    output["state_commit_deferred"] = True
    output["legality_reason"] = "newest_validated_same_layer_choice_is_current"
    return output


def _prelock_interaction_event(
    request: RuntimeV7APIRequest,
    *,
    request_id: str = "",
) -> Dict[str, Any]:
    """Build an objective, unvalidated event for cross-request freshness."""

    flow = (
        request.flow_context
        if isinstance(request.flow_context, dict)
        else {}
    )
    choice = (
        flow.get("choice_action_context")
        if isinstance(flow.get("choice_action_context"), dict)
        else {}
    )
    promo = (
        flow.get("promo_action_context")
        if isinstance(flow.get("promo_action_context"), dict)
        else {}
    )
    context = choice or promo
    if not context:
        return {}
    event_id = str(
        request.channel_event_id
        or request.message_id
        or request.idempotency_key
        or ""
    ).strip()
    if not event_id:
        return {}
    return {
        "event_id": event_id,
        "idempotency_key": str(
            request.idempotency_key or event_id
        ).strip(),
        "source": (
            "choice_action" if choice else "promo_action"
        ),
        "presentation_ref": str(
            context.get("presentation_ref")
            or context.get("catalog_version_id")
            or ""
        ).strip(),
        "choice_ref": str(
            context.get("choice_ref")
            or context.get("card_ref")
            or context.get("promo_id")
            or ""
        ).strip(),
        "choice_type": str(
            context.get("choice_type")
            or context.get("action")
            or ""
        ).strip(),
        "label": str(
            context.get("label")
            or context.get("selected_brand")
            or context.get("title")
            or ""
        ).strip(),
        "occurred_at": str(
            request.channel_event_ts
            or request.request_time
            or ""
        ).strip(),
        "received_at": str(
            request.request_time or now_manila_str()
        ).strip(),
        "request_id": str(request_id or "").strip(),
        "validation_status": "proposed",
    }


def _interaction_inbox_sort_key(
    event: Mapping[str, Any],
) -> tuple[float, float, str]:
    """Order provider events independently of HTTP/lock arrival order."""

    manila = ZoneInfo("Asia/Manila")

    def _timestamp(value: Any) -> float:
        parsed = _parse_datetime(str(value or ""))
        if parsed is None:
            return 0.0
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=manila)
        return parsed.timestamp()

    return (
        _timestamp(event.get("occurred_at")),
        _timestamp(event.get("received_at")),
        str(
            event.get("event_id")
            or event.get("idempotency_key")
            or ""
        ),
    )


def _latest_newer_prelock_interaction(
    events: Sequence[Mapping[str, Any]],
    *,
    current: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return the latest different event ordered after the current click."""

    current_id = str(
        current.get("event_id")
        or current.get("idempotency_key")
        or ""
    ).strip()
    if not current_id:
        return {}
    current_key = _interaction_inbox_sort_key(current)
    newer = [
        dict(event)
        for event in events or []
        if isinstance(event, Mapping)
        and str(
            event.get("event_id")
            or event.get("idempotency_key")
            or ""
        ).strip()
        not in {"", current_id}
        and _interaction_inbox_sort_key(event) > current_key
    ]
    if not newer:
        return {}
    latest = max(newer, key=_interaction_inbox_sort_key)
    return {
        key: latest.get(key)
        for key in (
            "event_id",
            "source",
            "presentation_ref",
            "choice_ref",
            "choice_type",
            "label",
            "occurred_at",
            "received_at",
        )
        if latest.get(key) not in (None, "")
    }


def _is_tracked_interaction_request(
    request: RuntimeV7APIRequest,
) -> bool:
    flow = (
        request.flow_context
        if isinstance(request.flow_context, dict)
        else {}
    )
    return isinstance(flow.get("choice_action_context"), dict) or isinstance(
        flow.get("promo_action_context"),
        dict,
    )


def _has_unresolved_interaction_history(
    harness: RuntimeV7Harness,
) -> bool:
    packet = compile_interaction_packet(
        choice_history=harness.choice_action_history,
        promo_history=harness.promo_action_history,
        current_event_id="",
        max_events=_interaction_max_events(),
        max_chars=2500,
    )
    return bool(packet)


def _current_interaction_is_valid(
    harness: RuntimeV7Harness,
    request: RuntimeV7APIRequest,
) -> bool:
    """Return whether this request produced one newly validated tracked event."""

    request_key = str(request.idempotency_key or "").strip()
    candidates = [
        getattr(harness, "latest_choice_action", {}),
        getattr(harness, "latest_promo_action", {}),
    ]
    return any(
        isinstance(item, dict)
        and str(item.get("idempotency_key") or "").strip() == request_key
        and str(item.get("validation_status") or "").strip().casefold()
        in {"valid", "ok", "accepted"}
        for item in candidates
    )


def _mark_current_interaction_delivery_status(
    harness: RuntimeV7Harness,
    *,
    request: RuntimeV7APIRequest,
    status: str,
) -> None:
    """Finalize the matching provisional ledger entry without rendering."""

    request_key = str(request.idempotency_key or "").strip()
    processed_at = now_manila_str()
    for latest_name, history_name in (
        ("latest_choice_action", "choice_action_history"),
        ("latest_promo_action", "promo_action_history"),
    ):
        latest = getattr(harness, latest_name, {})
        if (
            not isinstance(latest, dict)
            or str(latest.get("idempotency_key") or "").strip()
            != request_key
        ):
            continue
        updated = {
            **deepcopy(latest),
            "delivery_status": status,
            "processed_at": processed_at,
        }
        setattr(harness, latest_name, updated)
        history = list(getattr(harness, history_name, []) or [])
        for index in range(len(history) - 1, -1, -1):
            if (
                str(history[index].get("idempotency_key") or "").strip()
                == request_key
            ):
                history[index] = deepcopy(updated)
                break
        setattr(harness, history_name, history)


def _commit_validated_interaction_decision(
    harness: RuntimeV7Harness,
    *,
    packet: Mapping[str, Any],
    turn: Dict[str, Any],
) -> None:
    """Commit only the effective transition authorized by the typed decision."""

    decision = (
        turn.get("interaction_decision_validation")
        if isinstance(turn.get("interaction_decision_validation"), dict)
        else {}
    )
    if decision.get("status") != "valid":
        return
    interpretation = str(decision.get("interpretation") or "")
    if interpretation not in {
        "accept_latest",
        "accept_once",
        "hierarchical_advance",
    }:
        return
    event_ids = list(decision.get("effective_event_ids") or [])
    if len(event_ids) != 1:
        return
    action = event_for_id(
        [
            harness.choice_action_history,
            harness.promo_action_history,
        ],
        str(event_ids[0]),
    )
    if not action or action.get("validation_status") not in {
        "valid",
        "ok",
        "accepted",
    }:
        return
    choice_type = str(action.get("choice_type") or "")
    commit_status = "no_state_mutation_required"
    if choice_type == "product_selection":
        resolution = harness.tools.resolve_product_reference(
            {
                "presentation_ref": action.get("presentation_ref"),
                "card_ref": action.get("card_ref"),
            }
        )
        if resolution.get("status") == "resolved":
            harness._remember_selected_product_context_from_resolution(
                resolution
            )
            commit_status = "product_selection_committed"
        else:
            commit_status = "product_selection_resolution_failed"
    elif choice_type == "schedule_selection":
        slot_ref = str(action.get("slot_ref") or "").strip()
        if slot_ref:
            validation = harness.service_tools.validate_installation_slot(
                {
                    "observation_ref": action.get("observation_ref"),
                    "slot_ref": slot_ref,
                    "installation_partner_ref": action.get(
                        "installation_partner_ref"
                    ),
                }
            )
            commit_status = (
                "schedule_selection_committed"
                if validation.get("status") == "ok"
                and validation.get("valid") is True
                else "schedule_selection_validation_failed"
            )
        else:
            commit_status = "schedule_preference_committed"
    elif choice_type in {
        "price_category",
        "payment_option_selection",
        "payment_method_selection",
    }:
        _remember_validated_commercial_choice_signals(harness, action)
        commit_status = (
            "price_category_selection_committed"
            if choice_type == "price_category"
            else "payment_selection_committed"
        )
    elif choice_type in {
        "serviceable_province",
        "serviceable_city",
    }:
        _remember_validated_commercial_choice_signals(harness, action)
        store = harness.service_tools.store
        if choice_type == "serviceable_province":
            store.clear_location_dependent()
            commit_status = "province_selection_committed"
        else:
            location_label = ", ".join(
                value
                for value in (
                    str(action.get("label") or "").strip(),
                    str(action.get("province_label") or "").strip(),
                )
                if value
            )
            store.retain_compatible_location(location_label)
            commit_status = "city_selection_committed"
        _clear_location_dependent_order_state(harness)
    turn["interaction_state_commit"] = {
        "status": commit_status,
        "event_id": str(event_ids[0]),
        "choice_type": choice_type,
    }


def _commit_nonbatched_location_choice_state(
    harness: RuntimeV7Harness,
    *,
    request: RuntimeV7APIRequest,
    turn: Dict[str, Any],
) -> None:
    """Clear draft booking state after an immediately accepted location click."""

    action = (
        request.flow_context.get("choice_action_runtime_context")
        if isinstance(request.flow_context, dict)
        else {}
    )
    validated_location_click = bool(
        isinstance(action, dict)
        and action.get("validation_status") == "valid"
        and action.get("choice_type")
        in {"serviceable_province", "serviceable_city"}
    )
    plan = (
        turn.get("customer_turn_plan")
        if isinstance(turn.get("customer_turn_plan"), dict)
        else {}
    )
    progression = (
        plan.get("progression_context")
        if isinstance(plan.get("progression_context"), dict)
        else {}
    )
    province_only_free_text = (
        progression.get("location_precision") == "province_only"
    )
    if not validated_location_click and not province_only_free_text:
        return
    if province_only_free_text:
        harness.service_tools.store.clear_location_dependent()
    _clear_location_dependent_order_state(harness)


def _clear_location_dependent_order_state(
    harness: RuntimeV7Harness,
) -> None:
    """Invalidate draft order artifacts bound to a prior service location."""

    harness.latest_order_summary_snapshot = {}
    harness.order_payload_store = {}
    harness.latest_order_payload_ref = ""
    harness.payment_request_store = {}
    harness.latest_payment_request_ref = ""
    harness.choice_action_history = [
        action
        for action in harness.choice_action_history
        if str(action.get("choice_type") or "")
        != "schedule_selection"
    ]


def _refresh_turn_state_after_interaction_decision(
    harness: RuntimeV7Harness,
    *,
    packet: Mapping[str, Any],
    turn: Dict[str, Any],
    pre_interaction_state: Mapping[str, Any],
) -> None:
    """Align persisted and handoff snapshots with the validated batch decision."""

    decision = (
        turn.get("interaction_decision_validation")
        if isinstance(turn.get("interaction_decision_validation"), dict)
        else {}
    )
    interpretation = str(decision.get("interpretation") or "")
    effective_ids = {
        str(value)
        for value in decision.get("effective_event_ids") or []
        if str(value)
    }
    if interpretation in {"compare", "clarify"}:
        memory_payload = (
            pre_interaction_state.get("active_working_memory")
            if isinstance(
                pre_interaction_state.get("active_working_memory"),
                dict,
            )
            else {}
        )
        restored_memory = ActiveWorkingMemory.from_dict(memory_payload)
        harness.memory_store.save(harness.session_id, restored_memory)
        _restore_service_store(
            harness.service_tools.store,
            dict(
                pre_interaction_state.get(
                    "service_observations"
                )
                or {}
            ),
        )

    packet_event_ids = {
        str(event.get("event_id") or "")
        for event in packet.get("events") or []
        if isinstance(event, Mapping) and str(event.get("event_id") or "")
    }
    readiness_history = []
    for action in harness.choice_action_history:
        action_id = str(
            action.get("event_id")
            or action.get("message_id")
            or action.get("idempotency_key")
            or ""
        )
        if action_id in packet_event_ids and action_id not in effective_ids:
            continue
        readiness_history.append(action)
    memory = harness.memory_store.load(harness.session_id)
    signals = harness.signal_ledger.load(harness.session_id)
    readiness = build_order_readiness(
        current_user_message=str(turn.get("user_message") or ""),
        active_working_memory=memory.text,
        background_signals=signals,
        product_observation_store=harness.tools.store,
        service_observation_store=harness.service_tools.store,
        selected_product_context=harness.latest_selected_product_context,
        choice_action_history=readiness_history,
        previous_order_summary_snapshot=harness.latest_order_summary_snapshot,
        canonical_values_provider=harness.canonical_values_provider,
    )
    turn["active_working_memory_after_turn"] = memory.to_dict()
    turn["background_signal_ledger_after_turn"] = deepcopy(signals)
    turn["latest_selected_product_context_after_turn"] = deepcopy(
        harness.latest_selected_product_context
    )
    turn["service_observation_headers_after_turn"] = (
        harness.service_tools.store.headers(limit=3)
    )
    turn["order_readiness_after_tools"] = readiness.to_dict()


def _export_product_store(
    store: ProductObservationStore,
    *,
    pinned_observation_refs: Sequence[str] = (),
) -> Dict[str, Any]:
    all_observations = getattr(store, "_observations", {})
    observations = list(all_observations.values())[-3:]
    retained_refs = {item.observation_ref for item in observations}
    for pinned_ref in pinned_observation_refs:
        normalized_ref = str(pinned_ref or "").strip()
        pinned = all_observations.get(normalized_ref)
        if pinned is not None and normalized_ref not in retained_refs:
            observations.insert(0, pinned)
            retained_refs.add(normalized_ref)
    kept_refs = {item.observation_ref for item in observations}
    presentation_index = {
        str(presentation_ref): str(observation_ref)
        for presentation_ref, observation_ref in getattr(store, "_presentation_index", {}).items()
        if str(observation_ref) in kept_refs
    }
    latest_ref = getattr(store, "_latest_ref", None)
    if latest_ref not in kept_refs:
        latest_ref = observations[-1].observation_ref if observations else None
    return {
        "observations": [asdict(item) for item in observations],
        "presentation_index": presentation_index,
        "latest_ref": latest_ref,
    }


def _restore_product_store(store: ProductObservationStore, payload: Dict[str, Any]) -> None:
    observations = {}
    for item in payload.get("observations") or []:
        if isinstance(item, dict) and item.get("observation_ref"):
            observations[str(item["observation_ref"])] = ProductObservation(**item)
    store._observations = observations
    store._presentation_index = dict(payload.get("presentation_index") or {})
    store._latest_ref = payload.get("latest_ref")


def _export_service_store(store: ServiceObservationStore) -> Dict[str, Any]:
    return {
        "observations": [asdict(item) for item in getattr(store, "_observations", {}).values()],
        "latest_ref": getattr(store, "_latest_ref", None),
        "location_index": deepcopy(getattr(store, "_location_index", {})),
    }


def _restore_service_store(store: ServiceObservationStore, payload: Dict[str, Any]) -> None:
    observations = {}
    for item in payload.get("observations") or []:
        if isinstance(item, dict) and item.get("observation_ref"):
            observations[str(item["observation_ref"])] = ServiceObservation(**item)
    store._observations = observations
    store._latest_ref = payload.get("latest_ref")
    store._location_index = dict(payload.get("location_index") or {})


def _required_user_id(request: RuntimeV7APIRequest) -> str:
    user_id = str(request.user_id or request.channel_user_id or "").strip()
    if not user_id:
        raise ValueError("user_id is required")
    request.user_id = user_id
    request.channel_user_id = str(request.channel_user_id or user_id).strip()
    return user_id


def _stable_message_id(request: RuntimeV7APIRequest, *, user_id: str) -> str:
    payload = {
        "user_id": user_id,
        "channel": request.channel,
        "channel_subtype": request.channel_subtype,
        "user_text": request.user_text,
    }
    stable = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return f"msg_{hashlib.sha256(stable.encode('utf-8')).hexdigest()}"


def _extract_image_urls_from_text(text: str) -> List[str]:
    urls = re.findall(r"https?://[^\s)>\"]+", str(text or ""), flags=re.IGNORECASE)
    image_urls: List[str] = []
    for url in urls:
        cleaned = url.rstrip(".,;")
        lowered = cleaned.lower()
        if "gulong.ph/product" in lowered:
            continue
        if re.search(r"\.(?:png|jpg|jpeg|webp|gif)(?:\?|$)", lowered) or any(
            marker in lowered for marker in ["manychat", "cdn", "storage.googleapis.com", "scontent"]
        ):
            image_urls.append(cleaned)
    return _unique(image_urls)


def _existing_tag_names(profile_fields: Dict[str, Any]) -> List[str]:
    tags = profile_fields.get("tags")
    output: List[str] = []
    if isinstance(tags, list):
        for item in tags:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
            else:
                name = str(item or "").strip()
            if name:
                output.append(name)
    return output


def _load_manychat_profile(request: RuntimeV7APIRequest) -> Dict[str, Any]:
    try:
        from channels.manychat.session import ManychatSession

        session = ManychatSession(user_id=str(request.user_id), user_name=request.full_name or None)
        profile: Dict[str, Any] = {}
        info = session.get_user_info()
        data = info.get("data") if isinstance(info, dict) else {}
        if isinstance(data, dict):
            for source, target in [
                ("name", "full_name"),
                ("user_name", "full_name"),
                ("first_name", "first_name"),
                ("last_name", "last_name"),
            ]:
                if data.get(source):
                    profile.setdefault(target, data.get(source))
            if data.get("tags"):
                profile["tags"] = data.get("tags")
            if data.get("custom_fields"):
                profile["custom_fields"] = data.get("custom_fields")
        agent = session.get_agent_data()
        agent_data = agent.get("data") if isinstance(agent, dict) else {}
        if isinstance(agent_data, dict):
            assigned = agent_data.get("agent_assigned") or agent_data.get("assigned_agent")
            if assigned:
                profile["assigned_agent"] = assigned
                profile["agent_assigned"] = assigned
        profile["profile_loaded_at"] = now_manila_str()
        return profile
    except Exception:
        return {}


def _load_manychat_messages(request: RuntimeV7APIRequest) -> Dict[str, Any]:
    limit = int(os.getenv("RUNTIME_V7_MANYCHAT_MESSAGES_LIMIT", "20") or "20")
    timeout_s = float(os.getenv("RUNTIME_V7_MANYCHAT_MESSAGES_TIMEOUT_S", "5") or "5")
    message_age_days = int(os.getenv("RUNTIME_V7_MANYCHAT_MESSAGE_AGE_DAYS", "30") or "30")
    max_pages = int(os.getenv("RUNTIME_V7_MANYCHAT_MESSAGES_MAX_PAGES", "4") or "4")
    return load_manychat_messages_fast(
        user_id=str(request.user_id),
        user_name=str(request.full_name or ""),
        limit=max(1, limit),
        timeout_s=max(0.1, timeout_s),
        message_age_days=max(1, message_age_days),
        max_pages=max(1, max_pages),
    )


def _load_manychat_messages_for_freshness(request: RuntimeV7APIRequest) -> Dict[str, Any]:
    limit = int(os.getenv("RUNTIME_V7_FRESHNESS_MESSAGES_LIMIT", "8") or "8")
    timeout_s = float(os.getenv("RUNTIME_V7_FRESHNESS_TIMEOUT_S", "3") or "3")
    message_age_days = int(os.getenv("RUNTIME_V7_MANYCHAT_MESSAGE_AGE_DAYS", "30") or "30")
    return load_manychat_messages_fast(
        user_id=str(request.user_id),
        user_name=str(request.full_name or ""),
        limit=max(1, limit),
        timeout_s=max(0.1, timeout_s),
        message_age_days=max(1, message_age_days),
        max_pages=1,
    )


def _same_channel_message(message: Dict[str, Any], *, message_id: str, content: str) -> bool:
    if message_id:
        return str(message.get("message_id") or "").strip() == message_id
    return _compact_text(message.get("content")) == _compact_text(content)


def _latest_unprocessed_user_message(
    messages: Sequence[Dict[str, Any]],
    *,
    processed_message_ids: set[str],
) -> Dict[str, Any]:
    """Select the newest user event whose provider id is not in the ledger."""

    ordered = sorted(
        [dict(item) for item in messages if isinstance(item, dict)],
        key=lambda item: (
            str(
                item.get("datetime")
                or item.get("created_at")
                or item.get("timestamp")
                or ""
            ),
        ),
        reverse=True,
    )
    for message in ordered:
        if str(message.get("role") or "").strip() != "user":
            continue
        message_id = str(message.get("message_id") or "").strip()
        if message_id and message_id in processed_message_ids:
            continue
        return message
    return {}


def _latest_channel_message(messages: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    if not messages:
        return {}
    ordered = sorted(
        [dict(item) for item in messages if isinstance(item, dict)],
        key=lambda item: (str(item.get("datetime") or item.get("created_at") or item.get("timestamp") or ""),),
    )
    return dict(ordered[-1]) if ordered else {}


def _channel_message_text(message: Mapping[str, Any]) -> str:
    for key in ("content", "text", "message", "text_content", "msg_body"):
        value = str(message.get(key) or "").strip()
        if value:
            return value
    return ""


def _compact_channel_message(message: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "message_id": str(message.get("message_id") or ""),
        "role": str(message.get("role") or ""),
        "datetime": str(message.get("datetime") or ""),
        "content_preview": str(message.get("content") or "")[:180],
        "source": str(message.get("source") or ""),
    }


def _runtime_v7_session_lock_enabled() -> bool:
    return str(os.getenv("RUNTIME_V7_SESSION_LOCK_ENABLED", "1") or "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _interaction_batching_enabled() -> bool:
    return str(
        os.getenv("RUNTIME_V7_INTERACTION_BATCHING_ENABLED", "0") or "0"
    ).strip().lower() in {"1", "true", "yes", "on"}


def _interaction_settle_ms() -> int:
    try:
        value = int(
            os.getenv("RUNTIME_V7_INTERACTION_SETTLE_MS", "400") or "400"
        )
    except (TypeError, ValueError):
        value = 400
    return max(0, min(600, value))


def _interaction_max_wait_ms() -> int:
    try:
        value = int(
            os.getenv("RUNTIME_V7_INTERACTION_MAX_WAIT_MS", "600") or "600"
        )
    except (TypeError, ValueError):
        value = 600
    return max(0, min(600, value))


def _interaction_max_events() -> int:
    try:
        value = int(
            os.getenv("RUNTIME_V7_INTERACTION_MAX_EVENTS", "5") or "5"
        )
    except (TypeError, ValueError):
        value = 5
    return max(1, min(10, value))


def _runtime_v7_session_lock_recovery_enabled() -> bool:
    return str(os.getenv("RUNTIME_V7_SESSION_LOCK_RECOVERY_ENABLED", "1") or "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _runtime_v7_session_lock_recovery_wait_s() -> float:
    return max(0.0, float(os.getenv("RUNTIME_V7_SESSION_LOCK_RECOVERY_WAIT_S", "45") or "45"))


def _manychat_cloudsql_compare_enabled() -> bool:
    return str(os.getenv("RUNTIME_V7_MANYCHAT_CLOUDSQL_COMPARE_ENABLED", "0") or "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _manychat_cloudsql_compare_limit() -> int:
    raw = os.getenv(
        "RUNTIME_V7_MANYCHAT_CLOUDSQL_COMPARE_LIMIT",
        os.getenv("RUNTIME_V7_MANYCHAT_MESSAGES_LIMIT", "20"),
    )
    return max(1, int(raw or "20"))


def _manychat_cloudsql_compare_sample_rate() -> float:
    raw = os.getenv("RUNTIME_V7_MANYCHAT_CLOUDSQL_COMPARE_SAMPLE_RATE", "1")
    try:
        value = float(raw or "1")
    except (TypeError, ValueError):
        value = 1.0
    return max(0.0, min(1.0, value))


def _manychat_cloudsql_compare_sample_allows(request: RuntimeV7APIRequest) -> bool:
    rate = _manychat_cloudsql_compare_sample_rate()
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    seed = "|".join(
        [
            str(request.user_id or ""),
            str(request.message_id or ""),
            str(request.channel_event_id or ""),
            str(request.request_time or ""),
            str(request.user_text or ""),
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8]
    bucket = int(digest, 16) / 0xFFFFFFFF
    return bucket < rate


def _runtime_v7_delivery_freshness_enabled() -> bool:
    return str(os.getenv("RUNTIME_V7_PRE_DELIVERY_FRESHNESS_CHECK", "1") or "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _session_lock_recovery_flow_context(
    flow_context: Optional[Mapping[str, Any]],
    recovery: Mapping[str, Any],
) -> Dict[str, Any]:
    payload = dict(flow_context or {})
    payload["session_lock_recovery"] = _compact_session_lock_recovery(recovery)
    return payload


def _session_lock_recovered_normalized_payload(
    normalized_payload: Optional[Mapping[str, Any]],
    *,
    latest_text: str,
    latest_message_id: str,
    latest_channel_event_id: str,
    latest_datetime: str,
) -> Dict[str, Any]:
    payload = dict(normalized_payload or {})
    payload["user_text"] = str(latest_text or "")
    payload["message_id"] = str(latest_message_id or "")
    payload["channel_event_id"] = str(latest_channel_event_id or "")
    payload["channel_event_ts"] = str(latest_datetime or "")
    payload["session_lock_recovery_selected"] = True
    return payload


def _compact_session_lock_recovery(recovery: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not isinstance(recovery, Mapping):
        return {}
    allowed = {
        "enabled",
        "phase",
        "initial_wait_exhausted",
        "secondary_wait_s",
        "status",
        "history_refresh_attempted",
        "history_refresh_status",
        "history_message_count",
        "message_selection",
        "original_message_id",
        "selected_message_id",
        "selected_message_datetime",
        "post_lock_message_selection",
        "post_lock_selected_message_id",
        "post_lock_selected_message_datetime",
    }
    compact = {key: recovery.get(key) for key in allowed if recovery.get(key) not in (None, "", [], {})}
    latest = recovery.get("latest_message")
    if isinstance(latest, Mapping):
        compact["latest_message"] = dict(latest)
    return compact


def _session_busy_result(
    *,
    request: RuntimeV7APIRequest,
    request_id: str,
    trace_id: str,
    session_id: str,
    user_id: str,
    recovery: Optional[Dict[str, Any]] = None,
) -> RuntimeV7APIResult:
    delivery_result = {
        "status": "skipped",
        "reason": "session_lock_busy",
        "delivery_mode": _normalize_delivery_mode(request.delivery_mode),
    }
    compact_recovery = _compact_session_lock_recovery(recovery)
    if compact_recovery:
        delivery_result["session_lock_recovery"] = compact_recovery
    turn_record = {
        "turn_id": "turn_not_started_session_busy",
        "user_message": request.user_text,
        "tool_results": [],
        "llm_calls": [],
        "tagging": {"tags_to_add": []},
    }
    if compact_recovery:
        turn_record["session_lock_recovery"] = compact_recovery
    inbound_event = {
        "request_id": request_id,
        "trace_id": trace_id,
        "runtime_version": "v7",
        "message_id": str(request.message_id or ""),
        "event_key": "",
        "status": "session_lock_busy",
    }
    if compact_recovery:
        inbound_event["session_lock_recovery"] = compact_recovery
    return RuntimeV7APIResult(
        response={},
        content_messages=[],
        images=[],
        payment={},
        delivery_result=delivery_result,
        tagging_result={},
        turn_record=turn_record,
        session_id=session_id,
        trace_id=trace_id,
        request_id=request_id,
        message_id=str(request.message_id or ""),
        idempotency_key=str(request.idempotency_key or request.message_id or ""),
        state_saved=False,
        status="session_busy_retry_later",
        turn_trace=build_turn_trace(
            inbound_event=inbound_event,
            turn_record=turn_record,
            delivery_result=delivery_result,
            tagging_result={},
            state_saved=False,
        ),
    )


def _turn_trace_debug_payload(
    *,
    request: RuntimeV7APIRequest,
    turn: Dict[str, Any],
    rendered: RuntimeV7ChannelRender,
    turn_trace: Dict[str, Any],
    delivery_result: Dict[str, Any],
    tagging_result: Dict[str, Any],
) -> Dict[str, Any]:
    return _jsonable(
        {
            "schema_version": 1,
            "kind": "runtime_v7_turn_trace",
            "request": {
                "user_id": request.user_id,
                "channel_user_id": request.channel_user_id,
                "channel": request.channel,
                "channel_subtype": request.channel_subtype,
                "message_id": request.message_id,
                "message_id_source": request.message_id_source,
                "idempotency_key": request.idempotency_key,
                "channel_event_id": request.channel_event_id,
                "channel_event_ts": request.channel_event_ts,
                "request_time": request.request_time,
                "reset": request.reset,
                "delivery_mode": request.delivery_mode,
                "normalized_payload": request.normalized_payload,
                "flow_context": request.flow_context,
            },
            "turn_trace": turn_trace,
            "turn_record": turn,
            "rendered": {
                "response": rendered.response,
                "content_messages": rendered.content_messages,
                "images": rendered.images,
                "payment": rendered.payment,
                "text": rendered.text,
            },
            "delivery_result": delivery_result,
            "tagging_result": tagging_result,
        }
    )


def _compact_trace_log_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    trace = payload.get("turn_trace") if isinstance(payload.get("turn_trace"), dict) else {}
    turn = payload.get("turn_record") if isinstance(payload.get("turn_record"), dict) else {}
    usage = turn.get("llm_usage_summary") if isinstance(turn.get("llm_usage_summary"), dict) else {}
    return {
        "kind": payload.get("kind"),
        "trace_id": trace.get("trace_id"),
        "turn_id": trace.get("turn_id"),
        "status": trace.get("status"),
        "delivery_status": (payload.get("delivery_result") or {}).get("status")
        if isinstance(payload.get("delivery_result"), dict)
        else "",
        "tool_names": [
            item.get("name")
            for item in turn.get("tool_results") or []
            if isinstance(item, dict) and item.get("name")
        ],
        "llm_call_count": usage.get("llm_call_count"),
        "total_tokens": usage.get("total_tokens"),
        "cache_hit_rate": usage.get("cache_hit_rate"),
    }


def _emit_normalized_turn_logs(
    analytics_gateway: Any,
    *,
    request: RuntimeV7APIRequest,
    turn: Dict[str, Any],
    rendered: RuntimeV7ChannelRender,
    turn_trace: Dict[str, Any],
    delivery_result: Dict[str, Any],
    tagging_result: Dict[str, Any],
    session_id: str,
    request_id: str,
    trace_id: str,
    user_id: str,
) -> None:
    """Emit queryable Runtime V7 turn logs without depending on legacy runtime tables."""

    ts = now_manila_str()
    llm_calls = [
        item
        for key in ("llm_calls", "supplemental_llm_calls")
        for item in (turn.get(key) or [])
        if isinstance(item, dict)
    ]
    tool_results = [item for item in (turn.get("tool_results") or []) if isinstance(item, dict)]
    usage = turn.get("llm_usage_summary") if isinstance(turn.get("llm_usage_summary"), dict) else {}
    tokens_in = _int_or_none(usage.get("prompt_tokens"))
    tokens_out = _int_or_none(usage.get("completion_tokens"))
    tokens_total = _int_or_none(usage.get("total_tokens"))
    provider_llm_call_count = (
        _int_or_none(usage.get("llm_call_count")) or len(llm_calls)
    )
    turn_latency_ms = _turn_latency_ms(turn_trace, usage, llm_calls, tool_results)
    tool_failures = sum(1 for item in tool_results if _tool_failed(item))
    delivery_status = _text(delivery_result.get("status") if isinstance(delivery_result, dict) else "")
    status = _text(turn_trace.get("status") if isinstance(turn_trace, dict) else "") or "completed"
    if isinstance(delivery_result, dict) and delivery_result.get("reason") == "session_lock_busy":
        status = "session_busy_retry_later"
    flow_stage_after = _flow_stage_after(turn, tagging_result)
    request_payload = _runtime_v7_request_payload(request)
    final_response = _runtime_v7_final_response(rendered, delivery_result=delivery_result)
    request_source = _text(request.user_id_source) or _text(request.channel)
    common = {
        "request_id": request_id,
        "ts": ts,
        "trace_id": trace_id,
        "session_id": session_id,
        "user_id": user_id,
        "channel": request.channel,
        "business_unit": "gulong",
        "runtime_version": "v7",
    }

    _safe_enqueue_analytics(
        analytics_gateway,
        "enqueue_request_state_log",
        {
            **common,
            "message_id": request.message_id,
            "idempotency_key": request.idempotency_key,
            "request_source": request_source,
            "status": status,
            "attempt_count": 1,
            "llm_executed": bool(llm_calls),
            "last_error_type": _delivery_error_type(delivery_result),
            "last_error_stage": "delivery" if _delivery_error_type(delivery_result) else "",
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "flow_stage_after": flow_stage_after,
            "delivery_status": delivery_status,
            "request_payload": request_payload,
            "final_response": final_response,
            "meta": {
                "turn_id": turn.get("turn_id"),
                "channel_event_id": request.channel_event_id,
                "channel_event_ts": request.channel_event_ts,
                "message_id_source": request.message_id_source,
                "state_saved": status != "completed_state_not_saved",
                "delivery_mode": request.delivery_mode,
            },
        },
    )
    _safe_enqueue_analytics(
        analytics_gateway,
        "enqueue_request_attempt_log",
        {
            **common,
            "attempt_no": 1,
            "stage": "runtime_turn",
            "event_type": status,
            "retryable": status in {"session_busy_retry_later"},
            "latency_ms": turn_latency_ms,
            "backoff_seconds": 0,
            "session_locked": bool(status == "session_busy_retry_later" or (delivery_result or {}).get("reason") == "session_lock_busy"),
            "llm_executed": bool(llm_calls),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "error_type": _delivery_error_type(delivery_result),
            "error_message": _delivery_error_message(delivery_result),
            "model": _first_llm_model(llm_calls),
            "meta": {
                "turn_id": turn.get("turn_id"),
                "delivery_status": delivery_status,
                "tool_call_count": len(tool_results),
            },
        },
    )
    compact_llm_spans = [_compact_llm_span(item, index=index) for index, item in enumerate(llm_calls, start=1)]
    compact_tool_records = [_compact_tool_call_record(item, index=index) for index, item in enumerate(tool_results, start=1)]
    _safe_enqueue_analytics(
        analytics_gateway,
        "enqueue_turn_trace_log",
        {
            **common,
            "channel_user_id": request.channel_user_id or user_id,
            "user_id_source": request.user_id_source,
            "request_source": request_source,
            "orchestration_mode": "single_orchestrator",
            "flow_stage_after": flow_stage_after,
            "turn_latency_ms": turn_latency_ms,
            "llm_calls": provider_llm_call_count,
            "tool_calls": len(tool_results),
            "tool_failures": tool_failures,
            "request_payload": request_payload,
            "channel_context": _compact_json(
                {
                    "conversation_hydration": turn.get("conversation_hydration"),
                    "conversation_evidence": turn.get("conversation_evidence"),
                    "hydrated_recent_turns_before_turn": turn.get("hydrated_recent_turns_before_turn"),
                }
            ),
            "llm_spans": compact_llm_spans,
            "tool_call_records": compact_tool_records,
            "active_agents": [
                {
                    "agent_id": "runtime_v7_orchestrator",
                    "agent_role": "orchestrator",
                    "mode": "chat_completions_tool_loop",
                }
            ],
            "agent_graph": {"nodes": ["runtime_v7_orchestrator"], "edges": []},
            "memory_bank": _compact_json(turn.get("active_working_memory_after_turn") or {}),
            "slots": _compact_json(
                {
                    "background_signals_before_turn": turn.get("background_signals_before_turn"),
                    "missing_info_before_turn": turn.get("missing_info_before_turn"),
                    "order_readiness_before_turn": turn.get("order_readiness_before_turn"),
                }
            ),
            "compatibility_state": _compact_json(
                {
                    "latest_selected_product_context_after_turn": turn.get("latest_selected_product_context_after_turn"),
                    "latest_order_summary_snapshot_after_turn": turn.get("latest_order_summary_snapshot_after_turn"),
                    "latest_submitted_order_context_after_turn": turn.get("latest_submitted_order_context_after_turn"),
                    "latest_order_details_context_after_turn": turn.get("latest_order_details_context_after_turn"),
                }
            ),
            "canonical_state_snapshot": _compact_json(turn_trace.get("state_snapshots") if isinstance(turn_trace, dict) else []),
            "errors": _runtime_v7_error_rows(tool_results, delivery_result),
            "final_response": final_response,
            "tagging": _compact_json(tagging_result),
        },
    )
    response_bubble_count = len([value for value in (rendered.response or {}).values() if _text(value)])
    _safe_enqueue_analytics(
        analytics_gateway,
        "enqueue_turn_fact_log",
        {
            **common,
            "request_source": request_source,
            "orchestration_mode": "single_orchestrator",
            "flow_stage_after": flow_stage_after,
            "turn_latency_ms": turn_latency_ms,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "tokens_total": tokens_total,
            "llm_calls": provider_llm_call_count,
            "tool_calls": len(tool_results),
            "tool_failures": tool_failures,
            "has_tools": bool(tool_results),
            "out_of_flow_signal": _out_of_flow_signal(turn),
            "response_bubble_count": response_bubble_count,
            "request_payload": request_payload,
        },
    )
    for index, call in enumerate(llm_calls, start=1):
        span = _compact_llm_span(call, index=index)
        span_usage = call.get("usage_summary") if isinstance(call.get("usage_summary"), dict) else {}
        _safe_enqueue_analytics(
            analytics_gateway,
            "enqueue_llm_span_log",
            {
                **common,
                "span_index": index,
                "component": span.get("component"),
                "agent_id": "runtime_v7_orchestrator",
                "agent_role": "orchestrator",
                "parent_span_id": "",
                "model": span.get("model"),
                "provider": span.get("provider"),
                "tokens_in": _int_or_none(span_usage.get("prompt_tokens")),
                "tokens_out": _int_or_none(span_usage.get("completion_tokens")),
                "latency_ms": _int_or_none(call.get("latency_ms") or span_usage.get("latency_ms")),
                "meta": span,
            },
        )
    for index, tool_result in enumerate(tool_results, start=1):
        compact_tool = _compact_tool_call_record(tool_result, index=index)
        _safe_enqueue_analytics(
            analytics_gateway,
            "enqueue_tool_call_log",
            {
                **common,
                "call_index": index,
                "tool_call_id": compact_tool.get("tool_call_id"),
                "tool_name": compact_tool.get("tool_name"),
                "component": "runtime_tool_loop",
                "agent_id": "runtime_v7_orchestrator",
                "agent_role": "orchestrator",
                "ok": not _tool_failed(tool_result),
                "error": compact_tool.get("error"),
                "latency_ms": _int_or_none(tool_result.get("latency_ms")),
                "artifact_id": compact_tool.get("artifact_id"),
                "args": _compact_json(tool_result.get("args") or {}),
                "summary_context": compact_tool.get("summary_context"),
                "presentation": compact_tool.get("presentation"),
            },
        )
    _emit_interaction_events(
        analytics_gateway,
        request=request,
        turn=turn,
        rendered=rendered,
        delivery_result=delivery_result,
        common=common,
    )
    _safe_dispatch_normalized_analytics(analytics_gateway)


def _emit_interaction_events(
    analytics_gateway: Any,
    *,
    request: RuntimeV7APIRequest,
    rendered: RuntimeV7ChannelRender,
    delivery_result: Dict[str, Any],
    common: Dict[str, Any],
    turn: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit append-only discovery funnel events without blocking delivery."""

    delivery_status = _text(delivery_result.get("status"))

    def emit(event_type: str, **values: Any) -> None:
        _safe_enqueue_analytics(
            analytics_gateway,
            "enqueue_interaction_event_log",
            {
                **common,
                "event_type": event_type,
                "surface_type": "",
                "surface_ref": "",
                "catalog_version_id": "",
                "choice_type": "",
                "choice_ref": "",
                "promo_id": "",
                "card_id": "",
                "brand": "",
                "category": "",
                "tire_size": "",
                "position": 0,
                "idempotency_key": request.idempotency_key,
                "delivery_status": delivery_status,
                "details": {},
                **values,
            },
        )

    turn = turn if isinstance(turn, dict) else {}
    interaction_packet = (
        turn.get("interaction_packet")
        if isinstance(turn.get("interaction_packet"), dict)
        else {}
    )
    if interaction_packet:
        events = [
            item
            for item in interaction_packet.get("events") or []
            if isinstance(item, dict)
        ]
        latest_event = events[-1] if events else {}
        batch_details = {
            "batch_ref": interaction_packet.get("batch_ref"),
            "runtime_relation": interaction_packet.get("runtime_relation"),
            "event_count": len(events),
            "event_ids": [
                str(item.get("event_id") or "")
                for item in events
                if str(item.get("event_id") or "")
            ],
        }
        emit(
            "interaction_batch_started",
            surface_ref=latest_event.get("presentation_ref"),
            choice_type=latest_event.get("choice_type"),
            choice_ref=latest_event.get("choice_ref"),
            details=batch_details,
        )
        if len(events) > 1:
            emit(
                "interaction_event_joined",
                surface_ref=latest_event.get("presentation_ref"),
                choice_type=latest_event.get("choice_type"),
                choice_ref=latest_event.get("choice_ref"),
                details=batch_details,
            )
        if turn.get("interaction_turn_superseded"):
            emit(
                "interaction_turn_superseded",
                surface_ref=latest_event.get("presentation_ref"),
                choice_type=latest_event.get("choice_type"),
                choice_ref=latest_event.get("choice_ref"),
                details=batch_details,
            )
        decision = (
            turn.get("interaction_decision_validation")
            if isinstance(
                turn.get("interaction_decision_validation"),
                dict,
            )
            else {}
        )
        if decision.get("status") == "valid":
            decision_details = {
                **batch_details,
                "interpretation": decision.get("interpretation"),
                "reason_code": decision.get("reason_code"),
                "effective_event_ids": list(
                    decision.get("effective_event_ids") or []
                ),
            }
            emit(
                "interaction_batch_resolved",
                surface_ref=latest_event.get("presentation_ref"),
                choice_type=latest_event.get("choice_type"),
                choice_ref=latest_event.get("choice_ref"),
                details=decision_details,
            )
            if decision.get("needs_clarification"):
                emit(
                    "interaction_clarification_requested",
                    surface_ref=latest_event.get("presentation_ref"),
                    choice_type=latest_event.get("choice_type"),
                    choice_ref=latest_event.get("choice_ref"),
                    details=decision_details,
                )

    presentation_event = (
        "surface_delivery_succeeded"
        if delivery_status == "success"
        else "surface_delivery_failed"
        if delivery_status in {"error", "failed", "failure", "suppressed"}
        else ""
    )
    if (
        presentation_event
        and rendered.promo_presentation
        and _rendered_has_tracked_choice_token(rendered, prefix="pc1|")
    ):
        promo = rendered.promo_presentation
        emit(
            presentation_event,
            surface_type="promo_gallery",
            surface_ref=promo.get("presentation_ref"),
            catalog_version_id=promo.get("catalog_version_id"),
            details={"promo_ids": promo.get("promo_ids") or [], "card_refs": promo.get("card_refs") or []},
        )
    delivered_choice_presentations = rendered.choice_presentations if presentation_event else []
    token_prefixes = {
        "price_category": "bc1|",
        "product_selection": "ps1|",
        "serviceable_province": "lc1|",
        "serviceable_city": "lc1|",
        "schedule_selection": "ss1|",
        "payment_option_selection": "po1|",
        "payment_method_selection": "pm1|",
    }
    for presentation in delivered_choice_presentations:
        choice_type = str(presentation.get("choice_type") or "")
        token_prefix = token_prefixes.get(choice_type, "")
        if not _rendered_has_tracked_choice_token(rendered, prefix=token_prefix):
            continue
        emit(
            presentation_event,
            surface_type=presentation.get("surface_type"),
            surface_ref=presentation.get("presentation_ref"),
            choice_type=choice_type,
            tire_size=presentation.get("tire_size"),
            details={
                "choices": presentation.get("choices") or [],
                "renderer_variant": presentation.get("renderer_variant"),
                "level": presentation.get("level"),
                "parent_code": presentation.get("parent_code"),
                "source": presentation.get("source"),
                "source_version": presentation.get("source_version"),
            },
        )

    flow = request.flow_context if isinstance(request.flow_context, dict) else {}
    promo_context = flow.get("promo_action_context") if isinstance(flow.get("promo_action_context"), dict) else {}
    promo_tracking_context = (
        flow.get("promo_action_tracking_context")
        if isinstance(flow.get("promo_action_tracking_context"), dict)
        else {}
    )
    choice_context = (
        flow.get("choice_action_runtime_context")
        if isinstance(flow.get("choice_action_runtime_context"), dict)
        else {}
    )
    if promo_context:
        promo = promo_context.get("promo") if isinstance(promo_context.get("promo"), dict) else {}
        valid = str(promo_context.get("status") or "") in {"ok", "valid", "stale"}
        promo_event_values = {
            "surface_type": promo_tracking_context.get("surface_type") or "promo_gallery",
            "surface_ref": promo_tracking_context.get("surface_ref"),
            "catalog_version_id": promo_context.get("catalog_version_id"),
            "choice_type": "promo_action",
            "choice_ref": promo_tracking_context.get("choice_ref") or promo_context.get("action"),
            "promo_id": promo.get("promo_id"),
            "card_id": promo_tracking_context.get("card_ref") or promo_context.get("card_id"),
            "brand": promo_context.get("selected_brand"),
        }
        emit(
            "choice_clicked" if valid else "choice_rejected",
            **promo_event_values,
            details={
                "validation_status": promo_context.get("status"),
                "presentation_ref": promo_tracking_context.get("presentation_ref"),
                "presentation_ref_source": promo_tracking_context.get(
                    "presentation_ref_source"
                ),
                "surface_ref": promo_tracking_context.get("surface_ref"),
                "card_ref": promo_tracking_context.get("card_ref"),
                "choice_type": promo_tracking_context.get("choice_type")
                or "promo_action",
                "choice_ref": promo_tracking_context.get("choice_ref")
                or promo_context.get("action"),
                "event_id": request.channel_event_id or request.message_id,
                "idempotency_key": request.idempotency_key,
            },
        )
        if valid and delivery_status == "success":
            emit("choice_response_delivered", **promo_event_values)
            if rendered.product_presentations:
                promo_runtime_context = (
                    flow.get("promo_action_runtime_context")
                    if isinstance(flow.get("promo_action_runtime_context"), dict)
                    else {}
                )
                product_cards = [
                    card
                    for presentation in rendered.product_presentations
                    if isinstance(presentation, dict)
                    for card in presentation.get("cards") or []
                    if isinstance(card, dict)
                ]
                emit(
                    "products_presented_from_choice",
                    **promo_event_values,
                    tire_size=(
                        promo_runtime_context.get("trusted_tire_size")
                        or next(
                            (
                                card.get("tire_size")
                                for card in product_cards
                                if str(card.get("tire_size") or "").strip()
                            ),
                            "",
                        )
                    ),
                    details={
                        "product_presentation_refs": [
                            item.get("presentation_ref")
                            for item in rendered.product_presentations
                            if isinstance(item, dict)
                        ],
                        "product_card_count": len(product_cards),
                        "product_refs": list(
                            dict.fromkeys(
                                str(card.get("card_ref") or card.get("item_ref") or card.get("product_id") or "")
                                for card in product_cards
                                if str(
                                    card.get("card_ref")
                                    or card.get("item_ref")
                                    or card.get("product_id")
                                    or ""
                                )
                            )
                        )[:8],
                        "product_ids": list(
                            dict.fromkeys(
                                str(card.get("product_id") or "")
                                for card in product_cards
                                if str(card.get("product_id") or "")
                            )
                        )[:8],
                        "brands": list(
                            dict.fromkeys(
                                str(card.get("brand") or "")
                                for card in product_cards
                                if str(card.get("brand") or "")
                            )
                        )[:8],
                    },
                )
    if choice_context:
        valid = str(choice_context.get("validation_status") or "") == "valid"
        choice_type = str(choice_context.get("choice_type") or "price_category")
        surface_type = (
            "price_category_choices"
            if choice_type == "price_category"
            else "product_choices"
            if choice_type == "product_selection"
            else f"{choice_type}_choices"
        )
        choice_details = {
            "validation_status": choice_context.get("validation_status"),
            "surface_type": surface_type,
            "surface_ref": choice_context.get("presentation_ref"),
            "presentation_ref": choice_context.get("presentation_ref"),
            "choice_type": choice_type,
            "choice_ref": choice_context.get("choice_ref"),
            "event_id": request.channel_event_id or request.message_id,
            "idempotency_key": request.idempotency_key,
            "choice_code": choice_context.get("choice_code"),
            "label": choice_context.get("label"),
            "level": choice_context.get("level"),
            "parent_code": choice_context.get("parent_code"),
            "province_code": choice_context.get("province_code"),
            "province_label": choice_context.get("province_label"),
            "source": choice_context.get("source"),
            "source_version": choice_context.get("source_version"),
            "card_ref": choice_context.get("card_ref"),
            "item_ref": choice_context.get("item_ref"),
            "product_id": choice_context.get("product_id"),
            "brand": choice_context.get("brand"),
            "deal_price_line": choice_context.get("deal_price_line"),
            "selection_kind": choice_context.get("selection_kind"),
            "slot_ref": choice_context.get("slot_ref"),
            "date": choice_context.get("date"),
            "time_text": choice_context.get("time_text"),
            "time_window": choice_context.get("time_window"),
            "availability_status": choice_context.get("availability_status"),
            "option_id": choice_context.get("option_id"),
            "payment_type_id": choice_context.get("payment_type_id"),
            "payment_option_id": choice_context.get("payment_option_id"),
            "service_path": choice_context.get("service_path"),
            "product_brand": choice_context.get("product_brand"),
        }
        emit(
            "choice_clicked" if valid else "choice_rejected",
            surface_type=surface_type,
            surface_ref=choice_context.get("presentation_ref"),
            choice_type=choice_type,
            choice_ref=choice_context.get("choice_ref"),
            category=choice_context.get("category"),
            brand=choice_context.get("brand"),
            tire_size=choice_context.get("tire_size"),
            position=choice_context.get("position") or 0,
            details=choice_details,
        )
        if valid and delivery_status == "success":
            emit(
                "choice_response_delivered",
                surface_type=surface_type,
                surface_ref=choice_context.get("presentation_ref"),
                choice_type=choice_type,
                choice_ref=choice_context.get("choice_ref"),
                category=choice_context.get("category"),
                brand=choice_context.get("brand"),
                tire_size=choice_context.get("tire_size"),
                details=choice_details,
            )
            if rendered.product_presentations:
                emit(
                    "products_presented_from_choice",
                    surface_type=surface_type,
                    surface_ref=choice_context.get("presentation_ref"),
                    choice_type=choice_type,
                    choice_ref=choice_context.get("choice_ref"),
                    category=choice_context.get("category"),
                    tire_size=choice_context.get("tire_size"),
                    details={
                        "product_presentation_refs": [
                            item.get("presentation_ref")
                            for item in rendered.product_presentations
                            if isinstance(item, dict)
                        ]
                    },
                )


def _rendered_has_tracked_choice_token(
    rendered: RuntimeV7ChannelRender,
    *,
    prefix: str,
) -> bool:
    """Return whether the delivered card payload contains a tracked choice token."""

    expected = str(prefix or "")
    if not expected:
        return False
    for message in rendered.content_messages:
        if not isinstance(message, dict) or message.get("type") != "cards":
            continue
        for element in message.get("elements") or []:
            if not isinstance(element, dict):
                continue
            for button in element.get("buttons") or []:
                if not isinstance(button, dict):
                    continue
                for action in button.get("actions") or []:
                    if not isinstance(action, dict):
                        continue
                    if str(action.get("field_name") or "") != "promo_selected_id":
                        continue
                    if str(action.get("value") or "").startswith(expected):
                        return True
    return False


def _safe_enqueue_analytics(analytics_gateway: Any, method_name: str, payload: Dict[str, Any]) -> bool:
    method = getattr(analytics_gateway, method_name, None)
    if not callable(method):
        return False
    method(_jsonable(payload))
    return True


def _safe_dispatch_normalized_analytics(analytics_gateway: Any) -> bool:
    """Start the completed turn's normalized writes without blocking delivery."""

    method = getattr(analytics_gateway, "flush_normalized_async", None)
    if not callable(method):
        return False
    try:
        method()
    except Exception as exc:
        logger.warning(
            "Runtime normalized analytics dispatch failed error=%s",
            exc,
        )
        return False
    return True


def _qualification_interaction_context(
    request: RuntimeV7APIRequest,
    turn: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return tracked-action identifiers that can explain qualification later."""

    flow = request.flow_context if isinstance(request.flow_context, Mapping) else {}
    choice = flow.get("choice_action_runtime_context")
    if not isinstance(choice, Mapping):
        choice = flow.get("choice_action_context")
    promo = flow.get("promo_action_tracking_context")
    if not isinstance(promo, Mapping):
        promo = flow.get("promo_action_runtime_context")
    output: Dict[str, Any] = {}
    if isinstance(choice, Mapping):
        output["choice"] = dict(choice)
    if isinstance(promo, Mapping):
        output["promo"] = dict(promo)
    packet = turn.get("interaction_packet") if isinstance(turn, Mapping) else {}
    events = packet.get("events") if isinstance(packet, Mapping) else []
    if isinstance(events, list) and events:
        latest = events[-1]
        if isinstance(latest, Mapping):
            output[
                "promo"
                if str(latest.get("source") or "") == "promo_action"
                else "choice"
            ] = dict(latest)
    return output


def _runtime_v7_request_payload(request: RuntimeV7APIRequest) -> Dict[str, Any]:
    return _compact_json(
        {
            "user_text": request.user_text,
            "message_id": request.message_id,
            "message_id_source": request.message_id_source,
            "idempotency_key": request.idempotency_key,
            "channel_user_id": request.channel_user_id,
            "channel": request.channel,
            "channel_subtype": request.channel_subtype,
            "channel_event_id": request.channel_event_id,
            "channel_event_ts": request.channel_event_ts,
            "request_time": request.request_time,
            "reset": request.reset,
            "delivery_mode": request.delivery_mode,
            "normalized_payload": request.normalized_payload,
            "flow_context": request.flow_context,
        }
    )


def _runtime_v7_final_response(
    rendered: RuntimeV7ChannelRender,
    *,
    delivery_result: Dict[str, Any],
) -> Dict[str, Any]:
    return _compact_json(
        {
            "response": rendered.response,
            "content_messages": rendered.content_messages,
            "images": rendered.images,
            "payment": rendered.payment,
            "text": rendered.text,
            "delivery_result": delivery_result,
        }
    )


def _compact_llm_span(call: Dict[str, Any], *, index: int) -> Dict[str, Any]:
    model_output = call.get("model_output") if isinstance(call.get("model_output"), dict) else {}
    usage_summary = call.get("usage_summary") if isinstance(call.get("usage_summary"), dict) else {}
    tool_calls = [item for item in (call.get("tool_calls") or []) if isinstance(item, dict)]
    return _compact_json(
        {
            "span_index": index,
            "component": call.get("component") or "main_tool_loop",
            "round": call.get("round"),
            **(
                {"attempt_kind": call.get("attempt_kind")}
                if call.get("attempt_kind")
                else {}
            ),
            **(
                {"repair_reason": call.get("repair_reason")}
                if call.get("repair_reason")
                else {}
            ),
            **(
                {"violation_types": call.get("violation_types")}
                if call.get("violation_types")
                else {}
            ),
            "model": call.get("model") or model_output.get("model"),
            "provider": call.get("provider") or model_output.get("provider"),
            "finish_reason": call.get("finish_reason") or model_output.get("finish_reason"),
            "latency_ms": call.get("latency_ms"),
            "provider_call_count": call.get("provider_call_count") or 1,
            "metered_provider_call_count": call.get(
                "metered_provider_call_count"
            ),
            "usage_summary": usage_summary,
            "cache_summary": _llm_call_cache_summary(call),
            "tool_call_count": len(tool_calls),
            "tool_names": [_tool_call_name(item) for item in tool_calls],
            "tool_choice": call.get("tool_choice"),
            "response_format": call.get("response_format"),
            "request_cache": call.get("request_cache"),
            "cache_guard_events": call.get("cache_guard_events"),
            "transport_attempt_count": call.get("transport_attempt_count") or 1,
            "transport_retry_events": call.get("transport_retry_events") or [],
        }
    )


def _llm_call_cache_summary(call: Dict[str, Any]) -> Dict[str, Any]:
    request_cache = call.get("request_cache") if isinstance(call.get("request_cache"), dict) else {}
    usage_summary = call.get("usage_summary") if isinstance(call.get("usage_summary"), dict) else {}
    cache_guard_events = [item for item in (call.get("cache_guard_events") or []) if isinstance(item, dict)]
    return _compact_json(
        {
            "explicit_cache_enabled": bool(request_cache.get("enabled")) if request_cache else False,
            "strategy": request_cache.get("strategy"),
            "ttl": request_cache.get("ttl"),
            "skipped_reason": request_cache.get("skipped_reason"),
            "provider_mode": request_cache.get("provider_mode"),
            "marked_message_indexes": request_cache.get("marked_message_indexes") or [],
            "tool_schemas_in_cache_scope": bool(request_cache.get("tool_schemas_in_cache_scope")),
            "cache_read_input_tokens": _int_or_none(usage_summary.get("cache_read_input_tokens")),
            "uncached_prompt_tokens": _int_or_none(usage_summary.get("uncached_prompt_tokens")),
            "cache_hit_rate": usage_summary.get("cache_hit_rate"),
            "cache_guard_event_count": len(cache_guard_events),
        }
    )


def _compact_tool_call_record(tool_result: Dict[str, Any], *, index: int) -> Dict[str, Any]:
    compact_result = tool_result.get("result") if isinstance(tool_result.get("result"), dict) else {}
    full_result = tool_result.get("full_result") if isinstance(tool_result.get("full_result"), dict) else {}
    source = full_result or compact_result
    error = _tool_error_message(tool_result)
    presentation = _presentation_from_tool_result(tool_result)
    return _compact_json(
        {
            "call_index": index,
            "tool_call_id": tool_result.get("tool_call_id") or tool_result.get("id"),
            "tool_name": tool_result.get("name"),
            "status": source.get("status") if isinstance(source, dict) else "",
            "ok": not _tool_failed(tool_result),
            "error": error,
            "latency_ms": tool_result.get("latency_ms"),
            "artifact_id": _artifact_id_from_tool_result(tool_result),
            "summary_context": _tool_summary_context(tool_result),
            "presentation": presentation,
        }
    )


def _tool_summary_context(tool_result: Dict[str, Any]) -> Dict[str, Any]:
    compact_result = tool_result.get("result") if isinstance(tool_result.get("result"), dict) else {}
    full_result = tool_result.get("full_result") if isinstance(tool_result.get("full_result"), dict) else {}
    source = full_result or compact_result
    fields = [
        "status",
        "reason",
        "message",
        "error_type",
        "selected_ref",
        "observation_ref",
        "presentation_ref",
        "payment_request_ref",
        "order_payload_ref",
        "order_id",
        "order_no",
        "availability_status",
    ]
    return _compact_json({key: source.get(key) for key in fields if isinstance(source, dict) and source.get(key) not in (None, "", [], {})})


def _tool_call_name(tool_call: Dict[str, Any]) -> str:
    function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
    return _text(tool_call.get("name") or function.get("name"))


def _presentation_from_tool_result(tool_result: Dict[str, Any]) -> Dict[str, Any]:
    for key in ("presentation", "presentation_surface", "render_surface"):
        value = tool_result.get(key)
        if isinstance(value, dict) and value:
            return _compact_json(value)
    for result_key in ("result", "full_result"):
        result = tool_result.get(result_key)
        if not isinstance(result, dict):
            continue
        for key in ("presentation", "presentation_surface", "render_surface"):
            value = result.get(key)
            if isinstance(value, dict) and value:
                return _compact_json(value)
    return {}


def _artifact_id_from_tool_result(tool_result: Dict[str, Any]) -> str:
    keys = ("observation_ref", "presentation_ref", "payment_request_ref", "order_payload_ref", "order_id", "order_no")
    for key in keys:
        value = tool_result.get(key)
        if value not in (None, "", [], {}):
            return _text(value)
    for result_key in ("result", "full_result"):
        result = tool_result.get(result_key)
        if not isinstance(result, dict):
            continue
        for key in keys:
            value = result.get(key)
            if value not in (None, "", [], {}):
                return _text(value)
    return ""


def _runtime_v7_error_rows(tool_results: Sequence[Dict[str, Any]], delivery_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for tool_result in tool_results:
        if not _tool_failed(tool_result):
            continue
        rows.append(
            {
                "stage": "tool",
                "tool_name": tool_result.get("name"),
                "error": _tool_error_message(tool_result),
            }
        )
    delivery_error = _delivery_error_type(delivery_result)
    if delivery_error:
        rows.append(
            {
                "stage": "delivery",
                "error_type": delivery_error,
                "error": _delivery_error_message(delivery_result),
            }
        )
    return _compact_json(rows)


def _tool_failed(tool_result: Dict[str, Any]) -> bool:
    compact_result = tool_result.get("result") if isinstance(tool_result.get("result"), dict) else {}
    full_result = tool_result.get("full_result") if isinstance(tool_result.get("full_result"), dict) else {}
    source = full_result or compact_result
    status = _text(source.get("status") if isinstance(source, dict) else "").lower()
    if status in {"error", "failed", "exception", "timeout"}:
        return True
    if isinstance(source, dict) and any(source.get(key) not in (None, "", [], {}) for key in ("error", "error_type")):
        return True
    return False


def _tool_error_message(tool_result: Dict[str, Any]) -> str:
    compact_result = tool_result.get("result") if isinstance(tool_result.get("result"), dict) else {}
    full_result = tool_result.get("full_result") if isinstance(tool_result.get("full_result"), dict) else {}
    for source in (full_result, compact_result, tool_result):
        if not isinstance(source, dict):
            continue
        for key in ("error", "error_type", "reason", "message"):
            value = source.get(key)
            if value not in (None, "", [], {}):
                return _text(value)[:500]
    return ""


def _delivery_error_type(delivery_result: Dict[str, Any]) -> str:
    if not isinstance(delivery_result, dict):
        return ""
    status = _text(delivery_result.get("status")).lower()
    if status in {"error", "failed", "exception", "timeout"}:
        return _text(delivery_result.get("error_type") or status)
    if delivery_result.get("error_type") not in (None, "", [], {}):
        return _text(delivery_result.get("error_type"))
    return ""


def _delivery_error_message(delivery_result: Dict[str, Any]) -> str:
    if not isinstance(delivery_result, dict):
        return ""
    for key in ("error", "error_message", "reason", "message"):
        value = delivery_result.get(key)
        if value not in (None, "", [], {}):
            return _text(value)[:500]
    return ""


def _turn_latency_ms(
    turn_trace: Dict[str, Any],
    usage: Dict[str, Any],
    llm_calls: Sequence[Dict[str, Any]],
    tool_results: Sequence[Dict[str, Any]],
) -> Optional[int]:
    total = _int_or_none(usage.get("latency_ms"))
    if total is not None and total > 0:
        return total
    values: List[int] = []
    for item in list(llm_calls or []) + list(tool_results or []):
        value = _int_or_none(item.get("latency_ms"))
        if value is not None:
            values.append(value)
    spans = turn_trace.get("component_spans") if isinstance(turn_trace, dict) else []
    for span in spans or []:
        if not isinstance(span, dict):
            continue
        value = _int_or_none(span.get("latency_ms"))
        if value is not None:
            values.append(value)
    return sum(values) if values else None


def _first_llm_model(llm_calls: Sequence[Dict[str, Any]]) -> str:
    for call in llm_calls or []:
        model = call.get("model")
        if not model and isinstance(call.get("model_output"), dict):
            model = call["model_output"].get("model")
        if model:
            return _text(model)
    return ""


def _flow_stage_after(turn: Dict[str, Any], tagging_result: Dict[str, Any]) -> str:
    for key in ("flow_stage_after", "lead_status"):
        value = turn.get(key)
        if value not in (None, "", [], {}):
            return _text(value)
    tagging = tagging_result if isinstance(tagging_result, dict) else {}
    if tagging.get("moderate_intent"):
        return "moderate_intent"
    return ""


def _out_of_flow_signal(turn: Dict[str, Any]) -> str:
    capability = turn.get("capability_profile") if isinstance(turn.get("capability_profile"), dict) else {}
    cues = capability.get("advisory_cues") if isinstance(capability, dict) else []
    if isinstance(cues, list):
        for item in cues:
            if isinstance(item, dict) and item.get("type") in {"out_of_flow", "unsupported"}:
                return _text(item.get("type"))
    return ""


def _compact_json(value: Any, *, max_depth: int = 4, max_list_items: int = 20, max_dict_items: int = 80, max_string_chars: int = 1600) -> Any:
    value = _jsonable(value)
    if max_depth <= 0:
        if isinstance(value, (dict, list)):
            return {"truncated": True, "type": type(value).__name__}
        if isinstance(value, str) and len(value) > max_string_chars:
            return value[:max_string_chars] + "...[truncated]"
        return value
    if isinstance(value, dict):
        output: Dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_dict_items:
                output["_truncated_keys"] = max(0, len(value) - max_dict_items)
                break
            output[str(key)] = _compact_json(
                item,
                max_depth=max_depth - 1,
                max_list_items=max_list_items,
                max_dict_items=max_dict_items,
                max_string_chars=max_string_chars,
            )
        return output
    if isinstance(value, list):
        output = [
            _compact_json(
                item,
                max_depth=max_depth - 1,
                max_list_items=max_list_items,
                max_dict_items=max_dict_items,
                max_string_chars=max_string_chars,
            )
            for item in value[:max_list_items]
        ]
        if len(value) > max_list_items:
            output.append({"truncated_items": len(value) - max_list_items})
        return output
    if isinstance(value, str) and len(value) > max_string_chars:
        return value[:max_string_chars] + "...[truncated]"
    return value


def _nested_get(mapping: Dict[str, Any], *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    if not denominator:
        return None
    return round(float(numerator) / float(denominator), 4)


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        try:
            return _jsonable(value.to_dict())
        except Exception:
            pass
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump())
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _parse_datetime(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    candidates = [text]
    if text.endswith("Z"):
        candidates.append(text[:-1] + "+00:00")
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is not None:
                parsed = parsed.replace(tzinfo=None)
            return parsed
        except Exception:
            pass
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%m/%d/%y %H:%M", "%m/%d/%Y %H:%M"]:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass
    return None


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normalize_delivery_mode(value: str) -> str:
    mode = str(value or DEFAULT_DELIVERY_MODE).strip().lower()
    if mode in {"send", "direct", "send_content"}:
        return "send_content"
    if mode in {"send_and_return", "direct_and_return"}:
        return "send_and_return"
    return "return_only"


def _manychat_bubble_delay_ms() -> int:
    return _int_env_clamped(
        "RUNTIME_V7_MANYCHAT_BUBBLE_DELAY_MS",
        default=DEFAULT_MANYCHAT_BUBBLE_DELAY_MS,
        minimum=0,
        maximum=3000,
    )


def _manychat_bubble_delay_max_messages() -> int:
    return _int_env_clamped(
        "RUNTIME_V7_MANYCHAT_BUBBLE_DELAY_MAX_MESSAGES",
        default=DEFAULT_MANYCHAT_BUBBLE_DELAY_MAX_MESSAGES,
        minimum=1,
        maximum=12,
    )


def _int_env_clamped(name: str, *, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "")
    try:
        value = int(str(raw).strip()) if str(raw).strip() else int(default)
    except Exception:
        value = int(default)
    return max(minimum, min(maximum, value))


def _should_deliver_manychat_messages_sequentially(
    messages: Sequence[Dict[str, Any]],
    *,
    delay_ms: int,
    max_delayed_messages: int,
) -> bool:
    if delay_ms <= 0 or len(messages or []) <= 1 or max_delayed_messages <= 1:
        return False
    paced = list(messages or [])[:max_delayed_messages]
    return any(
        _should_delay_between_manychat_messages(previous, current)
        for previous, current in zip(paced, paced[1:])
    )


def _should_delay_between_manychat_messages(previous: Dict[str, Any], current: Dict[str, Any]) -> bool:
    return _manychat_message_type(previous) == "text" and _manychat_message_type(current) == "text"


def _manychat_message_type(message: Dict[str, Any]) -> str:
    if isinstance(message, dict):
        return str(message.get("type") or "").strip().lower()
    if isinstance(message, str):
        return "text"
    return ""


async def _send_manychat_content_with_bubble_delay(
    client: Any,
    messages: Sequence[Dict[str, Any]],
    *,
    channel_subtype: Optional[str],
    delay_ms: int,
    max_delayed_messages: int,
) -> Dict[str, Any]:
    normalized_messages = [message for message in list(messages or []) if message]
    paced_count = min(len(normalized_messages), max_delayed_messages)
    compact_results: List[Dict[str, Any]] = []
    delivered_count = 0
    delayed_gap_count = 0
    delay_seconds = delay_ms / 1000.0
    previous_message: Optional[Dict[str, Any]] = None

    for index, message in enumerate(normalized_messages[:paced_count]):
        if previous_message is not None and _should_delay_between_manychat_messages(previous_message, message):
            await asyncio.sleep(delay_seconds)
            delayed_gap_count += 1
        result = dict(await client.send_content([message], channel_subtype=channel_subtype) or {})
        compact_results.append(_compact_manychat_delivery_result(result, message_index=index))
        if result.get("status") != "success":
            return {
                "status": result.get("status") or "error",
                "sequential_delivery": True,
                "message_count": len(normalized_messages),
                "delivered_message_count": delivered_count,
                "partial_delivery": delivered_count > 0,
                "failed_message_index": index,
                "bubble_delay_ms": delay_ms,
                "delayed_gap_count": delayed_gap_count,
                "delivery_results": compact_results,
            }
        delivered_count += 1
        previous_message = message

    tail = normalized_messages[paced_count:]
    if tail:
        result = dict(await client.send_content(tail, channel_subtype=channel_subtype) or {})
        compact_results.append(_compact_manychat_delivery_result(result, message_index=paced_count, message_count=len(tail)))
        if result.get("status") != "success":
            return {
                "status": result.get("status") or "error",
                "sequential_delivery": True,
                "message_count": len(normalized_messages),
                "delivered_message_count": delivered_count,
                "partial_delivery": delivered_count > 0,
                "failed_message_index": paced_count,
                "bubble_delay_ms": delay_ms,
                "delayed_gap_count": delayed_gap_count,
                "delivery_results": compact_results,
            }
        delivered_count += len(tail)

    return {
        "status": "success",
        "sequential_delivery": True,
        "message_count": len(normalized_messages),
        "delivered_message_count": delivered_count,
        "bubble_delay_ms": delay_ms,
        "delayed_gap_count": delayed_gap_count,
        "delivery_results": compact_results,
    }


def _compact_manychat_delivery_result(
    result: Dict[str, Any],
    *,
    message_index: int,
    message_count: int = 1,
) -> Dict[str, Any]:
    compact = {
        "message_index": message_index,
        "message_count": message_count,
        "status": result.get("status"),
    }
    for key in ("status_code", "message", "error", "function", "timestamp", "channel_user_id"):
        value = result.get(key)
        if value not in (None, "", [], {}):
            compact[key] = value
    return compact


def _metadata(trace_id: str, component: str) -> Dict[str, str]:
    return {
        "business_unit": "gulong",
        "channel": "manychat",
        "component": component,
        "trace_id": trace_id,
        "prompt_version": "runtime_v7",
        "tool_policy_version": "runtime_v7",
        "renderer_version": "runtime_v7",
    }


def _empty_to_none(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _unique(values: Sequence[str]) -> List[str]:
    seen = set()
    output: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output
