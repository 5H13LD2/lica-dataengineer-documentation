"""Load runtime configuration files."""

from __future__ import annotations

import json
from dataclasses import asdict
import os
from pathlib import Path
from typing import Any, Dict, Optional

from runtime.gateways.event_bus_gateway import EventBusGatewayConfig
from runtime.shared.llm_types import LLMGatewayConfig, ModelPolicy
from runtime.storage.idempotency_store import IdempotencyStoreConfig
from runtime.storage.postgres_runtime_store import build_postgres_runtime_config
from runtime.storage.postgres_analytics_writer import build_postgres_analytics_config
from runtime.storage.session_store import (
    FirestoreSessionStoreConfig,
    SessionStoreConfig,
    STRATEGY_STATE_FORMAT_NESTED_MAP_V1,
)
from runtime.storage.bigquery.bigquery_client import BQWriterConfig
from configs.config import ENV


def resolve_bu_config_path(
    bu: Optional[str],
    filename: str,
    *,
    base_dir: Optional[Path] = None,
) -> Path:
    """
    Resolve BU-specific config path with fallbacks.

    Search order:
      1) runtime/bu/<bu>/config/<filename>
      2) runtime/bu/gulong/config/<filename>
      3) configs/defaults/<filename>
      4) configs/<filename>
    """
    root = base_dir or Path(__file__).resolve().parents[2]
    bu_key = (bu or "gulong").lower()
    candidates = [
        root / "runtime" / "bu" / bu_key / "config" / filename,
        root / "runtime" / "bu" / "gulong" / "config" / filename,
        root / "configs" / "defaults" / filename,
        root / "configs" / filename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load_session_store_config(path: str | Path) -> SessionStoreConfig:
    """Load SessionStoreConfig from JSON."""
    data = _load_json(Path(path))
    provider = _env("RUNTIME_SESSION_STORE_PROVIDER") or data.get("provider") or data.get("storage_kind") or "firestore"
    firestore_cfg = FirestoreSessionStoreConfig(
        project_id=_env("RUNTIME_FIRESTORE_PROJECT_ID") or data.get("project_id", ""),
        users_collection=_env("RUNTIME_FIRESTORE_USERS_COLLECTION") or data.get("users_collection", "users"),
        sessions_subcollection=_env("RUNTIME_FIRESTORE_SESSIONS_SUBCOLLECTION") or data.get("sessions_subcollection", "sessions"),
        credentials_json=_env("RUNTIME_FIRESTORE_CREDENTIALS_JSON") or data.get("credentials_json"),
        enable_firestore=_env_bool("RUNTIME_FIRESTORE_ENABLED", bool(data.get("enable_firestore", True))),
        strategy_state_format=(
            _env("RUNTIME_V7_FIRESTORE_STRATEGY_STATE_FORMAT")
            or data.get("strategy_state_format")
            or STRATEGY_STATE_FORMAT_NESTED_MAP_V1
        ),
    )
    postgres_cfg = None
    if str(provider).strip().lower() == "postgres":
        postgres_cfg = build_postgres_runtime_config(
            dsn=_env("RUNTIME_POSTGRES_DSN") or _env("DATABASE_URL") or "",
            schema=_env("RUNTIME_POSTGRES_SCHEMA", "runtime_shadow"),
            users_table=_env("RUNTIME_POSTGRES_USERS_TABLE", "users_kv"),
            sessions_table=_env("RUNTIME_POSTGRES_SESSIONS_TABLE", "sessions_kv"),
            idempotency_table=_env("RUNTIME_POSTGRES_IDEMPOTENCY_TABLE", "idempotency_kv"),
            connect_timeout_seconds=_env_int("RUNTIME_POSTGRES_CONNECT_TIMEOUT_SECONDS", 5),
            statement_timeout_ms=_env_int("RUNTIME_POSTGRES_STATEMENT_TIMEOUT_MS", 5000),
            ensure_tables=_env_bool("RUNTIME_POSTGRES_ENSURE_TABLES", True),
        )
    return SessionStoreConfig(provider=provider, firestore=firestore_cfg, postgres=postgres_cfg)


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_model_policy(path: str | Path) -> ModelPolicy:
    """Load ModelPolicy from a JSON config file."""
    data = _load_json(Path(path))
    return ModelPolicy(
        main=[tuple(item) for item in data.get("main", [])],
        main_tool_loop=[tuple(item) for item in data.get("main_tool_loop", [])],
        main_finalize=[tuple(item) for item in data.get("main_finalize", [])],
        slot_extract=[tuple(item) for item in data.get("slot_extract", [])],
        tool_llm=[tuple(item) for item in data.get("tool_llm", [])],
        env_keys=dict(data.get("env_keys", {})),
    )


def load_llm_gateway_config(path: str | Path) -> LLMGatewayConfig:
    """
    Load LLMGatewayConfig from JSON.

    If model_policy_path is provided, it is loaded and attached.
    """
    data = _load_json(Path(path))
    policy_path = data.pop("model_policy_path", None)
    model_policy: Optional[ModelPolicy] = None
    if "model_policy" in data and isinstance(data["model_policy"], dict):
        policy_data = data.pop("model_policy")
        model_policy = ModelPolicy(
            main=[tuple(item) for item in policy_data.get("main", [])],
            main_tool_loop=[tuple(item) for item in policy_data.get("main_tool_loop", [])],
            main_finalize=[tuple(item) for item in policy_data.get("main_finalize", [])],
            slot_extract=[tuple(item) for item in policy_data.get("slot_extract", [])],
            tool_llm=[tuple(item) for item in policy_data.get("tool_llm", [])],
            env_keys=dict(policy_data.get("env_keys", {})),
        )
    elif policy_path:
        model_policy = load_model_policy(policy_path)
    config = LLMGatewayConfig(
        primary_provider=data.get("primary_provider", "openai"),
        fallback_provider=data.get("fallback_provider", "gemini"),
        primary_model=data.get("primary_model", "gpt-4.1"),
        fallback_model=data.get("fallback_model", "gemini-2.5-pro"),
        main_model=data.get("main_model"),
        slot_model=data.get("slot_model"),
        tool_llm_model=data.get("tool_llm_model"),
        temperature=float(data.get("temperature", 0.2)),
        max_tokens=int(data.get("max_tokens", 1500)),
        max_retries=int(data.get("max_retries", 1)),
        timeout_s=float(data.get("timeout_s", 12.0)),
        backoff_base_s=float(data.get("backoff_base_s", 0.4)),
        backoff_jitter_s=float(data.get("backoff_jitter_s", 0.2)),
        hard_fail_closed=bool(data.get("hard_fail_closed", False)),
        log_request_bodies=bool(data.get("log_request_bodies", False)),
        model_policy=model_policy,
    )
    return config


def dump_llm_gateway_config(config: LLMGatewayConfig) -> Dict[str, Any]:
    """Return a JSON-serializable dict for the gateway config."""
    payload = asdict(config)
    return payload


def load_bq_analytics_config(path: str | Path) -> Dict[str, Any]:
    """Load BigQuery analytics writer config from JSON."""
    data = _load_json(Path(path))
    provider = _env("RUNTIME_ANALYTICS_WRITER_PROVIDER") or data.get("provider", "bigquery")
    gateway = _env("RUNTIME_ANALYTICS_GATEWAY") or data.get("gateway", "bigquery")
    enabled = _env_bool("RUNTIME_ANALYTICS_ENABLED", bool(data.get("enabled", False)))
    dataset_id = _env("RUNTIME_ANALYTICS_BQ_DATASET") or data.get("dataset_id", "")
    status = str(_env("STATUS") or "").strip().lower()
    if dataset_id:
        base = dataset_id
        if base.endswith(("_dev", "_live")):
            base = base.rsplit("_", 1)[0]
        suffix = "_live" if status in ("live", "prod") else "_dev"
        dataset_id = f"{base}{suffix}"
    writer_cfg = BQWriterConfig(
        project_id=_env("RUNTIME_ANALYTICS_BQ_PROJECT") or data.get("project_id", ""),
        dataset_id=dataset_id,
        location=_env("RUNTIME_ANALYTICS_BQ_LOCATION") or data.get("location", "asia-southeast1"),
        max_rows=_env_int("RUNTIME_ANALYTICS_BQ_MAX_ROWS", int(data.get("max_rows", 200))),
        max_age_s=float(_env("RUNTIME_ANALYTICS_BQ_MAX_AGE_S", str(data.get("max_age_s", 5.0))) or 5.0),
        retry_max=_env_int("RUNTIME_ANALYTICS_BQ_RETRY_MAX", int(data.get("retry_max", 2))),
        retry_backoff_s=float(_env("RUNTIME_ANALYTICS_BQ_RETRY_BACKOFF_S", str(data.get("retry_backoff_s", 0.5))) or 0.5),
        service_account=_env("RUNTIME_ANALYTICS_BQ_SERVICE_ACCOUNT") or data.get("service_account"),
    )
    postgres_cfg = None
    postgres_dsn = (
        _env("RUNTIME_ANALYTICS_POSTGRES_DSN")
        or _env("RUNTIME_POSTGRES_DSN")
        or _env("DATABASE_URL")
        or ""
    )
    if str(provider).strip().lower() in {"postgres", "dual"} or _env_bool(
        "RUNTIME_ANALYTICS_POSTGRES_ENABLED", False
    ):
        postgres_cfg = build_postgres_analytics_config(
            dsn=postgres_dsn,
            schema=_env("RUNTIME_ANALYTICS_POSTGRES_SCHEMA") or _env("RUNTIME_POSTGRES_SCHEMA", "runtime_shadow"),
            connect_timeout_seconds=_env_int("RUNTIME_ANALYTICS_POSTGRES_CONNECT_TIMEOUT_SECONDS", 5),
            statement_timeout_ms=_env_int("RUNTIME_ANALYTICS_POSTGRES_STATEMENT_TIMEOUT_MS", 5000),
            ensure_tables=_env_bool("RUNTIME_ANALYTICS_POSTGRES_ENSURE_TABLES", True),
            fail_open=_env_bool("RUNTIME_ANALYTICS_POSTGRES_FAIL_OPEN", True),
        )
    return {
        "enabled": enabled,
        "provider": provider,
        "gateway": gateway,
        "writer_config": writer_cfg,
        "postgres_writer_config": postgres_cfg,
    }


def load_tools_provider_config(path: str | Path) -> Dict[str, Any]:
    """Load tools provider config from JSON."""
    data = _load_json(Path(path))
    return {
        "provider": data.get("provider", "gulong"),
        "bu": data.get("bu", "gulong"),
    }


def load_idempotency_store_config(path: str | Path) -> Dict[str, Any]:
    """Load idempotency storage config from JSON."""
    data = _load_json(Path(path))
    provider = (_env("RUNTIME_IDEMPOTENCY_STORE_PROVIDER") or data.get("provider") or "firestore").lower()
    cfg = IdempotencyStoreConfig(
        project_id=_env("RUNTIME_FIRESTORE_PROJECT_ID") or data.get("project_id", ""),
        collection=_env("RUNTIME_IDEMPOTENCY_COLLECTION") or data.get("collection", "runtime_idempotency"),
        credentials_json=_env("RUNTIME_FIRESTORE_CREDENTIALS_JSON") or data.get("credentials_json"),
        enable_firestore=_env_bool("RUNTIME_FIRESTORE_ENABLED", bool(data.get("enable_firestore", True))),
    )
    postgres_cfg = None
    if provider == "postgres":
        postgres_cfg = build_postgres_runtime_config(
            dsn=_env("RUNTIME_POSTGRES_DSN") or _env("DATABASE_URL") or "",
            schema=_env("RUNTIME_POSTGRES_SCHEMA", "runtime_shadow"),
            users_table=_env("RUNTIME_POSTGRES_USERS_TABLE", "users_kv"),
            sessions_table=_env("RUNTIME_POSTGRES_SESSIONS_TABLE", "sessions_kv"),
            idempotency_table=_env("RUNTIME_POSTGRES_IDEMPOTENCY_TABLE", "idempotency_kv"),
            connect_timeout_seconds=_env_int("RUNTIME_POSTGRES_CONNECT_TIMEOUT_SECONDS", 5),
            statement_timeout_ms=_env_int("RUNTIME_POSTGRES_STATEMENT_TIMEOUT_MS", 5000),
            ensure_tables=_env_bool("RUNTIME_POSTGRES_ENSURE_TABLES", True),
        )
    return {
        "provider": provider,
        "ttl_seconds": int(data.get("ttl_seconds", 900)),
        "poll_timeout_s": float(data.get("poll_timeout_s", 2.0)),
        "poll_interval_s": float(data.get("poll_interval_s", 0.2)),
        "store_config": cfg,
        "postgres_config": postgres_cfg,
    }


def load_event_bus_config(path: str | Path) -> EventBusGatewayConfig:
    """Load event-bus config from JSON."""
    data = _load_json(Path(path))
    return EventBusGatewayConfig(
        provider=str(data.get("provider", "memory")).lower(),
        enabled=bool(data.get("enabled", False)),
        project_id=data.get("project_id"),
        topic_id=data.get("topic_id"),
    )


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value is None:
        value = ENV.get(name)
    text = str(value).strip() if value is not None else ""
    return text or default


def _env_bool(name: str, default: bool) -> bool:
    value = _env(name)
    if value is None:
        return bool(default)
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = _env(name)
    if value is None:
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)
