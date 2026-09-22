"""Cloud SQL read-compare helpers for Runtime V7 ManyChat history.

These helpers are intentionally read-only and fail-open. Phase 2I uses them to
measure Cloud SQL parity without changing the model-facing conversation history.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import os
import re
import time
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

try:  # pragma: no cover - optional outside VM/Postgres-enabled tests
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]
    sql = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]

from configs.log_utils import manila_tz
from runtime_v7.manychat_message_loader import DEFAULT_MESSAGE_TYPES


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ManyChatCloudSQLReadConfig:
    """Connection settings for read-only ManyChat Cloud SQL comparisons."""

    dsn: str
    schema: str = "manychat_shadow"
    messages_table: str = "messages"
    business_unit: str = "gulong"
    connect_timeout_seconds: int = 3
    statement_timeout_ms: int = 3000


def manychat_cloudsql_read_config_from_env() -> Optional[ManyChatCloudSQLReadConfig]:
    """Build read config from VM/runtime env vars, returning None when absent."""

    dsn = (
        os.getenv("RUNTIME_V7_MANYCHAT_CLOUDSQL_DSN")
        or os.getenv("RUNTIME_ANALYTICS_POSTGRES_DSN")
        or os.getenv("RUNTIME_POSTGRES_DSN")
        or os.getenv("DATABASE_URL")
        or ""
    ).strip()
    if not dsn:
        return None
    return ManyChatCloudSQLReadConfig(
        dsn=dsn,
        schema=_validate_identifier(os.getenv("RUNTIME_V7_MANYCHAT_CLOUDSQL_SCHEMA", "manychat_shadow")),
        messages_table=_validate_identifier(os.getenv("RUNTIME_V7_MANYCHAT_CLOUDSQL_MESSAGES_TABLE", "messages")),
        business_unit=str(os.getenv("RUNTIME_V7_MANYCHAT_CLOUDSQL_BUSINESS_UNIT", "gulong") or "gulong").strip(),
        connect_timeout_seconds=max(1, int(os.getenv("RUNTIME_V7_MANYCHAT_CLOUDSQL_CONNECT_TIMEOUT_SECONDS", "3") or "3")),
        statement_timeout_ms=max(0, int(os.getenv("RUNTIME_V7_MANYCHAT_CLOUDSQL_STATEMENT_TIMEOUT_MS", "3000") or "3000")),
    )


def load_manychat_messages_from_cloudsql(
    *,
    user_id: str,
    user_name: str = "",
    limit: int = 20,
    message_age_days: int = 30,
    config: Optional[ManyChatCloudSQLReadConfig] = None,
    connect: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Load compact ManyChat messages from Cloud SQL with best-effort semantics."""

    started = time.perf_counter()
    clean_user_id = str(user_id or "").strip()
    accepted_limit = max(1, int(limit or 20))
    if not clean_user_id:
        return _result("error", [], started, "user_id is required")
    cfg = config or manychat_cloudsql_read_config_from_env()
    if cfg is None:
        return _result("skipped", [], started, "ManyChat Cloud SQL DSN is not configured")
    if connect is None and not _cloudsql_reader_available():
        return _result("skipped", [], started, "psycopg is not installed")

    try:
        rows = _fetch_message_rows(
            cfg,
            user_id=clean_user_id,
            limit=accepted_limit,
            message_age_days=max(1, int(message_age_days or 30)),
            connect=connect,
        )
        messages = _normalize_message_rows(rows, user_id=clean_user_id, user_name=user_name, limit=accepted_limit)
        return _result(
            "success",
            messages,
            started,
            f"Loaded {len(messages)} compact ManyChat Cloud SQL messages.",
            row_count=len(rows),
        )
    except Exception as exc:
        return _result("error", [], started, f"{type(exc).__name__}: {exc}")


