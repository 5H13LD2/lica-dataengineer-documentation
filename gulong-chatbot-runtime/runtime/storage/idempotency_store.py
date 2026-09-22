"""Idempotency persistence backends for inbound request dedupe."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from configs.log_utils import get_logger, manila_tz

try:
    from google.cloud import firestore  # type: ignore
    from google.oauth2 import service_account  # type: ignore
except ImportError:  # pragma: no cover
    firestore = None
    service_account = None

logger = get_logger(__file__, level="INFO")


@dataclass
class IdempotencyStoreConfig:
    project_id: str
    collection: str = "runtime_idempotency"
    credentials_json: Optional[str] = None
    enable_firestore: bool = True


@dataclass
class IdempotencyRecord:
    user_id: str
    idempotency_key: str
    message_id: str
    request_id: str
    payload_hash: str
    status: str
    created_at: str
    updated_at: str
    expires_at: str
    response_payload: Optional[Dict[str, Any]] = None
    error_type: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "idempotency_key": self.idempotency_key,
            "message_id": self.message_id,
            "request_id": self.request_id,
            "payload_hash": self.payload_hash,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "response_payload": self.response_payload,
            "error_type": self.error_type,
        }


@dataclass
class IdempotencyBeginResult:
    status: str
    record: IdempotencyRecord


class IdempotencyStore:
    """Store abstraction for idempotency records."""

    def begin(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        payload_hash: str,
        request_id: str,
        message_id: str,
        now_ts: str,
        ttl_seconds: int,
    ) -> IdempotencyBeginResult:
        raise NotImplementedError

    def get(self, *, user_id: str, idempotency_key: str) -> Optional[IdempotencyRecord]:
        raise NotImplementedError

    def mark_completed(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        response_payload: Dict[str, Any],
        now_ts: str,
    ) -> Optional[IdempotencyRecord]:
        raise NotImplementedError

    def mark_failed(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        error_type: str,
        now_ts: str,
    ) -> Optional[IdempotencyRecord]:
        raise NotImplementedError


class MemoryIdempotencyStore(IdempotencyStore):
    """In-memory idempotency store for tests/local fallback."""

    def __init__(self) -> None:
        self._records: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _key(self, user_id: str, idempotency_key: str) -> str:
        return f"{user_id}:{idempotency_key}"

    def begin(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        payload_hash: str,
        request_id: str,
        message_id: str,
        now_ts: str,
        ttl_seconds: int,
    ) -> IdempotencyBeginResult:
        with self._lock:
            key = self._key(user_id, idempotency_key)
            existing = self._records.get(key)
            if not existing:
                record = IdempotencyRecord(
                    user_id=user_id,
                    idempotency_key=idempotency_key,
                    message_id=message_id,
                    request_id=request_id,
                    payload_hash=payload_hash,
                    status="processing",
                    created_at=now_ts,
                    updated_at=now_ts,
                    expires_at=_expiry_ts(now_ts, ttl_seconds),
                )
                self._records[key] = record.to_dict()
                return IdempotencyBeginResult(status="new", record=record)

            if str(existing.get("payload_hash") or "") != payload_hash:
                return IdempotencyBeginResult(status="conflict", record=_record_from_dict(existing))

            status = str(existing.get("status") or "processing")
            existing["updated_at"] = now_ts
            if status == "completed":
                return IdempotencyBeginResult(status="completed", record=_record_from_dict(existing))
            if status == "failed":
                existing["status"] = "processing"
                existing["request_id"] = request_id
                existing["message_id"] = message_id
                existing["error_type"] = None
                existing["response_payload"] = None
                existing["expires_at"] = _expiry_ts(now_ts, ttl_seconds)
                return IdempotencyBeginResult(status="new", record=_record_from_dict(existing))
            return IdempotencyBeginResult(status="processing", record=_record_from_dict(existing))

    def get(self, *, user_id: str, idempotency_key: str) -> Optional[IdempotencyRecord]:
        with self._lock:
            record = self._records.get(self._key(user_id, idempotency_key))
            return _record_from_dict(record) if record else None

    def mark_completed(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        response_payload: Dict[str, Any],
        now_ts: str,
    ) -> Optional[IdempotencyRecord]:
        with self._lock:
            key = self._key(user_id, idempotency_key)
            record = self._records.get(key)
            if not record:
                return None
            record["status"] = "completed"
            record["updated_at"] = now_ts
            record["response_payload"] = response_payload
            record["error_type"] = None
            return _record_from_dict(record)

    def mark_failed(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        error_type: str,
        now_ts: str,
    ) -> Optional[IdempotencyRecord]:
        with self._lock:
            key = self._key(user_id, idempotency_key)
            record = self._records.get(key)
            if not record:
                return None
            record["status"] = "failed"
            record["updated_at"] = now_ts
            record["error_type"] = error_type
            return _record_from_dict(record)


class FirestoreIdempotencyStore(IdempotencyStore):
    """Firestore-backed idempotency store."""

    def __init__(
        self,
        *,
        config: IdempotencyStoreConfig,
        firestore_client: Optional[Any] = None,
    ) -> None:
        self._config = config
        self._client = self._init_client(firestore_client)

    def begin(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        payload_hash: str,
        request_id: str,
        message_id: str,
        now_ts: str,
        ttl_seconds: int,
    ) -> IdempotencyBeginResult:
        if not self._client:
            record = IdempotencyRecord(
                user_id=user_id,
                idempotency_key=idempotency_key,
                message_id=message_id,
                request_id=request_id,
                payload_hash=payload_hash,
                status="processing",
                created_at=now_ts,
                updated_at=now_ts,
                expires_at=_expiry_ts(now_ts, ttl_seconds),
            )
            return IdempotencyBeginResult(status="new", record=record)

        doc_ref = self._doc_ref(user_id=user_id, idempotency_key=idempotency_key)
        transaction = self._client.transaction()

        @firestore.transactional  # type: ignore[misc]
        def _txn(txn: Any) -> Dict[str, Any]:
            snap = doc_ref.get(transaction=txn)
            if not snap.exists:
                record = IdempotencyRecord(
                    user_id=user_id,
                    idempotency_key=idempotency_key,
                    message_id=message_id,
                    request_id=request_id,
                    payload_hash=payload_hash,
                    status="processing",
                    created_at=now_ts,
                    updated_at=now_ts,
                    expires_at=_expiry_ts(now_ts, ttl_seconds),
                )
                txn.set(doc_ref, record.to_dict(), merge=True)
                return {"status": "new", "record": record.to_dict()}

            data = snap.to_dict() or {}
            existing_hash = str(data.get("payload_hash") or "")
            if existing_hash != payload_hash:
                return {"status": "conflict", "record": data}

            status = str(data.get("status") or "processing")
            if status == "completed":
                return {"status": "completed", "record": data}

            if status == "failed":
                data["status"] = "processing"
                data["request_id"] = request_id
                data["message_id"] = message_id
                data["response_payload"] = None
                data["error_type"] = None
                data["updated_at"] = now_ts
                data["expires_at"] = _expiry_ts(now_ts, ttl_seconds)
                txn.set(doc_ref, data, merge=True)
                return {"status": "new", "record": data}

            data["updated_at"] = now_ts
            txn.set(doc_ref, {"updated_at": now_ts}, merge=True)
            return {"status": "processing", "record": data}

        result = _txn(transaction)
        return IdempotencyBeginResult(status=str(result.get("status") or "processing"), record=_record_from_dict(result.get("record")))

    def get(self, *, user_id: str, idempotency_key: str) -> Optional[IdempotencyRecord]:
        if not self._client:
            return None
        snap = self._doc_ref(user_id=user_id, idempotency_key=idempotency_key).get()
        if not snap.exists:
            return None
        return _record_from_dict(snap.to_dict() or {})

    def mark_completed(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        response_payload: Dict[str, Any],
        now_ts: str,
    ) -> Optional[IdempotencyRecord]:
        if not self._client:
            return None
        ref = self._doc_ref(user_id=user_id, idempotency_key=idempotency_key)
        ref.set(
            {
                "status": "completed",
                "updated_at": now_ts,
                "response_payload": response_payload,
                "error_type": None,
            },
            merge=True,
        )
        snap = ref.get()
        return _record_from_dict(snap.to_dict() or {}) if snap.exists else None

    def mark_failed(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        error_type: str,
        now_ts: str,
    ) -> Optional[IdempotencyRecord]:
        if not self._client:
            return None
        ref = self._doc_ref(user_id=user_id, idempotency_key=idempotency_key)
        ref.set(
            {
                "status": "failed",
                "updated_at": now_ts,
                "error_type": error_type,
            },
            merge=True,
        )
        snap = ref.get()
        return _record_from_dict(snap.to_dict() or {}) if snap.exists else None

    def _doc_ref(self, *, user_id: str, idempotency_key: str) -> Any:
        digest = hashlib.sha256(f"{user_id}:{idempotency_key}".encode("utf-8")).hexdigest()
        return self._client.collection(self._config.collection).document(digest)

    def _init_client(self, firestore_client: Optional[Any]) -> Optional[Any]:
        if not self._config.enable_firestore:
            return None
        if firestore_client is not None:
            return firestore_client
        if firestore is None:
            logger.warning("google-cloud-firestore not available; idempotency store disabled")
            return None
        try:
            creds_payload = self._config.credentials_json
            if creds_payload and isinstance(creds_payload, str):
                creds_payload = json.loads(creds_payload)
            if creds_payload and service_account is not None:
                creds = service_account.Credentials.from_service_account_info(creds_payload)
                return firestore.Client(project=self._config.project_id, credentials=creds)
            return firestore.Client(project=self._config.project_id)
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to init Firestore idempotency client: %s", exc)
            return None


def _record_from_dict(data: Optional[Dict[str, Any]]) -> IdempotencyRecord:
    data = data or {}
    return IdempotencyRecord(
        user_id=str(data.get("user_id") or ""),
        idempotency_key=str(data.get("idempotency_key") or ""),
        message_id=str(data.get("message_id") or ""),
        request_id=str(data.get("request_id") or ""),
        payload_hash=str(data.get("payload_hash") or ""),
        status=str(data.get("status") or "processing"),
        created_at=str(data.get("created_at") or ""),
        updated_at=str(data.get("updated_at") or ""),
        expires_at=str(data.get("expires_at") or ""),
        response_payload=data.get("response_payload") if isinstance(data.get("response_payload"), dict) else None,
        error_type=str(data.get("error_type") or "") or None,
    )


def _expiry_ts(now_ts: str, ttl_seconds: int) -> str:
    try:
        base = datetime.strptime(now_ts, "%Y-%m-%d %H:%M:%S")
        base = base.replace(tzinfo=manila_tz)
    except Exception:
        base = datetime.now(manila_tz)
    return (base + timedelta(seconds=max(1, int(ttl_seconds)))).strftime("%Y-%m-%d %H:%M:%S")
