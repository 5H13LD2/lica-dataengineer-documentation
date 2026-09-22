"""Ingress idempotency gateway for duplicate request handling."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from runtime.storage.idempotency_store import IdempotencyBeginResult, IdempotencyStore
from runtime.utils.time_utils import now_manila_str


@dataclass
class IdempotencyDecision:
    action: str
    request_id: str
    message_id: str
    idempotency_key: str
    reason: str = ""
    replay_payload: Optional[Dict[str, Any]] = None


class IdempotencyGateway:
    """Coordinates idempotency store state and replay semantics."""

    def __init__(
        self,
        *,
        store: IdempotencyStore,
        enabled: bool = True,
        ttl_seconds: int = 900,
        poll_timeout_s: float = 2.0,
        poll_interval_s: float = 0.2,
    ) -> None:
        self._store = store
        self._enabled = bool(enabled)
        self._ttl_seconds = max(60, int(ttl_seconds))
        self._poll_timeout_s = max(0.1, float(poll_timeout_s))
        self._poll_interval_s = max(0.05, float(poll_interval_s))

    def begin(
        self,
        *,
        user_id: str,
        message_id: str,
        idempotency_key: str,
        payload: Dict[str, Any],
        request_id: Optional[str] = None,
    ) -> IdempotencyDecision:
        req_id = str(request_id or f"req_{uuid.uuid4().hex}")
        if not self._enabled:
            return IdempotencyDecision(
                action="process",
                request_id=req_id,
                message_id=message_id,
                idempotency_key=idempotency_key,
                reason="idempotency_disabled",
            )

        begin = self._store.begin(
            user_id=user_id,
            idempotency_key=idempotency_key,
            payload_hash=self.payload_hash(payload),
            request_id=req_id,
            message_id=message_id,
            now_ts=now_manila_str(),
            ttl_seconds=self._ttl_seconds,
        )
        return self._decision_from_begin(begin, user_id=user_id, idempotency_key=idempotency_key)

    def complete(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        response_payload: Dict[str, Any],
    ) -> None:
        if not self._enabled:
            return
        self._store.mark_completed(
            user_id=user_id,
            idempotency_key=idempotency_key,
            response_payload=response_payload,
            now_ts=now_manila_str(),
        )

    def fail(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        error_type: str,
    ) -> None:
        if not self._enabled:
            return
        self._store.mark_failed(
            user_id=user_id,
            idempotency_key=idempotency_key,
            error_type=error_type,
            now_ts=now_manila_str(),
        )

    @staticmethod
    def payload_hash(payload: Dict[str, Any]) -> str:
        stable = json.dumps(payload or {}, sort_keys=True, ensure_ascii=True, default=str)
        return hashlib.sha256(stable.encode("utf-8")).hexdigest()

    def _decision_from_begin(
        self,
        begin: IdempotencyBeginResult,
        *,
        user_id: str,
        idempotency_key: str,
    ) -> IdempotencyDecision:
        record = begin.record
        if begin.status == "new":
            return IdempotencyDecision(
                action="process",
                request_id=record.request_id,
                message_id=record.message_id,
                idempotency_key=record.idempotency_key,
                reason="new_request",
            )
        if begin.status == "completed":
            return IdempotencyDecision(
                action="replay",
                request_id=record.request_id,
                message_id=record.message_id,
                idempotency_key=record.idempotency_key,
                replay_payload=record.response_payload,
                reason="completed_duplicate",
            )
        if begin.status == "conflict":
            return IdempotencyDecision(
                action="conflict",
                request_id=record.request_id,
                message_id=record.message_id,
                idempotency_key=record.idempotency_key,
                reason="payload_hash_mismatch",
            )

        deadline = time.monotonic() + self._poll_timeout_s
        while time.monotonic() < deadline:
            polled = self._store.get(user_id=user_id, idempotency_key=idempotency_key)
            if polled and polled.status == "completed" and isinstance(polled.response_payload, dict):
                return IdempotencyDecision(
                    action="replay",
                    request_id=polled.request_id,
                    message_id=polled.message_id,
                    idempotency_key=polled.idempotency_key,
                    replay_payload=polled.response_payload,
                    reason="processing_duplicate_replayed",
                )
            time.sleep(self._poll_interval_s)

        return IdempotencyDecision(
            action="in_progress",
            request_id=record.request_id,
            message_id=record.message_id,
            idempotency_key=record.idempotency_key,
            reason="processing_duplicate_timeout",
        )
