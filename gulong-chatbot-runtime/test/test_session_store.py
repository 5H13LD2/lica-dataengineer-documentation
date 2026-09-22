"""Session-store persistence contract tests."""

from copy import deepcopy
from datetime import datetime
import hashlib

from google.api_core import exceptions as google_exceptions
from google.api_core.retry import Retry
from google.cloud import firestore
import pytest

from runtime.gateways.sessions_gateway import (
    SessionsGateway,
    SessionsGatewayConfig,
)
from runtime.storage import session_store as session_store_module
from runtime.storage.session_store import FirestoreSessionStore
from runtime.storage.session_store import FirestoreSessionStoreConfig
from runtime.storage.session_store import MemorySessionStore
from runtime.storage.session_store import StrategyStateStorageError
from runtime.storage.session_store import STRATEGY_STATE_FORMAT_CANONICAL_JSON_V1
from runtime.storage.session_store import STRATEGY_STATE_FORMAT_NESTED_MAP_V1
from runtime.storage.session_store import STRATEGY_STATE_JSON_FIELD_V1
from runtime.storage.session_store import _add_strategy_state_representation_deletes
from runtime.storage.session_store import _FIRESTORE_RPC_TRACE_CONTEXT
from runtime.storage.session_store import _begin_save_activity
from runtime.storage.session_store import _clear_owned_session_lock, _replace_session_document_in_transaction
from runtime.storage.session_store import _end_save_activity
from runtime.storage.session_store import _install_firestore_rpc_observer
from runtime.storage.session_store import _prepare_session_payload_for_firestore
from runtime.storage.session_store import _restore_session_payload_from_firestore
from runtime.storage.session_store import _session_save_diagnostics


class _FakeWrappedMethod:
    def __init__(self, target) -> None:
        self._target = target


class _FakeFirestoreTransport:
    def __init__(self, begin_target, commit_target) -> None:
        self.begin_transaction = object()
        self.commit = object()
        self._wrapped_methods = {
            self.begin_transaction: _FakeWrappedMethod(begin_target),
            self.commit: _FakeWrappedMethod(commit_target),
        }


class _FakeFirestoreAPI:
    def __init__(self, transport) -> None:
        self._transport = transport


class _FakeFirestoreClient:
    def __init__(self, transport) -> None:
        self._firestore_api = _FakeFirestoreAPI(transport)


class RecordingTransaction:
    def __init__(self) -> None:
        self.calls = []

    def update(self, reference, payload) -> None:
        self.calls.append(("update", reference, payload))

    def set(self, reference, payload, **kwargs) -> None:
        self.calls.append(("set", reference, payload, kwargs))


class _StateSnapshot:
    def __init__(self, value) -> None:
        self._value = deepcopy(value)
        self.exists = value is not None

    def to_dict(self):
        return deepcopy(self._value)


class _StateDocumentRef:
    def __init__(self, client, path) -> None:
        self._client = client
        self._path = path

    def collection(self, name):
        return _StateCollectionRef(self._client, self._path + (name,))

    def get(self, transaction=None):
        del transaction
        return _StateSnapshot(self._client.documents.get(self._path))

    def set(self, payload, merge=False):
        current = (
            deepcopy(self._client.documents.get(self._path) or {})
            if merge
            else {}
        )
        for key, value in payload.items():
            if value is firestore.DELETE_FIELD:
                current.pop(key, None)
            else:
                current[key] = deepcopy(value)
        self._client.documents[self._path] = current


class _StateCollectionRef:
    def __init__(self, client, path) -> None:
        self._client = client
        self._path = path

    def document(self, name):
        return _StateDocumentRef(self._client, self._path + (name,))


class _StateTransaction:
    def update(self, reference, payload) -> None:
        reference.set(payload, merge=True)

    def set(self, reference, payload, merge=False) -> None:
        reference.set(payload, merge=merge)


class _StateClient:
    def __init__(self) -> None:
        self.documents = {}

    def collection(self, name):
        return _StateCollectionRef(self, (name,))

    def transaction(self):
        return _StateTransaction()


def _state_store(client, strategy_state_format):
    return FirestoreSessionStore(
        config=FirestoreSessionStoreConfig(
            project_id="test",
            users_collection="users",
            sessions_subcollection="sessions",
            strategy_state_format=strategy_state_format,
        ),
        firestore_client=client,
    )