def compare_manychat_message_sets(
    primary_messages: Sequence[Mapping[str, Any]],
    cloudsql_messages: Sequence[Mapping[str, Any]],
    *,
    current_message_id: str = "",
    current_user_text: str = "",
) -> Dict[str, Any]:
    """Return a compact parity summary without exposing message bodies."""

    primary = [dict(item) for item in primary_messages or [] if isinstance(item, Mapping)]
    primary_manychat = [item for item in primary if not _is_runtime_synthetic_message(item)]
    cloudsql_rows = [dict(item) for item in cloudsql_messages or [] if isinstance(item, Mapping)]
    primary_keys = {_message_key(item) for item in primary_manychat}
    cloudsql_keys = {_message_key(item) for item in cloudsql_rows}
    primary_keys.discard("")
    cloudsql_keys.discard("")
    missing_in_cloudsql = sorted(primary_keys - cloudsql_keys)
    missing_in_primary = sorted(cloudsql_keys - primary_keys)
    current_requires_cloudsql = _current_message_requires_cloudsql(
        current_message_id=current_message_id,
        current_user_text=current_user_text,
    )
    current_in_primary = _contains_current_message(
        primary,
        current_message_id=current_message_id,
        current_user_text=current_user_text,
    )
    current_in_cloudsql = _contains_current_message(
        cloudsql_rows,
        current_message_id=current_message_id,
        current_user_text=current_user_text,
    )
    if not cloudsql_rows:
        match_status = "cloudsql_empty"
    elif current_requires_cloudsql and not current_in_cloudsql:
        match_status = "current_missing_in_cloudsql"
    elif not missing_in_cloudsql:
        match_status = "covered"
    else:
        match_status = "partial"
    return {
        "match_status": match_status,
        "primary_message_count": len(primary),
        "primary_manychat_message_count": len(primary_manychat),
        "cloudsql_message_count": len(cloudsql_rows),
        "primary_key_count": len(primary_keys),
        "cloudsql_key_count": len(cloudsql_keys),
        "shared_key_count": len(primary_keys & cloudsql_keys),
        "missing_in_cloudsql_count": len(missing_in_cloudsql),
        "missing_in_primary_count": len(missing_in_primary),
        "ignored_runtime_synthetic_count": len(primary) - len(primary_manychat),
        "current_in_primary": bool(current_in_primary),
        "current_in_cloudsql": bool(current_in_cloudsql),
        "latest_primary_message_id": _latest_message_id(primary_manychat),
        "latest_cloudsql_message_id": _latest_message_id(cloudsql_rows),
        "latest_primary_datetime": _latest_datetime(primary_manychat),
        "latest_cloudsql_datetime": _latest_datetime(cloudsql_rows),
    }


def _fetch_message_rows(
    config: ManyChatCloudSQLReadConfig,
    *,
    user_id: str,
    limit: int,
    message_age_days: int,
    connect: Optional[Callable[..., Any]],
) -> List[Dict[str, Any]]:
    connector = connect or psycopg.connect
    cutoff = datetime.now(manila_tz).replace(tzinfo=None) - timedelta(days=max(1, int(message_age_days or 30)))
    query = sql.SQL(
        """
        SELECT
            user_id,
            user_name,
            business_unit,
            datetime,
            type,
            role,
            sender,
            message_id,
            sort_id,
            raw_timestamp,
            source,
            text_content,
            content_extracted,
            image_url,
            content_kind
        FROM {table}
        WHERE user_id = %s
          AND business_unit = %s
          AND datetime >= %s
        ORDER BY datetime DESC NULLS LAST, sort_id DESC NULLS LAST, raw_timestamp DESC NULLS LAST
        LIMIT %s
        """
    ).format(table=sql.Identifier(config.schema, config.messages_table))
    with connector(config.dsn, **_connect_kwargs(config)) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (str(user_id), str(config.business_unit), cutoff, max(1, int(limit or 20)) * 3))
            return [dict(row) for row in cur.fetchall()]


def _normalize_message_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    user_id: str,
    user_name: str,
    limit: int,
) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in rows or []:
        row = dict(item or {})
        message_type = str(row.get("type") or "").strip()
        if message_type and message_type not in DEFAULT_MESSAGE_TYPES:
            continue
        role = str(row.get("role") or "").strip() or _role_from_type(message_type)
        content = _message_content(row)
        if not content:
            continue
        is_automated = message_type.startswith("msgout_default")
        normalized.append(
            {
                "datetime": _format_datetime(row.get("datetime")),
                "type": message_type,
                "user_id": str(row.get("user_id") or user_id or ""),
                "user_name": str(row.get("user_name") or user_name or ""),
                "sender": str(row.get("sender") or ""),
                "role": role,
                "message_id": str(row.get("message_id") or "").strip(),
                "content": content,
                **({"is_automated": True, "message_kind": "manychat_automation"} if is_automated else {}),
                "source": "manychat_cloudsql_messages",
            }
        )
    unique = {_message_key(row): row for row in normalized if _message_key(row)}
    ordered = sorted(unique.values(), key=lambda row: (str(row.get("datetime") or ""), str(row.get("message_id") or "")))
    return ordered[-max(1, int(limit or 20)) :]


