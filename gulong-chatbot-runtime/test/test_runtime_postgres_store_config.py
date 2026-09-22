import json

import pytest

from runtime import runtime_app
from runtime.shared.config_loader import (
    load_bq_analytics_config,
    load_idempotency_store_config,
    load_session_store_config,
)
from runtime.shared import provider_registry
from runtime.storage.postgres_runtime_store import PostgresRuntimeStoreUnavailable, build_postgres_runtime_config


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_session_store_defaults_to_firestore_without_env(tmp_path, monkeypatch):
    monkeypatch.delenv("RUNTIME_SESSION_STORE_PROVIDER", raising=False)
    monkeypatch.delenv("RUNTIME_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("RUNTIME_V7_FIRESTORE_STRATEGY_STATE_FORMAT", raising=False)
    config_path = _write_json(
        tmp_path / "session_store.json",
        {
            "provider": "firestore",
            "project_id": "project-1",
            "users_collection": "users",
            "sessions_subcollection": "sessions",
        },
    )

    cfg = load_session_store_config(config_path)

    assert cfg.provider == "firestore"
    assert cfg.postgres is None
    assert cfg.firestore.project_id == "project-1"
    assert cfg.firestore.strategy_state_format == "nested_map_v1"


def test_session_store_accepts_canonical_strategy_state_env(tmp_path, monkeypatch):
    config_path = _write_json(tmp_path / "session_store.json", {"provider": "firestore"})
    monkeypatch.setenv(
        "RUNTIME_V7_FIRESTORE_STRATEGY_STATE_FORMAT",
        "canonical_json_v1",
    )

    cfg = load_session_store_config(config_path)

    assert cfg.firestore.strategy_state_format == "canonical_json_v1"


def test_session_store_rejects_unknown_strategy_state_env(tmp_path, monkeypatch):
    config_path = _write_json(tmp_path / "session_store.json", {"provider": "firestore"})
    monkeypatch.setenv(
        "RUNTIME_V7_FIRESTORE_STRATEGY_STATE_FORMAT",
        "future-v9",
    )

    with pytest.raises(ValueError, match="unsupported Firestore strategy_state format"):
        load_session_store_config(config_path)


def test_session_store_env_can_select_postgres(tmp_path, monkeypatch):
    config_path = _write_json(tmp_path / "session_store.json", {"provider": "firestore"})
    monkeypatch.setenv("RUNTIME_SESSION_STORE_PROVIDER", "postgres")
    monkeypatch.setenv("RUNTIME_POSTGRES_DSN", "postgresql://runtime:test@127.0.0.1/db")
    monkeypatch.setenv("RUNTIME_POSTGRES_SCHEMA", "runtime_canary")
    monkeypatch.setenv("RUNTIME_POSTGRES_ENSURE_TABLES", "0")

    cfg = load_session_store_config(config_path)

    assert cfg.provider == "postgres"
    assert cfg.postgres is not None
    assert cfg.postgres.schema == "runtime_canary"
    assert cfg.postgres.ensure_tables is False


def test_postgres_provider_requires_dsn(tmp_path, monkeypatch):
    config_path = _write_json(tmp_path / "session_store.json", {"provider": "firestore"})
    monkeypatch.setenv("RUNTIME_SESSION_STORE_PROVIDER", "postgres")
    monkeypatch.delenv("RUNTIME_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(PostgresRuntimeStoreUnavailable):
        load_session_store_config(config_path)


def test_idempotency_store_env_can_select_postgres(tmp_path, monkeypatch):
    config_path = _write_json(tmp_path / "idempotency_store.json", {"provider": "firestore"})
    monkeypatch.setenv("RUNTIME_IDEMPOTENCY_STORE_PROVIDER", "postgres")
    monkeypatch.setenv("RUNTIME_POSTGRES_DSN", "postgresql://runtime:test@127.0.0.1/db")
    monkeypatch.setenv("RUNTIME_POSTGRES_IDEMPOTENCY_TABLE", "runtime_idempotency_kv")

    cfg = load_idempotency_store_config(config_path)

    assert cfg["provider"] == "postgres"
    assert cfg["postgres_config"].idempotency_table == "runtime_idempotency_kv"


def test_postgres_config_rejects_unsafe_identifiers():
    with pytest.raises(ValueError):
        build_postgres_runtime_config(
            dsn="postgresql://runtime:test@127.0.0.1/db",
            schema="runtime_shadow;drop",
        )


def test_build_sessions_gateway_resolves_registered_postgres_provider(tmp_path, monkeypatch):
    class FakeStore:
        def __init__(self, cfg):
            self.cfg = cfg

        def is_available(self):
            return True

    config_path = _write_json(tmp_path / "session_store.json", {"provider": "firestore"})
    monkeypatch.setenv("RUNTIME_SESSION_STORE_PROVIDER", "postgres")
    monkeypatch.setenv("RUNTIME_POSTGRES_DSN", "postgresql://runtime:test@127.0.0.1/db")
    provider_registry.register_session_store("postgres", lambda cfg: FakeStore(cfg))

    gateway = runtime_app.build_sessions_gateway(config_path=str(config_path))

    assert isinstance(gateway._store, FakeStore)
    assert gateway._store.cfg["postgres_config"].dsn.startswith("postgresql://")


def test_build_idempotency_gateway_resolves_postgres_store(tmp_path, monkeypatch):
    class FakeIdempotencyStore:
        def __init__(self, *, config):
            self.config = config

    config_path = _write_json(tmp_path / "idempotency_store.json", {"provider": "firestore"})
    monkeypatch.setenv("RUNTIME_IDEMPOTENCY_STORE_PROVIDER", "postgres")
    monkeypatch.setenv("RUNTIME_POSTGRES_DSN", "postgresql://runtime:test@127.0.0.1/db")
    monkeypatch.setattr(runtime_app, "PostgresIdempotencyStore", FakeIdempotencyStore)

    gateway = runtime_app.build_idempotency_gateway(config_path=str(config_path))

    assert isinstance(gateway._store, FakeIdempotencyStore)
    assert gateway._store.config.dsn.startswith("postgresql://")


def test_analytics_env_can_select_dual_postgres_writer(tmp_path, monkeypatch):
    config_path = tmp_path / "bq_analytics.json"
    config_path.write_text(
        """
        {
          "enabled": false,
          "provider": "bigquery",
          "gateway": "bigquery",
          "project_id": "gulong-chatbot-459723",
          "dataset_id": "gulong_chatbot",
          "location": "asia-southeast1"
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("RUNTIME_ANALYTICS_ENABLED", "true")
    monkeypatch.setenv("RUNTIME_ANALYTICS_WRITER_PROVIDER", "dual")
    monkeypatch.setenv("RUNTIME_ANALYTICS_POSTGRES_DSN", "postgresql://runtime:test@127.0.0.1/db")
    monkeypatch.setenv("RUNTIME_ANALYTICS_POSTGRES_SCHEMA", "runtime_shadow")

    cfg = load_bq_analytics_config(config_path)

    assert cfg["enabled"] is True
    assert cfg["provider"] == "dual"
    assert cfg["postgres_writer_config"].schema == "runtime_shadow"