def test_strategy_state_legacy_format_preserves_stable_runtime_contract() -> None:
    state = {"runtime_v7": {"turn": 3}}
    stored = _prepare_session_payload_for_firestore(
        {"revision": 2, "strategy_state": state},
        strategy_state_format=STRATEGY_STATE_FORMAT_NESTED_MAP_V1,
    )

    assert stored == {"revision": 2, "strategy_state": state}
    assert _restore_session_payload_from_firestore(stored) == stored


def test_strategy_state_canonical_json_roundtrip_strips_storage_metadata() -> None:
    state = {"z": [1, {"value": "two"}], "a": {"enabled": True}}
    stored = _prepare_session_payload_for_firestore(
        {"revision": 4, "strategy_state": state},
        strategy_state_format=STRATEGY_STATE_FORMAT_CANONICAL_JSON_V1,
    )

    assert "strategy_state" not in stored
    assert stored[STRATEGY_STATE_JSON_FIELD_V1] == (
        '{"a":{"enabled":true},"z":[1,{"value":"two"}]}'
    )
    assert stored["strategy_state_encoding"] == "canonical_json_v1"
    assert stored["strategy_state_schema_version"] == 1
    assert len(stored["strategy_state_sha256"]) == 64
    assert _restore_session_payload_from_firestore(stored) == {
        "revision": 4,
        "strategy_state": state,
    }


def test_strategy_state_canonical_metadata_wins_over_stale_legacy_map() -> None:
    stored = _prepare_session_payload_for_firestore(
        {"revision": 8, "strategy_state": {"canonical": True}},
        strategy_state_format=STRATEGY_STATE_FORMAT_CANONICAL_JSON_V1,
    )
    stored["strategy_state"] = {"legacy": True}

    restored = _restore_session_payload_from_firestore(stored)

    assert restored == {
        "revision": 8,
        "strategy_state": {"canonical": True},
    }


@pytest.mark.parametrize(
    ("stored", "reason"),
    [
        (
            {
                "strategy_state_encoding": "canonical_json_v1",
                STRATEGY_STATE_JSON_FIELD_V1: "{bad-json",
                "strategy_state_schema_version": 1,
                "strategy_state_sha256": hashlib.sha256(
                    b"{bad-json"
                ).hexdigest(),
            },
            "strategy_state_json_invalid",
        ),
        (
            {
                "strategy_state_encoding": "canonical_json_v1",
                STRATEGY_STATE_JSON_FIELD_V1: "{}",
                "strategy_state_schema_version": 1,
                "strategy_state_sha256": "incorrect",
            },
            "strategy_state_hash_mismatch",
        ),
        (
            {
                "strategy_state_encoding": "future_format_v9",
                STRATEGY_STATE_JSON_FIELD_V1: "{}",
            },
            "strategy_state_encoding_unknown",
        ),
        (
            {
                "strategy_state_encoding": "canonical_json_v1",
                STRATEGY_STATE_JSON_FIELD_V1: "[1,2]",
                "strategy_state_schema_version": 1,
                "strategy_state_sha256": hashlib.sha256(b"[1,2]").hexdigest(),
            },
            "strategy_state_shape_invalid",
        ),
        (
            {
                "strategy_state_encoding": "canonical_json_v1",
                STRATEGY_STATE_JSON_FIELD_V1: "{}",
                "strategy_state_schema_version": 1,
            },
            "strategy_state_hash_missing",
        ),
        (
            {
                "strategy_state_encoding": "canonical_json_v1",
                STRATEGY_STATE_JSON_FIELD_V1: "{}",
                "strategy_state_schema_version": 2,
                "strategy_state_sha256": hashlib.sha256(b"{}").hexdigest(),
            },
            "strategy_state_schema_unknown",
        ),
    ],
)
def test_strategy_state_corruption_fails_closed_without_content(stored, reason) -> None:
    with pytest.raises(StrategyStateStorageError) as captured:
        _restore_session_payload_from_firestore(stored)

    assert str(captured.value) == reason
    assert "bad-json" not in str(captured.value)


def test_strategy_state_format_rejects_unknown_configuration() -> None:
    with pytest.raises(ValueError, match="unsupported Firestore strategy_state format"):
        FirestoreSessionStoreConfig(
            project_id="test",
            users_collection="users",
            sessions_subcollection="sessions",
            strategy_state_format="unknown-v9",
        )


