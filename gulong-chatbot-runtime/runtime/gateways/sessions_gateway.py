"""
SessionsGateway for runtime (user_id-keyed sessions).

Storage is abstracted behind a SessionStore so Firestore can be swapped
without changing session logic.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from configs.log_utils import get_logger

from runtime.shared.types import MessageTurn, SessionDoc, UserDoc
from runtime.utils.time_utils import now_manila_str
from runtime.storage.session_store import (
    FirestoreSessionStore,
    FirestoreSessionStoreConfig,
    MemorySessionStore,
    SessionStore,
    STRATEGY_STATE_FORMAT_NESTED_MAP_V1,
)


logger = get_logger(__file__, level="INFO")


class SessionConflictError(RuntimeError):
    """Raised when CAS session save fails due to revision mismatch."""


@dataclass
class SessionsGatewayConfig:
    """
    Configuration for session storage.

    Fields:
        users_collection: Collection keyed by user_id (Firestore).
        sessions_subcollection: Subcollection under each user doc (Firestore).
        credentials_json: Optional service account JSON object (Firestore).
        storage_kind: "firestore" or "memory".
    """
    project_id: str
    users_collection: str
    sessions_subcollection: str
    enable_firestore: bool = True
    credentials_json: Optional[str] = None
    storage_kind: str = "firestore"
    strategy_state_format: str = STRATEGY_STATE_FORMAT_NESTED_MAP_V1


@dataclass
class SessionLoadResult:
    """
    Result of session load or creation.

    Fields:
        created_new_session: True if a new session doc was created.
        used_fallback: True if Firestore was unavailable.
    """
    user_doc: UserDoc
    session_doc: SessionDoc
    created_new_session: bool
    used_fallback: bool


class SessionsGateway:
    """
    Firestore-backed session resolution for user_id -> session_id.

    Behavior:
        - Resolves the active_session_id in the user doc.
        - Creates a new session if missing or not found.
        - Uses Asia/Manila timestamps for all stored datetime fields.
    """

    def __init__(
        self,
        *,
        config: SessionsGatewayConfig,
        store: Optional[SessionStore] = None,
        firestore_client: Optional[Any] = None,
    ) -> None:
        self._config = config
        self._store = store or self._init_store(firestore_client)

    def load(
        self,
        *,
        user_id: str,
        channel_user_id: Optional[str] = None,
        user_id_source: Optional[str] = None,
        reset: bool = False,
    ) -> SessionLoadResult:
        """
        Load or create the active session for a user_id.

        Returns a SessionLoadResult containing both user and session docs.
        """
        now = now_manila_str()
        if not self._store or not self._store.is_available():
            return self._fallback_session(
                user_id=user_id,
                channel_user_id=channel_user_id,
                user_id_source=user_id_source,
                now=now,
            )

        user_data = self._store.load_user(user_id)

        active_session_id = user_data.get("active_session_id") if user_data else None
        created_new_session = False
        if reset or not active_session_id:
            active_session_id = self._new_session_id()
            created_new_session = True

        user_doc = UserDoc(
            user_id=user_id,
            channel_user_id=channel_user_id or (user_data or {}).get("channel_user_id"),
            active_session_id=active_session_id,
            updated_at=now,
            user_id_source=user_id_source or (user_data or {}).get("user_id_source"),
        )
        self._store.save_user(user_id, user_doc.to_dict())

        session_doc, created_session_doc = self._load_or_create_session(
            session_id=active_session_id,
            user_id=user_id,
            now=now,
        )
        created_new_session = created_new_session or created_session_doc

        return SessionLoadResult(
            user_doc=user_doc,
            session_doc=session_doc,
            created_new_session=created_new_session,
            used_fallback=False,
        )

    def save(
        self,
        *,
        user_doc: UserDoc,
        session_doc: SessionDoc,
        expected_revision: Optional[int] = None,
        request_id: Optional[str] = None,
        use_cas: bool = False,
        raise_on_conflict: bool = False,
    ) -> bool:
        """Persist user and session docs (best-effort)."""
        if not self._store or not self._store.is_available():
            logger.warning("Session store unavailable; skip session save for user_id=%s", user_doc.user_id)
            return False
        now = now_manila_str()
        # load() owns the user -> active_session_id pointer. Rewriting it when a
        # long-running older turn finishes can reactivate a session that a reset
        # has already superseded.
        session_doc.updated_at = now
        cas_enabled = use_cas or str(os.getenv("SESSION_CAS_ON", "0") or "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if cas_enabled and expected_revision is not None:
            ok = self._store.save_session_cas(
                user_doc.user_id,
                session_doc.session_id,
                int(expected_revision),
                session_doc.to_dict(),
                request_id=request_id,
            )
            if not ok and raise_on_conflict:
                raise SessionConflictError(
                    f"session_cas_conflict:user_id={user_doc.user_id}:session_id={session_doc.session_id}:"
                    f"expected_revision={expected_revision}"
                )
            if ok:
                session_doc.revision = int(expected_revision) + 1
                if request_id:
                    session_doc.last_request_id = request_id
            return bool(ok)
        payload = session_doc.to_dict()
        if request_id:
            payload["last_request_id"] = request_id
            session_doc.last_request_id = request_id
        self._store.save_session(user_doc.user_id, session_doc.session_id, payload)
        return True

    def last_save_diagnostics(self) -> Dict[str, Any]:
        """Return bounded backend diagnostics for the latest caller-thread save."""

        loader = getattr(self._store, "last_save_diagnostics", None)
        if not callable(loader):
            return {}
        diagnostics = loader()
        return dict(diagnostics) if isinstance(diagnostics, dict) else {}

    def reload_session(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> Optional[SessionDoc]:
        """Read the exact session again without rewriting the user pointer."""

        if not self._store or not self._store.is_available():
            return None
        session_doc, _created = self._load_or_create_session(
            session_id=session_id,
            user_id=user_id,
            now=now_manila_str(),
        )
        return session_doc

    def acquire_lock(
        self,
        *,
        user_id: str,
        session_id: str,
        owner: str,
        ttl_seconds: int = 90,
    ) -> Tuple[bool, str]:
        """Acquire a lightweight active-turn lock for a session."""

        if not self._store or not self._store.is_available():
            return False, ""
        now = now_manila_str()
        lock_until = _format_manila_datetime(_parse_manila_datetime(now) + timedelta(seconds=max(1, int(ttl_seconds or 90))))
        ok = self._store.acquire_session_lock(
            user_id,
            session_id,
            owner=owner,
            lock_until=lock_until,
            now=now,
        )
        return bool(ok), lock_until if ok else ""

    def release_lock(
        self,
        *,
        user_id: str,
        session_id: str,
        owner: str,
    ) -> None:
        """Release an active-turn lock if this owner still holds it."""

        if not self._store or not self._store.is_available():
            return
        self._store.release_session_lock(user_id, session_id, owner=owner)

    def record_interaction_event(
        self,
        *,
        user_id: str,
        session_id: str,
        event: Dict[str, Any],
        max_events: int = 10,
    ) -> bool:
        """Persist a tracked click before it waits for the main turn lock."""

        if not self._store or not self._store.is_available():
            return False
        return bool(
            self._store.record_interaction_event(
                user_id,
                session_id,
                dict(event),
                max_events=max_events,
            )
        )

    def load_interaction_events(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> List[Dict[str, Any]]:
        """Read the pre-lock tracked-click inbox."""

        if not self._store or not self._store.is_available():
            return []
        return self._store.load_interaction_events(user_id, session_id)

    def remove_interaction_events(
        self,
        *,
        user_id: str,
        session_id: str,
        event_ids: Sequence[str],
    ) -> None:
        """Remove events only after their resolved batch is persisted."""

        if not self._store or not self._store.is_available():
            return
        self._store.remove_interaction_events(
            user_id,
            session_id,
            event_ids=event_ids,
        )

    def _load_or_create_session(
        self,
        *,
        session_id: str,
        user_id: str,
        now: str,
    ) -> Tuple[SessionDoc, bool]:
        """Load an existing session or create a new one."""
        data = self._store.load_session(user_id, session_id) if self._store else None
        if data:
            messages = [
                MessageTurn(
                    role=item.get("role", "user"),
                    text=item.get("text", ""),
                    ts=item.get("ts", now),
                    tool_summary_refs=item.get("tool_summary_refs"),
                )
                for item in (data.get("messages") or [])
                if isinstance(item, dict)
            ]
            return (
                SessionDoc(
                    session_id=session_id,
                    user_id=user_id,
                    status=data.get("status", "active"),
                    opened_at=data.get("opened_at", now),
                    last_user_message_at=data.get("last_user_message_at", now),
                    closed_at=data.get("closed_at"),
                    summary=data.get("summary", ""),
                    slots=data.get("slots") or {},
                    messages=messages,
                    strategy_state=data.get("strategy_state"),
                    handoff_state=data.get("handoff_state"),
                    updated_at=data.get("updated_at", now),
                    revision=int(data.get("revision") or 0),
                    last_request_id=data.get("last_request_id"),
                    active_lock_until=data.get("active_lock_until"),
                    active_lock_owner=data.get("active_lock_owner"),
                ),
                False,
            )

        session_doc = SessionDoc(
            session_id=session_id,
            user_id=user_id,
            status="active",
            opened_at=now,
            last_user_message_at=now,
            closed_at=None,
            summary="",
            slots={},
            messages=[],
            strategy_state=None,
            handoff_state=None,
            updated_at=now,
            revision=0,
            last_request_id=None,
            active_lock_until=None,
            active_lock_owner=None,
        )
        if self._store:
            self._store.save_session(user_id, session_id, session_doc.to_dict())
        return session_doc, True

    def _fallback_session(
        self,
        *,
        user_id: str,
        channel_user_id: Optional[str],
        user_id_source: Optional[str],
        now: str,
    ) -> SessionLoadResult:
        """Create a fallback session when Firestore is unavailable."""
        session_id = self._new_session_id()
        user_doc = UserDoc(
            user_id=user_id,
            channel_user_id=channel_user_id,
            active_session_id=session_id,
            updated_at=now,
            user_id_source=user_id_source,
        )
        session_doc = SessionDoc(
            session_id=session_id,
            user_id=user_id,
            status="active",
            opened_at=now,
            last_user_message_at=now,
            closed_at=None,
            summary="",
            slots={},
            messages=[],
            strategy_state=None,
            handoff_state=None,
            updated_at=now,
            revision=0,
            last_request_id=None,
            active_lock_until=None,
            active_lock_owner=None,
        )
        logger.warning("Firestore unavailable; using fallback session for user_id=%s", user_id)
        return SessionLoadResult(
            user_doc=user_doc,
            session_doc=session_doc,
            created_new_session=True,
            used_fallback=True,
        )

    def _init_store(self, firestore_client: Optional[Any]) -> SessionStore:
        """Initialize storage backend based on config."""
        kind = (self._config.storage_kind or "firestore").lower()
        if kind == "memory":
            return MemorySessionStore()
        fs_config = FirestoreSessionStoreConfig(
            project_id=self._config.project_id,
            users_collection=self._config.users_collection,
            sessions_subcollection=self._config.sessions_subcollection,
            credentials_json=self._config.credentials_json,
            enable_firestore=self._config.enable_firestore,
            strategy_state_format=self._config.strategy_state_format,
        )
        return FirestoreSessionStore(config=fs_config, firestore_client=firestore_client)

    @staticmethod
    def _new_session_id() -> str:
        """Return a new deterministic session id prefix."""
        return f"sess_{uuid.uuid4().hex}"


def _parse_manila_datetime(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.now()
    try:
        return datetime.fromisoformat(text)
    except Exception:
        pass
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.now()


def _format_manila_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")
