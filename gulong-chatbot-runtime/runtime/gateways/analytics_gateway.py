"""Analytics gateway interfaces for runtime (best-effort logging)."""

from __future__ import annotations

from collections import deque
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Optional, Protocol

from configs.log_utils import get_logger

from runtime.shared.analytics_schema import (
    assistant_log_schema,
    debug_log_schema,
    error_log_schema,
    followup_event_log_schema,
    interaction_event_log_schema,
    llm_span_log_schema,
    request_attempt_log_schema,
    request_state_log_schema,
    slots_log_schema,
    tool_call_log_schema,
    tool_output_log_schema,
    turn_fact_log_schema,
    turn_trace_log_schema,
)


class AnalyticsGateway(Protocol):
    """Best-effort analytics logger interface."""

    def enqueue_assistant_log(self, payload: Dict[str, object]) -> None:
        ...

    def enqueue_tool_output_log(self, payload: Dict[str, object]) -> None:
        ...

    def enqueue_error_log(self, payload: Dict[str, object]) -> None:
        ...

    def enqueue_slots_log(self, payload: Dict[str, object]) -> None:
        ...

    def enqueue_debug_log(self, payload: Dict[str, object]) -> None:
        ...

    def enqueue_request_state_log(self, payload: Dict[str, object]) -> None:
        ...

    def enqueue_request_attempt_log(self, payload: Dict[str, object]) -> None:
        ...

    def enqueue_turn_trace_log(self, payload: Dict[str, object]) -> None:
        ...

    def enqueue_turn_fact_log(self, payload: Dict[str, object]) -> None:
        ...

    def enqueue_llm_span_log(self, payload: Dict[str, object]) -> None:
        ...

    def enqueue_tool_call_log(self, payload: Dict[str, object]) -> None:
        ...

    def enqueue_followup_event_log(self, payload: Dict[str, object]) -> None:
        ...

    def enqueue_interaction_event_log(self, payload: Dict[str, object]) -> None:
        ...

    def flush_normalized_async(self) -> None:
        ...


@dataclass
class MemoryAnalyticsGateway:
    """
    In-memory analytics logger for local testing or fallback use.

    Stores payloads in bounded deques to avoid unbounded memory growth.
    """

    max_items: int = 2000
    assistant_logs: Deque[Dict[str, object]] = field(default_factory=deque)
    tool_output_logs: Deque[Dict[str, object]] = field(default_factory=deque)
    error_logs: Deque[Dict[str, object]] = field(default_factory=deque)
    slots_logs: Deque[Dict[str, object]] = field(default_factory=deque)
    debug_logs: Deque[Dict[str, object]] = field(default_factory=deque)
    request_state_logs: Deque[Dict[str, object]] = field(default_factory=deque)
    request_attempt_logs: Deque[Dict[str, object]] = field(default_factory=deque)
    turn_trace_logs: Deque[Dict[str, object]] = field(default_factory=deque)
    turn_fact_logs: Deque[Dict[str, object]] = field(default_factory=deque)
    llm_span_logs: Deque[Dict[str, object]] = field(default_factory=deque)
    tool_call_logs: Deque[Dict[str, object]] = field(default_factory=deque)
    followup_event_logs: Deque[Dict[str, object]] = field(default_factory=deque)
    interaction_event_logs: Deque[Dict[str, object]] = field(default_factory=deque)

    def enqueue_assistant_log(self, payload: Dict[str, object]) -> None:
        self._append(self.assistant_logs, payload)

    def enqueue_tool_output_log(self, payload: Dict[str, object]) -> None:
        self._append(self.tool_output_logs, payload)

    def enqueue_error_log(self, payload: Dict[str, object]) -> None:
        self._append(self.error_logs, payload)

    def enqueue_slots_log(self, payload: Dict[str, object]) -> None:
        self._append(self.slots_logs, payload)

    def enqueue_debug_log(self, payload: Dict[str, object]) -> None:
        self._append(self.debug_logs, payload)

    def enqueue_request_state_log(self, payload: Dict[str, object]) -> None:
        self._append(self.request_state_logs, payload)

    def enqueue_request_attempt_log(self, payload: Dict[str, object]) -> None:
        self._append(self.request_attempt_logs, payload)

    def enqueue_turn_trace_log(self, payload: Dict[str, object]) -> None:
        self._append(self.turn_trace_logs, payload)

    def enqueue_turn_fact_log(self, payload: Dict[str, object]) -> None:
        self._append(self.turn_fact_logs, payload)

    def enqueue_llm_span_log(self, payload: Dict[str, object]) -> None:
        self._append(self.llm_span_logs, payload)

    def enqueue_tool_call_log(self, payload: Dict[str, object]) -> None:
        self._append(self.tool_call_logs, payload)

    def enqueue_followup_event_log(self, payload: Dict[str, object]) -> None:
        self._append(self.followup_event_logs, payload)

    def enqueue_interaction_event_log(self, payload: Dict[str, object]) -> None:
        self._append(self.interaction_event_logs, payload)

    def flush_normalized_async(self) -> None:
        return None

    def _append(self, queue: Deque[Dict[str, object]], payload: Dict[str, object]) -> None:
        queue.append(payload)
        while len(queue) > self.max_items:
            queue.popleft()

    def last_assistant_log(self) -> Optional[Dict[str, object]]:
        return self.assistant_logs[-1] if self.assistant_logs else None

    def last_tool_output_log(self) -> Optional[Dict[str, object]]:
        return self.tool_output_logs[-1] if self.tool_output_logs else None

    def last_error_log(self) -> Optional[Dict[str, object]]:
        return self.error_logs[-1] if self.error_logs else None

    def last_slots_log(self) -> Optional[Dict[str, object]]:
        return self.slots_logs[-1] if self.slots_logs else None

    def last_debug_log(self) -> Optional[Dict[str, object]]:
        return self.debug_logs[-1] if self.debug_logs else None

    def last_turn_trace_log(self) -> Optional[Dict[str, object]]:
        return self.turn_trace_logs[-1] if self.turn_trace_logs else None