@pytest.mark.parametrize(
    "invalid_state",
    [
        {"value": float("nan")},
        {"value": datetime(2026, 9, 12)},
        {"value": b"bytes"},
    ],
)
def test_canonical_strategy_state_rejects_non_json_native_values(
    invalid_state,
) -> None:
    with pytest.raises(
        StrategyStateStorageError,
        match="strategy_state_not_json_native",
    ):
        _prepare_session_payload_for_firestore(
            {"strategy_state": invalid_state},
            strategy_state_format=STRATEGY_STATE_FORMAT_CANONICAL_JSON_V1,
        )


def test_canonical_strategy_state_rejects_recursive_values() -> None:
    recursive = {}
    recursive["self"] = recursive

    with pytest.raises(
        StrategyStateStorageError,
        match="strategy_state_not_json_native",
    ):
        _prepare_session_payload_for_firestore(
            {"strategy_state": recursive},
            strategy_state_format=STRATEGY_STATE_FORMAT_CANONICAL_JSON_V1,
        )


def test_representation_switch_adds_atomic_opposite_field_deletes() -> None:
    sentinel = object()
    canonical = _prepare_session_payload_for_firestore(
        {"strategy_state": {"turn": 1}},
        strategy_state_format=STRATEGY_STATE_FORMAT_CANONICAL_JSON_V1,
    )
    canonical_write = _add_strategy_state_representation_deletes(
        canonical,
        strategy_state_format=STRATEGY_STATE_FORMAT_CANONICAL_JSON_V1,
        delete_field=sentinel,
    )
    legacy_write = _add_strategy_state_representation_deletes(
        {"strategy_state": {"turn": 2}},
        strategy_state_format=STRATEGY_STATE_FORMAT_NESTED_MAP_V1,
        delete_field=sentinel,
    )

    assert canonical_write["strategy_state"] is sentinel
    assert isinstance(canonical_write[STRATEGY_STATE_JSON_FIELD_V1], str)
    assert legacy_write[STRATEGY_STATE_JSON_FIELD_V1] is sentinel
    assert legacy_write["strategy_state_encoding"] is sentinel
    assert legacy_write["strategy_state_schema_version"] is sentinel
    assert legacy_write["strategy_state_sha256"] is sentinel


def test_existing_session_write_replaces_top_level_state_maps() -> None:
    transaction = RecordingTransaction()
    payload = {"strategy_state": {"runtime_v7": {"active_working_memory": {"metadata": {}}}}}

    _replace_session_document_in_transaction(transaction, "session-ref", payload, exists=True)

    assert transaction.calls == [("update", "session-ref", payload)]


def test_new_session_write_creates_complete_document_without_merge() -> None:
    transaction = RecordingTransaction()
    payload = {"revision": 1, "strategy_state": {}}

    _replace_session_document_in_transaction(transaction, "session-ref", payload, exists=False)

    assert transaction.calls == [("set", "session-ref", payload, {})]


def test_new_session_write_omits_delete_sentinels_but_existing_write_keeps_them() -> None:
    new_transaction = RecordingTransaction()
    existing_transaction = RecordingTransaction()
    payload = {
        "revision": 1,
        "strategy_state": firestore.DELETE_FIELD,
        STRATEGY_STATE_JSON_FIELD_V1: "{}",
    }

    _replace_session_document_in_transaction(
        new_transaction,
        "session-ref",
        payload,
        exists=False,
    )
    _replace_session_document_in_transaction(
        existing_transaction,
        "session-ref",
        payload,
        exists=True,
    )

    assert new_transaction.calls == [
        (
            "set",
            "session-ref",
            {"revision": 1, STRATEGY_STATE_JSON_FIELD_V1: "{}"},
            {},
        )
    ]
    assert existing_transaction.calls == [("update", "session-ref", payload)]


