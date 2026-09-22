"""Benchmark Runtime V7 Firestore session writes in isolated collections.

The runner clones one synthetic evaluator session into explicitly named
benchmark-only collection groups and measures the existing transactional CAS
write path. It never changes the source session, does not alter indexes, and
removes only the exact benchmark documents it creates unless ``--keep`` is
provided. Index configuration is intentionally managed and verified outside
this script so the resulting artifact can distinguish configuration evidence
from write-latency evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

from google.cloud import firestore

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.storage.session_store import (  # noqa: E402
    FirestoreSessionStore,
    FirestoreSessionStoreConfig,
)


DEFAULT_PROJECT_ID = "gulong-chatbot-459723"
DEFAULT_SOURCE_USERS_COLLECTION = "users_test"
DEFAULT_SOURCE_SESSIONS_SUBCOLLECTION = "sessions_test"
DEFAULT_TARGET_USERS_COLLECTION = "users_persistence_benchmark_v1"
DEFAULT_INDEXED_SESSIONS_SUBCOLLECTION = "sessions_persist_benchmark_indexed_v1"
DEFAULT_EXEMPT_SESSIONS_SUBCOLLECTION = "sessions_persist_benchmark_state_exempt_v1"


def _json_size_bytes(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    )


def _percentile(values: Sequence[float], percentile: float) -> float:
    """Return a nearest-rank percentile suitable for small latency samples."""

    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    rank = max(1, math.ceil((float(percentile) / 100.0) * len(ordered)))
    return ordered[min(rank - 1, len(ordered) - 1)]


def _latency_summary(values: Sequence[float]) -> Dict[str, Any]:
    measured = [round(float(value), 3) for value in values]
    return {
        "count": len(measured),
        "values_ms": measured,
        "min_ms": min(measured) if measured else 0.0,
        "p50_ms": round(statistics.median(measured), 3) if measured else 0.0,
        "p95_ms": round(_percentile(measured, 95), 3),
        "max_ms": max(measured) if measured else 0.0,
        "mean_ms": round(statistics.fmean(measured), 3) if measured else 0.0,
    }


def _hashed_identifier(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _field_size_rows(value: Mapping[str, Any]) -> list[Dict[str, Any]]:
    return sorted(
        (
            {"field": str(key), "json_bytes": _json_size_bytes(field_value)}
            for key, field_value in value.items()
        ),
        key=lambda row: int(row["json_bytes"]),
        reverse=True,
    )


def _payload_profile(payload: Mapping[str, Any]) -> Dict[str, Any]:
    strategy_state = (
        payload.get("strategy_state")
        if isinstance(payload.get("strategy_state"), Mapping)
        else {}
    )
    runtime_v7 = (
        strategy_state.get("runtime_v7")
        if isinstance(strategy_state.get("runtime_v7"), Mapping)
        else {}
    )
    return {
        "document_json_bytes": _json_size_bytes(payload),
        "top_level_fields": _field_size_rows(payload),
        "strategy_state_json_bytes": _json_size_bytes(strategy_state),
        "strategy_state_fields": _field_size_rows(strategy_state),
        "runtime_v7_json_bytes": _json_size_bytes(runtime_v7),
        "runtime_v7_largest_fields": _field_size_rows(runtime_v7)[:20],
    }


def _validate_isolated_targets(
    *,
    source_users_collection: str,
    source_sessions_subcollection: str,
    target_users_collection: str,
    target_session_groups: Iterable[str],
) -> None:
    """Reject any benchmark target that could overlap serving/test sessions."""

    protected = {
        "users",
        "users_test",
        "sessions",
        "sessions_test",
        str(source_users_collection).strip(),
        str(source_sessions_subcollection).strip(),
    }
    targets = {
        str(target_users_collection).strip(),
        *(str(value).strip() for value in target_session_groups),
    }
    if any(not value or "benchmark" not in value.casefold() for value in targets):
        raise ValueError("all target collections must contain 'benchmark'")
    overlap = sorted(protected & targets)
    if overlap:
        raise ValueError(f"benchmark targets overlap protected collections: {overlap}")
    if len(targets) != 3:
        raise ValueError("benchmark target collection names must be distinct")


def _target_payload(
    source_payload: Mapping[str, Any],
    *,
    benchmark_user_id: str,
    benchmark_session_id: str,
) -> Dict[str, Any]:
    payload = deepcopy(dict(source_payload))
    payload["user_id"] = benchmark_user_id
    payload["session_id"] = benchmark_session_id
    payload["revision"] = 0
    payload["last_request_id"] = None
    payload["active_lock_owner"] = None
    payload["active_lock_until"] = None
    payload["benchmark_marker_v1"] = {
        "synthetic": True,
        "iteration": 0,
    }
    return payload


def _toggle_strategy_leaf_values(value: Any) -> tuple[Any, int]:
    """Return a same-shape state variant that changes every scalar leaf.

    Alternating the source and toggled variants forces recursive automatic
    indexes to update instead of benchmarking a nearly no-op document write.
    The transformation is benchmark-only and is never written to the source.
    """

    if isinstance(value, Mapping):
        output: Dict[str, Any] = {}
        changed = 0
        for key, nested in value.items():
            transformed, nested_changed = _toggle_strategy_leaf_values(nested)
            output[str(key)] = transformed
            changed += nested_changed
        return output, changed
    if isinstance(value, list):
        output_list = []
        changed = 0
        for nested in value:
            transformed, nested_changed = _toggle_strategy_leaf_values(nested)
            output_list.append(transformed)
            changed += nested_changed
        return output_list, changed
    if isinstance(value, str):
        return f"{value}~", 1
    if isinstance(value, bool):
        return (not value), 1
    if isinstance(value, int):
        return value + 1, 1
    if isinstance(value, float):
        return value + 0.000001, 1
    if value is None:
        return "~", 1
    return f"{value}~", 1


def _write_candidate(
    payload: Mapping[str, Any],
    *,
    iteration: int,
    mutation_mode: str,
) -> tuple[Dict[str, Any], int]:
    candidate = deepcopy(dict(payload))
    changed_leaf_count = 0
    if mutation_mode == "strategy_leaf_toggle" and iteration % 2:
        transformed, changed_leaf_count = _toggle_strategy_leaf_values(
            candidate.get("strategy_state") or {}
        )
        candidate["strategy_state"] = transformed
    candidate["benchmark_marker_v1"] = {
        "synthetic": True,
        "iteration": iteration,
        "mutation_mode": mutation_mode,
    }
    return candidate, changed_leaf_count


def _benchmark_one_group(
    *,
    client: Any,
    project_id: str,
    users_collection: str,
    sessions_subcollection: str,
    benchmark_user_id: str,
    benchmark_session_id: str,
    payload: Mapping[str, Any],
    warmups: int,
    rounds: int,
    mutation_mode: str,
) -> Dict[str, Any]:
    config = FirestoreSessionStoreConfig(
        project_id=project_id,
        users_collection=users_collection,
        sessions_subcollection=sessions_subcollection,
        enable_firestore=True,
    )
    store = FirestoreSessionStore(config=config, firestore_client=client)
    ref = (
        client.collection(users_collection)
        .document(benchmark_user_id)
        .collection(sessions_subcollection)
        .document(benchmark_session_id)
    )
    initial, _ = _write_candidate(
        payload,
        iteration=0,
        mutation_mode=mutation_mode,
    )
    create_started = time.perf_counter()
    ref.set(initial)
    create_elapsed_ms = (time.perf_counter() - create_started) * 1000.0
    expected_revision = 0
    warmup_values: list[float] = []
    measured_values: list[float] = []
    changed_leaf_counts: list[int] = []
    measured_backend_diagnostics: list[Dict[str, Any]] = []
    for iteration in range(warmups + rounds):
        candidate, changed_leaf_count = _write_candidate(
            payload,
            iteration=iteration + 1,
            mutation_mode=mutation_mode,
        )
        started = time.perf_counter()
        saved = store.save_session_cas(
            benchmark_user_id,
            benchmark_session_id,
            expected_revision,
            candidate,
            request_id=f"benchmark-{iteration + 1}",
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if not saved:
            raise RuntimeError(
                f"CAS save failed for {sessions_subcollection} at revision "
                f"{expected_revision}"
            )
        expected_revision += 1
        if iteration < warmups:
            warmup_values.append(elapsed_ms)
        else:
            measured_values.append(elapsed_ms)
            changed_leaf_counts.append(changed_leaf_count)
            measured_backend_diagnostics.append(
                store.last_save_diagnostics()
            )
    final_snapshot = ref.get()
    final_data = final_snapshot.to_dict() if final_snapshot.exists else {}
    return {
        "collection_group": sessions_subcollection,
        "document_path_hash": _hashed_identifier(ref.path),
        "create_ms": round(create_elapsed_ms, 3),
        "warmup": _latency_summary(warmup_values),
        "measured": _latency_summary(measured_values),
        "changed_strategy_leaf_counts": changed_leaf_counts,
        "backend_diagnostics": measured_backend_diagnostics,
        "final_revision": int((final_data or {}).get("revision") or 0),
        "readback_ok": bool(
            final_snapshot.exists
            and int((final_data or {}).get("revision") or 0)
            == warmups + rounds
            and isinstance((final_data or {}).get("strategy_state"), Mapping)
        ),
    }


def _comparison(
    indexed: Mapping[str, Any],
    exempt: Mapping[str, Any],
) -> Dict[str, Any]:
    indexed_p50 = float(indexed["measured"]["p50_ms"])
    exempt_p50 = float(exempt["measured"]["p50_ms"])
    indexed_p95 = float(indexed["measured"]["p95_ms"])
    exempt_p95 = float(exempt["measured"]["p95_ms"])

    def reduction(before: float, after: float) -> float | None:
        if before <= 0:
            return None
        return round(((before - after) / before) * 100.0, 2)

    return {
        "p50_reduction_percent": reduction(indexed_p50, exempt_p50),
        "p95_reduction_percent": reduction(indexed_p95, exempt_p95),
        "indexed_to_exempt_p50_ratio": (
            round(indexed_p50 / exempt_p50, 3) if exempt_p50 > 0 else None
        ),
        "indexed_to_exempt_p95_ratio": (
            round(indexed_p95 / exempt_p95, 3) if exempt_p95 > 0 else None
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--source-user-id", required=True)
    parser.add_argument("--source-session-id", required=True)
    parser.add_argument(
        "--source-users-collection",
        default=DEFAULT_SOURCE_USERS_COLLECTION,
    )
    parser.add_argument(
        "--source-sessions-subcollection",
        default=DEFAULT_SOURCE_SESSIONS_SUBCOLLECTION,
    )
    parser.add_argument(
        "--target-users-collection",
        default=DEFAULT_TARGET_USERS_COLLECTION,
    )
    parser.add_argument(
        "--indexed-sessions-subcollection",
        default=DEFAULT_INDEXED_SESSIONS_SUBCOLLECTION,
    )
    parser.add_argument(
        "--exempt-sessions-subcollection",
        default=DEFAULT_EXEMPT_SESSIONS_SUBCOLLECTION,
    )
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--rounds", type=int, default=8)
    parser.add_argument(
        "--mutation-mode",
        choices=("stable", "strategy_leaf_toggle"),
        default="strategy_leaf_toggle",
    )
    parser.add_argument(
        "--variant-order",
        choices=("indexed_first", "exempt_first"),
        default="indexed_first",
        help="Run the reciprocal order in a second trial to bound order drift.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--confirm-isolated-writes",
        action="store_true",
        help="Required acknowledgement that benchmark-only Firestore writes are intended.",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Retain the exact benchmark documents instead of deleting them.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.confirm_isolated_writes:
        raise SystemExit("--confirm-isolated-writes is required")
    if args.warmups < 0 or args.rounds < 2:
        raise SystemExit("warmups must be >= 0 and rounds must be >= 2")
    _validate_isolated_targets(
        source_users_collection=args.source_users_collection,
        source_sessions_subcollection=args.source_sessions_subcollection,
        target_users_collection=args.target_users_collection,
        target_session_groups=(
            args.indexed_sessions_subcollection,
            args.exempt_sessions_subcollection,
        ),
    )

    client = firestore.Client(project=args.project_id)
    source_ref = (
        client.collection(args.source_users_collection)
        .document(args.source_user_id)
        .collection(args.source_sessions_subcollection)
        .document(args.source_session_id)
    )
    source_snapshot = source_ref.get()
    if not source_snapshot.exists:
        raise SystemExit("synthetic source evaluator session was not found")
    source_payload = source_snapshot.to_dict() or {}
    if not str(source_payload.get("user_id") or "").startswith("rc-"):
        raise SystemExit("source session is not an rc-* synthetic evaluator session")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    benchmark_user_id = f"runtime-v7-benchmark-{run_id}"
    benchmark_session_id = f"session-{run_id}"
    payload = _target_payload(
        source_payload,
        benchmark_user_id=benchmark_user_id,
        benchmark_session_id=benchmark_session_id,
    )
    results: list[Dict[str, Any]] = []
    collection_groups = (
        (
            args.indexed_sessions_subcollection,
            args.exempt_sessions_subcollection,
        )
        if args.variant_order == "indexed_first"
        else (
            args.exempt_sessions_subcollection,
            args.indexed_sessions_subcollection,
        )
    )
    refs = [
        client.collection(args.target_users_collection)
        .document(benchmark_user_id)
        .collection(collection_group)
        .document(benchmark_session_id)
        for collection_group in collection_groups
    ]
    cleanup_errors: list[str] = []
    try:
        for collection_group in collection_groups:
            result = _benchmark_one_group(
                client=client,
                project_id=args.project_id,
                users_collection=args.target_users_collection,
                sessions_subcollection=collection_group,
                benchmark_user_id=benchmark_user_id,
                benchmark_session_id=benchmark_session_id,
                payload=payload,
                warmups=args.warmups,
                rounds=args.rounds,
                mutation_mode=args.mutation_mode,
            )
            results.append(result)
    finally:
        if not args.keep:
            for ref in refs:
                try:
                    ref.delete()
                except Exception as exc:  # pragma: no cover - external cleanup failure
                    cleanup_errors.append(f"{type(exc).__name__}: {exc}")

    results_by_group = {
        str(result["collection_group"]): result for result in results
    }
    indexed = results_by_group[args.indexed_sessions_subcollection]
    exempt = results_by_group[args.exempt_sessions_subcollection]
    artifact = {
        "schema_version": "runtime_v7_firestore_persistence_benchmark_v1",
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_id": args.project_id,
        "source": {
            "users_collection": args.source_users_collection,
            "sessions_subcollection": args.source_sessions_subcollection,
            "document_path_hash": _hashed_identifier(source_ref.path),
            "synthetic_evaluator_source": True,
        },
        "targets": {
            "users_collection": args.target_users_collection,
            "indexed_collection_group": args.indexed_sessions_subcollection,
            "state_exempt_collection_group": args.exempt_sessions_subcollection,
            "writes_confirmed_isolated": True,
            "documents_retained": bool(args.keep),
        },
        "method": {
            "write_path": "FirestoreSessionStore.save_session_cas",
            "transaction_semantics": "transactional_read_revision_then_full_document_update",
            "warmups_per_variant": args.warmups,
            "measured_rounds_per_variant": args.rounds,
            "mutation_mode": args.mutation_mode,
            "variant_order": list(collection_groups),
            "index_configuration_managed_externally": True,
        },
        "payload_profile": _payload_profile(payload),
        "results": results,
        "comparison": _comparison(indexed, exempt),
        "cleanup": {
            "requested": not args.keep,
            "completed": bool(not args.keep and not cleanup_errors),
            "errors": cleanup_errors,
        },
        "interpretation_limits": [
            "This measures Firestore CAS persistence only, not complete runtime latency.",
            "One synthetic five-turn evaluator payload is not a production traffic distribution.",
            "The artifact does not prove the external index configuration; record that separately.",
            "Variants run sequentially; use reciprocal-order trials to bound temporal or caching drift.",
            "A compact or delta persistence design was not implemented or benchmarked.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(str(args.output.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