@dataclass
class BigQueryAnalyticsGateway:
    """
    BigQuery-backed analytics gateway with batch writes.

    Uses a BigQueryBatchWriter for best-effort, non-blocking append ingestion.
    Runtime analytics tables are event/audit logs; current-state semantics
    should be derived downstream instead of making request workers issue MERGEs
    or wait for synchronous table flushes.
    """

    writer: Any
    fallback: Optional[MemoryAnalyticsGateway] = None
    _target_logged: bool = False

    _INT_FIELDS = {
        "assistant_log": {"elapsed_ms", "llm_calls", "tool_calls", "tool_failures", "tool_rounds"},
        "request_state_log": {"attempt_count", "tokens_in", "tokens_out"},
        "request_attempt_log": {"attempt_no", "latency_ms", "backoff_seconds", "tokens_in", "tokens_out"},
        "turn_trace_log": {"turn_latency_ms", "llm_calls", "tool_calls", "tool_failures"},
        "turn_fact_log": {
            "turn_latency_ms",
            "tokens_in",
            "tokens_out",
            "tokens_total",
            "llm_calls",
            "tool_calls",
            "tool_failures",
            "response_bubble_count",
        },
        "llm_span_log": {"span_index", "tokens_in", "tokens_out", "latency_ms"},
        "tool_call_log": {"call_index", "latency_ms"},
        "followup_event_log": {"tokens_in", "tokens_out", "tokens_total", "latency_ms"},
        "interaction_event_log": {"position"},
    }
    _NORMALIZED_TABLES = {
        "request_state_log",
        "request_attempt_log",
        "turn_trace_log",
        "turn_fact_log",
        "llm_span_log",
        "tool_call_log",
        "followup_event_log",
        "interaction_event_log",
    }
    _RUNTIME_METADATA_ENV = {
        "service_environment": ("SERVICE_ENVIRONMENT",),
        "runtime_host": ("RUNTIME_HOST", "K_SERVICE"),
        "release_version": ("RELEASE_VERSION",),
        "git_sha": ("GIT_SHA",),
    }

    def enqueue_assistant_log(self, payload: Dict[str, object]) -> None:
        payload = self._normalize_payload("assistant_log", payload)
        self._log_target_once("assistant_log")
        self.writer.enqueue(
            "assistant_log",
            [self._with_row_id("assistant_log", payload)],
            schema=assistant_log_schema(),
            key_columns=None,
        )
        if self.fallback:
            self.fallback.enqueue_assistant_log(payload)

    def enqueue_tool_output_log(self, payload: Dict[str, object]) -> None:
        payload = self._normalize_payload("tool_output_log", payload)
        self._log_target_once("tool_output_log")
        self.writer.enqueue(
            "tool_output_log",
            [self._with_row_id("tool_output_log", payload)],
            schema=tool_output_log_schema(),
            key_columns=None,
        )
        if self.fallback:
            self.fallback.enqueue_tool_output_log(payload)

    def enqueue_error_log(self, payload: Dict[str, object]) -> None:
        payload = self._normalize_payload("error_log", payload)
        self._log_target_once("error_log")
        self.writer.enqueue(
            "error_log",
            [self._with_row_id("error_log", payload)],
            schema=error_log_schema(),
            key_columns=None,
        )
        if self.fallback:
            self.fallback.enqueue_error_log(payload)

    def enqueue_slots_log(self, payload: Dict[str, object]) -> None:
        payload = self._normalize_payload("slots_log", payload)
        self._log_target_once("slots_log")
        self.writer.enqueue(
            "slots_log",
            [self._with_row_id("slots_log", payload)],
            schema=slots_log_schema(),
            key_columns=None,
        )
        if self.fallback:
            self.fallback.enqueue_slots_log(payload)

    def enqueue_debug_log(self, payload: Dict[str, object]) -> None:
        payload = self._normalize_payload("debug_log", payload)
        self._log_target_once("debug_log")
        self.writer.enqueue(
            "debug_log",
            [self._with_row_id("debug_log", payload)],
            schema=debug_log_schema(),
            key_columns=None,
        )
        if self.fallback:
            self.fallback.enqueue_debug_log(payload)

    def enqueue_request_state_log(self, payload: Dict[str, object]) -> None:
        self._enqueue_normalized("request_state_log", payload, request_state_log_schema)
        if self.fallback:
            self.fallback.enqueue_request_state_log(payload)

    def enqueue_request_attempt_log(self, payload: Dict[str, object]) -> None:
        self._enqueue_normalized("request_attempt_log", payload, request_attempt_log_schema)
        if self.fallback:
            self.fallback.enqueue_request_attempt_log(payload)

    def enqueue_turn_trace_log(self, payload: Dict[str, object]) -> None:
        self._enqueue_normalized("turn_trace_log", payload, turn_trace_log_schema)
        if self.fallback:
            self.fallback.enqueue_turn_trace_log(payload)

    def enqueue_turn_fact_log(self, payload: Dict[str, object]) -> None:
        self._enqueue_normalized("turn_fact_log", payload, turn_fact_log_schema)
        if self.fallback:
            self.fallback.enqueue_turn_fact_log(payload)

    def enqueue_llm_span_log(self, payload: Dict[str, object]) -> None:
        self._enqueue_normalized("llm_span_log", payload, llm_span_log_schema)
        if self.fallback:
            self.fallback.enqueue_llm_span_log(payload)

    def enqueue_tool_call_log(self, payload: Dict[str, object]) -> None:
        self._enqueue_normalized("tool_call_log", payload, tool_call_log_schema)
        if self.fallback:
            self.fallback.enqueue_tool_call_log(payload)

    def enqueue_followup_event_log(self, payload: Dict[str, object]) -> None:
        self._enqueue_normalized("followup_event_log", payload, followup_event_log_schema)
        if self.fallback:
            self.fallback.enqueue_followup_event_log(payload)

    def enqueue_interaction_event_log(self, payload: Dict[str, object]) -> None:
        self._enqueue_normalized("interaction_event_log", payload, interaction_event_log_schema)
        if self.fallback:
            self.fallback.enqueue_interaction_event_log(payload)

    def _enqueue_normalized(self, table: str, payload: Dict[str, object], schema_loader: Any) -> None:
        payload = self._normalize_payload(table, payload)
        self._log_target_once(table)
        self.writer.enqueue(
            table,
            [self._with_row_id(table, payload)],
            schema=schema_loader(),
            key_columns=None,
        )

    def flush_normalized_async(self) -> None:
        """Dispatch each completed normalized-table batch without request I/O.

        A gateway/writer is currently scoped to one API request.  Waiting for
        its age timer therefore does not combine rows across customer turns and
        creates a container-replacement loss window.  Dispatching once after
        the turn is fully emitted preserves per-table batching (including all
        LLM spans/tool calls from the turn) without blocking delivery.
        """

        flush_async = getattr(self.writer, "flush_async", None)
        if not callable(flush_async):
            return
        logger = get_logger(__name__, level="INFO")
        for table in sorted(self._NORMALIZED_TABLES):
            try:
                flush_async(table)
            except Exception as exc:
                logger.warning(
                    "Runtime normalized analytics async dispatch failed table=%s error=%s",
                    table,
                    exc,
                )

    def _normalize_payload(self, table: str, payload: Dict[str, object]) -> Dict[str, object]:
        if not payload:
            return payload
        normalized = dict(payload)
        if table in self._NORMALIZED_TABLES:
            normalized = self._with_runtime_metadata(normalized)
        for key in self._INT_FIELDS.get(table, set()):
            if key in normalized:
                try:
                    normalized[key] = int(normalized[key])  # type: ignore[arg-type]
                except Exception:
                    normalized[key] = None
        return normalized

    def _with_runtime_metadata(self, payload: Dict[str, object]) -> Dict[str, object]:
        materialized = dict(payload)
        for field_name, env_names in self._RUNTIME_METADATA_ENV.items():
            current = materialized.get(field_name)
            if current not in (None, ""):
                continue
            for env_name in env_names:
                value = os.getenv(env_name)
                if value:
                    materialized[field_name] = value
                    break
        return materialized

    def _log_target_once(self, table: str) -> None:
        if self._target_logged:
            return
        logger = get_logger(__name__, level="INFO")
        dataset = None
        project = None
        try:
            config = getattr(self.writer, "_config", None)
            if config:
                dataset = getattr(config, "dataset_id", None)
                project = getattr(config, "project_id", None)
        except Exception:
            pass
        if dataset or project:
            logger.info("Analytics target: %s.%s.%s", project or "unknown", dataset or "unknown", table)
        self._target_logged = True

    def _with_row_id(self, table: str, payload: Dict[str, object]) -> Dict[str, object]:
        if payload.get("row_id"):
            return payload
        materialized = dict(payload)
        raw = dict(materialized)
        raw.pop("row_id", None)
        stable = json.dumps(raw, sort_keys=True, default=str, ensure_ascii=True)
        digest = hashlib.sha256(f"{table}:{stable}".encode("utf-8")).hexdigest()
        materialized["row_id"] = digest
        return materialized