def test_strategy_state_switch_preserves_cas_lock_and_inbox_contracts(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        session_store_module.firestore,
        "transactional",
        lambda function: function,
    )
    client = _StateClient()
    nested_store = _state_store(client, STRATEGY_STATE_FORMAT_NESTED_MAP_V1)
    canonical_store = _state_store(
        client,
        STRATEGY_STATE_FORMAT_CANONICAL_JSON_V1,
    )
    user_id = "synthetic-user"
    session_id = "synthetic-session"
    initial_inbox = [{"event_id": "evt-1", "kind": "choice"}]
    nested_store.save_session(
        user_id,
        session_id,
        {
            "revision": 0,
            "strategy_state": {"turn": 1},
            "interaction_inbox_v1": initial_inbox,
            "active_lock_owner": None,
            "active_lock_until": None,
        },
    )

    assert canonical_store.load_session(user_id, session_id)["strategy_state"] == {
        "turn": 1
    }
    assert canonical_store.save_session_cas(
        user_id,
        session_id,
        0,
        {"strategy_state": {"turn": 2}},
        request_id="request-1",
    )
    path = ("users", user_id, "sessions", session_id)
    canonical_raw = deepcopy(client.documents[path])
    assert "strategy_state" not in canonical_raw
    assert isinstance(canonical_raw[STRATEGY_STATE_JSON_FIELD_V1], str)
    assert canonical_raw["interaction_inbox_v1"] == initial_inbox

    assert not canonical_store.save_session_cas(
        user_id,
        session_id,
        0,
        {"strategy_state": {"turn": 999}},
        request_id="stale-request",
    )
    assert client.documents[path] == canonical_raw

    assert canonical_store.acquire_session_lock(
        user_id,
        session_id,
        owner="lock-owner",
        lock_until="2026-09-12 14:05:00+08:00",
        now="2026-09-12 14:00:00+08:00",
    )
    canonical_store.release_session_lock(
        user_id,
        session_id,
        owner="lock-owner",
    )
    assert canonical_store.record_interaction_event(
        user_id,
        session_id,
        {"event_id": "evt-2", "kind": "choice"},
        max_events=5,
    )
    canonical_store.remove_interaction_events(
        user_id,
        session_id,
        event_ids=["evt-2"],
    )
    after_partial_writes = client.documents[path]
    for field_name in (
        STRATEGY_STATE_JSON_FIELD_V1,
        "strategy_state_encoding",
        "strategy_state_schema_version",
        "strategy_state_sha256",
    ):
        assert after_partial_writes[field_name] == canonical_raw[field_name]
    assert after_partial_writes["interaction_inbox_v1"] == initial_inbox

    assert nested_store.load_session(user_id, session_id)["strategy_state"] == {
        "turn": 2
    }
    assert nested_store.save_session_cas(
        user_id,
        session_id,
        1,
        {"strategy_state": {"turn": 3}},
        request_id="request-2",
    )
    nested_raw = client.documents[path]
    assert nested_raw["strategy_state"] == {"turn": 3}
    assert STRATEGY_STATE_JSON_FIELD_V1 not in nested_raw
    assert "strategy_state_encoding" not in nested_raw
    assert "strategy_state_schema_version" not in nested_raw
    assert "strategy_state_sha256" not in nested_raw
    assert nested_raw["interaction_inbox_v1"] == initial_inbox


def test_session_cas_clears_only_the_owned_turn_lock() -> None:
    owned_payload = {"strategy_state": {}}
    _clear_owned_session_lock(
        owned_payload,
        existing={"active_lock_owner": "req-1", "active_lock_until": "later"},
        owner="req-1",
    )
    other_payload = {"strategy_state": {}}
    _clear_owned_session_lock(
        other_payload,
        existing={"active_lock_owner": "req-2", "active_lock_until": "later"},
        owner="req-1",
    )

    assert owned_payload["active_lock_owner"] is None
    assert owned_payload["active_lock_until"] is None
    assert "active_lock_owner" not in other_payload
    assert "active_lock_until" not in other_payload


def test_session_save_diagnostics_are_bounded_and_content_free() -> None:
    diagnostics = _session_save_diagnostics(
        total_ms=2050.5,
        attempts=[
            {"read_ms": 125.25, "transaction_body_ms": 130.0},
            {"read_ms": 100.0, "transaction_body_ms": 105.0},
        ],
        payload={
            "revision": 4,
            "strategy_state": {"runtime_v7": {"secret_text": "not exposed"}},
        },
        expected_revision=4,
        saved=True,
        include_payload_sizes=True,
    )

    assert diagnostics["attempt_count"] == 2
    assert diagnostics["read_ms"] == [125.25, 100.0]
    assert diagnostics["commit_retry_overhead_ms"] == 1815.5
    assert diagnostics["payload_json_bytes"] > diagnostics["strategy_state_json_bytes"]
    assert "secret_text" not in str(diagnostics)


def test_session_save_diagnostics_skip_payload_serialization_by_default(
    monkeypatch,
) -> None:
    def fail_if_called(value):
        raise AssertionError(f"unexpected payload serialization: {value!r}")

    monkeypatch.setattr(
        "runtime.storage.session_store._diagnostic_json_size",
        fail_if_called,
    )

    diagnostics = _session_save_diagnostics(
        total_ms=50.0,
        attempts=[{"read_ms": 10.0, "transaction_body_ms": 12.0}],
        payload={"strategy_state": {"runtime_v7": {"text": "not read"}}},
        expected_revision=1,
        saved=True,
    )

    assert diagnostics["payload_sizes_measured"] is False
    assert diagnostics["payload_json_bytes"] == 0
    assert diagnostics["strategy_state_json_bytes"] == 0


