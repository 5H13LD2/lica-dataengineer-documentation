"""
Session storage interfaces for runtime.

This isolates persistence concerns from SessionsGateway so Firestore can be
swapped without changing slot/session logic.
"""

from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime
from dataclasses import dataclass
import functools
import gc
import hashlib
import hmac
import json
import os
import threading
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence

try:
    import resource
except ImportError:  # pragma: no cover - unavailable on Windows
    resource = None  # type: ignore[assignment]

from configs.config import ENV
from configs.log_utils import get_logger

try:
    from google.cloud import firestore  # type: ignore
    from google.oauth2 import service_account  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    firestore = None
    service_account = None

logger = get_logger(__file__, level="INFO")

_PROCESS_STARTED_MONOTONIC = time.monotonic()
_SAVE_ACTIVITY_LOCK = threading.Lock()
_ACTIVE_SAVE_COUNT = 0
_PEAK_ACTIVE_SAVE_COUNT = 0
_SAVE_OBSERVATION_SEQUENCE = 0
_FIRESTORE_RPC_TRACE_CONTEXT: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "runtime_v7_firestore_rpc_trace",
    default=None,
)
_FIRESTORE_RPC_OBSERVER_LOCK = threading.Lock()
_MAX_RPC_ATTEMPTS_RECORDED = 20
STRATEGY_STATE_FORMAT_NESTED_MAP_V1 = "nested_map_v1"
STRATEGY_STATE_FORMAT_CANONICAL_JSON_V1 = "canonical_json_v1"
STRATEGY_STATE_JSON_FIELD_V1 = "strategy_state_json_v1"
STRATEGY_STATE_ENCODING_FIELD = "strategy_state_encoding"
STRATEGY_STATE_SCHEMA_VERSION_FIELD = "strategy_state_schema_version"
STRATEGY_STATE_SHA256_FIELD = "strategy_state_sha256"
_STRATEGY_STATE_STORAGE_FIELDS = (
    STRATEGY_STATE_JSON_FIELD_V1,
    STRATEGY_STATE_ENCODING_FIELD,
    STRATEGY_STATE_SCHEMA_VERSION_FIELD,
    STRATEGY_STATE_SHA256_FIELD,
)


class StrategyStateStorageError(ValueError):
    """Reject invalid encoded session state without exposing its contents."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def normalize_strategy_state_format(value: Any) -> str:
    """Return one supported Firestore strategy-state storage format."""

    normalized = str(value or STRATEGY_STATE_FORMAT_NESTED_MAP_V1).strip().casefold()
    allowed = {
        STRATEGY_STATE_FORMAT_NESTED_MAP_V1,
        STRATEGY_STATE_FORMAT_CANONICAL_JSON_V1,
    }
    if normalized not in allowed:
        raise ValueError("unsupported Firestore strategy_state format")
    return normalized


def _canonical_strategy_state_json(value: Any) -> str:
    """Serialize the JSON-native strategy state deterministically and strictly."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise StrategyStateStorageError("strategy_state_not_json_native") from exc


def _prepare_session_payload_for_firestore(
    data: Mapping[str, Any],
    *,
    strategy_state_format: str,
) -> Dict[str, Any]:
    """Apply the configured strategy-state representation to a session payload."""

    payload = dict(data or {})
    storage_format = normalize_strategy_state_format(strategy_state_format)
    # Normal runtime payloads always carry this key. Missing-key payloads are
    # partial session updates and must not erase an existing representation.
    if "strategy_state" not in payload:
        return payload
    for field_name in _STRATEGY_STATE_STORAGE_FIELDS:
        payload.pop(field_name, None)
    if storage_format == STRATEGY_STATE_FORMAT_NESTED_MAP_V1:
        return payload

    encoded = _canonical_strategy_state_json(payload.pop("strategy_state"))
    payload[STRATEGY_STATE_JSON_FIELD_V1] = encoded
    payload[STRATEGY_STATE_ENCODING_FIELD] = (
        STRATEGY_STATE_FORMAT_CANONICAL_JSON_V1
    )
    payload[STRATEGY_STATE_SCHEMA_VERSION_FIELD] = 1
    payload[STRATEGY_STATE_SHA256_FIELD] = hashlib.sha256(
        encoded.encode("utf-8")
    ).hexdigest()
    return payload


def _add_strategy_state_representation_deletes(
    payload: Mapping[str, Any],
    *,
    strategy_state_format: str,
    delete_field: Any,
) -> Dict[str, Any]:
    """Atomically remove fields belonging to the non-authoritative format."""

    prepared = dict(payload or {})
    storage_format = normalize_strategy_state_format(strategy_state_format)
    if storage_format == STRATEGY_STATE_FORMAT_CANONICAL_JSON_V1:
        prepared["strategy_state"] = delete_field
        return prepared
    for field_name in _STRATEGY_STATE_STORAGE_FIELDS:
        prepared[field_name] = delete_field
    return prepared


def _restore_session_payload_from_firestore(data: Mapping[str, Any]) -> Dict[str, Any]:
    """Restore versioned scalar state to the stable in-memory session contract."""

    payload = dict(data or {})
    encoding = str(payload.get(STRATEGY_STATE_ENCODING_FIELD) or "").strip()
    has_scalar_metadata = bool(
        encoding
        or STRATEGY_STATE_JSON_FIELD_V1 in payload
        or STRATEGY_STATE_SCHEMA_VERSION_FIELD in payload
        or STRATEGY_STATE_SHA256_FIELD in payload
    )
    if has_scalar_metadata:
        if encoding != STRATEGY_STATE_FORMAT_CANONICAL_JSON_V1:
            raise StrategyStateStorageError("strategy_state_encoding_unknown")
        schema_version = payload.get(STRATEGY_STATE_SCHEMA_VERSION_FIELD)
        if schema_version != 1:
            raise StrategyStateStorageError("strategy_state_schema_unknown")
        raw = payload.get(STRATEGY_STATE_JSON_FIELD_V1)
        if not isinstance(raw, str):
            raise StrategyStateStorageError("strategy_state_json_missing")
        expected_hash = str(payload.get(STRATEGY_STATE_SHA256_FIELD) or "").strip()
        if not expected_hash:
            raise StrategyStateStorageError("strategy_state_hash_missing")
        actual_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(expected_hash, actual_hash):
            raise StrategyStateStorageError("strategy_state_hash_mismatch")
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise StrategyStateStorageError("strategy_state_json_invalid") from exc
        if decoded is not None and not isinstance(decoded, dict):
            raise StrategyStateStorageError("strategy_state_shape_invalid")
        for field_name in _STRATEGY_STATE_STORAGE_FIELDS:
            payload.pop(field_name, None)
        payload.pop("strategy_state", None)
        payload["strategy_state"] = decoded
        return payload

    legacy_state = payload.get("strategy_state")
    if "strategy_state" in payload and (
        legacy_state is None or isinstance(legacy_state, dict)
    ):
        return payload
    return payload


