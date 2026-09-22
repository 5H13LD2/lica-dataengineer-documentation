"""Runtime service factories for the Gulong chatbot Cloud Run app."""

from __future__ import annotations

from typing import Callable, Optional

from runtime.gateways.analytics_gateway import AnalyticsGateway, MemoryAnalyticsGateway
from runtime.gateways.idempotency_gateway import IdempotencyGateway
from runtime.gateways.sessions_gateway import SessionsGateway, SessionsGatewayConfig
from runtime.shared.config_loader import (
    load_bq_analytics_config,
    load_idempotency_store_config,
    load_session_store_config,
    resolve_bu_config_path,
)
from runtime.shared.provider_registry import (
    register_default_providers,
    resolve_analytics_gateway,
    resolve_analytics_writer,
    resolve_session_store,
)
from runtime.storage.idempotency_store import FirestoreIdempotencyStore, MemoryIdempotencyStore
from runtime.storage.postgres_runtime_store import PostgresIdempotencyStore


class AnalyticsWriterProtocol:
    """Minimal writer interface for analytics gateways."""

    def enqueue(
        self,
        table: str,
        rows,
        *,
        schema=None,
        key_columns=None,
    ) -> None:  # pragma: no cover - protocol only
        raise NotImplementedError


def build_sessions_gateway(
    config_path: Optional[str] = None,
    *,
    bu: str = "gulong",
) -> SessionsGateway:
    """Build the configured session gateway."""

    register_default_providers()
    resolved_path = resolve_bu_config_path(bu, "session_store.json")
    cfg = load_session_store_config(config_path or resolved_path)
    provider = cfg.provider.lower()
    store_factory = resolve_session_store(provider)
    store = store_factory({"firestore_config": cfg.firestore, "postgres_config": cfg.postgres, "firestore_client": None})
    gateway_config = SessionsGatewayConfig(
        project_id=cfg.firestore.project_id,
        users_collection=cfg.firestore.users_collection,
        sessions_subcollection=cfg.firestore.sessions_subcollection,
        enable_firestore=cfg.firestore.enable_firestore,
        credentials_json=cfg.firestore.credentials_json,
        storage_kind=cfg.provider,
        strategy_state_format=cfg.firestore.strategy_state_format,
    )
    return SessionsGateway(config=gateway_config, store=store)


def build_analytics_gateway(
    config_path: Optional[str] = None,
    *,
    bu: str = "gulong",
    gateway_factory: Optional[Callable[[dict], AnalyticsGateway]] = None,
    writer_factory: Optional[Callable[[dict], AnalyticsWriterProtocol]] = None,
) -> AnalyticsGateway:
    """Build the configured analytics gateway."""

    register_default_providers()
    resolved_path = resolve_bu_config_path(bu, "bq_analytics.json")
    cfg = load_bq_analytics_config(config_path or resolved_path)
    if not cfg.get("enabled", False):
        return MemoryAnalyticsGateway()
    if gateway_factory:
        return gateway_factory(cfg)
    gateway = str(cfg.get("gateway") or "bigquery").lower()
    gateway_factory = resolve_analytics_gateway(gateway)
    if writer_factory:
        cfg["writer_factory"] = writer_factory
    return gateway_factory(cfg)


def build_analytics_writer(
    cfg: dict,
    *,
    writer_factory: Optional[Callable[[dict], AnalyticsWriterProtocol]] = None,
) -> AnalyticsWriterProtocol:
    """Build the configured analytics writer."""

    if writer_factory:
        return writer_factory(cfg)
    provider = str(cfg.get("provider") or "bigquery").lower()
    writer_factory = resolve_analytics_writer(provider)
    return writer_factory(cfg)


def build_idempotency_gateway(
    *,
    bu: str = "gulong",
    config_path: Optional[str] = None,
) -> IdempotencyGateway:
    """Build the configured ingress idempotency gateway."""

    resolved_path = resolve_bu_config_path(bu, "idempotency_store.json")
    cfg = load_idempotency_store_config(config_path or resolved_path)
    provider = str(cfg.get("provider") or "firestore").lower()
    if provider == "memory":
        store = MemoryIdempotencyStore()
    elif provider == "postgres":
        store = PostgresIdempotencyStore(config=cfg["postgres_config"])
    else:
        store = FirestoreIdempotencyStore(config=cfg["store_config"])
    return IdempotencyGateway(
        store=store,
        enabled=True,
        ttl_seconds=int(cfg.get("ttl_seconds") or 900),
        poll_timeout_s=float(cfg.get("poll_timeout_s") or 2.0),
        poll_interval_s=float(cfg.get("poll_interval_s") or 0.2),
    )


def main() -> None:  # pragma: no cover
    raise SystemExit("runtime factories only; use apps.api.main:app")


if __name__ == "__main__":  # pragma: no cover
    main()
