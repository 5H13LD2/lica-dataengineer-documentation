"""Run a guarded, content-free Firestore transport probe on Cloud Run.

The probe writes only generated data to a dedicated benchmark collection and
uses the production ``FirestoreSessionStore.save_session_cas`` path. It exists
to distinguish Firestore RPC latency and retries from LLM/runtime work; it must
never read serving, evaluator, or customer session documents.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import statistics
import time
from typing import Any, Dict, Iterable, Sequence
import uuid

from google.cloud import firestore

from runtime.storage.session_store import (
    FirestoreSessionStore,
    FirestoreSessionStoreConfig,
    STRATEGY_STATE_ENCODING_FIELD,
    STRATEGY_STATE_FORMAT_CANONICAL_JSON_V1,
    STRATEGY_STATE_FORMAT_NESTED_MAP_V1,
    STRATEGY_STATE_JSON_FIELD_V1,
    STRATEGY_STATE_SCHEMA_VERSION_FIELD,
    STRATEGY_STATE_SHA256_FIELD,
    normalize_strategy_state_format,
)


PROBE_USERS_COLLECTION = "users_transport_benchmark_v1"
PROBE_SESSIONS_SUBCOLLECTION = "sessions_transport_benchmark_v1"
ALLOWED_PAYLOAD_KIB = {40, 140}
REPRESENTATION_VARIANTS = (
    "nested_map_v1",
    "canonical_json_v1",
    "gzip_json_v1",
)


def _json_size_bytes(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    )


def _canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON-native benchmark state without lossy fallbacks."""

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _shape_profile(value: Any) -> Dict[str, int]:
    """Return content-free structural counts for generated state."""

    scalars = 0
    maps = 0
    lists = 0
    max_depth = 0

    def visit(item: Any, depth: int) -> None:
        """Accumulate counts while walking generated JSON-native values."""

        nonlocal scalars, maps, lists, max_depth
        max_depth = max(max_depth, depth)
        if isinstance(item, dict):
            maps += 1
            for child in item.values():
                visit(child, depth + 1)
        elif isinstance(item, list):
            lists += 1
            for child in item:
                visit(child, depth + 1)
        else:
            scalars += 1

    visit(value, 0)
    return {
        "scalars": scalars,
        "maps": maps,
        "lists": lists,
        "max_depth": max_depth,
    }