def _execution_snapshot() -> Dict[str, Any]:
    """Capture content-free CPU, GC, and scheduler counters for one process."""

    thread_clock = getattr(time, "thread_time", None)
    snapshot: Dict[str, Any] = {
        "process_cpu_s": time.process_time(),
        "thread_cpu_s": thread_clock() if callable(thread_clock) else 0.0,
        "gc_stats": [dict(item) for item in gc.get_stats()],
    }
    if resource is not None:
        try:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            snapshot["resource_usage"] = {
                key: float(getattr(usage, key, 0.0) or 0.0)
                for key in (
                    "ru_utime",
                    "ru_stime",
                    "ru_minflt",
                    "ru_majflt",
                    "ru_nvcsw",
                    "ru_nivcsw",
                )
            }
        except Exception:
            snapshot["resource_usage"] = {}
    return snapshot


def _execution_delta(started: Mapping[str, Any]) -> Dict[str, Any]:
    """Return non-negative execution deltas without exposing application data."""

    finished = _execution_snapshot()
    process_cpu_ms = max(
        (float(finished.get("process_cpu_s") or 0.0) - float(started.get("process_cpu_s") or 0.0))
        * 1000.0,
        0.0,
    )
    thread_cpu_ms = max(
        (float(finished.get("thread_cpu_s") or 0.0) - float(started.get("thread_cpu_s") or 0.0))
        * 1000.0,
        0.0,
    )
    before_gc = started.get("gc_stats") if isinstance(started.get("gc_stats"), list) else []
    after_gc = finished.get("gc_stats") if isinstance(finished.get("gc_stats"), list) else []
    gc_collections: list[int] = []
    gc_collected: list[int] = []
    for generation in range(3):
        before = before_gc[generation] if generation < len(before_gc) else {}
        after = after_gc[generation] if generation < len(after_gc) else {}
        before = before if isinstance(before, Mapping) else {}
        after = after if isinstance(after, Mapping) else {}
        gc_collections.append(
            max(int(after.get("collections") or 0) - int(before.get("collections") or 0), 0)
        )
        gc_collected.append(
            max(int(after.get("collected") or 0) - int(before.get("collected") or 0), 0)
        )
    before_usage = started.get("resource_usage")
    after_usage = finished.get("resource_usage")
    before_usage = before_usage if isinstance(before_usage, Mapping) else {}
    after_usage = after_usage if isinstance(after_usage, Mapping) else {}

    def usage_delta(key: str, *, scale: float = 1.0) -> float:
        """Calculate one non-negative process resource-counter delta."""
        return max(
            (float(after_usage.get(key) or 0.0) - float(before_usage.get(key) or 0.0))
            * scale,
            0.0,
        )

    return {
        "process_cpu_ms": round(process_cpu_ms, 3),
        "thread_cpu_ms": round(thread_cpu_ms, 3),
        "other_threads_cpu_ms": round(max(process_cpu_ms - thread_cpu_ms, 0.0), 3),
        "user_cpu_ms": round(usage_delta("ru_utime", scale=1000.0), 3),
        "system_cpu_ms": round(usage_delta("ru_stime", scale=1000.0), 3),
        "minor_page_faults": int(usage_delta("ru_minflt")),
        "major_page_faults": int(usage_delta("ru_majflt")),
        "voluntary_context_switches": int(usage_delta("ru_nvcsw")),
        "involuntary_context_switches": int(usage_delta("ru_nivcsw")),
        "gc_collections": gc_collections,
        "gc_collected": gc_collected,
    }


def _firestore_rpc_diagnostics_enabled() -> bool:
    """Enable private-client RPC observation only on non-live environments."""

    environment = str(ENV.get("SERVICE_ENVIRONMENT") or "").strip().casefold()
    if environment in {"live", "production", "prod"}:
        return False
    raw = str(ENV.get("RUNTIME_V7_FIRESTORE_RPC_DIAGNOSTICS") or "").strip()
    return raw.casefold() in {"1", "true", "yes", "on"}


def _firestore_rpc_status_code(exc: BaseException) -> str:
    """Return a bounded status name without exposing an exception message."""

    code = getattr(exc, "code", None)
    try:
        value = code() if callable(code) else code
    except Exception:
        value = None
    name = getattr(value, "name", None)
    if name:
        return str(name)[:80]
    text = str(value or "").strip()
    return text.rsplit(".", 1)[-1][:80] if text else ""


def _record_firestore_rpc_attempt(
    *,
    operation: str,
    elapsed_ms: float,
    outcome: str,
    error: Optional[BaseException] = None,
    execution: Optional[Mapping[str, Any]] = None,
) -> None:
    """Append one content-free raw RPC attempt to the active save trace."""

    context = _FIRESTORE_RPC_TRACE_CONTEXT.get()
    attempts = context.get("attempts") if isinstance(context, dict) else None
    if not isinstance(attempts, list) or len(attempts) >= _MAX_RPC_ATTEMPTS_RECORDED:
        return
    error_type = type(error).__name__[:80] if error else ""
    status_code = _firestore_rpc_status_code(error) if error else ""
    normalized_errors = {
        value.casefold().replace("_", "")
        for value in (status_code, error_type)
        if value
    }
    begin_retryable = {
        "deadlineexceeded",
        "internalservererror",
        "resourceexhausted",
        "serviceunavailable",
        "unavailable",
        "429",
        "500",
        "503",
        "504",
    }
    commit_retryable = {
        "resourceexhausted",
        "serviceunavailable",
        "unavailable",
        "429",
        "503",
    }
    gapic_retryable = bool(
        normalized_errors
        & (begin_retryable if operation == "begin_transaction" else commit_retryable)
    )
    attempt = {
        "operation": str(operation or "")[:40],
        "ordinal": len(attempts) + 1,
        "elapsed_ms": round(max(float(elapsed_ms), 0.0), 3),
        "outcome": str(outcome or "")[:20],
        "error_type": error_type,
        "status_code": status_code,
        "gapic_default_retryable": bool(error and gapic_retryable),
        "transactional_retryable": bool(
            error and normalized_errors & {"aborted", "409"}
        ),
    }
    execution = execution if isinstance(execution, Mapping) else {}
    for key in (
        "process_cpu_ms",
        "thread_cpu_ms",
        "other_threads_cpu_ms",
        "user_cpu_ms",
        "system_cpu_ms",
        "minor_page_faults",
        "major_page_faults",
        "voluntary_context_switches",
        "involuntary_context_switches",
    ):
        attempt[key] = execution.get(key, 0)
    attempt["gc_collections"] = list(execution.get("gc_collections") or [])[:3]
    attempt["gc_collected"] = list(execution.get("gc_collected") or [])[:3]
    attempts.append(attempt)
    activity = context.get("activity") if isinstance(context, dict) else {}
    activity = activity if isinstance(activity, dict) else {}
    log = logger.warning if error else logger.info
    log(
        "runtime_firestore_transport_attempt observation_id=%s operation=%s "
        "ordinal=%s elapsed_ms=%s outcome=%s error_type=%s status_code=%s "
        "gapic_default_retryable=%s transactional_retryable=%s process_id=%s "
        "instance_id_hash=%s active_saves_at_start=%s process_cpu_ms=%s "
        "thread_cpu_ms=%s other_threads_cpu_ms=%s gc_collections=%s "
        "gc_collected=%s voluntary_context_switches=%s "
        "involuntary_context_switches=%s",
        context.get("observation_id", ""),
        attempt["operation"],
        attempt["ordinal"],
        attempt["elapsed_ms"],
        attempt["outcome"],
        attempt["error_type"],
        attempt["status_code"],
        attempt["gapic_default_retryable"],
        attempt["transactional_retryable"],
        activity.get("process_id", 0),
        activity.get("instance_id_hash", ""),
        activity.get("active_saves_at_start", 0),
        attempt["process_cpu_ms"],
        attempt["thread_cpu_ms"],
        attempt["other_threads_cpu_ms"],
        attempt["gc_collections"],
        attempt["gc_collected"],
        attempt["voluntary_context_switches"],
        attempt["involuntary_context_switches"],
    )