def test_firestore_rpc_observer_records_each_retry_without_changing_policy(
    monkeypatch,
) -> None:
    monkeypatch.setitem(
        __import__("runtime.storage.session_store", fromlist=["ENV"]).ENV,
        "SERVICE_ENVIRONMENT",
        "staging",
    )
    monkeypatch.setitem(
        __import__("runtime.storage.session_store", fromlist=["ENV"]).ENV,
        "RUNTIME_V7_FIRESTORE_RPC_DIAGNOSTICS",
        "1",
    )
    calls = 0

    def commit_target(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise google_exceptions.ServiceUnavailable("transient")
        return "committed"

    transport = _FakeFirestoreTransport(lambda *_a, **_k: "begun", commit_target)
    client = _FakeFirestoreClient(transport)

    assert _install_firestore_rpc_observer(client) == "active"
    attempts = []
    activity = _begin_save_activity()
    token = _FIRESTORE_RPC_TRACE_CONTEXT.set(
        {
            "observation_id": activity["observation_id"],
            "activity": activity,
            "attempts": attempts,
        }
    )
    try:
        observed_commit = transport._wrapped_methods[transport.commit]._target
        result = Retry(
            predicate=lambda exc: isinstance(
                exc,
                google_exceptions.ServiceUnavailable,
            ),
            initial=0,
            maximum=0,
            multiplier=1,
            timeout=1,
        )(observed_commit)()
    finally:
        _FIRESTORE_RPC_TRACE_CONTEXT.reset(token)
        _end_save_activity(activity)

    assert result == "committed"
    assert calls == 2
    assert [item["outcome"] for item in attempts] == ["error", "success"]
    assert attempts[0]["gapic_default_retryable"] is True
    assert attempts[0]["transactional_retryable"] is False
    assert attempts[0]["error_type"] == "ServiceUnavailable"
    assert all("transient" not in str(item) for item in attempts)


def test_firestore_rpc_observer_rethrows_same_nonretryable_exception(
    monkeypatch,
) -> None:
    monkeypatch.setitem(
        __import__("runtime.storage.session_store", fromlist=["ENV"]).ENV,
        "SERVICE_ENVIRONMENT",
        "staging",
    )
    monkeypatch.setitem(
        __import__("runtime.storage.session_store", fromlist=["ENV"]).ENV,
        "RUNTIME_V7_FIRESTORE_RPC_DIAGNOSTICS",
        "1",
    )
    expected = google_exceptions.InvalidArgument("must stay private")

    def commit_target(*_args, **_kwargs):
        raise expected

    transport = _FakeFirestoreTransport(lambda *_a, **_k: "begun", commit_target)
    client = _FakeFirestoreClient(transport)
    _install_firestore_rpc_observer(client)
    attempts = []
    token = _FIRESTORE_RPC_TRACE_CONTEXT.set(
        {"observation_id": "test", "activity": {}, "attempts": attempts}
    )
    try:
        observed_commit = transport._wrapped_methods[transport.commit]._target
        with pytest.raises(google_exceptions.InvalidArgument) as captured:
            observed_commit(object())
    finally:
        _FIRESTORE_RPC_TRACE_CONTEXT.reset(token)

    assert captured.value is expected
    assert attempts[0]["outcome"] == "error"
    assert attempts[0]["gapic_default_retryable"] is False
    assert "must stay private" not in str(attempts)


def test_session_save_diagnostics_decomposes_rpc_and_process_time() -> None:
    diagnostics = _session_save_diagnostics(
        total_ms=30_000.0,
        attempts=[{"read_ms": 100.0, "transaction_body_ms": 500.0}],
        rpc_attempts=[
            {
                "operation": "begin_transaction",
                "elapsed_ms": 100.0,
                "outcome": "success",
            },
            {
                "operation": "commit",
                "elapsed_ms": 10_000.0,
                "outcome": "error",
                "error_type": "ServiceUnavailable",
                "status_code": "UNAVAILABLE",
                "gapic_default_retryable": True,
            },
            {
                "operation": "commit",
                "elapsed_ms": 15_000.0,
                "outcome": "success",
                "process_cpu_ms": 14_000.0,
                "thread_cpu_ms": 500.0,
                "other_threads_cpu_ms": 13_500.0,
                "user_cpu_ms": 13_000.0,
                "system_cpu_ms": 1_000.0,
                "minor_page_faults": 12,
                "major_page_faults": 1,
                "voluntary_context_switches": 30,
                "involuntary_context_switches": 4,
                "gc_collections": [2, 1, 0],
                "gc_collected": [20, 5, 0],
            },
        ],
        runtime_context={
            "rpc_observer_status": "active",
            "observation_id": "123-4",
            "process_id": 123,
            "instance_id_hash": "abc123",
            "active_saves_at_start": 2,
            "active_saves_before_end": 2,
            "process_peak_active_saves": 2,
            "process_cpu_ms": 600.0,
        },
        payload={"strategy_state": {}},
        expected_revision=1,
        saved=True,
    )

    assert diagnostics["begin_rpc_attempt_count"] == 1
    assert diagnostics["commit_rpc_attempt_count"] == 2
    assert diagnostics["commit_rpc_attempt_ms"] == [10_000.0, 15_000.0]
    assert diagnostics["commit_rpc_outcomes"] == ["error", "success"]
    assert diagnostics["commit_rpc_gapic_retryable"] == [True, False]
    assert diagnostics["commit_rpc_process_cpu_ms"] == [0.0, 14_000.0]
    assert diagnostics["commit_rpc_thread_cpu_ms"] == [0.0, 500.0]
    assert diagnostics["commit_rpc_other_threads_cpu_ms"] == [0.0, 13_500.0]
    assert diagnostics["commit_rpc_gc_collections"] == [[], [2, 1, 0]]
    assert diagnostics["commit_rpc_gc_collected"] == [[], [20, 5, 0]]
    assert diagnostics["commit_rpc_major_page_faults"] == [0, 1]
    assert diagnostics["rpc_unattributed_ms"] == 4_400.0
    assert diagnostics["process_cpu_to_wall_percent"] == 2.0
    assert diagnostics["active_saves_at_start"] == 2


def test_superseded_turn_save_cannot_reactivate_session_after_reset() -> None:
    store = MemorySessionStore()
    gateway = SessionsGateway(
        config=SessionsGatewayConfig(
            project_id="test",
            users_collection="users",
            sessions_subcollection="sessions",
            storage_kind="memory",
        ),
        store=store,
    )
    old = gateway.load(user_id="trial")
    current = gateway.load(user_id="trial", reset=True)

    saved = gateway.save(
        user_doc=old.user_doc,
        session_doc=old.session_doc,
    )

    assert saved is True
    assert old.session_doc.session_id != current.session_doc.session_id
    assert store.load_user("trial")["active_session_id"] == (
        current.session_doc.session_id
    )


def test_prelock_interaction_inbox_is_bounded_and_preserves_turn_lock() -> None:
    store = MemorySessionStore()
    gateway = SessionsGateway(
        config=SessionsGatewayConfig(
            project_id="test",
            users_collection="users",
            sessions_subcollection="sessions",
            storage_kind="memory",
        ),
        store=store,
    )
    loaded = gateway.load(user_id="trial")
    session_id = loaded.session_doc.session_id
    acquired, _ = gateway.acquire_lock(
        user_id="trial",
        session_id=session_id,
        owner="req-1",
    )

    for index in range(4):
        assert gateway.record_interaction_event(
            user_id="trial",
            session_id=session_id,
            event={
                "event_id": f"evt-{index}",
                "received_at": f"2026-07-28 10:00:0{index}",
            },
            max_events=3,
        )
    gateway.record_interaction_event(
        user_id="trial",
        session_id=session_id,
        event={
            "event_id": "evt-3",
            "received_at": "2026-07-28 10:00:09",
        },
        max_events=3,
    )

    assert acquired is True
    stored = store.load_session("trial", session_id)
    assert stored["active_lock_owner"] == "req-1"
    assert [
        item["event_id"]
        for item in gateway.load_interaction_events(
            user_id="trial",
            session_id=session_id,
        )
    ] == ["evt-1", "evt-2", "evt-3"]
    assert gateway.load_interaction_events(
        user_id="trial",
        session_id=session_id,
    )[-1]["received_at"] == "2026-07-28 10:00:09"

    gateway.remove_interaction_events(
        user_id="trial",
        session_id=session_id,
        event_ids=["evt-1", "evt-3"],
    )

    assert [
        item["event_id"]
        for item in gateway.load_interaction_events(
            user_id="trial",
            session_id=session_id,
        )
    ] == ["evt-2"]
