"""
Provider registry for runtime adapters.

This module keeps provider selection configurable and avoids hardcoded imports.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict

from runtime.gateways.analytics_gateway import AnalyticsGateway
from runtime.gateways.analytics_gateway import BigQueryAnalyticsGateway, MemoryAnalyticsGateway
from runtime.gateways.event_bus_gateway import EventBusGatewayConfig, build_event_bus_gateway
from runtime.storage.postgres_runtime_store import PostgresSessionStore
from runtime.storage.postgres_analytics_writer import DualAnalyticsWriter, PostgresAnalyticsWriter
from runtime.storage.session_store import FirestoreSessionStore, MemorySessionStore, SessionStore

AnalyticsGatewayFactory = Callable[[Dict[str, Any]], AnalyticsGateway]
AnalyticsWriterFactory = Callable[[Dict[str, Any]], Any]
SessionStoreFactory = Callable[[Dict[str, Any]], SessionStore]
EventBusFactory = Callable[[Dict[str, Any]], Any]

_ANALYTICS_GATEWAYS: Dict[str, AnalyticsGatewayFactory] = {}
_ANALYTICS_WRITERS: Dict[str, AnalyticsWriterFactory] = {}
_SESSION_STORES: Dict[str, SessionStoreFactory] = {}
_EVENT_BUSES: Dict[str, EventBusFactory] = {}


def register_analytics_gateway(name: str, factory: AnalyticsGatewayFactory) -> None:
    _ANALYTICS_GATEWAYS[name.lower()] = factory


def register_analytics_writer(name: str, factory: AnalyticsWriterFactory) -> None:
    _ANALYTICS_WRITERS[name.lower()] = factory


def register_session_store(name: str, factory: SessionStoreFactory) -> None:
    _SESSION_STORES[name.lower()] = factory


def register_event_bus(name: str, factory: EventBusFactory) -> None:
    _EVENT_BUSES[name.lower()] = factory


def resolve_analytics_gateway(name: str) -> AnalyticsGatewayFactory:
    return _ANALYTICS_GATEWAYS[name.lower()]


def resolve_analytics_writer(name: str) -> AnalyticsWriterFactory:
    return _ANALYTICS_WRITERS[name.lower()]


def resolve_session_store(name: str) -> SessionStoreFactory:
    return _SESSION_STORES[name.lower()]


def resolve_event_bus(name: str) -> EventBusFactory:
    return _EVENT_BUSES[name.lower()]


def register_default_providers() -> None:
    """
    Register built-in providers.

    BigQuery imports are lazy to avoid coupling for non-BQ deployments.
    """

    if "memory" not in _ANALYTICS_GATEWAYS:
        register_analytics_gateway("memory", lambda _cfg: MemoryAnalyticsGateway())

    if "bigquery" not in _ANALYTICS_GATEWAYS:
        def _bq_gateway(cfg: Dict[str, Any]) -> AnalyticsGateway:
            fallback = MemoryAnalyticsGateway()
            cfg["on_error"] = cfg.get("on_error") or (lambda payload: fallback.enqueue_error_log(
                {
                    "trace_id": payload.get("trace_id") or "bq_error",
                    "session_id": payload.get("session_id") or "bq_error",
                    "user_id": payload.get("user_id") or "bq_error",
                    "ts": payload.get("timestamp"),
                    "error": json.dumps(payload, ensure_ascii=True, default=str),
                }
            ))
            writer_provider = str(cfg.get("provider") or "bigquery").strip().lower()
            writer_factory = cfg.get("writer_factory") or resolve_analytics_writer(writer_provider)
            writer = writer_factory(cfg)
            return BigQueryAnalyticsGateway(writer=writer, fallback=fallback)
        register_analytics_gateway("bigquery", _bq_gateway)

    if "bigquery" not in _ANALYTICS_WRITERS:
        def _bq_writer(cfg: Dict[str, Any]) -> Any:
            from runtime.storage.bigquery.bigquery_client import BigQueryBatchWriter

            return BigQueryBatchWriter(
                config=cfg["writer_config"],
                on_error=cfg.get("on_error"),
            )
        register_analytics_writer("bigquery", _bq_writer)

    if "postgres" not in _ANALYTICS_WRITERS:
        def _pg_writer(cfg: Dict[str, Any]) -> Any:
            return PostgresAnalyticsWriter(
                config=cfg["postgres_writer_config"],
                on_error=cfg.get("on_error"),
            )
        register_analytics_writer("postgres", _pg_writer)

    if "dual" not in _ANALYTICS_WRITERS:
        def _dual_writer(cfg: Dict[str, Any]) -> Any:
            primary = resolve_analytics_writer("bigquery")(cfg)
            secondary = resolve_analytics_writer("postgres")(cfg)
            fail_open = True
            pg_cfg = cfg.get("postgres_writer_config")
            if pg_cfg is not None:
                fail_open = bool(getattr(pg_cfg, "fail_open", True))
            return DualAnalyticsWriter(primary=primary, secondary=secondary, fail_open=fail_open)
        register_analytics_writer("dual", _dual_writer)

    if "memory" not in _SESSION_STORES:
        register_session_store("memory", lambda _cfg: MemorySessionStore())

    if "firestore" not in _SESSION_STORES:
        def _fs_store(cfg: Dict[str, Any]) -> SessionStore:
            return FirestoreSessionStore(config=cfg["firestore_config"], firestore_client=cfg.get("firestore_client"))
        register_session_store("firestore", _fs_store)

    if "postgres" not in _SESSION_STORES:
        def _pg_store(cfg: Dict[str, Any]) -> SessionStore:
            return PostgresSessionStore(config=cfg["postgres_config"])
        register_session_store("postgres", _pg_store)

    if "memory" not in _EVENT_BUSES:
        register_event_bus(
            "memory",
            lambda _cfg: build_event_bus_gateway(EventBusGatewayConfig(provider="memory", enabled=False)),
        )
    if "pubsub" not in _EVENT_BUSES:
        def _pubsub_bus(cfg: Dict[str, Any]) -> Any:
            return build_event_bus_gateway(
                EventBusGatewayConfig(
                    provider="pubsub",
                    enabled=bool(cfg.get("enabled", True)),
                    project_id=cfg.get("project_id"),
                    topic_id=cfg.get("topic_id"),
                )
            )
        register_event_bus("pubsub", _pubsub_bus)