def _install_firestore_rpc_observer(client: Any) -> str:
    """Wrap raw GAPIC targets so SDK retries retain their existing semantics.

    The generated Firestore callable applies retry and timeout decorators around
    its private ``_target``. Wrapping only that target observes every actual RPC
    attempt while leaving the callable's configured retry predicate, backoff,
    timeout, request, metadata, and result handling unchanged. Unsupported
    client versions fail open and report ``unsupported``.
    """

    if not _firestore_rpc_diagnostics_enabled():
        return "disabled"
    try:
        api = getattr(client, "_firestore_api")
        transport = getattr(api, "_transport")
        wrapped_methods = getattr(transport, "_wrapped_methods")
    except Exception:
        return "unsupported"

    installed = 0
    with _FIRESTORE_RPC_OBSERVER_LOCK:
        for operation in ("begin_transaction", "commit"):
            try:
                transport_method = getattr(transport, operation)
                wrapped = wrapped_methods[transport_method]
                if getattr(wrapped, "_runtime_v7_rpc_observed", False):
                    installed += 1
                    continue
                target = getattr(wrapped, "_target")

                @functools.wraps(target)
                def observed_target(
                    *args: Any,
                    _operation: str = operation,
                    _target: Any = target,
                    **kwargs: Any,
                ) -> Any:
                    """Record one raw Firestore RPC attempt without inspecting its data."""
                    started = time.perf_counter()
                    execution_started = _execution_snapshot()
                    try:
                        result = _target(*args, **kwargs)
                    except BaseException as exc:
                        _record_firestore_rpc_attempt(
                            operation=_operation,
                            elapsed_ms=(time.perf_counter() - started) * 1000.0,
                            outcome="error",
                            error=exc,
                            execution=_execution_delta(execution_started),
                        )
                        raise
                    _record_firestore_rpc_attempt(
                        operation=_operation,
                        elapsed_ms=(time.perf_counter() - started) * 1000.0,
                        outcome="success",
                        execution=_execution_delta(execution_started),
                    )
                    return result

                wrapped._target = observed_target
                wrapped._runtime_v7_rpc_observed = True
                installed += 1
            except Exception:
                continue
    return "active" if installed == 2 else "partial" if installed else "unsupported"


def _begin_save_activity() -> Dict[str, Any]:
    """Record bounded process identity and in-process save concurrency."""

    global _ACTIVE_SAVE_COUNT, _PEAK_ACTIVE_SAVE_COUNT, _SAVE_OBSERVATION_SEQUENCE
    with _SAVE_ACTIVITY_LOCK:
        _ACTIVE_SAVE_COUNT += 1
        _PEAK_ACTIVE_SAVE_COUNT = max(_PEAK_ACTIVE_SAVE_COUNT, _ACTIVE_SAVE_COUNT)
        _SAVE_OBSERVATION_SEQUENCE += 1
        active_at_start = _ACTIVE_SAVE_COUNT
        process_peak = _PEAK_ACTIVE_SAVE_COUNT
        observation_sequence = _SAVE_OBSERVATION_SEQUENCE
    instance_basis = str(os.getenv("HOSTNAME") or "local")
    return {
        "process_id": os.getpid(),
        "instance_id_hash": hashlib.sha256(
            instance_basis.encode("utf-8")
        ).hexdigest()[:12],
        "observation_id": f"{os.getpid()}-{observation_sequence}",
        "revision": str(os.getenv("K_REVISION") or "")[:100],
        "process_uptime_ms": round(
            max(time.monotonic() - _PROCESS_STARTED_MONOTONIC, 0.0) * 1000.0,
            3,
        ),
        "active_saves_at_start": active_at_start,
        "process_peak_active_saves": process_peak,
    }


def _end_save_activity(activity: Dict[str, Any]) -> None:
    """Close one process-local save activity counter without going negative."""

    global _ACTIVE_SAVE_COUNT
    with _SAVE_ACTIVITY_LOCK:
        activity["active_saves_before_end"] = _ACTIVE_SAVE_COUNT
        _ACTIVE_SAVE_COUNT = max(_ACTIVE_SAVE_COUNT - 1, 0)


