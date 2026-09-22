"""Tests for the staging-only no-model Firestore transport probe."""

from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from apps.api.main import create_app
from apps.api.routers import gulong
from runtime.storage import firestore_transport_probe
from runtime.storage.firestore_transport_probe import (
    ALLOWED_PAYLOAD_KIB,
    PROBE_SESSIONS_SUBCOLLECTION,
    PROBE_USERS_COLLECTION,
    REPRESENTATION_VARIANTS,
    _canonical_json_bytes,
    _decode_representation,
    _encode_representation,
    _generated_payload,
    _generated_runtime_state,
    _json_size_bytes,
    _rotated_variants,
    _shape_profile,
    run_firestore_representation_probe,
)
from runtime.storage.session_store import (
    STRATEGY_STATE_FORMAT_CANONICAL_JSON_V1,
    STRATEGY_STATE_FORMAT_NESTED_MAP_V1,
    _prepare_session_payload_for_firestore,
    _restore_session_payload_from_firestore,
)


class _FakeSnapshot:
    def __init__(self, value):
        self._value = deepcopy(value)
        self.exists = value is not None

    def to_dict(self):
        return deepcopy(self._value)


class _FakeDocumentRef:
    def __init__(self, client, path):
        self._client = client
        self._path = path

    def collection(self, name):
        return _FakeCollectionRef(self._client, self._path + (name,))

    def set(self, value):
        self._client.documents[self._path] = deepcopy(value)

    def get(self):
        return _FakeSnapshot(self._client.documents.get(self._path))

    def delete(self):
        self._client.documents.pop(self._path, None)


class _FakeCollectionRef:
    def __init__(self, client, path):
        self._client = client
        self._path = path

    def document(self, name):
        return _FakeDocumentRef(self._client, self._path + (name,))


class _FakeClient:
    def __init__(self):
        self.documents = {}

    def collection(self, name):
        return _FakeCollectionRef(self, (name,))


class _FakeSessionStore:
    calls = []

    def __init__(self, *, config, firestore_client):
        self._config = config
        self._client = firestore_client
        self._last = {}

    def save_session_cas(
        self, user_id, session_id, expected_revision, data, request_id=None
    ):
        ref = (
            self._client.collection(self._config.users_collection)
            .document(user_id)
            .collection(self._config.sessions_subcollection)
            .document(session_id)
        )
        current = ref.get().to_dict() or {}
        self.__class__.calls.append(
            (session_id.split("-")[1], expected_revision, request_id)
        )
        if int(current.get("revision") or 0) != expected_revision:
            self._last = {"saved": False, "expected_revision": expected_revision}
            return False
        payload = _prepare_session_payload_for_firestore(
            data,
            strategy_state_format=self._config.strategy_state_format,
        )
        payload["revision"] = expected_revision + 1
        payload["last_request_id"] = request_id
        ref.set(payload)
        self._last = {"saved": True, "expected_revision": expected_revision}
        return True

    def save_session(self, user_id, session_id, data):
        ref = (
            self._client.collection(self._config.users_collection)
            .document(user_id)
            .collection(self._config.sessions_subcollection)
            .document(session_id)
        )
        payload = _prepare_session_payload_for_firestore(
            data,
            strategy_state_format=self._config.strategy_state_format,
        )
        ref.set(payload)

    def load_session(self, user_id, session_id):
        ref = (
            self._client.collection(self._config.users_collection)
            .document(user_id)
            .collection(self._config.sessions_subcollection)
            .document(session_id)
        )
        raw = ref.get().to_dict()
        return _restore_session_payload_from_firestore(raw) if raw else None

    def last_save_diagnostics(self):
        return deepcopy(self._last)


def test_generated_transport_payload_is_synthetic_bounded_and_same_shape() -> None:
    first = _generated_payload(payload_kib=40, iteration=1)
    second = _generated_payload(payload_kib=40, iteration=2)

    assert ALLOWED_PAYLOAD_KIB == {40, 140}
    assert "benchmark" in PROBE_USERS_COLLECTION
    assert "benchmark" in PROBE_SESSIONS_SUBCOLLECTION
    assert 35 * 1024 <= _json_size_bytes(first) <= 45 * 1024
    assert first.keys() == second.keys()
    assert (
        first["strategy_state"]["runtime_v7"]["transport_probe_v1"]["fields"].keys()
        == second["strategy_state"]["runtime_v7"]["transport_probe_v1"]["fields"].keys()
    )
    assert first != second


