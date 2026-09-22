"""Optional Postgres stores for Runtime V7 session and idempotency state.

The runtime keeps the existing Firestore default. These stores are only used
when the VM deployment explicitly selects the ``postgres`` provider through
environment configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

try:  # pragma: no cover - optional unless the provider is enabled
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]
    sql = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]
    Jsonb = None  # type: ignore[assignment]

from configs.log_utils import get_logger
from runtime.storage.idempotency_store import (
    IdempotencyBeginResult,
    IdempotencyRecord,
    IdempotencyStore,
    _expiry_ts,
    _record_from_dict,
)
from runtime.storage.session_store import (
    SessionStore,
    _interaction_event_id,
    _lock_is_active,
    _upsert_interaction_event,
)


logger = get_logger(__file__, level="INFO")

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PostgresRuntimeStoreUnavailable(RuntimeError):
    """Raised when the Postgres runtime store cannot be used."""


@dataclass(frozen=True)
class PostgresRuntimeStoreConfig:
    """Connection and table settings for Runtime V7 Postgres stores."""

    dsn: str
    schema: str = "runtime_shadow"
    users_table: str = "users_kv"
    sessions_table: str = "sessions_kv"
    idempotency_table: str = "idempotency_kv"
    connect_timeout_seconds: int = 5
    statement_timeout_ms: int = 5000
    ensure_tables: bool = True


def postgres_runtime_available() -> bool:
    """Return true when the optional psycopg dependency is importable."""

    return psycopg is not None and sql is not None and Jsonb is not None


def build_postgres_runtime_config(
    *,
    dsn: str,
    schema: str = "runtime_shadow",
    users_table: str = "users_kv",
    sessions_table: str = "sessions_kv",
    idempotency_table: str = "idempotency_kv",
    connect_timeout_seconds: int = 5,
    statement_timeout_ms: int = 5000,
    ensure_tables: bool = True,
) -> PostgresRuntimeStoreConfig:
    """Build a validated Postgres runtime store config."""

    if not str(dsn or "").strip():
        raise PostgresRuntimeStoreUnavailable("RUNTIME_POSTGRES_DSN/DATABASE_URL is required")
    for value in (schema, users_table, sessions_table, idempotency_table):
        _validate_identifier(value)
    return PostgresRuntimeStoreConfig(
        dsn=str(dsn).strip(),
        schema=str(schema or "runtime_shadow").strip(),
        users_table=str(users_table or "users_kv").strip(),
        sessions_table=str(sessions_table or "sessions_kv").strip(),
        idempotency_table=str(idempotency_table or "idempotency_kv").strip(),
        connect_timeout_seconds=max(1, int(connect_timeout_seconds or 5)),
        statement_timeout_ms=max(0, int(statement_timeout_ms or 0)),
        ensure_tables=bool(ensure_tables),
    )


class PostgresSessionStore(SessionStore):
    """Postgres JSONB-backed implementation of the runtime SessionStore."""

    def __init__(self, config: PostgresRuntimeStoreConfig) -> None:
        _require_postgres()
        self.config = config
        if config.ensure_tables:
            self.ensure_tables()

    def is_available(self) -> bool:
        return postgres_runtime_available() and bool(self.config.dsn)

    def load_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        query = sql.SQL("SELECT payload FROM {table} WHERE user_id = %s").format(
            table=self._users_table()
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (str(user_id),))
                row = cur.fetchone()
        return _row_payload(row)

    def save_user(self, user_id: str, data: Dict[str, Any]) -> None:
        payload = dict(data or {})
        payload.setdefault("user_id", str(user_id))
        query = sql.SQL(
            """
            INSERT INTO {table} (user_id, payload)
            VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                payload = EXCLUDED.payload,
                updated_at = NOW()
            """
        ).format(table=self._users_table())
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (str(user_id), _jsonb(payload)))

    def load_session(self, user_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        query = sql.SQL(
            "SELECT payload FROM {table} WHERE user_id = %s AND session_id = %s"
        ).format(table=self._sessions_table())
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (str(user_id), str(session_id)))
                row = cur.fetchone()
        return _row_payload(row)

    def save_session(self, user_id: str, session_id: str, data: Dict[str, Any]) -> None:
        payload = dict(data or {})
        payload.setdefault("user_id", str(user_id))
        payload.setdefault("session_id", str(session_id))
        query = sql.SQL(
            """
            INSERT INTO {table} (user_id, session_id, payload)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, session_id) DO UPDATE SET
                payload = EXCLUDED.payload || CASE
                    WHEN {table}.payload ? 'interaction_inbox_v1'
                    THEN jsonb_build_object(
                        'interaction_inbox_v1',
                        {table}.payload->'interaction_inbox_v1'
                    )
                    ELSE '{{}}'::jsonb
                END,
                updated_at = NOW()
            """
        ).format(table=self._sessions_table())
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (str(user_id), str(session_id), _jsonb(payload)))

    def save_session_cas(
        self,
        user_id: str,
        session_id: str,
        expected_revision: int,
        data: Dict[str, Any],
        request_id: Optional[str] = None,
    ) -> bool:
        payload = dict(data or {})
        payload["user_id"] = str(user_id)
        payload["session_id"] = str(session_id)
        payload["revision"] = int(expected_revision) + 1
        if request_id:
            payload["last_request_id"] = request_id
        query = sql.SQL(
            """
            INSERT INTO {table} (user_id, session_id, payload)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, session_id) DO UPDATE SET
                payload = EXCLUDED.payload || CASE
                    WHEN {table}.payload ? 'interaction_inbox_v1'
                    THEN jsonb_build_object(
                        'interaction_inbox_v1',
                        {table}.payload->'interaction_inbox_v1'
                    )
                    ELSE '{{}}'::jsonb
                END,
                updated_at = NOW()
            WHERE COALESCE(({table}.payload->>'revision')::int, 0) = %s
            """
        ).format(table=self._sessions_table())
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (str(user_id), str(session_id), _jsonb(payload), int(expected_revision)))
                return int(cur.rowcount or 0) > 0

    def acquire_session_lock(
        self,
        user_id: str,
        session_id: str,
        *,
        owner: str,
        lock_until: str,
        now: str,
    ) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        "SELECT payload FROM {table} WHERE user_id = %s AND session_id = %s FOR UPDATE"
                    ).format(table=self._sessions_table()),
                    (str(user_id), str(session_id)),
                )
                current = _row_payload(cur.fetchone()) or {"user_id": str(user_id), "session_id": str(session_id)}
                active_until = str(current.get("active_lock_until") or "")
                active_owner = str(current.get("active_lock_owner") or "")
                if active_until and _lock_is_active(active_until, now) and active_owner != owner:
                    return False
                current["active_lock_until"] = lock_until
                current["active_lock_owner"] = owner
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO {table} (user_id, session_id, payload)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (user_id, session_id) DO UPDATE SET
                            payload = EXCLUDED.payload,
                            updated_at = NOW()
                        """
                    ).format(table=self._sessions_table()),
                    (str(user_id), str(session_id), _jsonb(current)),
                )
        return True

    def release_session_lock(
        self,
        user_id: str,
        session_id: str,
        *,
        owner: str,
    ) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        "SELECT payload FROM {table} WHERE user_id = %s AND session_id = %s FOR UPDATE"
                    ).format(table=self._sessions_table()),
                    (str(user_id), str(session_id)),
                )
                current = _row_payload(cur.fetchone())
                if not current:
                    return
                active_owner = str(current.get("active_lock_owner") or "")
                if active_owner and active_owner != owner:
                    return
                current["active_lock_until"] = None
                current["active_lock_owner"] = None
                cur.execute(
                    sql.SQL(
                        """
                        UPDATE {table}
                        SET payload = %s, updated_at = NOW()
                        WHERE user_id = %s AND session_id = %s
                        """
                    ).format(table=self._sessions_table()),
                    (_jsonb(current), str(user_id), str(session_id)),
                )

    def record_interaction_event(
        self,
        user_id: str,
        session_id: str,
        event: Dict[str, Any],
        *,
        max_events: int,
    ) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        "SELECT payload FROM {table} "
                        "WHERE user_id = %s AND session_id = %s FOR UPDATE"
                    ).format(table=self._sessions_table()),
                    (str(user_id), str(session_id)),
                )
                current = _row_payload(cur.fetchone()) or {
                    "user_id": str(user_id),
                    "session_id": str(session_id),
                }
                current["interaction_inbox_v1"] = _upsert_interaction_event(
                    current.get("interaction_inbox_v1"),
                    event,
                    max_events=max_events,
                )
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO {table} (user_id, session_id, payload)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (user_id, session_id) DO UPDATE SET
                            payload = EXCLUDED.payload,
                            updated_at = NOW()
                        """
                    ).format(table=self._sessions_table()),
                    (
                        str(user_id),
                        str(session_id),
                        _jsonb(current),
                    ),
                )
        return True

    def load_interaction_events(
        self,
        user_id: str,
        session_id: str,
    ) -> List[Dict[str, Any]]:
        current = self.load_session(user_id, session_id) or {}
        return [
            dict(item)
            for item in current.get("interaction_inbox_v1") or []
            if isinstance(item, dict)
        ]

    def remove_interaction_events(
        self,
        user_id: str,
        session_id: str,
        *,
        event_ids: Sequence[str],
    ) -> None:
        remove_ids = {
            str(item or "").strip()
            for item in event_ids
            if str(item or "").strip()
        }
        if not remove_ids:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        "SELECT payload FROM {table} "
                        "WHERE user_id = %s AND session_id = %s FOR UPDATE"
                    ).format(table=self._sessions_table()),
                    (str(user_id), str(session_id)),
                )
                current = _row_payload(cur.fetchone())
                if not current:
                    return
                current["interaction_inbox_v1"] = [
                    dict(item)
                    for item in current.get("interaction_inbox_v1") or []
                    if isinstance(item, dict)
                    and _interaction_event_id(item) not in remove_ids
                ]
                cur.execute(
                    sql.SQL(
                        """
                        UPDATE {table}
                        SET payload = %s, updated_at = NOW()
                        WHERE user_id = %s AND session_id = %s
                        """
                    ).format(table=self._sessions_table()),
                    (
                        _jsonb(current),
                        str(user_id),
                        str(session_id),
                    ),
                )

    def ensure_tables(self) -> None:
        """Create the minimal runtime tables if they do not already exist."""

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {schema}").format(schema=self._schema()))
                cur.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {table} (
                            user_id TEXT PRIMARY KEY,
                            payload JSONB NOT NULL,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    ).format(table=self._users_table())
                )
                cur.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {table} (
                            user_id TEXT NOT NULL,
                            session_id TEXT NOT NULL,
                            payload JSONB NOT NULL,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            PRIMARY KEY (user_id, session_id)
                        )
                        """
                    ).format(table=self._sessions_table())
                )
                cur.execute(
                    sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {table} (updated_at DESC)").format(
                        idx=sql.Identifier(f"{self.config.sessions_table}_updated_at_idx"),
                        table=self._sessions_table(),
                    )
                )

    def _connect(self) -> Any:
        return psycopg.connect(self.config.dsn, **_connect_kwargs(self.config))

    def _schema(self) -> Any:
        return sql.Identifier(self.config.schema)

    def _users_table(self) -> Any:
        return sql.Identifier(self.config.schema, self.config.users_table)

    def _sessions_table(self) -> Any:
        return sql.Identifier(self.config.schema, self.config.sessions_table)


