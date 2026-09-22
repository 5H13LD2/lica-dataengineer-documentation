"""Postgres writer for Runtime V7 analytics parity tables.

This writer mirrors the BigQuery analytics writer interface so VM deployments
can dual-write the same normalized runtime facts to Cloud SQL. BigQuery remains
the reporting surface; these tables are parity and future-migration storage.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

from configs.log_utils import get_logger

try:  # pragma: no cover - optional unless enabled by VM config
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]
    sql = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]
    Jsonb = None  # type: ignore[assignment]


logger = get_logger(__file__, level="INFO")

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_TYPE_MAP = {
    "STRING": "TEXT",
    "INTEGER": "BIGINT",
    "INT64": "BIGINT",
    "BOOLEAN": "BOOLEAN",
    "BOOL": "BOOLEAN",
    "DATETIME": "TIMESTAMP WITHOUT TIME ZONE",
    "TIMESTAMP": "TIMESTAMPTZ",
    "JSON": "JSONB",
}


class PostgresAnalyticsWriterUnavailable(RuntimeError):
    """Raised when Postgres analytics writes cannot be initialized."""


@dataclass(frozen=True)
class PostgresAnalyticsWriterConfig:
    dsn: str
    schema: str = "runtime_shadow"
    connect_timeout_seconds: int = 5
    statement_timeout_ms: int = 5000
    ensure_tables: bool = True
    fail_open: bool = True


def postgres_analytics_available() -> bool:
    return psycopg is not None and sql is not None and Jsonb is not None


def build_postgres_analytics_config(
    *,
    dsn: str,
    schema: str = "runtime_shadow",
    connect_timeout_seconds: int = 5,
    statement_timeout_ms: int = 5000,
    ensure_tables: bool = True,
    fail_open: bool = True,
) -> PostgresAnalyticsWriterConfig:
    if not str(dsn or "").strip():
        raise PostgresAnalyticsWriterUnavailable("RUNTIME_ANALYTICS_POSTGRES_DSN/RUNTIME_POSTGRES_DSN is required")
    _validate_identifier(schema)
    return PostgresAnalyticsWriterConfig(
        dsn=str(dsn).strip(),
        schema=str(schema or "runtime_shadow").strip(),
        connect_timeout_seconds=max(1, int(connect_timeout_seconds or 5)),
        statement_timeout_ms=max(0, int(statement_timeout_ms or 0)),
        ensure_tables=bool(ensure_tables),
        fail_open=bool(fail_open),
    )


class PostgresAnalyticsWriter:
    """Writer interface compatible with BigQueryBatchWriter."""

    def __init__(self, config: PostgresAnalyticsWriterConfig, on_error: Optional[Any] = None) -> None:
        if not postgres_analytics_available():
            raise PostgresAnalyticsWriterUnavailable("psycopg is not installed")
        self.config = config
        self._on_error = on_error
        self._ensured_tables: set[str] = set()

    def enqueue(
        self,
        table: str,
        rows: Iterable[Mapping[str, Any]],
        *,
        schema: Optional[Sequence[Mapping[str, str]]] = None,
        key_columns: Optional[Sequence[str]] = None,
    ) -> None:
        table_name = _validate_identifier(table)
        row_list = [dict(row or {}) for row in rows]
        if not row_list:
            return
        try:
            if self.config.ensure_tables and schema is not None and table_name not in self._ensured_tables:
                self.ensure_table(table_name, schema)
                self._ensured_tables.add(table_name)
            self._upsert_rows(table_name, row_list, key_columns=key_columns, json_columns=_json_columns(schema or []))
        except Exception as exc:
            self._record_error(table_name, exc)
            if not self.config.fail_open:
                raise

    def flush(self, table: Optional[str] = None) -> None:
        return None

    def ensure_table(self, table: str, schema: Sequence[Mapping[str, str]]) -> None:
        table_name = _validate_identifier(table)
        columns = _schema_columns(schema)
        if not _has_column(columns, "row_id"):
            columns.insert(0, {"name": "row_id", "type": "TEXT"})
        column_sql = []
        for field in columns:
            name = _validate_identifier(str(field["name"]))
            pg_type = _postgres_type(str(field.get("type") or "STRING"))
            suffix = " PRIMARY KEY" if name == "row_id" else ""
            column_sql.append(sql.SQL("{} {}{}").format(sql.Identifier(name), sql.SQL(pg_type), sql.SQL(suffix)))

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {schema}").format(schema=self._schema()))
                cur.execute(
                    sql.SQL("CREATE TABLE IF NOT EXISTS {table} ({columns})").format(
                        table=self._table(table_name),
                        columns=sql.SQL(", ").join(column_sql),
                    )
                )
                for index_column in ("ts", "request_id", "trace_id", "session_id", "user_id"):
                    if any(col["name"] == index_column for col in columns):
                        cur.execute(
                            sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {table} ({col})").format(
                                idx=sql.Identifier(f"{table_name}_{index_column}_idx"),
                                table=self._table(table_name),
                                col=sql.Identifier(index_column),
                            )
                        )

    def _upsert_rows(
        self,
        table: str,
        rows: List[Dict[str, Any]],
        *,
        key_columns: Optional[Sequence[str]],
        json_columns: Set[str],
    ) -> None:
        if not rows:
            return
        columns = list(rows[0].keys())
        for row in rows[1:]:
            for key in row.keys():
                if key not in columns:
                    columns.append(key)
        for column in columns:
            _validate_identifier(column)
        keys = list(key_columns or ["row_id"])
        for key in keys:
            _validate_identifier(key)
        assignments = [col for col in columns if col not in set(keys)]
        values = [[_coerce_value(row.get(col), is_json=col in json_columns) for col in columns] for row in rows]

        query = sql.SQL(
            """
            INSERT INTO {table} ({columns})
            VALUES ({placeholders})
            ON CONFLICT ({keys}) DO UPDATE SET {assignments}
            """
        ).format(
            table=self._table(table),
            columns=sql.SQL(", ").join(sql.Identifier(col) for col in columns),
            placeholders=sql.SQL(", ").join(sql.Placeholder() for _ in columns),
            keys=sql.SQL(", ").join(sql.Identifier(key) for key in keys),
            assignments=sql.SQL(", ").join(
                sql.SQL("{col} = EXCLUDED.{col}").format(col=sql.Identifier(col)) for col in assignments
            )
            if assignments
            else sql.SQL("{key} = EXCLUDED.{key}").format(key=sql.Identifier(keys[0])),
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(query, values)

    def _connect(self) -> Any:
        return psycopg.connect(self.config.dsn, **_connect_kwargs(self.config))

    def _schema(self) -> Any:
        return sql.Identifier(self.config.schema)

    def _table(self, table: str) -> Any:
        return sql.Identifier(self.config.schema, table)

    def _record_error(self, table: str, exc: Exception) -> None:
        logger.warning("Runtime Postgres analytics write failed table=%s error=%s", table, exc)
        if not callable(self._on_error):
            return
        try:
            self._on_error(
                {
                    "table": table,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "component": "postgres_analytics_writer",
                }
            )
        except Exception:
            pass


class DualAnalyticsWriter:
    """Fan-out writer that preserves BigQuery writes while adding CloudSQL parity."""

    def __init__(self, primary: Any, secondary: Any, *, fail_open: bool = True) -> None:
        self.primary = primary
        self.secondary = secondary
        self.fail_open = bool(fail_open)

    def enqueue(
        self,
        table: str,
        rows: Iterable[Mapping[str, Any]],
        *,
        schema: Optional[Sequence[Mapping[str, str]]] = None,
        key_columns: Optional[Sequence[str]] = None,
    ) -> None:
        row_list = [dict(row or {}) for row in rows]
        primary_error: Optional[Exception] = None
        try:
            self.primary.enqueue(table, row_list, schema=schema, key_columns=key_columns)
        except Exception as exc:
            primary_error = exc
            if not self.fail_open:
                raise
        try:
            self.secondary.enqueue(table, row_list, schema=schema, key_columns=key_columns)
        except Exception:
            if not self.fail_open:
                raise
        if primary_error is not None and not self.fail_open:
            raise primary_error

    def flush(self, table: Optional[str] = None) -> None:
        for writer in (self.primary, self.secondary):
            flush = getattr(writer, "flush", None)
            if not callable(flush):
                continue
            try:
                flush(table)
            except Exception:
                if not self.fail_open:
                    raise

    def flush_async(self, table: Optional[str] = None) -> None:
        """Dispatch a non-blocking primary flush when the writer supports it.

        PostgreSQL ``enqueue`` is already committed synchronously, so the
        secondary does not need another operation here.
        """

        flush_async = getattr(self.primary, "flush_async", None)
        if not callable(flush_async):
            return
        try:
            flush_async(table)
        except Exception:
            if not self.fail_open:
                raise


def _connect_kwargs(config: PostgresAnalyticsWriterConfig) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {"row_factory": dict_row}
    if config.connect_timeout_seconds > 0:
        kwargs["connect_timeout"] = int(config.connect_timeout_seconds)
    if config.statement_timeout_ms > 0:
        kwargs["options"] = f"-c statement_timeout={int(config.statement_timeout_ms)}"
    return kwargs


def _schema_columns(schema: Sequence[Mapping[str, str]]) -> List[Dict[str, str]]:
    columns: List[Dict[str, str]] = []
    for field in schema:
        name = str(field.get("name") or "").strip()
        if not name:
            continue
        columns.append({"name": name, "type": str(field.get("type") or "STRING").upper()})
    return columns


def _has_column(columns: Sequence[Mapping[str, str]], name: str) -> bool:
    return any(str(col.get("name") or "") == name for col in columns)


def _json_columns(schema: Sequence[Mapping[str, str]]) -> Set[str]:
    columns: Set[str] = set()
    for field in schema:
        if str(field.get("type") or "").strip().upper() == "JSON":
            name = str(field.get("name") or "").strip()
            if name:
                columns.add(name)
    return columns


def _postgres_type(field_type: str) -> str:
    return _TYPE_MAP.get(field_type.strip().upper(), "TEXT")


def _coerce_value(value: Any, *, is_json: bool = False) -> Any:
    if is_json:
        return Jsonb(_json_safe(value))
    if isinstance(value, Mapping):
        return Jsonb(_json_safe(dict(value)))
    if isinstance(value, list):
        return Jsonb(_json_safe(value))
    return value


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _validate_identifier(value: str) -> str:
    text = str(value or "").strip()
    if not _IDENTIFIER_RE.match(text):
        raise ValueError(f"Invalid Postgres identifier: {value!r}")
    return text