def test_generated_runtime_state_matches_observed_dense_shape() -> None:
    first = _generated_runtime_state(payload_kib=40, iteration=1)
    second = _generated_runtime_state(payload_kib=40, iteration=2)
    profile = _shape_profile(first)

    assert len(_canonical_json_bytes(first)) == 40 * 1024
    assert len(_canonical_json_bytes(second)) == 40 * 1024
    assert profile["scalars"] >= 950
    assert 190 <= profile["maps"] <= 220
    assert 95 <= profile["lists"] <= 110
    assert profile["max_depth"] >= 11
    assert _shape_profile(second) == profile
    assert _canonical_json_bytes(first) != _canonical_json_bytes(second)

    def assert_no_nested_arrays(value) -> None:
        if isinstance(value, dict):
            for child in value.values():
                assert_no_nested_arrays(child)
        elif isinstance(value, list):
            assert not any(isinstance(child, list) for child in value)
            for child in value:
                assert_no_nested_arrays(child)

    assert_no_nested_arrays(first)


def test_representation_encodings_roundtrip_to_identical_state() -> None:
    logical = _generated_runtime_state(payload_kib=40, iteration=7)
    encoded = {}
    for variant in REPRESENTATION_VARIANTS:
        payload, stored_bytes, digest = _encode_representation(
            logical,
            variant=variant,
            user_id="synthetic-user",
            session_id=f"synthetic-{variant}",
            iteration=7,
        )
        encoded[variant] = (payload, stored_bytes, digest)
        assert _decode_representation(payload) == logical

    assert len({entry[2] for entry in encoded.values()}) == 1
    assert encoded["nested_map_v1"][1] == 40 * 1024
    assert encoded["canonical_json_v1"][1] == 40 * 1024
    assert encoded["gzip_json_v1"][1] < 40 * 1024
    assert _rotated_variants(0) == REPRESENTATION_VARIANTS
    assert _rotated_variants(1)[0] == "canonical_json_v1"
    assert _rotated_variants(2)[0] == "gzip_json_v1"


@pytest.mark.parametrize(
    ("configured_format", "opposite_format"),
    (
        (
            STRATEGY_STATE_FORMAT_NESTED_MAP_V1,
            STRATEGY_STATE_FORMAT_CANONICAL_JSON_V1,
        ),
        (
            STRATEGY_STATE_FORMAT_CANONICAL_JSON_V1,
            STRATEGY_STATE_FORMAT_NESTED_MAP_V1,
        ),
    ),
)
def test_representation_probe_preserves_cas_roundtrip_and_cleanup(
    monkeypatch,
    configured_format,
    opposite_format,
) -> None:
    client = _FakeClient()
    _FakeSessionStore.calls = []
    monkeypatch.setattr(
        firestore_transport_probe, "FirestoreSessionStore", _FakeSessionStore
    )

    result = run_firestore_representation_probe(
        project_id="synthetic-project",
        warmups=1,
        rounds=2,
        payload_kib=40,
        configured_strategy_state_format=configured_format,
        firestore_client=client,
    )

    assert result["schema_version"] == "runtime_v7_firestore_representation_probe_v1"
    assert result["method"]["logical_json_bytes"] == 40 * 1024
    assert result["method"]["index_configuration"] == "inherited_default"
    assert result["cleanup"] == {"completed": True, "error_types": []}
    assert result["configured_format_canary"] == {
        "configured_format": configured_format,
        "opposite_seed_format": opposite_format,
        "opposite_seed_succeeded": True,
        "pre_switch_adapter_roundtrip_verified": True,
        "switch_save_succeeded": True,
        "raw_storage_shape_verified": True,
        "post_switch_adapter_roundtrip_verified": True,
        "stale_cas_rejected": True,
        "stale_cas_no_mutation": True,
        "non_cas_create_verified": True,
        "backend_diagnostics": {"saved": True, "expected_revision": 1},
    }
    assert client.documents == {}
    for variant in REPRESENTATION_VARIANTS:
        assert result["variants"][variant]["save"]["count"] == 2
        assert result["variants"][variant]["roundtrip_verified"] is True
        assert result["variants"][variant]["stale_cas_control"]["rejected"] is True
    assert result["variants"]["nested_map_v1"][
        "storage_adapter_roundtrip_verified"
    ] is True
    assert result["variants"]["canonical_json_v1"][
        "storage_adapter_roundtrip_verified"
    ] is True
    assert result["variants"]["gzip_json_v1"][
        "storage_adapter_roundtrip_verified"
    ] is None
    assert sorted(call[1] for call in _FakeSessionStore.calls).count(0) == 4
    assert sorted(call[1] for call in _FakeSessionStore.calls).count(1) == 5
    assert sorted(call[1] for call in _FakeSessionStore.calls).count(2) == 6