class PostgresIdempotencyStore(IdempotencyStore):
    """Postgres JSONB-backed implementation of the runtime IdempotencyStore."""

    def __init__(self, config: PostgresRuntimeStoreConfig) -> None:
        _require_postgres()
        self.config = config
        if config.ensure_tables:
            self.ensure_tables()

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
        digest = _idempotency_digest(user_id=user_id, idempotency_key=idempotency_key)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT payload FROM {table} WHERE record_key = %s FOR UPDATE").format(
                        table=self._idempotency_table()
                    ),
                    (digest,),
                )
                existing = _row_payload(cur.fetchone())
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
                    cur.execute(
                        sql.SQL(
                            """
                            INSERT INTO {table} (record_key, user_id, idempotency_key, payload)
                            VALUES (%s, %s, %s, %s)
                            """
                        ).format(table=self._idempotency_table()),
                        (digest, user_id, idempotency_key, _jsonb(record.to_dict())),
                    )
                    return IdempotencyBeginResult(status="new", record=record)

                if str(existing.get("payload_hash") or "") != payload_hash:
                    return IdempotencyBeginResult(status="conflict", record=_record_from_dict(existing))

                status = str(existing.get("status") or "processing")
                if status == "completed":
                    return IdempotencyBeginResult(status="completed", record=_record_from_dict(existing))

                if status == "failed":
                    existing.update(
                        {
                            "status": "processing",
                            "request_id": request_id,
                            "message_id": message_id,
                            "response_payload": None,
                            "error_type": None,
                            "updated_at": now_ts,
                            "expires_at": _expiry_ts(now_ts, ttl_seconds),
                        }
                    )
                    self._update_payload(cur, digest, existing)
                    return IdempotencyBeginResult(status="new", record=_record_from_dict(existing))

                existing["updated_at"] = now_ts
                self._update_payload(cur, digest, existing)
                return IdempotencyBeginResult(status="processing", record=_record_from_dict(existing))

    def get(self, *, user_id: str, idempotency_key: str) -> Optional[IdempotencyRecord]:
        digest = _idempotency_digest(user_id=user_id, idempotency_key=idempotency_key)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT payload FROM {table} WHERE record_key = %s").format(
                        table=self._idempotency_table()
                    ),
                    (digest,),
                )
                payload = _row_payload(cur.fetchone())
        return _record_from_dict(payload) if payload else None

    def mark_completed(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        response_payload: Dict[str, Any],
        now_ts: str,
    ) -> Optional[IdempotencyRecord]:
        return self._mark(
            user_id=user_id,
            idempotency_key=idempotency_key,
            updates={"status": "completed", "updated_at": now_ts, "response_payload": response_payload, "error_type": None},
        )

    def mark_failed(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        error_type: str,
        now_ts: str,
    ) -> Optional[IdempotencyRecord]:
        return self._mark(
            user_id=user_id,
            idempotency_key=idempotency_key,
            updates={"status": "failed", "updated_at": now_ts, "error_type": error_type},
        )

    def ensure_tables(self) -> None:
        """Create the minimal idempotency table if it does not already exist."""

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {schema}").format(schema=self._schema()))
                cur.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {table} (
                            record_key TEXT PRIMARY KEY,
                            user_id TEXT NOT NULL,
                            idempotency_key TEXT NOT NULL,
                            payload JSONB NOT NULL,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    ).format(table=self._idempotency_table())
                )
                cur.execute(
                    sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {table} (user_id, idempotency_key)").format(
                        idx=sql.Identifier(f"{self.config.idempotency_table}_user_key_idx"),
                        table=self._idempotency_table(),
                    )
                )

    def _mark(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        updates: Mapping[str, Any],
    ) -> Optional[IdempotencyRecord]:
        digest = _idempotency_digest(user_id=user_id, idempotency_key=idempotency_key)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT payload FROM {table} WHERE record_key = %s FOR UPDATE").format(
                        table=self._idempotency_table()
                    ),
                    (digest,),
                )
                payload = _row_payload(cur.fetchone())
                if not payload:
                    return None
                payload.update(dict(updates))
                self._update_payload(cur, digest, payload)
        return _record_from_dict(payload)

    def _update_payload(self, cur: Any, record_key: str, payload: Mapping[str, Any]) -> None:
        cur.execute(
            sql.SQL(
                """
                UPDATE {table}
                SET payload = %s, updated_at = NOW()
                WHERE record_key = %s
                """
            ).format(table=self._idempotency_table()),
            (_jsonb(payload), record_key),
        )

    def _connect(self) -> Any:
        return psycopg.connect(self.config.dsn, **_connect_kwargs(self.config))

    def _schema(self) -> Any:
        return sql.Identifier(self.config.schema)

    def _idempotency_table(self) -> Any:
        return sql.Identifier(self.config.schema, self.config.idempotency_table)


