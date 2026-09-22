"""
BigQuery utilities used across the platform (agents-agnostic).

Purpose:
- Provide streaming (Storage Write API) and load-job helpers for writing/reading BigQuery tables.
- Normalize payloads (including nested repeated strings) before ingestion.

Key dependencies:
- google.cloud.bigquery
- google.cloud.bigquery_storage
- pyarrow
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union
from uuid import uuid4

import pandas as pd
import pyarrow as pa
from google.api_core.exceptions import Conflict, NotFound
from google.cloud import bigquery, bigquery_storage
from google.cloud.bigquery import LoadJobConfig, SchemaField
from google.cloud.bigquery_storage_v1 import types as bqs_types
from google.cloud.bigquery_storage_v1 import writer as bq_writer
from google.oauth2 import service_account

from configs.config import ENV
from configs.log_utils import get_logger, manila_tz


def _now_ts() -> str:
    return dt.datetime.now(manila_tz).strftime("%Y-%m-%d %H:%M:%S")

logger = get_logger(__name__, level="INFO")

_BQ_CLIENT_CACHE: Dict[str, bigquery.Client] = {}
_BQ_STORAGE_CACHE: Dict[str, bigquery_storage.BigQueryWriteClient] = {}


def _load_service_account_mapping(raw: str) -> Dict[str, Any]:
    """Parse service-account credentials from JSON or Python-literal strings."""

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = ast.literal_eval(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Service account credentials must parse to a mapping.")
    return parsed
_CLIENT_LOCK = threading.Lock()


@dataclass(frozen=True)
class BQWriterConfig:
    """Configuration for BigQueryBatchWriter."""

    project_id: str
    dataset_id: str
    location: str = "asia-southeast1"
    max_rows: int = 200
    max_age_s: float = 5.0
    retry_max: int = 2
    retry_backoff_s: float = 0.5
    service_account: Optional[Dict[str, Any]] = None


class BigQueryBatchWriter:
    """
    Best-effort batch writer for BigQuery analytics tables.

    Uses BigQueryUtils.insert_rows which prefers the Storage Write API and
    falls back to a load job when streaming fails.
    """

    def __init__(
        self,
        *,
        config: BQWriterConfig,
        on_error: Optional[callable] = None,
    ) -> None:
        self._config = config
        self._on_error = on_error
        self._lock = threading.Lock()
        self._buffers: Dict[str, Dict[str, Any]] = {}
        self._bq_cache: Dict[str, BigQueryUtils] = {}

    def enqueue(
        self,
        table: str,
        rows: Union[List[Dict[str, Any]], Iterable[Dict[str, Any]]],
        *,
        schema: Optional[Sequence[SchemaField]] = None,
        key_columns: Optional[Sequence[str]] = None,
    ) -> None:
        rows_list = [row for row in rows if isinstance(row, dict)]
        if not rows_list:
            return
        drained = None
        with self._lock:
            buf = self._buffers.get(table)
            if not buf:
                buf = {"rows": [], "schema": schema, "timer": None, "key_columns": key_columns}
                self._buffers[table] = buf
            buf["rows"].extend(rows_list)
            if schema is not None:
                buf["schema"] = schema
            if key_columns is not None:
                buf["key_columns"] = key_columns
            if len(buf["rows"]) >= self._config.max_rows:
                drained = self._drain_locked(table)
            elif buf.get("timer") is None:
                timer = threading.Timer(self._config.max_age_s, self._flush, args=(table,))
                timer.daemon = True
                buf["timer"] = timer
                timer.start()
        if drained is not None:
            self._write_in_background(table, drained)

    def _flush(self, table: str) -> None:
        with self._lock:
            drained = self._drain_locked(table)
        if drained is not None:
            rows, schema, key_columns = drained
            self._write_rows(table, rows, schema=schema, key_columns=key_columns)

    def flush(self, table: str) -> None:
        """Synchronously flush a table buffer for higher durability logging."""
        self._flush(table)

    def flush_async(self, table: str) -> None:
        """Dispatch a table buffer immediately without blocking the request.

        This is intended for the small number of canonical telemetry surfaces
        whose rows must start landing before a VM or container replacement can
        cancel the normal age-based timer.  It deliberately preserves the
        writer's best-effort, non-blocking contract.
        """

        with self._lock:
            drained = self._drain_locked(table)
        if drained is not None:
            self._write_in_background(table, drained)

    def _drain_locked(
        self,
        table: str,
    ) -> Optional[tuple[List[Dict[str, Any]], Optional[Sequence[SchemaField]], Optional[Sequence[str]]]]:
        buf = self._buffers.get(table)
        if not buf:
            return None
        rows = list(buf.get("rows") or [])
        schema = buf.get("schema")
        key_columns = buf.get("key_columns")
        timer = buf.get("timer")
        if timer:
            try:
                timer.cancel()
            except Exception:
                pass
        buf["rows"] = []
        buf["timer"] = None
        if not rows:
            return None
        return rows, schema, key_columns

    def _write_in_background(
        self,
        table: str,
        drained: tuple[List[Dict[str, Any]], Optional[Sequence[SchemaField]], Optional[Sequence[str]]],
    ) -> None:
        rows, schema, key_columns = drained
        thread = threading.Thread(
            target=self._write_rows,
            args=(table, rows),
            kwargs={"schema": schema, "key_columns": key_columns},
            daemon=True,
        )
        thread.start()

    def _write_rows(
        self,
        table: str,
        rows: List[Dict[str, Any]],
        schema: Optional[Sequence[SchemaField]],
        key_columns: Optional[Sequence[str]],
    ) -> None:
        util = self._get_util(table)
        attempts = 0
        error_text: Optional[str] = None
        while attempts <= self._config.retry_max:
            attempts += 1
            try:
                result = util.insert_rows(rows=rows, schema=schema, key_columns=key_columns)
                if result.get("error"):
                    raise RuntimeError(result.get("error"))
                return
            except Exception as exc:
                error_text = str(exc)
                if attempts <= self._config.retry_max:
                    time.sleep(self._config.retry_backoff_s * attempts)
        schema_fields = None
        try:
            if schema is not None:
                schema_fields = list(schema)
            else:
                util = self._get_util(table)
                if util.table_ref is not None:
                    table_obj = util.client.get_table(util.table_ref)
                    schema_fields = list(table_obj.schema)
        except Exception:
            schema_fields = None
        row_sample = rows[0] if rows else {}
        row_types = {key: type(value).__name__ for key, value in (row_sample or {}).items()}
        schema_dump = None
        if schema_fields:
            schema_dump = []
            for field in schema_fields:
                if isinstance(field, dict):
                    schema_dump.append(
                        {
                            "name": field.get("name"),
                            "type": field.get("type") or field.get("field_type"),
                            "mode": field.get("mode"),
                        }
                    )
                else:
                    schema_dump.append(
                        {"name": field.name, "type": field.field_type, "mode": field.mode}
                    )
        # Row-level fallback: try inserting rows one-by-one for better diagnostics.
        failed_rows: List[Dict[str, Any]] = []
        for row in rows:
            try:
                result = util.insert_rows(rows=[row], schema=schema, key_columns=key_columns)
                if result.get("error"):
                    raise RuntimeError(result.get("error"))
            except Exception:
                failed_rows.append(row)

        self._emit_error(
            {
                "timestamp": _now_ts(),
                "project_id": self._config.project_id,
                "dataset_id": self._config.dataset_id,
                "table": table,
                "error": error_text or "unknown_error",
                "row_count": len(rows),
                "row_sample": row_sample,
                "row_types": row_types,
                "schema": schema_dump,
                "row_level_fallback": True,
                "row_level_failures": len(failed_rows),
                "row_level_samples": failed_rows[:3],
            }
        )

    def _get_util(self, table: str) -> BigQueryUtils:
        util = self._bq_cache.get(table)
        if util is None:
            util = BigQueryUtils(
                project_id=self._config.project_id,
                dataset_id=self._config.dataset_id,
                table_id=table,
                service_account=self._config.service_account,
                location=self._config.location,
            )
            self._bq_cache[table] = util
        return util

    def _emit_error(self, payload: Dict[str, Any]) -> None:
        if self._on_error:
            try:
                self._on_error(payload)
            except Exception:
                pass
        logger.warning("BQ batch write failed: %s", payload)

def _shared_bigquery_client(
    project_id: str,
    credentials: service_account.Credentials,
    location: Optional[str],
) -> bigquery.Client:
    cache_key = f"{project_id}:{location or 'default'}"
    with _CLIENT_LOCK:
        client = _BQ_CLIENT_CACHE.get(cache_key)
        if client is None:
            client = bigquery.Client(
                project=project_id,
                credentials=credentials,
                location=location,
            )
            _BQ_CLIENT_CACHE[cache_key] = client
    return client


def _shared_storage_client(
    credentials: service_account.Credentials,
) -> bigquery_storage.BigQueryWriteClient:
    cache_key = credentials.service_account_email
    with _CLIENT_LOCK:
        storage_client = _BQ_STORAGE_CACHE.get(cache_key)
        if storage_client is None:
            storage_client = bigquery_storage.BigQueryWriteClient(credentials=credentials)
            _BQ_STORAGE_CACHE[cache_key] = storage_client
    return storage_client

class BigQueryUtils:
    """
    Shared BigQuery helper that prefers streaming ingest.

    The helper encapsulates dataset/table creation, ingestion via the Storage
    Write API with automatic load-job fallback, and light query utilities. It
    caches google-cloud clients when none are explicitly provided.
    """

    def __init__(
        self,
        project_id: str,
        dataset_id: str,
        table_id: Optional[str] = None,
        service_account: Optional[Union[str, Dict[str, Any]]] = None,
        location: Optional[str] = "asia-southeast1",
        *,
        client: Optional[bigquery.Client] = None,
        storage_client: Optional[bigquery_storage.BigQueryWriteClient] = None,
    ) -> None:
        credentials = None
        if client is None or storage_client is None:
            status = load_credentials(service_account)
            credentials = status.get("credentials")
            if not credentials:
                raise ValueError("Error fetching service account/credentials.")

        self.client = client or _shared_bigquery_client(project_id, credentials, location)  # type: ignore[arg-type]
        self.storage_client = storage_client or _shared_storage_client(credentials)  # type: ignore[arg-type]
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.table_id = table_id
        self.location = location
        self.dataset_ref = bigquery.DatasetReference(project_id, dataset_id)
        self.table_ref = self.dataset_ref.table(table_id) if table_id else None

    # Table / Dataset management
    def dataset_exists(self) -> bool:
        """Return True when the dataset is reachable."""
        try:
            self.client.get_dataset(self.dataset_ref)
            return True
        except NotFound:
            return False

    def ensure_dataset(self, location: Optional[str] = None) -> None:
        """Create the dataset if it does not exist."""
        if not self.dataset_exists():
            ds = bigquery.Dataset(self.dataset_ref)
            if location or self.location:
                ds.location = location or self.location
            created = self.client.create_dataset(ds)
            logger.info("Created dataset: %s", created.full_dataset_id)

    def table_exists(self) -> bool:
        """Return True when the configured table exists."""
        if not self.table_ref:
            return False
        try:
            self.client.get_table(self.table_ref)
            return True
        except NotFound:
            return False

    def ensure_table(
        self,
        schema: Optional[Sequence[SchemaField]] = None,
        from_dataframe: Optional[pd.DataFrame] = None,
        location: Optional[str] = None,
        time_partitioning: Optional[bigquery.TimePartitioning] = None,
        clustering_fields: Optional[Sequence[str]] = None,
    ) -> None:
        """
        Create the table with the supplied schema when missing.

        If a DataFrame is provided and no explicit schema is supplied, its
        columns are converted to BigQuery fields.
        """
        if not self.table_id:
            raise ValueError("table_id is required to manage tables.")

        self.ensure_dataset(location=location)

        if self.table_exists():
            if schema is None:
                return
            try:
                table = self.client.get_table(self.table_ref)
                existing = {field.name for field in table.schema}
                additions = [field for field in schema if field.name not in existing]
                if additions:
                    table.schema = list(table.schema) + additions
                    self.client.update_table(table, ["schema"])
            except Exception:
                pass
            return

        if schema is None and from_dataframe is not None:
            schema = bigquery.Schema.from_dataframe(from_dataframe)  # type: ignore[attr-defined]
        if schema is None:
            raise ValueError("Table missing and schema not provided.")

        table = bigquery.Table(self.table_ref, schema=list(schema))
        if time_partitioning:
            table.time_partitioning = time_partitioning
        if clustering_fields:
            table.clustering_fields = list(clustering_fields)
        try:
            created = self.client.create_table(table)
            logger.info("Created table: %s", created.full_table_id)
        except Conflict:
            # Another worker likely created the table; safe to proceed.
            return

    def _load_with_merge(
        self,
        target_ref: bigquery.TableReference,
        rows: List[Dict[str, Any]],
        schema_fields: Sequence[SchemaField],
        key_columns: Sequence[str],
    ) -> None:
        dataset_ref = bigquery.DatasetReference(self.project_id, self.dataset_id)
        stg_name = f"{target_ref.table_id}__stg_{uuid4().hex[:8]}"
        stg_ref = dataset_ref.table(stg_name)
        stg_tbl = bigquery.Table(stg_ref, schema=list(schema_fields))
        stg_tbl.expires = dt.datetime.now(tz=manila_tz) + dt.timedelta(hours=1)
        self.client.create_table(stg_tbl)
        try:
            job_config = LoadJobConfig(
                schema=list(schema_fields),
                write_disposition="WRITE_TRUNCATE",
                ignore_unknown_values=True,
                autodetect=False,
            )
            self.client.load_table_from_json(list(rows), stg_ref, job_config=job_config).result()
            self._merge_tables(target_ref, stg_ref, schema_fields, key_columns)
        finally:
            self.client.delete_table(stg_ref, not_found_ok=True)

    def _ensure_bq_schema(self, schema_obj: Sequence[Union[SchemaField, Dict[str, Any]]]) -> List[SchemaField]:
        fixed: List[SchemaField] = []
        for i, item in enumerate(schema_obj):
            if isinstance(item, SchemaField):
                fixed.append(item)
            elif isinstance(item, dict):
                fixed.append(SchemaField.from_api_repr(item))
            else:
                raise TypeError(f"Schema item #{i} must be SchemaField or dict, got {type(item)}")
        return fixed

    # Load methods
    def load_dataframe(
        self,
        df: pd.DataFrame,
        write_disposition: str = "WRITE_APPEND",
        schema: Optional[Sequence[SchemaField]] = None,
        ignore_unknown_values: bool = True,
        allow_quoted_newlines: bool = True,
        create_if_needed: bool = True,
    ) -> bigquery.LoadJob:
        """
        Load a pandas DataFrame into BigQuery via a load job.

        When `create_if_needed` is True the table will be created first when
        missing.
        """
        if create_if_needed:
            self.ensure_table(schema=schema, from_dataframe=df)

        if self.table_ref is None:
            raise ValueError("table_id is required to load dataframe.")

        job_config = LoadJobConfig(
            write_disposition=write_disposition,
            ignore_unknown_values=ignore_unknown_values,
            allow_quoted_newlines=allow_quoted_newlines,
        )
        if schema is not None:
            job_config.schema = list(schema)
        job = self.client.load_table_from_dataframe(df, self.table_ref, job_config=job_config)
        job.result()
        logger.info("Loaded DataFrame: %s rows -> %s", job.output_rows, self._fqtn())
        return job

    def load_json(
        self,
        rows: Union[List[Dict[str, Any]], Iterable[Dict[str, Any]]],
        write_disposition: str = "WRITE_APPEND",
        schema: Optional[Sequence[SchemaField]] = None,
        autodetect: bool = False,
        create_if_needed: bool = True,
        ignore_unknown_values: bool = True,
    ) -> bigquery.LoadJob:
        """
        Load JSON-like rows into BigQuery.
        """
        if create_if_needed and not self.table_exists():
            if not schema and not autodetect:
                raise ValueError("Table missing. Provide `schema` or set `autodetect=True`.")
            self.ensure_table(schema=schema)

        job_config = LoadJobConfig(
            write_disposition=write_disposition,
            ignore_unknown_values=ignore_unknown_values,
            autodetect=autodetect,
        )
        if schema is not None:
            job_config.schema = list(schema)

        if self.table_ref is None:
            raise ValueError("table_id is required to load json.")

        job = self.client.load_table_from_json(list(rows), self.table_ref, job_config=job_config)
        job.result()
        logger.info("Loaded JSON: %s rows -> %s", job.output_rows, self._fqtn())
        return job

    # Streaming API
    def insert_rows(self, rows: Iterable[Dict[str, Any]], schema: Optional[Sequence[SchemaField]] = None, key_columns: Optional[Sequence[str]] = None, ensure_table: bool = True) -> Dict[str, Any]:
        """
        Stream rows using the Storage Write API, falling back to load jobs on failure.

        When `key_columns` is provided the method uses a staging table plus
        MERGE to update existing rows; otherwise rows are appended.
        """
        rows_list = list(rows)
        if not rows_list:
            return {"stream_ok": True, "fallback_used": False, "error": None}
        if schema is None:
            if not self.table_exists():
                raise ValueError("Schema required when table schema cannot be fetched.")
            if self.table_ref is None:
                raise ValueError("table_id is required to insert rows.")
            table = self.client.get_table(self.table_ref)
            schema_fields = list(table.schema)
        else:
            schema_fields = self._ensure_bq_schema(schema)
        if ensure_table:
            self.ensure_table(schema=schema_fields)

        stream_ok = False
        fallback_used = False
        error_text: Optional[str] = None
        normalized_rows = self._prepare_rows(rows_list, schema_fields)
        try:
            self._stream_rows(self.table_id, normalized_rows, schema_fields, key_columns=key_columns)
            stream_ok = True
        except Exception as exc:
            fallback_used = True
            error_text = str(exc)
            if key_columns:
                self._load_with_merge(self._table_ref(), normalized_rows, schema_fields, key_columns)
            else:
                self.load_json(normalized_rows, schema=schema_fields, autodetect=False, create_if_needed=True)
        return {"stream_ok": stream_ok, "fallback_used": fallback_used, "error": error_text}

    def stream_rows(self, table_id: Optional[str], rows: Iterable[Dict[str, Any]], *, schema: Sequence[SchemaField], key_columns: Optional[Sequence[str]] = None) -> None:
        """
        Stream rows into the given table using the supplied schema.
        """
        rows_list = list(rows)
        if not rows_list:
            return
        schema_fields = self._ensure_bq_schema(schema)
        self.ensure_table(schema=schema_fields)
        self._stream_rows(table_id, rows_list, schema_fields, key_columns=key_columns)

    def _stream_rows(self, table_id: Optional[str], rows: List[Dict[str, Any]], schema_fields: Sequence[SchemaField], key_columns: Optional[Sequence[str]] = None) -> None:
        """Choose merge vs append streaming path."""
        table_ref = self._table_ref(table_id)
        if key_columns:
            self._stream_with_merge(table_ref, rows, schema_fields, key_columns)
        else:
            self._write_via_storage_api(table_ref, rows, schema_fields)

    def _table_ref(self, table_id: Optional[str] = None) -> bigquery.TableReference:
        tid = table_id or self.table_id
        if not tid:
            raise ValueError("table_id is required for streaming operations.")
        return self.dataset_ref.table(tid)

    def _stream_with_merge(self, target_ref: bigquery.TableReference, rows: List[Dict[str, Any]], schema_fields: Sequence[SchemaField], key_columns: Sequence[str]) -> None:
        """Stream rows into a staging table and MERGE into the target table."""
        dataset_ref = bigquery.DatasetReference(self.project_id, self.dataset_id)
        stg_name = f"{target_ref.table_id}__stg_{uuid4().hex[:8]}"
        stg_ref = dataset_ref.table(stg_name)
        stg_tbl = bigquery.Table(stg_ref, schema=list(schema_fields))
        stg_tbl.expires = dt.datetime.now(tz=manila_tz) + dt.timedelta(hours=1)
        self.client.create_table(stg_tbl)
        try:
            self._write_via_storage_api(stg_ref, rows, schema_fields)
            self._merge_tables(target_ref, stg_ref, schema_fields, key_columns)
        finally:
            self.client.delete_table(stg_ref, not_found_ok=True)

    def _write_via_storage_api(self, table_ref: bigquery.TableReference, rows: Iterable[Dict[str, Any]], schema_fields: Sequence[SchemaField]) -> None:
        """Append rows using the BigQuery Storage Write API."""
        rows_list = list(rows)
        if not rows_list:
            return
        arrow_schema = self._build_arrow_schema(schema_fields)
        parent = self.storage_client.table_path(table_ref.project, table_ref.dataset_id, table_ref.table_id)
        stream_name = f"{parent}/_default"
        request_template = bqs_types.AppendRowsRequest()
        request_template.write_stream = stream_name
        arrow_data = bqs_types.AppendRowsRequest.ArrowData()
        arrow_data.writer_schema.serialized_schema = arrow_schema.serialize().to_pybytes()
        request_template.arrow_rows = arrow_data
        append_stream = bq_writer.AppendRowsStream(self.storage_client, request_template)
        try:
            for chunk in self._chunks(rows_list, 500):
                prepared = self._prepare_rows(chunk, schema_fields)
                table = self._rows_to_arrow_table(prepared, arrow_schema)
                for batch in table.to_batches():
                    request = bqs_types.AppendRowsRequest()
                    request.arrow_rows.rows.serialized_record_batch = batch.serialize().to_pybytes()
                    append_stream.send(request).result()
        finally:
            pass

    @staticmethod
    def _chunks(data: List[Dict[str, Any]], size: int) -> Iterable[List[Dict[str, Any]]]:
        for i in range(0, len(data), size):
            yield data[i : i + size]

    def _build_arrow_schema(self, schema_fields: Sequence[SchemaField]) -> pa.Schema:
        return pa.schema([
            pa.field(field.name, self._field_to_arrow_type(field), nullable=(field.mode or "NULLABLE").upper() != "REQUIRED")
            for field in schema_fields
        ])

    @staticmethod
    def _rows_to_arrow_table(rows: List[Dict[str, Any]], arrow_schema: pa.Schema) -> pa.Table:
        """Convert normalized rows into a pyarrow Table using the provided schema."""
        if not rows:
            return pa.Table.from_pylist([], schema=arrow_schema)
        try:
            return pa.Table.from_pylist(rows, schema=arrow_schema)
        except Exception:
            columns = []
            for field in arrow_schema:
                values = [row.get(field.name) for row in rows]
                columns.append(pa.array(values, type=field.type))
            return pa.Table.from_arrays(columns, schema=arrow_schema)

    def _field_to_arrow_type(self, field: SchemaField) -> pa.DataType:
        mapping: Dict[str, pa.DataType] = {
            "STRING": pa.large_string(),
            "INT64": pa.int64(),
            "INTEGER": pa.int64(),
            "FLOAT64": pa.float64(),
            "FLOAT": pa.float64(),
            "BOOL": pa.bool_(),
            "BOOLEAN": pa.bool_(),
            "BYTES": pa.binary(),
            "TIMESTAMP": pa.timestamp("us", tz="UTC"),
            "DATE": pa.date32(),
            "TIME": pa.time64("us"),
            "DATETIME": pa.timestamp("us"),
            "NUMERIC": pa.large_string(),
            "BIGNUMERIC": pa.large_string(),
            "JSON": pa.large_string(),
        }
        field_type = field.field_type.upper()
        if field_type == "RECORD":
            children = [
                pa.field(child.name, self._field_to_arrow_type(child), nullable=(child.mode or 'NULLABLE').upper() != "REQUIRED")
                for child in field.fields
            ]
            base = pa.struct(children)
        else:
            base = mapping.get(field_type, pa.large_string())
        if (field.mode or 'NULLABLE').upper() == "REPEATED":
            return pa.list_(base)
        return base

    def _prepare_rows(self, rows: List[Dict[str, Any]], schema_fields: Sequence[SchemaField]) -> List[Dict[str, Any]]:
        prepared: List[Dict[str, Any]] = []
        for row in rows:
            converted: Dict[str, Any] = {}
            for field in schema_fields:
                converted[field.name] = self._normalize_value(field, row.get(field.name))
            prepared.append(converted)
        return prepared

    def _normalize_value(self, field: SchemaField, value: Any) -> Any:
        if (field.mode or 'NULLABLE').upper() == "REPEATED":
            if value in (None, []):
                return []
            coerced = value
            ftype = (field.field_type or "").upper()
            if ftype == "STRING" and isinstance(value, str):
                parsed = self._parse_jsonish_sequence(value)
                if parsed is not None and isinstance(parsed, list):
                    coerced = parsed
            elif ftype in ("RECORD", "STRUCT") and isinstance(value, str):
                parsed = self._parse_jsonish_sequence(value)
                if parsed is not None:
                    coerced = parsed if isinstance(parsed, list) else [parsed]
            if isinstance(coerced, list) and coerced and all(isinstance(ch, str) and len(ch) == 1 for ch in coerced):
                joined = "".join(coerced)
                reparsed = self._parse_jsonish_sequence(joined)
                if isinstance(reparsed, list):
                    coerced = reparsed
            seq = coerced if isinstance(coerced, list) else [coerced]
            return [self._normalize_scalar(field, item) for item in seq]
        return self._normalize_scalar(field, value)

    @staticmethod
    def _parse_jsonish_sequence(value: str) -> Optional[Union[List[Any], Dict[str, Any]]]:
        """Best-effort conversion of JSON-dumped strings to Python objects."""
        for parser in (json.loads, None):
            try:
                if parser is json.loads:
                    parsed = json.loads(value)
                else:
                    import ast
                    parsed = ast.literal_eval(value)
            except Exception:
                continue
            if isinstance(parsed, (list, dict)):
                return parsed
        return None

    def _normalize_scalar(self, field: SchemaField, value: Any) -> Any:
        if value is None:
            return None
        ftype = field.field_type.upper()
        if ftype in ("DATETIME", "TIMESTAMP"):
            if isinstance(value, str):
                parsed = self._parse_datetime(value)
                return parsed if parsed is not None else value
            return value
        if ftype == "JSON":
            if isinstance(value, str):
                try:
                    return json.dumps(json.loads(value))
                except Exception:
                    return json.dumps(value)
            return json.dumps(value)
        if ftype == "STRING" and not isinstance(value, str):
            try:
                return str(value)
            except Exception:
                return value
        if ftype in ("INT64", "INTEGER"):
            try:
                return int(value)
            except Exception:
                return None
        if ftype in ("FLOAT64", "FLOAT"):
            try:
                return float(value)
            except Exception:
                return None
        if ftype in ("BOOL", "BOOLEAN"):
            return bool(value)
        return value

    @staticmethod
    def _parse_datetime(value: str) -> Optional[dt.datetime]:
        """Best-effort parse for DATETIME/TIMESTAMP string values."""
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return dt.datetime.strptime(text, fmt)
            except Exception:
                continue
        try:
            return dt.datetime.fromisoformat(text)
        except Exception:
            return None

    def _merge_tables(self, target_ref: bigquery.TableReference, staging_ref: bigquery.TableReference, schema_fields: Sequence[SchemaField], key_columns: Sequence[str]) -> None:
        merge_conditions = " AND ".join([f"T.{col}=S.{col}" for col in key_columns])
        update_assignments = ", ".join([f"T.{f.name}=S.{f.name}" for f in schema_fields])
        insert_columns = ", ".join([f.name for f in schema_fields])
        insert_values = ", ".join([f"S.{f.name}" for f in schema_fields])
        sql = f"""
        MERGE `{self._fqtn(target_ref)}` T
        USING `{self._fqtn(staging_ref)}` S
        ON {merge_conditions}
        WHEN MATCHED THEN UPDATE SET {update_assignments}
        WHEN NOT MATCHED THEN INSERT ({insert_columns}) VALUES ({insert_values})
        """
        self.client.query(sql).result()

    def _prepare_merge_rows(self, rows: List[Dict[str, Any]], schema_fields: Sequence[SchemaField], key_columns: Sequence[str]) -> List[Dict[str, Any]]:
        required = {f.name for f in schema_fields}
        out: List[Dict[str, Any]] = []
        for row in rows:
            base = {k: row.get(k) for k in required}
            if any(col not in row for col in key_columns):
                raise ValueError("Missing key column in row for merge.")
            out.append(base)
        return out

    def _write_via_load_job(
        self,
        target_table: str,
        rows: List[Dict[str, Any]],
        schema: Optional[Sequence[SchemaField]] = None,
        write_disposition: str = "WRITE_APPEND",
        autodetect: bool = False,
    ) -> bigquery.LoadJob:
        job = self.client.load_table_from_json(
            rows,
            destination=f"{self.project_id}.{self.dataset_id}.{target_table}",
            job_config=bigquery.LoadJobConfig(
                schema=list(schema) if schema else None,
                write_disposition=write_disposition,
                autodetect=autodetect,
                ignore_unknown_values=True,
            ),
        )
        return job

    def _fqtn(self, table_ref: Optional[bigquery.TableReference] = None) -> str:
        ref = table_ref or self.table_ref
        if not ref:
            raise ValueError("table_id is required.")
        return f"{ref.project}.{ref.dataset_id}.{ref.table_id}"

def load_credentials(service_account_info: Optional[Union[str, Dict[str, Any]]] = None, path: str = "gulong-chatbot-459723-d62aa45e3803.json") -> Dict[str, Any]:
    """Load credentials from dicts, JSON strings, explicit files, or ENV."""
    info: Optional[Dict[str, Any]] = None
    source = None
    try:
        if isinstance(service_account_info, dict):
            info = service_account_info
            source = "provided mapping"
        elif isinstance(service_account_info, str) and service_account_info.strip():
            if service_account_info.strip().startswith("{"):
                info = _load_service_account_mapping(service_account_info)
                source = "provided string"
            else:
                with open(service_account_info, "r", encoding="utf-8") as fp:
                    info = json.load(fp)
                source = service_account_info
        elif ENV.get("CREDENTIALS"):
            info = _load_service_account_mapping(ENV["CREDENTIALS"])
            source = "environment variable"
        else:
            with open(path, "r", encoding="utf-8") as fp:
                info = json.load(fp)
            source = path

        if info is None:
            raise ValueError("Unable to load service account credentials.")

        creds = service_account.Credentials.from_service_account_info(info)
        return {
            "status": "success",
            "message": f"Successfully loaded credentials from {source}.",
            "credentials": creds,
        }
    except Exception as exc:
        logger.error("Error loading credentials: %s", exc)
        return {"status": "error", "message": f"Error loading credentials: {exc}", "credentials": None}


__all__ = [
    "BigQueryUtils",
    "load_credentials",
]