def _message_content(row: Mapping[str, Any]) -> str:
    for key in ("text_content", "content_extracted", "image_url"):
        value = str(row.get(key) or "").strip()
        if value:
            return " ".join(value.split())
    return ""


def _role_from_type(message_type: str) -> str:
    if message_type.startswith("msgin"):
        return "user"
    if message_type.startswith("msgout_api") or message_type.startswith("msgout_default"):
        return "assistant"
    if message_type.startswith("msgout_lc"):
        return "human_agent"
    return "unknown"


def _format_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(manila_tz).replace(tzinfo=None)
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value or "").strip()


def _message_key(message: Mapping[str, Any]) -> str:
    message_id = str(message.get("message_id") or "").strip()
    if message_id:
        return f"id:{message_id}"
    return "body:{}:{}:{}".format(
        str(message.get("datetime") or "").strip(),
        str(message.get("role") or "").strip(),
        _compact_text(message.get("content")),
    )


def _contains_current_message(
    messages: Sequence[Mapping[str, Any]],
    *,
    current_message_id: str,
    current_user_text: str,
) -> bool:
    current_id = str(current_message_id or "").strip()
    current_text = _compact_text(current_user_text)
    for message in messages or []:
        if current_id and str(message.get("message_id") or "").strip() == current_id:
            return True
        if current_text and str(message.get("role") or "") == "user" and _compact_text(message.get("content")) == current_text:
            return True
    return False


def _current_message_requires_cloudsql(*, current_message_id: str, current_user_text: str) -> bool:
    current_id = str(current_message_id or "").strip()
    if current_id and not _is_runtime_synthetic_message_id(current_id):
        return True
    return bool(_compact_text(current_user_text))


def _is_runtime_synthetic_message(message: Mapping[str, Any]) -> bool:
    return _is_runtime_synthetic_message_id(str(message.get("message_id") or ""))


def _is_runtime_synthetic_message_id(message_id: str) -> bool:
    text = str(message_id or "").strip().lower()
    return text.startswith("assistant_") or text.startswith("runtime_")


def _latest_message_id(messages: Sequence[Mapping[str, Any]]) -> str:
    if not messages:
        return ""
    return str(messages[-1].get("message_id") or "").strip()


def _latest_datetime(messages: Sequence[Mapping[str, Any]]) -> str:
    if not messages:
        return ""
    return str(messages[-1].get("datetime") or "").strip()


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _connect_kwargs(config: ManyChatCloudSQLReadConfig) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    if dict_row is not None:
        kwargs["row_factory"] = dict_row
    if config.connect_timeout_seconds > 0:
        kwargs["connect_timeout"] = int(config.connect_timeout_seconds)
    if config.statement_timeout_ms > 0:
        kwargs["options"] = f"-c statement_timeout={int(config.statement_timeout_ms)}"
    return kwargs


def _cloudsql_reader_available() -> bool:
    return psycopg is not None and sql is not None


def _result(
    status: str,
    data: List[Dict[str, Any]],
    started: float,
    message: str,
    *,
    row_count: int = 0,
) -> Dict[str, Any]:
    return {
        "status": status,
        "message": message,
        "data": data,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "row_count": int(row_count or 0),
        "source": "runtime_v7_manychat_cloudsql_reader",
    }


def _validate_identifier(value: str) -> str:
    text = str(value or "").strip()
    if not _IDENTIFIER_RE.match(text):
        raise ValueError(f"Invalid Postgres identifier: {value!r}")
    return text


__all__ = [
    "ManyChatCloudSQLReadConfig",
    "compare_manychat_message_sets",
    "load_manychat_messages_from_cloudsql",
    "manychat_cloudsql_read_config_from_env",
]