def _connect_kwargs(config: PostgresRuntimeStoreConfig) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {"row_factory": dict_row}
    if config.connect_timeout_seconds > 0:
        kwargs["connect_timeout"] = int(config.connect_timeout_seconds)
    if config.statement_timeout_ms > 0:
        kwargs["options"] = f"-c statement_timeout={int(config.statement_timeout_ms)}"
    return kwargs


def _idempotency_digest(*, user_id: str, idempotency_key: str) -> str:
    return hashlib.sha256(f"{user_id}:{idempotency_key}".encode("utf-8")).hexdigest()


def _jsonb(value: Mapping[str, Any]) -> Any:
    if Jsonb is None:
        raise PostgresRuntimeStoreUnavailable("psycopg Jsonb adapter is unavailable")
    return Jsonb(dict(value or {}))


def _row_payload(row: Any) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    value = row.get("payload") if isinstance(row, Mapping) else row[0]
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        return dict(parsed) if isinstance(parsed, Mapping) else None
    return None


def _require_postgres() -> None:
    if not postgres_runtime_available():
        raise PostgresRuntimeStoreUnavailable("psycopg is not installed")


def _validate_identifier(value: str) -> None:
    if not _IDENTIFIER_RE.match(str(value or "")):
        raise ValueError(f"Invalid Postgres identifier: {value!r}")