class SessionStore:
    """Interface for session storage backends."""

    def is_available(self) -> bool:
        return True

    def last_save_diagnostics(self) -> Dict[str, Any]:
        """Return bounded diagnostics for the latest save on this thread."""

        return {}

    def last_load_diagnostics(self) -> Dict[str, Any]:
        """Return bounded representation diagnostics for the latest load."""

        return {}

    def load_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def save_user(self, user_id: str, data: Dict[str, Any]) -> None:
        raise NotImplementedError

    def load_session(self, user_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def save_session(self, user_id: str, session_id: str, data: Dict[str, Any]) -> None:
        raise NotImplementedError

    def save_session_cas(
        self,
        user_id: str,
        session_id: str,
        expected_revision: int,
        data: Dict[str, Any],
        request_id: Optional[str] = None,
    ) -> bool:
        raise NotImplementedError

    def acquire_session_lock(
        self,
        user_id: str,
        session_id: str,
        *,
        owner: str,
        lock_until: str,
        now: str,
    ) -> bool:
        raise NotImplementedError

    def release_session_lock(
        self,
        user_id: str,
        session_id: str,
        *,
        owner: str,
    ) -> None:
        raise NotImplementedError

    def record_interaction_event(
        self,
        user_id: str,
        session_id: str,
        event: Dict[str, Any],
        *,
        max_events: int,
    ) -> bool:
        """Record a tracked interaction before the main session lock."""

        raise NotImplementedError

    def load_interaction_events(
        self,
        user_id: str,
        session_id: str,
    ) -> List[Dict[str, Any]]:
        """Load the bounded pre-lock interaction inbox."""

        raise NotImplementedError

    def remove_interaction_events(
        self,
        user_id: str,
        session_id: str,
        *,
        event_ids: Sequence[str],
    ) -> None:
        """Remove resolved events from the pre-lock interaction inbox."""

        raise NotImplementedError


class MemorySessionStore(SessionStore):
    """In-memory session store (non-persistent, for tests/dev)."""

    def __init__(self) -> None:
        self._users: Dict[str, Dict[str, Any]] = {}
        self._sessions: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def load_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self._users.get(user_id)

    def save_user(self, user_id: str, data: Dict[str, Any]) -> None:
        self._users[user_id] = dict(data)

    def load_session(self, user_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        return (self._sessions.get(user_id) or {}).get(session_id)

    def save_session(self, user_id: str, session_id: str, data: Dict[str, Any]) -> None:
        with self._lock:
            if user_id not in self._sessions:
                self._sessions[user_id] = {}
            current = self._sessions[user_id].get(session_id) or {}
            payload = dict(data)
            if (
                "interaction_inbox_v1" not in payload
                and current.get("interaction_inbox_v1")
            ):
                payload["interaction_inbox_v1"] = [
                    dict(item)
                    for item in current["interaction_inbox_v1"]
                    if isinstance(item, dict)
                ]
            self._sessions[user_id][session_id] = payload

    def save_session_cas(
        self,
        user_id: str,
        session_id: str,
        expected_revision: int,
        data: Dict[str, Any],
        request_id: Optional[str] = None,
    ) -> bool:
        with self._lock:
            current = (self._sessions.get(user_id) or {}).get(session_id) or {}
            current_revision = int(current.get("revision") or 0)
            if current_revision != int(expected_revision):
                return False
            payload = dict(data or {})
            if (
                "interaction_inbox_v1" not in payload
                and current.get("interaction_inbox_v1")
            ):
                payload["interaction_inbox_v1"] = [
                    dict(item)
                    for item in current["interaction_inbox_v1"]
                    if isinstance(item, dict)
                ]
            payload["revision"] = current_revision + 1
            if request_id:
                payload["last_request_id"] = request_id
            if user_id not in self._sessions:
                self._sessions[user_id] = {}
            self._sessions[user_id][session_id] = payload
            return True

    def acquire_session_lock(
        self,
        user_id: str,
        session_id: str,
        *,
        owner: str,
        lock_until: str,
        now: str,
    ) -> bool:
        with self._lock:
            current = (self._sessions.get(user_id) or {}).get(session_id) or {}
            active_until = str(current.get("active_lock_until") or "")
            active_owner = str(current.get("active_lock_owner") or "")
            if active_until and _lock_is_active(active_until, now) and active_owner != owner:
                return False
            payload = dict(current or {})
            payload["active_lock_until"] = lock_until
            payload["active_lock_owner"] = owner
            if user_id not in self._sessions:
                self._sessions[user_id] = {}
            self._sessions[user_id][session_id] = payload
            return True

    def release_session_lock(
        self,
        user_id: str,
        session_id: str,
        *,
        owner: str,
    ) -> None:
        with self._lock:
            current = (self._sessions.get(user_id) or {}).get(session_id)
            if not current:
                return
            active_owner = str(current.get("active_lock_owner") or "")
            if active_owner and active_owner != owner:
                return
            current["active_lock_until"] = None
            current["active_lock_owner"] = None

    def record_interaction_event(
        self,
        user_id: str,
        session_id: str,
        event: Dict[str, Any],
        *,
        max_events: int,
    ) -> bool:
        with self._lock:
            current = (self._sessions.get(user_id) or {}).get(session_id) or {}
            payload = dict(current)
            payload["interaction_inbox_v1"] = _upsert_interaction_event(
                current.get("interaction_inbox_v1"),
                event,
                max_events=max_events,
            )
            if user_id not in self._sessions:
                self._sessions[user_id] = {}
            self._sessions[user_id][session_id] = payload
            return True

    def load_interaction_events(
        self,
        user_id: str,
        session_id: str,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            current = (self._sessions.get(user_id) or {}).get(session_id) or {}
            return [
                dict(item)
                for item in current.get("interaction_inbox_v1") or []
                if isinstance(item, dict)
            ]

    def remove_interaction_events(
        self,
        user_id: str,
        session_id: str,
        *,
        event_ids: Sequence[str],
    ) -> None:
        remove_ids = {
            str(item or "").strip()
            for item in event_ids
            if str(item or "").strip()
        }
        if not remove_ids:
            return
        with self._lock:
            current = (self._sessions.get(user_id) or {}).get(session_id)
            if not current:
                return
            current["interaction_inbox_v1"] = [
                dict(item)
                for item in current.get("interaction_inbox_v1") or []
                if isinstance(item, dict)
                and _interaction_event_id(item) not in remove_ids
            ]

    def reset(self) -> None:
        """Clear all in-memory users/sessions."""
        self._users.clear()
        self._sessions.clear()


@dataclass
class FirestoreSessionStoreConfig:
    """Configure Firestore collections and the authoritative state writer.

    ``strategy_state_format`` changes only the persisted representation. The
    store reader remains compatible with both supported formats so deployment
    and rollback can be staged independently from lazy document migration.
    """

    project_id: str
    users_collection: str
    sessions_subcollection: str
    credentials_json: Optional[str] = None
    enable_firestore: bool = True
    strategy_state_format: str = STRATEGY_STATE_FORMAT_NESTED_MAP_V1

    def __post_init__(self) -> None:
        """Reject an unknown format before any session read or write occurs."""

        self.strategy_state_format = normalize_strategy_state_format(
            self.strategy_state_format
        )


@dataclass
class SessionStoreConfig:
    """High-level store config for choosing provider."""

    provider: str
    firestore: FirestoreSessionStoreConfig
    postgres: Optional[Any] = None


class FirestoreSessionStore(SessionStore):
    """Firestore-backed session store (user_id keyed)."""

    def __init__(
        self,
        *,
        config: FirestoreSessionStoreConfig,
        firestore_client: Optional[Any] = None,
    ) -> None:
        self._config = config
        self._client = self._init_client(firestore_client)
        self._diagnostics_local = threading.local()
        self._rpc_observer_status = _install_firestore_rpc_observer(self._client)

    def is_available(self) -> bool:
        return self._client is not None

    def last_save_diagnostics(self) -> Dict[str, Any]:
        return dict(getattr(self._diagnostics_local, "last_save", {}) or {})

    def last_load_diagnostics(self) -> Dict[str, Any]:
        """Return content-free decode evidence for the latest session load."""

        return dict(getattr(self._diagnostics_local, "last_load", {}) or {})

    def load_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        if not self._client:
            return None
        ref = self._client.collection(self._config.users_collection).document(user_id)
        snapshot = ref.get()
        return snapshot.to_dict() if snapshot.exists else None

    def save_user(self, user_id: str, data: Dict[str, Any]) -> None:
        if not self._client:
            return
        ref = self._client.collection(self._config.users_collection).document(user_id)
        ref.set(dict(data), merge=True)

    def load_session(self, user_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        """Load one session and restore its stable in-memory state contract.

        Canonical scalar state is hash-validated and decoded here. Invalid
        canonical metadata fails closed with content-free diagnostics; callers
        never receive storage-only representation fields.
        """

        if not self._client:
            return None
        user_ref = self._client.collection(self._config.users_collection).document(user_id)
        session_ref = user_ref.collection(self._config.sessions_subcollection).document(session_id)
        snapshot = session_ref.get()
        if not snapshot.exists:
            self._diagnostics_local.last_load = {
                "exists": False,
                "decoded": False,
                "stored_strategy_state_format": "",
                "error_reason": "",
            }
            return None
        raw = snapshot.to_dict() or {}
        stored_format = str(
            raw.get(STRATEGY_STATE_ENCODING_FIELD)
            or (
                STRATEGY_STATE_FORMAT_NESTED_MAP_V1
                if "strategy_state" in raw
                else ""
            )
        )[:40]
        try:
            restored = _restore_session_payload_from_firestore(raw)
            self._diagnostics_local.last_load = {
                "exists": True,
                "decoded": True,
                "stored_strategy_state_format": stored_format,
                "schema_version": str(
                    raw.get(STRATEGY_STATE_SCHEMA_VERSION_FIELD) or ""
                )[:20],
                "stored_state_bytes": (
                    len(raw[STRATEGY_STATE_JSON_FIELD_V1].encode("utf-8"))
                    if isinstance(raw.get(STRATEGY_STATE_JSON_FIELD_V1), str)
                    else 0
                ),
                "error_reason": "",
            }
            return restored
        except StrategyStateStorageError as exc:
            self._diagnostics_local.last_load = {
                "exists": True,
                "decoded": False,
                "stored_strategy_state_format": stored_format,
                "schema_version": str(
                    raw.get(STRATEGY_STATE_SCHEMA_VERSION_FIELD) or ""
                )[:20],
                "stored_state_bytes": (
                    len(raw[STRATEGY_STATE_JSON_FIELD_V1].encode("utf-8"))
                    if isinstance(raw.get(STRATEGY_STATE_JSON_FIELD_V1), str)
                    else 0
                ),
                "error_reason": exc.reason[:80],
            }
            logger.error(
                "runtime_session_state_decode_failed error_type=%s reason=%s "
                "encoding=%s schema_version=%s",
                type(exc).__name__,
                exc.reason[:80],
                str(raw.get(STRATEGY_STATE_ENCODING_FIELD) or "")[:40],
                str(raw.get(STRATEGY_STATE_SCHEMA_VERSION_FIELD) or "")[:20],
            )
            raise

    def save_session(self, user_id: str, session_id: str, data: Dict[str, Any]) -> None:
        """Merge a session using the configured authoritative state format.

        Full state payloads atomically delete fields from the opposite
        representation. Partial payloads remain narrow merges and therefore do
        not migrate or erase existing strategy state.
        """

        if not self._client:
            return
        user_ref = self._client.collection(self._config.users_collection).document(user_id)
        session_ref = user_ref.collection(self._config.sessions_subcollection).document(session_id)
        try:
            payload = _prepare_session_payload_for_firestore(
                data,
                strategy_state_format=self._config.strategy_state_format,
            )
        except StrategyStateStorageError as exc:
            logger.error(
                "runtime_session_state_encode_failed error_type=%s reason=%s "
                "strategy_state_storage_format=%s",
                type(exc).__name__,
                exc.reason[:80],
                self._config.strategy_state_format,
            )
            raise
        if "strategy_state" in data and firestore is not None:
            payload = _add_strategy_state_representation_deletes(
                payload,
                strategy_state_format=self._config.strategy_state_format,
                delete_field=firestore.DELETE_FIELD,
            )
        session_ref.set(payload, merge=True)

    def save_session_cas(
        self,
        user_id: str,
        session_id: str,
        expected_revision: int,
        data: Dict[str, Any],
        request_id: Optional[str] = None,
    ) -> bool:
        """Persist one revisioned session atomically and reject stale state."""

        if not self._client or firestore is None:
            return False
        self._diagnostics_local.last_save = {}
        save_started = time.perf_counter()
        cpu_started = time.process_time()
        encode_started = time.perf_counter()
        try:
            prepared_data = _prepare_session_payload_for_firestore(
                data,
                strategy_state_format=self._config.strategy_state_format,
            )
        except StrategyStateStorageError as exc:
            strategy_state_encode_ms = (
                time.perf_counter() - encode_started
            ) * 1000.0
            self._diagnostics_local.last_save = {
                "storage_kind": "firestore",
                "write_mode": "transactional_full_document_cas",
                "saved": False,
                "error_type": type(exc).__name__,
                "error_reason": exc.reason[:80],
                "expected_revision": int(expected_revision),
                "attempt_count": 0,
                "total_ms": round(
                    (time.perf_counter() - save_started) * 1000.0,
                    3,
                ),
                "process_cpu_ms": round(
                    (time.process_time() - cpu_started) * 1000.0,
                    3,
                ),
                "strategy_state_encode_ms": round(
                    strategy_state_encode_ms,
                    3,
                ),
                "strategy_state_storage_format": (
                    self._config.strategy_state_format
                ),
            }
            logger.error(
                "runtime_session_state_encode_failed error_type=%s reason=%s "
                "strategy_state_storage_format=%s",
                type(exc).__name__,
                exc.reason[:80],
                self._config.strategy_state_format,
            )
            raise
        write_data = prepared_data
        if "strategy_state" in data:
            write_data = _add_strategy_state_representation_deletes(
                prepared_data,
                strategy_state_format=self._config.strategy_state_format,
                delete_field=firestore.DELETE_FIELD,
            )
        strategy_state_encode_ms = (
            time.perf_counter() - encode_started
        ) * 1000.0
        user_ref = self._client.collection(self._config.users_collection).document(user_id)
        session_ref = user_ref.collection(self._config.sessions_subcollection).document(session_id)
        txn = self._client.transaction()
        attempts: List[Dict[str, float]] = []
        rpc_attempts: List[Dict[str, Any]] = []

        @firestore.transactional  # type: ignore[misc]
        def _txn(transaction: Any) -> bool:
            attempt_started = time.perf_counter()
            read_started = time.perf_counter()
            snapshot = session_ref.get(transaction=transaction)
            read_ms = (time.perf_counter() - read_started) * 1000.0
            existing = snapshot.to_dict() if snapshot.exists else {}
            current_revision = int((existing or {}).get("revision") or 0)
            if current_revision != int(expected_revision):
                attempts.append(
                    {
                        "read_ms": read_ms,
                        "transaction_body_ms": (
                            time.perf_counter() - attempt_started
                        )
                        * 1000.0,
                    }
                )
                return False
            payload = dict(write_data or {})
            payload["revision"] = current_revision + 1
            if request_id:
                payload["last_request_id"] = request_id
            _clear_owned_session_lock(
                payload,
                existing=existing or {},
                owner=request_id,
            )
            _replace_session_document_in_transaction(
                transaction,
                session_ref,
                payload,
                exists=bool(snapshot.exists),
            )
            attempts.append(
                {
                    "read_ms": read_ms,
                    "transaction_body_ms": (
                        time.perf_counter() - attempt_started
                    )
                    * 1000.0,
                }
            )
            return True

        activity = _begin_save_activity()
        rpc_context_token = _FIRESTORE_RPC_TRACE_CONTEXT.set(
            {
                "observation_id": activity["observation_id"],
                "activity": activity,
                "attempts": rpc_attempts,
            }
        )
        error_type = ""
        saved = False
        try:
            saved = bool(_txn(txn))
        except Exception as exc:
            error_type = type(exc).__name__
            raise
        finally:
            _FIRESTORE_RPC_TRACE_CONTEXT.reset(rpc_context_token)
            storage_total_ms = (time.perf_counter() - save_started) * 1000.0
            process_cpu_ms = (time.process_time() - cpu_started) * 1000.0
            _end_save_activity(activity)
            diagnostic_started = time.perf_counter()
            diagnostics = _session_save_diagnostics(
                total_ms=storage_total_ms,
                attempts=attempts,
                rpc_attempts=rpc_attempts,
                runtime_context={
                    **activity,
                    "rpc_observer_status": self._rpc_observer_status,
                    "process_cpu_ms": process_cpu_ms,
                },
                payload=prepared_data,
                expected_revision=expected_revision,
                saved=saved,
                error_type=error_type,
                include_payload_sizes=(
                    storage_total_ms >= 2000.0
                    or bool(error_type)
                    or not saved
                ),
            )
            diagnostic_overhead_ms = (
                time.perf_counter() - diagnostic_started
            ) * 1000.0
            diagnostics["diagnostic_overhead_ms"] = round(
                diagnostic_overhead_ms,
                3,
            )
            diagnostics["instrumented_call_total_ms"] = round(
                storage_total_ms + diagnostic_overhead_ms,
                3,
            )
            diagnostics["strategy_state_encode_ms"] = round(
                strategy_state_encode_ms,
                3,
            )
            diagnostics["strategy_state_storage_format"] = (
                self._config.strategy_state_format
            )
            self._diagnostics_local.last_save = diagnostics
            if storage_total_ms >= 2000.0:
                logger.warning(
                    "runtime_session_save_slow total_ms=%s attempts=%s "
                    "read_ms=%s transaction_body_ms=%s "
                    "commit_retry_overhead_ms=%s commit_rpc_attempts=%s "
                    "commit_rpc_ms=%s commit_rpc_outcomes=%s "
                    "commit_rpc_status_codes=%s rpc_unattributed_ms=%s "
                    "commit_rpc_process_cpu_ms=%s commit_rpc_thread_cpu_ms=%s "
                    "commit_rpc_other_threads_cpu_ms=%s commit_rpc_gc_collections=%s "
                    "commit_rpc_gc_collected=%s "
                    "process_id=%s instance_id_hash=%s active_saves=%s "
                    "process_cpu_ms=%s payload_json_bytes=%s "
                    "strategy_state_json_bytes=%s strategy_state_encode_ms=%s "
                    "strategy_state_storage_format=%s diagnostic_overhead_ms=%s "
                    "instrumented_call_total_ms=%s error_type=%s",
                    diagnostics["total_ms"],
                    diagnostics["attempt_count"],
                    diagnostics["read_ms"],
                    diagnostics["transaction_body_ms"],
                    diagnostics["commit_retry_overhead_ms"],
                    diagnostics["commit_rpc_attempt_count"],
                    diagnostics["commit_rpc_attempt_ms"],
                    diagnostics["commit_rpc_outcomes"],
                    diagnostics["commit_rpc_status_codes"],
                    diagnostics["rpc_unattributed_ms"],
                    diagnostics["commit_rpc_process_cpu_ms"],
                    diagnostics["commit_rpc_thread_cpu_ms"],
                    diagnostics["commit_rpc_other_threads_cpu_ms"],
                    diagnostics["commit_rpc_gc_collections"],
                    diagnostics["commit_rpc_gc_collected"],
                    diagnostics["process_id"],
                    diagnostics["instance_id_hash"],
                    diagnostics["active_saves_at_start"],
                    diagnostics["process_cpu_ms"],
                    diagnostics["payload_json_bytes"],
                    diagnostics["strategy_state_json_bytes"],
                    diagnostics["strategy_state_encode_ms"],
                    diagnostics["strategy_state_storage_format"],
                    diagnostics["diagnostic_overhead_ms"],
                    diagnostics["instrumented_call_total_ms"],
                    diagnostics["error_type"],
                )
        return saved

    def acquire_session_lock(
        self,
        user_id: str,
        session_id: str,
        *,
        owner: str,
        lock_until: str,
        now: str,
    ) -> bool:
        """Acquire or renew the session lock in one Firestore transaction."""

        if not self._client or firestore is None:
            return False
        user_ref = self._client.collection(self._config.users_collection).document(user_id)
        session_ref = user_ref.collection(self._config.sessions_subcollection).document(session_id)
        txn = self._client.transaction()

        @firestore.transactional  # type: ignore[misc]
        def _txn(transaction: Any) -> bool:
            snapshot = session_ref.get(transaction=transaction)
            existing = snapshot.to_dict() if snapshot.exists else {}
            active_until = str((existing or {}).get("active_lock_until") or "")
            active_owner = str((existing or {}).get("active_lock_owner") or "")
            if active_until and _lock_is_active(active_until, now) and active_owner != owner:
                return False
            transaction.set(
                session_ref,
                {
                    "active_lock_until": lock_until,
                    "active_lock_owner": owner,
                },
                merge=True,
            )
            return True

        return bool(_txn(txn))

    def release_session_lock(
        self,
        user_id: str,
        session_id: str,
        *,
        owner: str,
    ) -> None:
        if not self._client:
            return
        user_ref = self._client.collection(self._config.users_collection).document(user_id)
        session_ref = user_ref.collection(self._config.sessions_subcollection).document(session_id)
        snapshot = session_ref.get()
        data = snapshot.to_dict() if snapshot.exists else {}
        active_owner = str((data or {}).get("active_lock_owner") or "")
        if not active_owner:
            return
        if active_owner and active_owner != owner:
            return
        session_ref.set(
            {
                "active_lock_until": None,
                "active_lock_owner": None,
            },
            merge=True,
        )

    def record_interaction_event(
        self,
        user_id: str,
        session_id: str,
        event: Dict[str, Any],
        *,
        max_events: int,
    ) -> bool:
        if not self._client or firestore is None:
            return False
        user_ref = self._client.collection(self._config.users_collection).document(user_id)
        session_ref = user_ref.collection(self._config.sessions_subcollection).document(session_id)
        txn = self._client.transaction()

        @firestore.transactional  # type: ignore[misc]
        def _txn(transaction: Any) -> bool:
            snapshot = session_ref.get(transaction=transaction)
            existing = snapshot.to_dict() if snapshot.exists else {}
            transaction.set(
                session_ref,
                {
                    "interaction_inbox_v1": _upsert_interaction_event(
                        (existing or {}).get("interaction_inbox_v1"),
                        event,
                        max_events=max_events,
                    )
                },
                merge=True,
            )
            return True

        return bool(_txn(txn))

    def load_interaction_events(
        self,
        user_id: str,
        session_id: str,
    ) -> List[Dict[str, Any]]:
        if not self._client:
            return []
        user_ref = self._client.collection(self._config.users_collection).document(user_id)
        session_ref = user_ref.collection(self._config.sessions_subcollection).document(session_id)
        snapshot = session_ref.get()
        data = snapshot.to_dict() if snapshot.exists else {}
        return [
            dict(item)
            for item in (data or {}).get("interaction_inbox_v1") or []
            if isinstance(item, dict)
        ]

    def remove_interaction_events(
        self,
        user_id: str,
        session_id: str,
        *,
        event_ids: Sequence[str],
    ) -> None:
        remove_ids = {
            str(item or "").strip()
            for item in event_ids
            if str(item or "").strip()
        }
        if not self._client or firestore is None or not remove_ids:
            return
        user_ref = self._client.collection(self._config.users_collection).document(user_id)
        session_ref = user_ref.collection(self._config.sessions_subcollection).document(session_id)
        txn = self._client.transaction()

        @firestore.transactional  # type: ignore[misc]
        def _txn(transaction: Any) -> None:
            snapshot = session_ref.get(transaction=transaction)
            existing = snapshot.to_dict() if snapshot.exists else {}
            transaction.set(
                session_ref,
                {
                    "interaction_inbox_v1": [
                        dict(item)
                        for item in (existing or {}).get("interaction_inbox_v1") or []
                        if isinstance(item, dict)
                        and _interaction_event_id(item) not in remove_ids
                    ]
                },
                merge=True,
            )

        _txn(txn)

    def _init_client(self, firestore_client: Optional[Any]) -> Optional[Any]:
        if not self._config.enable_firestore:
            return None
        if firestore_client is not None:
            return firestore_client
        if firestore is None:
            logger.warning("google-cloud-firestore not available; Firestore disabled")
            return None
        try:
            creds_payload = self._config.credentials_json
            if not creds_payload:
                creds_payload = ENV.get("CREDENTIALS")
            if creds_payload and service_account is not None:
                if isinstance(creds_payload, str):
                    try:
                        creds_payload = json.loads(creds_payload)
                    except Exception:
                        creds_payload = None
            if creds_payload and service_account is not None:
                creds = service_account.Credentials.from_service_account_info(creds_payload)
                return firestore.Client(project=self._config.project_id, credentials=creds)
            return firestore.Client(project=self._config.project_id)
        except Exception as exc:  # pragma: no cover - runtime credential dependency
            logger.warning("Failed to init Firestore client: %s", exc)
            return None


def _interaction_event_id(event: Dict[str, Any]) -> str:
    return str(
        event.get("event_id")
        or event.get("idempotency_key")
        or ""
    ).strip()


def _session_save_diagnostics(
    *,
    total_ms: float,
    attempts: Sequence[Dict[str, float]],
    rpc_attempts: Sequence[Mapping[str, Any]] = (),
    runtime_context: Optional[Mapping[str, Any]] = None,
    payload: Dict[str, Any],
    expected_revision: int,
    saved: bool,
    error_type: str = "",
    include_payload_sizes: bool = False,
) -> Dict[str, Any]:
    """Build content-free timing and size evidence for one Firestore CAS save."""

    read_values = [max(float(item.get("read_ms") or 0.0), 0.0) for item in attempts]
    body_values = [
        max(float(item.get("transaction_body_ms") or 0.0), 0.0)
        for item in attempts
    ]
    measured_total = max(float(total_ms), 0.0)
    transaction_body_total = sum(body_values)
    safe_rpc_attempts = [
        dict(item)
        for item in rpc_attempts[:_MAX_RPC_ATTEMPTS_RECORDED]
        if isinstance(item, Mapping)
        and str(item.get("operation") or "") in {"begin_transaction", "commit"}
    ]
    begin_rpc_attempts = [
        item for item in safe_rpc_attempts
        if item.get("operation") == "begin_transaction"
    ]
    commit_rpc_attempts = [
        item for item in safe_rpc_attempts if item.get("operation") == "commit"
    ]
    measured_rpc_ms = sum(
        max(float(item.get("elapsed_ms") or 0.0), 0.0)
        for item in safe_rpc_attempts
    )
    context = dict(runtime_context or {})
    process_cpu_ms = max(float(context.get("process_cpu_ms") or 0.0), 0.0)
    payload_json_bytes = 0
    strategy_state_json_bytes = 0
    stored_strategy_state_format = str(
        payload.get(STRATEGY_STATE_ENCODING_FIELD)
        or (
            STRATEGY_STATE_FORMAT_NESTED_MAP_V1
            if "strategy_state" in payload
            else ""
        )
    )
    if include_payload_sizes:
        payload_json_bytes = _diagnostic_json_size(payload)
        if isinstance(payload.get("strategy_state"), dict):
            strategy_state_json_bytes = _diagnostic_json_size(
                payload.get("strategy_state")
            )
        elif isinstance(payload.get(STRATEGY_STATE_JSON_FIELD_V1), str):
            strategy_state_json_bytes = len(
                payload[STRATEGY_STATE_JSON_FIELD_V1].encode("utf-8")
            )
    return {
        "storage_kind": "firestore",
        "write_mode": "transactional_full_document_cas",
        "saved": bool(saved and not error_type),
        "error_type": str(error_type or ""),
        "expected_revision": int(expected_revision),
        "attempt_count": len(attempts),
        "total_ms": round(measured_total, 3),
        "read_ms": [round(value, 3) for value in read_values],
        "transaction_body_ms": [round(value, 3) for value in body_values],
        "commit_retry_overhead_ms": round(
            max(measured_total - transaction_body_total, 0.0),
            3,
        ),
        "rpc_observer_status": str(context.get("rpc_observer_status") or ""),
        "begin_rpc_attempt_count": len(begin_rpc_attempts),
        "begin_rpc_attempt_ms": [
            round(max(float(item.get("elapsed_ms") or 0.0), 0.0), 3)
            for item in begin_rpc_attempts
        ],
        "begin_rpc_outcomes": [
            str(item.get("outcome") or "")[:20] for item in begin_rpc_attempts
        ],
        "begin_rpc_status_codes": [
            str(item.get("status_code") or "")[:80]
            for item in begin_rpc_attempts
        ],
        "commit_rpc_attempt_count": len(commit_rpc_attempts),
        "commit_rpc_attempt_ms": [
            round(max(float(item.get("elapsed_ms") or 0.0), 0.0), 3)
            for item in commit_rpc_attempts
        ],
        "commit_rpc_outcomes": [
            str(item.get("outcome") or "")[:20] for item in commit_rpc_attempts
        ],
        "commit_rpc_error_types": [
            str(item.get("error_type") or "")[:80] for item in commit_rpc_attempts
        ],
        "commit_rpc_status_codes": [
            str(item.get("status_code") or "")[:80]
            for item in commit_rpc_attempts
        ],
        "commit_rpc_gapic_retryable": [
            bool(item.get("gapic_default_retryable"))
            for item in commit_rpc_attempts
        ],
        "commit_rpc_transactional_retryable": [
            bool(item.get("transactional_retryable"))
            for item in commit_rpc_attempts
        ],
        "commit_rpc_process_cpu_ms": [
            round(max(float(item.get("process_cpu_ms") or 0.0), 0.0), 3)
            for item in commit_rpc_attempts
        ],
        "commit_rpc_thread_cpu_ms": [
            round(max(float(item.get("thread_cpu_ms") or 0.0), 0.0), 3)
            for item in commit_rpc_attempts
        ],
        "commit_rpc_other_threads_cpu_ms": [
            round(max(float(item.get("other_threads_cpu_ms") or 0.0), 0.0), 3)
            for item in commit_rpc_attempts
        ],
        "commit_rpc_user_cpu_ms": [
            round(max(float(item.get("user_cpu_ms") or 0.0), 0.0), 3)
            for item in commit_rpc_attempts
        ],
        "commit_rpc_system_cpu_ms": [
            round(max(float(item.get("system_cpu_ms") or 0.0), 0.0), 3)
            for item in commit_rpc_attempts
        ],
        "commit_rpc_minor_page_faults": [
            max(int(item.get("minor_page_faults") or 0), 0)
            for item in commit_rpc_attempts
        ],
        "commit_rpc_major_page_faults": [
            max(int(item.get("major_page_faults") or 0), 0)
            for item in commit_rpc_attempts
        ],
        "commit_rpc_voluntary_context_switches": [
            max(int(item.get("voluntary_context_switches") or 0), 0)
            for item in commit_rpc_attempts
        ],
        "commit_rpc_involuntary_context_switches": [
            max(int(item.get("involuntary_context_switches") or 0), 0)
            for item in commit_rpc_attempts
        ],
        "commit_rpc_gc_collections": [
            [max(int(value or 0), 0) for value in list(item.get("gc_collections") or [])[:3]]
            for item in commit_rpc_attempts
        ],
        "commit_rpc_gc_collected": [
            [max(int(value or 0), 0) for value in list(item.get("gc_collected") or [])[:3]]
            for item in commit_rpc_attempts
        ],
        "rpc_unattributed_ms": round(
            max(measured_total - transaction_body_total - measured_rpc_ms, 0.0),
            3,
        ),
        "observation_id": str(context.get("observation_id") or "")[:80],
        "process_id": int(context.get("process_id") or 0),
        "instance_id_hash": str(context.get("instance_id_hash") or "")[:20],
        "revision": str(context.get("revision") or "")[:100],
        "process_uptime_ms": round(
            max(float(context.get("process_uptime_ms") or 0.0), 0.0),
            3,
        ),
        "active_saves_at_start": int(context.get("active_saves_at_start") or 0),
        "active_saves_before_end": int(context.get("active_saves_before_end") or 0),
        "process_peak_active_saves": int(
            context.get("process_peak_active_saves") or 0
        ),
        "process_cpu_ms": round(process_cpu_ms, 3),
        "process_cpu_to_wall_percent": round(
            (process_cpu_ms / measured_total) * 100.0 if measured_total else 0.0,
            3,
        ),
        "payload_sizes_measured": bool(include_payload_sizes),
        "payload_json_bytes": payload_json_bytes,
        "strategy_state_json_bytes": strategy_state_json_bytes,
        "stored_strategy_state_format": stored_strategy_state_format[:40],
    }


def _diagnostic_json_size(value: Any) -> int:
    try:
        return len(
            json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        )
    except Exception:
        return 0


def _upsert_interaction_event(
    existing: Any,
    event: Dict[str, Any],
    *,
    max_events: int,
) -> List[Dict[str, Any]]:
    """Upsert one event without changing session revision or lock ownership."""

    limit = max(1, int(max_events or 1))
    event_id = _interaction_event_id(event)
    retained = [
        dict(item)
        for item in existing or []
        if isinstance(item, dict)
        and (not event_id or _interaction_event_id(item) != event_id)
    ]
    if event_id:
        retained.append(dict(event))
    return retained[-limit:]


def _replace_session_document_in_transaction(
    transaction: Any,
    session_ref: Any,
    payload: Dict[str, Any],
    *,
    exists: bool,
) -> None:
    """Replace persisted session fields so removed nested state stays removed."""

    if exists:
        transaction.update(session_ref, payload)
        return
    create_payload = {
        key: value
        for key, value in payload.items()
        if firestore is None or value is not firestore.DELETE_FIELD
    }
    transaction.set(session_ref, create_payload)


def _clear_owned_session_lock(
    payload: Dict[str, Any],
    *,
    existing: Dict[str, Any],
    owner: Optional[str],
) -> None:
    """Clear a turn lock in the same CAS write only when the caller owns it."""

    if owner and str(existing.get("active_lock_owner") or "") == str(owner):
        payload["active_lock_owner"] = None
        payload["active_lock_until"] = None


def _lock_is_active(active_until: str, now: str) -> bool:
    active_dt = _parse_manila_datetime(active_until)
    now_dt = _parse_manila_datetime(now)
    if not active_dt or not now_dt:
        return False
    return active_dt > now_dt


def _parse_manila_datetime(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except Exception:
        pass
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None