def test_transport_probe_is_authenticated_staging_only_and_no_model(monkeypatch) -> None:
    monkeypatch.setenv("FOLLOWUP_WEBHOOK_TOKEN", "transport-probe-secret")
    monkeypatch.setenv("SERVICE_ENVIRONMENT", "staging")
    monkeypatch.setenv("RUNTIME_V7_FIRESTORE_RPC_DIAGNOSTICS", "1")
    calls = []

    def fake_probe(**kwargs):
        calls.append(kwargs)
        return {
            "schema_version": "runtime_v7_firestore_transport_probe_v1",
            "measured": {"count": kwargs["rounds"]},
            "backend_diagnostics": [],
            "cleanup": {"completed": True, "error_type": ""},
        }

    monkeypatch.setattr(gulong, "run_firestore_transport_probe", fake_probe)
    client = TestClient(create_app())
    body = {"warmups": 1, "rounds": 3, "payload_kib": 40}

    assert (
        client.post("/gulong/v7/session-persistence/tester", json=body).status_code
        == 401
    )
    accepted = client.post(
        "/gulong/v7/session-persistence/tester",
        json=body,
        headers={"Authorization": "Bearer transport-probe-secret"},
    )

    assert accepted.status_code == 200
    assert accepted.json()["measured"]["count"] == 3
    assert calls == [
        {
            "project_id": "gulong-chatbot-459723",
            "warmups": 1,
            "rounds": 3,
            "payload_kib": 40,
        }
    ]


def test_transport_probe_stays_disabled_on_live_even_when_flag_is_set(
    monkeypatch,
) -> None:
    monkeypatch.setenv("FOLLOWUP_WEBHOOK_TOKEN", "transport-probe-secret")
    monkeypatch.setenv("SERVICE_ENVIRONMENT", "live")
    monkeypatch.setenv("RUNTIME_V7_FIRESTORE_RPC_DIAGNOSTICS", "1")

    def fail_if_called(**_kwargs):
        raise AssertionError("live must reject the probe before Firestore I/O")

    monkeypatch.setattr(gulong, "run_firestore_transport_probe", fail_if_called)
    client = TestClient(create_app())
    result = client.post(
        "/gulong/v7/session-persistence/tester",
        json={"warmups": 0, "rounds": 2, "payload_kib": 140},
        headers={"Authorization": "Bearer transport-probe-secret"},
    )

    assert result.status_code == 404
    assert result.json()["detail"] == "transport_probe_disabled"


def test_representation_probe_route_is_authenticated_and_staging_only(monkeypatch) -> None:
    monkeypatch.setenv("FOLLOWUP_WEBHOOK_TOKEN", "transport-probe-secret")
    monkeypatch.setenv("SERVICE_ENVIRONMENT", "staging")
    monkeypatch.setenv("RUNTIME_V7_FIRESTORE_RPC_DIAGNOSTICS", "1")
    calls = []

    def fake_probe(**kwargs):
        calls.append(kwargs)
        return {
            "schema_version": "runtime_v7_firestore_representation_probe_v1",
            "cleanup": {"completed": True, "error_types": []},
        }

    monkeypatch.setattr(gulong, "run_firestore_representation_probe", fake_probe)
    client = TestClient(create_app())
    body = {"warmups": 1, "rounds": 3, "payload_kib": 40}

    assert (
        client.post(
            "/gulong/v7/session-persistence/representation-tester", json=body
        ).status_code
        == 401
    )
    accepted = client.post(
        "/gulong/v7/session-persistence/representation-tester",
        json=body,
        headers={"Authorization": "Bearer transport-probe-secret"},
    )

    assert accepted.status_code == 200
    assert calls == [
        {
            "project_id": "gulong-chatbot-459723",
            "warmups": 1,
            "rounds": 3,
            "payload_kib": 40,
            "configured_strategy_state_format": "nested_map_v1",
        }
    ]

    monkeypatch.setenv("SERVICE_ENVIRONMENT", "live")
    rejected = client.post(
        "/gulong/v7/session-persistence/representation-tester",
        json=body,
        headers={"Authorization": "Bearer transport-probe-secret"},
    )
    assert rejected.status_code == 404
    assert len(calls) == 1