def _latency_summary(values: Sequence[float]) -> Dict[str, Any]:
    measured = sorted(round(max(float(value), 0.0), 3) for value in values)
    if not measured:
        return {"count": 0, "values_ms": [], "p50_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
    p95_index = max(0, math.ceil(0.95 * len(measured)) - 1)
    return {
        "count": len(measured),
        "values_ms": measured,
        "p50_ms": round(statistics.median(measured), 3),
        "p95_ms": measured[p95_index],
        "max_ms": measured[-1],
    }


def _generated_payload(*, payload_kib: int, iteration: int) -> Dict[str, Any]:
    """Build same-shape generated nested state near the requested byte size."""

    if payload_kib not in ALLOWED_PAYLOAD_KIB:
        raise ValueError(f"unsupported payload_kib: {payload_kib}")
    field_count = 128
    target_bytes = payload_kib * 1024
    per_field_chars = max(32, (target_bytes - 4096) // field_count)
    marker = "a" if iteration % 2 == 0 else "b"
    fields = {
        f"field_{index:03d}": marker + ("x" * max(per_field_chars - 1, 1))
        for index in range(field_count)
    }
    return {
        "revision": 0,
        "strategy_state": {
            "runtime_v7": {
                "transport_probe_v1": {
                    "synthetic": True,
                    "iteration": iteration,
                    "fields": fields,
                }
            }
        },
        "active_lock_owner": None,
        "active_lock_until": None,
        "benchmark_marker_v1": {"synthetic": True, "iteration": iteration},
    }


def _generated_runtime_state(*, payload_kib: int, iteration: int) -> Dict[str, Any]:
    """Build fixed-topology, runtime-dense, generated logical session state."""

    if payload_kib not in ALLOWED_PAYLOAD_KIB:
        raise ValueError(f"unsupported payload_kib: {payload_kib}")
    record_count = 15 if payload_kib == 40 else 55
    turn = f"{iteration:06d}"
    records = []
    for index in range(record_count):
        item = f"{index:04d}"
        records.append(
            {
                "turn": turn,
                "item": f"{turn}-{item}",
                "intent": {
                    "name": f"intent-{turn}-{item}",
                    "confidence_ppm": iteration * 10000 + index,
                    "evidence": [
                        {"kind": f"explicit-{turn}", "value": f"value-a-{turn}-{item}"},
                        {"kind": f"context-{turn}", "value": f"value-b-{turn}-{item}"},
                    ],
                },
                "tool": {
                    "name": f"tool-{turn}-{item}",
                    "arguments": {
                        "tire_size": f"195-60-R15-{turn}",
                        "brand": f"brand-{turn}-{item}",
                        "location": f"location-{turn}-{item}",
                        "payment": f"payment-{turn}-{item}",
                    },
                    "result": {
                        "status": f"status-{turn}",
                        "claims": [
                            f"claim-{claim_index:02d}-{turn}-{item}"
                            for claim_index in range(30)
                        ],
                    },
                },
                "composer": {
                    "obligations": [
                        {
                            "id": f"obligation-a-{turn}-{item}",
                            "state": f"state-a-{turn}",
                        },
                        {
                            "id": f"obligation-b-{turn}-{item}",
                            "state": f"state-b-{turn}",
                        },
                    ],
                    "history": {
                        "recent": [
                            {"role": f"user-{turn}", "ref": f"u-{turn}-{item}"},
                            {"role": f"assistant-{turn}", "ref": f"a-{turn}-{item}"},
                        ]
                    },
                },
            }
        )
    state: Dict[str, Any] = {
        "runtime_v7": {
            "representation_probe_v1": {
                "turn": turn,
                "records": records,
                "list_buckets": {
                    f"bucket_{bucket:03d}": [
                        f"bucket-{bucket:03d}-{value:02d}-{turn}"
                        for value in range(5)
                    ]
                    for bucket in range(40 if payload_kib == 40 else 120)
                },
                "deep_state": {
                    "level_1": {
                        "level_2": {
                            "level_3": {
                                "level_4": {
                                    "level_5": {
                                        "level_6": {
                                            "level_7": {
                                                "turn": turn,
                                                "padding": "",
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
            }
        }
    }
    target_bytes = payload_kib * 1024
    base_bytes = len(_canonical_json_bytes(state))
    if base_bytes > target_bytes:
        raise ValueError("runtime-shaped benchmark topology exceeds requested size")
    state["runtime_v7"]["representation_probe_v1"]["deep_state"]["level_1"][
        "level_2"
    ]["level_3"]["level_4"]["level_5"]["level_6"]["level_7"]["padding"] = (
        ("x" if iteration % 2 == 0 else "y") * (target_bytes - base_bytes)
    )
    if len(_canonical_json_bytes(state)) != target_bytes:
        raise RuntimeError("runtime-shaped benchmark size calculation failed")
    return state


def _encode_representation(
    logical_state: Dict[str, Any],
    *,
    variant: str,
    user_id: str,
    session_id: str,
    iteration: int,
) -> tuple[Dict[str, Any], int, str]:
    """Encode one logical state in one benchmark-only persistence format."""

    canonical = _canonical_json_bytes(logical_state)
    digest = hashlib.sha256(canonical).hexdigest()
    payload: Dict[str, Any] = {
        "revision": 0,
        "user_id": user_id,
        "session_id": session_id,
        "active_lock_owner": None,
        "active_lock_until": None,
        "benchmark_marker_v1": {"synthetic": True, "iteration": iteration},
        "strategy_state_schema_version": 1,
        "strategy_state_encoding": variant,
        "strategy_state_sha256": digest,
    }
    if variant == "nested_map_v1":
        payload["strategy_state"] = deepcopy(logical_state)
        stored_bytes = len(canonical)
    elif variant == "canonical_json_v1":
        payload["strategy_state_json_v1"] = canonical.decode("utf-8")
        stored_bytes = len(canonical)
    elif variant == "gzip_json_v1":
        compressed = gzip.compress(canonical, compresslevel=6, mtime=0)
        payload["strategy_state_gzip_v1"] = compressed
        stored_bytes = len(compressed)
    else:
        raise ValueError(f"unsupported representation variant: {variant}")
    return payload, stored_bytes, digest


def _decode_representation(payload: Dict[str, Any]) -> Dict[str, Any]:
    variant = str(payload.get("strategy_state_encoding") or "")
    if variant == "nested_map_v1" or (
        not variant and isinstance(payload.get("strategy_state"), dict)
    ):
        value = payload.get("strategy_state")
        if not isinstance(value, dict):
            raise ValueError("nested map representation is missing")
        return value
    if variant == "canonical_json_v1":
        raw = payload.get("strategy_state_json_v1")
        if not isinstance(raw, str):
            raise ValueError("canonical JSON representation is missing")
        value = json.loads(raw)
    elif variant == "gzip_json_v1":
        raw = payload.get("strategy_state_gzip_v1")
        if not isinstance(raw, (bytes, bytearray)):
            raise ValueError("gzip JSON representation is missing")
        value = json.loads(gzip.decompress(bytes(raw)).decode("utf-8"))
    else:
        raise ValueError("unknown strategy state encoding")
    if not isinstance(value, dict):
        raise ValueError("decoded strategy state must be a map")
    return value


def _matches_authoritative_storage_shape(
    payload: Any,
    *,
    strategy_state_format: str,
) -> bool:
    """Verify exactly one complete strategy-state representation is present."""

    if not isinstance(payload, dict):
        return False
    canonical_fields = (
        STRATEGY_STATE_JSON_FIELD_V1,
        STRATEGY_STATE_ENCODING_FIELD,
        STRATEGY_STATE_SCHEMA_VERSION_FIELD,
        STRATEGY_STATE_SHA256_FIELD,
    )
    if strategy_state_format == STRATEGY_STATE_FORMAT_CANONICAL_JSON_V1:
        return bool(
            "strategy_state" not in payload
            and isinstance(payload.get(STRATEGY_STATE_JSON_FIELD_V1), str)
            and payload.get(STRATEGY_STATE_ENCODING_FIELD)
            == STRATEGY_STATE_FORMAT_CANONICAL_JSON_V1
            and payload.get(STRATEGY_STATE_SCHEMA_VERSION_FIELD) == 1
            and isinstance(payload.get(STRATEGY_STATE_SHA256_FIELD), str)
            and len(payload[STRATEGY_STATE_SHA256_FIELD]) == 64
        )
    return bool(
        isinstance(payload.get("strategy_state"), dict)
        and not any(field_name in payload for field_name in canonical_fields)
    )


def _rotated_variants(iteration: int) -> tuple[str, ...]:
    offset = iteration % len(REPRESENTATION_VARIANTS)
    return REPRESENTATION_VARIANTS[offset:] + REPRESENTATION_VARIANTS[:offset]


def _cleanup_exact_refs(refs: Iterable[Any]) -> Dict[str, Any]:
    error_types: list[str] = []
    for ref in refs:
        try:
            ref.delete()
        except Exception as exc:
            error_types.append(type(exc).__name__)
    for ref in refs:
        try:
            if ref.get().exists:
                error_types.append("DocumentStillExists")
        except Exception as exc:
            error_types.append(type(exc).__name__)
    return {
        "completed": not error_types,
        "error_types": sorted(set(error_types)),
    }


def run_firestore_transport_probe(
    *,
    project_id: str,
    warmups: int = 2,
    rounds: int = 8,
    payload_kib: int = 140,
    firestore_client: Any = None,
) -> Dict[str, Any]:
    """Measure CAS persistence without model calls and clean exact test data."""

    if warmups < 0 or warmups > 5:
        raise ValueError("warmups must be between 0 and 5")
    if rounds < 2 or rounds > 20:
        raise ValueError("rounds must be between 2 and 20")
    if payload_kib not in ALLOWED_PAYLOAD_KIB:
        raise ValueError("payload_kib must be 40 or 140")

    client = firestore_client or firestore.Client(project=project_id)
    config = FirestoreSessionStoreConfig(
        project_id=project_id,
        users_collection=PROBE_USERS_COLLECTION,
        sessions_subcollection=PROBE_SESSIONS_SUBCOLLECTION,
        enable_firestore=True,
    )
    store = FirestoreSessionStore(config=config, firestore_client=client)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    user_id = f"runtime-v7-transport-benchmark-{run_id}"
    session_id = f"session-{run_id}"
    ref = (
        client.collection(PROBE_USERS_COLLECTION)
        .document(user_id)
        .collection(PROBE_SESSIONS_SUBCOLLECTION)
        .document(session_id)
    )
    initial = _generated_payload(payload_kib=payload_kib, iteration=0)
    initial["user_id"] = user_id
    initial["session_id"] = session_id
    measured_ms: list[float] = []
    diagnostics: list[Dict[str, Any]] = []
    cleanup_error_type = ""
    create_started = time.perf_counter()
    try:
        ref.set(initial)
        create_ms = (time.perf_counter() - create_started) * 1000.0
        expected_revision = 0
        for iteration in range(warmups + rounds):
            payload = deepcopy(
                _generated_payload(
                    payload_kib=payload_kib,
                    iteration=iteration + 1,
                )
            )
            payload["user_id"] = user_id
            payload["session_id"] = session_id
            started = time.perf_counter()
            saved = store.save_session_cas(
                user_id,
                session_id,
                expected_revision,
                payload,
                request_id=f"transport-probe-{iteration + 1}",
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if not saved:
                raise RuntimeError("transport probe CAS save failed")
            expected_revision += 1
            if iteration >= warmups:
                measured_ms.append(elapsed_ms)
                diagnostics.append(store.last_save_diagnostics())
    finally:
        try:
            ref.delete()
        except Exception as exc:
            cleanup_error_type = type(exc).__name__

    return {
        "schema_version": "runtime_v7_firestore_transport_probe_v1",
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target": {
            "users_collection": PROBE_USERS_COLLECTION,
            "sessions_subcollection": PROBE_SESSIONS_SUBCOLLECTION,
            "generated_payload_only": True,
        },
        "method": {
            "write_path": "FirestoreSessionStore.save_session_cas",
            "warmups": warmups,
            "rounds": rounds,
            "payload_kib_requested": payload_kib,
            "payload_json_bytes": _json_size_bytes(initial),
        },
        "create_ms": round(create_ms, 3),
        "measured": _latency_summary(measured_ms),
        "backend_diagnostics": diagnostics,
        "cleanup": {
            "completed": not cleanup_error_type,
            "error_type": cleanup_error_type,
        },
        "interpretation_limits": [
            "Generated data only; this does not inspect customer or evaluator sessions.",
            "This measures persistence and process context, not chatbot model latency.",
            "Process concurrency is local to one Gunicorn worker.",
        ],
    }


def run_firestore_representation_probe(
    *,
    project_id: str,
    warmups: int = 2,
    rounds: int = 8,
    payload_kib: int = 40,
    configured_strategy_state_format: str = STRATEGY_STATE_FORMAT_NESTED_MAP_V1,
    firestore_client: Any = None,
) -> Dict[str, Any]:
    """Compare three encodings through the same generated-data CAS path."""

    if warmups < 0 or warmups > 5:
        raise ValueError("warmups must be between 0 and 5")
    if rounds < 2 or rounds > 20:
        raise ValueError("rounds must be between 2 and 20")
    if payload_kib not in ALLOWED_PAYLOAD_KIB:
        raise ValueError("payload_kib must be 40 or 140")
    configured_strategy_state_format = normalize_strategy_state_format(
        configured_strategy_state_format
    )

    client = firestore_client or firestore.Client(project=project_id)
    config = FirestoreSessionStoreConfig(
        project_id=project_id,
        users_collection=PROBE_USERS_COLLECTION,
        sessions_subcollection=PROBE_SESSIONS_SUBCOLLECTION,
        enable_firestore=True,
        strategy_state_format=STRATEGY_STATE_FORMAT_NESTED_MAP_V1,
    )
    store = FirestoreSessionStore(config=config, firestore_client=client)
    configured_store = FirestoreSessionStore(
        config=FirestoreSessionStoreConfig(
            project_id=project_id,
            users_collection=PROBE_USERS_COLLECTION,
            sessions_subcollection=PROBE_SESSIONS_SUBCOLLECTION,
            enable_firestore=True,
            strategy_state_format=configured_strategy_state_format,
        ),
        firestore_client=client,
    )
    opposite_strategy_state_format = (
        STRATEGY_STATE_FORMAT_NESTED_MAP_V1
        if configured_strategy_state_format
        == STRATEGY_STATE_FORMAT_CANONICAL_JSON_V1
        else STRATEGY_STATE_FORMAT_CANONICAL_JSON_V1
    )
    opposite_store = FirestoreSessionStore(
        config=FirestoreSessionStoreConfig(
            project_id=project_id,
            users_collection=PROBE_USERS_COLLECTION,
            sessions_subcollection=PROBE_SESSIONS_SUBCOLLECTION,
            enable_firestore=True,
            strategy_state_format=opposite_strategy_state_format,
        ),
        firestore_client=client,
    )
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    user_id = f"runtime-v7-representation-benchmark-{run_id}"
    refs: Dict[str, Any] = {}
    session_ids: Dict[str, str] = {}
    for variant in REPRESENTATION_VARIANTS:
        session_id = f"session-{variant}-{run_id}"
        session_ids[variant] = session_id
        refs[variant] = (
            client.collection(PROBE_USERS_COLLECTION)
            .document(user_id)
            .collection(PROBE_SESSIONS_SUBCOLLECTION)
            .document(session_id)
        )
    configured_session_id = f"session-configured-{run_id}"
    configured_ref = (
        client.collection(PROBE_USERS_COLLECTION)
        .document(user_id)
        .collection(PROBE_SESSIONS_SUBCOLLECTION)
        .document(configured_session_id)
    )
    configured_non_cas_session_id = f"session-configured-non-cas-{run_id}"
    configured_non_cas_ref = (
        client.collection(PROBE_USERS_COLLECTION)
        .document(user_id)
        .collection(PROBE_SESSIONS_SUBCOLLECTION)
        .document(configured_non_cas_session_id)
    )

    logical_initial = _generated_runtime_state(payload_kib=payload_kib, iteration=0)
    samples: Dict[str, list[Dict[str, Any]]] = {
        variant: [] for variant in REPRESENTATION_VARIANTS
    }
    stale_controls: Dict[str, Dict[str, Any]] = {}
    configured_canary: Dict[str, Any] = {}
    cleanup = {"completed": False, "error_types": []}
    try:
        opposite_payload = {
            "revision": 0,
            "user_id": user_id,
            "session_id": configured_session_id,
            "active_lock_owner": None,
            "active_lock_until": None,
            "benchmark_marker_v1": {"synthetic": True, "iteration": 0},
            "strategy_state": deepcopy(logical_initial),
        }
        opposite_seed_saved = opposite_store.save_session_cas(
            user_id,
            configured_session_id,
            0,
            opposite_payload,
            request_id="representation-probe-opposite-seed",
        )
        configured_pre_switch_loaded = configured_store.load_session(
            user_id,
            configured_session_id,
        )
        pre_switch_adapter_roundtrip_verified = bool(
            isinstance(configured_pre_switch_loaded, dict)
            and configured_pre_switch_loaded.get("strategy_state")
            == logical_initial
            and STRATEGY_STATE_JSON_FIELD_V1
            not in configured_pre_switch_loaded
        )

        logical_switched = _generated_runtime_state(
            payload_kib=payload_kib,
            iteration=1,
        )
        configured_payload = {
            **opposite_payload,
            "benchmark_marker_v1": {"synthetic": True, "iteration": 1},
            "strategy_state": deepcopy(logical_switched),
        }
        configured_saved = configured_store.save_session_cas(
            user_id,
            configured_session_id,
            1,
            configured_payload,
            request_id="representation-probe-format-switch",
        )
        configured_raw_snapshot = configured_ref.get()
        configured_raw = (
            configured_raw_snapshot.to_dict()
            if configured_raw_snapshot.exists
            else None
        )
        configured_loaded = configured_store.load_session(
            user_id,
            configured_session_id,
        )
        raw_shape_verified = _matches_authoritative_storage_shape(
            configured_raw,
            strategy_state_format=configured_strategy_state_format,
        )
        adapter_roundtrip_verified = bool(
            isinstance(configured_loaded, dict)
            and configured_loaded.get("strategy_state") == logical_switched
            and STRATEGY_STATE_JSON_FIELD_V1 not in configured_loaded
        )
        configured_save_diagnostics = configured_store.last_save_diagnostics()
        configured_raw_before_stale = deepcopy(configured_raw)
        configured_stale_rejected = not configured_store.save_session_cas(
            user_id,
            configured_session_id,
            1,
            configured_payload,
            request_id="representation-probe-configured-stale",
        )
        configured_raw_after_stale_snapshot = configured_ref.get()
        configured_raw_after_stale = (
            configured_raw_after_stale_snapshot.to_dict()
            if configured_raw_after_stale_snapshot.exists
            else None
        )
        stale_cas_no_mutation = bool(
            configured_raw_before_stale == configured_raw_after_stale
        )
        configured_store.save_session(
            user_id,
            configured_non_cas_session_id,
            {
                "revision": 0,
                "user_id": user_id,
                "session_id": configured_non_cas_session_id,
                "benchmark_marker_v1": {
                    "synthetic": True,
                    "write_mode": "non_cas_create",
                },
                "strategy_state": deepcopy(logical_switched),
            },
        )
        configured_non_cas_snapshot = configured_non_cas_ref.get()
        configured_non_cas_raw = (
            configured_non_cas_snapshot.to_dict()
            if configured_non_cas_snapshot.exists
            else None
        )
        configured_non_cas_loaded = configured_store.load_session(
            user_id,
            configured_non_cas_session_id,
        )
        non_cas_create_verified = bool(
            _matches_authoritative_storage_shape(
                configured_non_cas_raw,
                strategy_state_format=configured_strategy_state_format,
            )
            and isinstance(configured_non_cas_loaded, dict)
            and configured_non_cas_loaded.get("strategy_state")
            == logical_switched
        )
        if not (
            opposite_seed_saved
            and pre_switch_adapter_roundtrip_verified
            and configured_saved
            and raw_shape_verified
            and adapter_roundtrip_verified
            and configured_stale_rejected
            and stale_cas_no_mutation
            and non_cas_create_verified
        ):
            raise RuntimeError("configured representation canary failed")
        configured_canary = {
            "configured_format": configured_strategy_state_format,
            "opposite_seed_format": opposite_strategy_state_format,
            "opposite_seed_succeeded": True,
            "pre_switch_adapter_roundtrip_verified": True,
            "switch_save_succeeded": True,
            "raw_storage_shape_verified": True,
            "post_switch_adapter_roundtrip_verified": True,
            "stale_cas_rejected": True,
            "stale_cas_no_mutation": True,
            "non_cas_create_verified": True,
            "backend_diagnostics": configured_save_diagnostics,
        }

        for variant in REPRESENTATION_VARIANTS:
            payload, _, _ = _encode_representation(
                logical_initial,
                variant=variant,
                user_id=user_id,
                session_id=session_ids[variant],
                iteration=0,
            )
            refs[variant].set(payload)

        total_iterations = warmups + rounds
        for iteration in range(total_iterations):
            logical_state = _generated_runtime_state(
                payload_kib=payload_kib,
                iteration=iteration + 1,
            )
            canonical = _canonical_json_bytes(logical_state)
            for order_index, variant in enumerate(_rotated_variants(iteration)):
                encode_started = time.perf_counter()
                payload, stored_bytes, digest = _encode_representation(
                    logical_state,
                    variant=variant,
                    user_id=user_id,
                    session_id=session_ids[variant],
                    iteration=iteration + 1,
                )
                encode_ms = (time.perf_counter() - encode_started) * 1000.0
                save_started = time.perf_counter()
                saved = store.save_session_cas(
                    user_id,
                    session_ids[variant],
                    iteration,
                    payload,
                    request_id=f"representation-probe-{variant}-{iteration + 1}",
                )
                save_ms = (time.perf_counter() - save_started) * 1000.0
                diagnostics = store.last_save_diagnostics()
                if not saved:
                    raise RuntimeError("representation probe CAS save failed")

                snapshot = refs[variant].get()
                persisted = snapshot.to_dict() if snapshot.exists else None
                if not isinstance(persisted, dict):
                    raise RuntimeError("representation probe readback failed")
                decoded = _decode_representation(persisted)
                adapter_roundtrip = None
                if variant in {
                    "nested_map_v1",
                    "canonical_json_v1",
                }:
                    adapter_payload = store.load_session(
                        user_id,
                        session_ids[variant],
                    )
                    adapter_roundtrip = bool(
                        isinstance(adapter_payload, dict)
                        and adapter_payload.get("strategy_state") == logical_state
                        and STRATEGY_STATE_JSON_FIELD_V1 not in adapter_payload
                    )
                roundtrip_digest = hashlib.sha256(
                    _canonical_json_bytes(decoded)
                ).hexdigest()
                roundtrip_ok = (
                    decoded == logical_state
                    and roundtrip_digest == digest
                    and (
                        persisted.get("strategy_state_sha256") == digest
                        or (
                            variant == "nested_map_v1"
                            and not persisted.get("strategy_state_sha256")
                        )
                    )
                    and int(persisted.get("revision") or 0) == iteration + 1
                    and adapter_roundtrip is not False
                )
                if not roundtrip_ok:
                    raise RuntimeError("representation probe roundtrip failed")
                if iteration >= warmups:
                    samples[variant].append(
                        {
                            "round": iteration - warmups + 1,
                            "execution_order": order_index + 1,
                            "encode_ms": round(encode_ms, 3),
                            "save_ms": round(save_ms, 3),
                            "end_to_end_ms": round(encode_ms + save_ms, 3),
                            "logical_json_bytes": len(canonical),
                            "stored_state_bytes": stored_bytes,
                            "sha256": digest,
                            "revision": iteration + 1,
                            "roundtrip_verified": True,
                            "storage_adapter_roundtrip_verified": adapter_roundtrip,
                            "backend_diagnostics": diagnostics,
                        }
                    )

        stale_logical = _generated_runtime_state(
            payload_kib=payload_kib,
            iteration=total_iterations + 1,
        )
        for variant in REPRESENTATION_VARIANTS:
            before = refs[variant].get().to_dict()
            stale_payload, _, _ = _encode_representation(
                stale_logical,
                variant=variant,
                user_id=user_id,
                session_id=session_ids[variant],
                iteration=total_iterations + 1,
            )
            stale_saved = store.save_session_cas(
                user_id,
                session_ids[variant],
                total_iterations - 1,
                stale_payload,
                request_id=f"representation-probe-stale-{variant}",
            )
            after = refs[variant].get().to_dict()
            unchanged = (
                isinstance(before, dict)
                and isinstance(after, dict)
                and before.get("revision") == after.get("revision")
                and before.get("strategy_state_sha256")
                == after.get("strategy_state_sha256")
            )
            if stale_saved or not unchanged:
                raise RuntimeError("representation probe stale CAS control failed")
            stale_controls[variant] = {
                "rejected": True,
                "stored_revision_unchanged": True,
                "stored_hash_unchanged": True,
            }
    finally:
        cleanup = _cleanup_exact_refs(
            [
                *refs.values(),
                configured_ref,
                configured_non_cas_ref,
            ]
        )

    if not cleanup["completed"]:
        raise RuntimeError("representation probe cleanup verification failed")

    variant_results: Dict[str, Any] = {}
    for variant, variant_samples in samples.items():
        variant_results[variant] = {
            "encode": _latency_summary(
                [sample["encode_ms"] for sample in variant_samples]
            ),
            "save": _latency_summary(
                [sample["save_ms"] for sample in variant_samples]
            ),
            "end_to_end": _latency_summary(
                [sample["end_to_end_ms"] for sample in variant_samples]
            ),
            "stored_state_bytes": sorted(
                {sample["stored_state_bytes"] for sample in variant_samples}
            ),
            "roundtrip_verified": all(
                sample["roundtrip_verified"] for sample in variant_samples
            ),
            "storage_adapter_roundtrip_verified": (
                all(
                    sample["storage_adapter_roundtrip_verified"] is True
                    for sample in variant_samples
                )
                if variant in {"nested_map_v1", "canonical_json_v1"}
                else None
            ),
            "samples": variant_samples,
            "stale_cas_control": stale_controls[variant],
        }

    return {
        "schema_version": "runtime_v7_firestore_representation_probe_v1",
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target": {
            "users_collection": PROBE_USERS_COLLECTION,
            "sessions_subcollection": PROBE_SESSIONS_SUBCOLLECTION,
            "generated_payload_only": True,
            "document_count": len(REPRESENTATION_VARIANTS) + 2,
        },
        "method": {
            "write_path": "FirestoreSessionStore.save_session_cas",
            "index_configuration": "inherited_default",
            "warmups": warmups,
            "rounds": rounds,
            "payload_kib_requested": payload_kib,
            "logical_json_bytes": len(_canonical_json_bytes(logical_initial)),
            "logical_shape": _shape_profile(logical_initial),
            "rotating_execution_order": True,
        },
        "variants": variant_results,
        "configured_format_canary": configured_canary,
        "cleanup": cleanup,
        "interpretation_limits": [
            "Generated data only; this does not inspect customer or evaluator sessions.",
            "This isolates representation under inherited indexing; it does not change production storage.",
            "Application encoding and Firestore CAS timings are reported separately.",
            "A winning representation still requires a versioned reader and migration design before production use.",
        ],
    }
