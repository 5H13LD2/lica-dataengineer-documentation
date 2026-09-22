"""Event bus gateway for trace/slot/tool event fanout."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

from configs.log_utils import get_logger

logger = get_logger(__file__, level="INFO")

try:
    from google.cloud import pubsub_v1  # type: ignore
except ImportError:  # pragma: no cover
    pubsub_v1 = None


@dataclass
class EventBusGatewayConfig:
    provider: str = "memory"
    enabled: bool = False
    project_id: Optional[str] = None
    topic_id: Optional[str] = None


class EventBusGateway:
    """Base interface for event bus publishers."""

    def publish(self, *, event_type: str, payload: Dict[str, Any]) -> None:
        raise NotImplementedError

    def publish_many(self, *, event_type: str, payloads: List[Dict[str, Any]]) -> None:
        for payload in payloads or []:
            self.publish(event_type=event_type, payload=payload)


@dataclass
class MemoryEventBusGateway(EventBusGateway):
    max_items: int = 5000
    events: Deque[Dict[str, Any]] = field(default_factory=deque)

    def publish(self, *, event_type: str, payload: Dict[str, Any]) -> None:
        event = {"event_type": event_type, "payload": dict(payload or {})}
        self.events.append(event)
        while len(self.events) > self.max_items:
            self.events.popleft()
        try:
            from apps.platform.state.runtime_state import get_platform_state  # Local fallback sink

            get_platform_state().add_event(str(event_type or "").strip().lower(), dict(payload or {}))
        except Exception:
            pass


class PubSubEventBusGateway(EventBusGateway):
    """Google Pub/Sub event publisher."""

    def __init__(self, *, project_id: str, topic_id: str) -> None:
        self._project_id = project_id
        self._topic_id = topic_id
        self._publisher = pubsub_v1.PublisherClient() if pubsub_v1 is not None else None

    def publish(self, *, event_type: str, payload: Dict[str, Any]) -> None:
        if not self._publisher:
            return
        try:
            topic_path = self._publisher.topic_path(self._project_id, self._topic_id)
            body = json.dumps({"event_type": event_type, "payload": payload}, ensure_ascii=True, default=str)
            self._publisher.publish(topic_path, body.encode("utf-8"))
        except Exception as exc:  # pragma: no cover
            logger.warning("Event publish failed: %s", exc)


def build_event_bus_gateway(config: Optional[EventBusGatewayConfig] = None) -> EventBusGateway:
    cfg = config or EventBusGatewayConfig()
    provider = str(cfg.provider or "memory").strip().lower()
    if not cfg.enabled:
        return MemoryEventBusGateway()
    if provider == "pubsub" and cfg.project_id and cfg.topic_id and pubsub_v1 is not None:
        return PubSubEventBusGateway(project_id=cfg.project_id, topic_id=cfg.topic_id)
    return MemoryEventBusGateway()
