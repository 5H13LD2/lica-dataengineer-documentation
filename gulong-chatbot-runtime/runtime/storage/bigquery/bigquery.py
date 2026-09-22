"""
BigQuery helper module that centralizes CRUD helpers, Storage API streaming,
concurrency utilities, and MERGE-based upserts using a shared service-account
context.

Features:
- automatic client bootstrap with shared credentials
- SELECT query builder with DataFrame or list-of-dict outputs
- load/append/truncate helpers backed by pandas DataFrames
- Storage Write API streaming via dynamically generated protobufs (Google protocol buffers)
- thread-pooled concurrent task runner spanning multiple helper types
- upsert helper that stages rows in a temp table before issuing MERGE

"""
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from dataclasses import dataclass
import logging
import os, json, threading, datetime, decimal, numbers, re, uuid
from typing import Optional, List, Dict, Any, Union, Tuple, Type

from google.cloud import bigquery
from google.cloud.bigquery_storage_v1 import (
    BigQueryReadClient,
    BigQueryWriteClient,
    types as bq_storage_types,
    writer as bq_writer,
)
from google.oauth2 import service_account
from google.cloud.bigquery import SchemaField
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory, message as proto_message
import pandas as pd

@dataclass
class _StreamResources:
    """Cached artifacts required to send Proto rows to BigQuery Storage."""

    stream: bq_writer.AppendRowsStream
    message_cls: Type[proto_message.Message]
    schema_map: Dict[str, SchemaField]
    descriptor_pool: descriptor_pool.DescriptorPool

class BigQuery:
    """A utility class for BigQuery operations including querying, loading, and saving data."""

    _PROTO_TYPE_MAP = {
        "STRING": descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
        "BYTES": descriptor_pb2.FieldDescriptorProto.TYPE_BYTES,
        "INT64": descriptor_pb2.FieldDescriptorProto.TYPE_INT64,
        "INTEGER": descriptor_pb2.FieldDescriptorProto.TYPE_INT64,
        "FLOAT": descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE,
        "FLOAT64": descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE,
        "DOUBLE": descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE,
        "BOOL": descriptor_pb2.FieldDescriptorProto.TYPE_BOOL,
        "BOOLEAN": descriptor_pb2.FieldDescriptorProto.TYPE_BOOL,
        "NUMERIC": descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
        "BIGNUMERIC": descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
        "TIMESTAMP": descriptor_pb2.FieldDescriptorProto.TYPE_INT64,
        "DATE": descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
        "TIME": descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
        "DATETIME": descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
        "GEOGRAPHY": descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
        "JSON": descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
    }

    def __init__(self, *,
                 account_file: Optional[str] = None,
                 account_key: Optional[str] = None,
                 account_info: Optional[Dict[str, Any]] = None,
                 location: str = "asia-southeast1") -> None:
        """
        Bootstrap the BigQuery, BigQuery Storage Read, and Storage Write clients using
        service-account credentials so the helper can issue queries, load jobs, and
        streaming writes against a single GCP project.

        Args:
            None.

        Kwargs:
            account_file (str): Path to a service-account JSON file to load credentials from.
            account_key (str): Name of an environment variable that stores the JSON credentials.
            account_info (dict): In-memory service-account info if file/env are not used.
            location (str): Default geographic location for dataset operations (e.g., asia-southeast1).

        Returns:
            BigQuery instance.

        Raises:
            ValueError: If credentials cannot be found in ``account_info``, ``account_file``, or ``account_key``.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.location = location
        self.valid_write_mode = {"WRITE_TRUNCATE", "WRITE_APPEND"}

        credentials = self._get_credentials(account_file, account_key, account_info)
        self.client = bigquery.Client(credentials=credentials, project=credentials.project_id)
        self.read_client = BigQueryReadClient(credentials=credentials)
        self.write_client = BigQueryWriteClient(credentials=credentials)
        self.project_id = credentials.project_id
        self.logger.debug(f"BQ client initialized for project: {self.project_id}")

        self._table_ref_cache: Dict[str, Tuple[str, str, str]] = {}
        self._stream_cache: Dict[str, "_StreamResources"] = {}
        self._stream_lock = threading.RLock()  # serialize concurrent stream cache creation

    def _get_credentials(self,
            account_file: Optional[str],
            account_key: Optional[str],
            account_info: Optional[Dict[str, Any]]
        ) -> service_account.Credentials:
        """
        Load service-account credentials from the provided in-memory dict, a JSON file,
        or an environment variable so downstream clients share a consistent auth context.

        Args:
            account_file (str | None): Path to a service account JSON file on disk.
            account_key (str | None): Environment variable name holding JSON credentials.
            account_info (dict | None): In-memory service account payload.

        Returns:
            google.oauth2.service_account.Credentials: Auth context shared by all clients.

        Raises:
            ValueError: If no credentials can be resolved from kwargs or the environment.

        Used By:
            __init__
        """

        if account_key and account_key in os.environ:
            account_info = json.loads(os.environ[account_key])
            self.logger.debug("Credentials loaded from environment variable")

        elif account_file and os.path.exists(account_file):
            with open(account_file, 'r') as f:
                account_info = json.load(f)
            self.logger.debug(f"Credentials loaded from file")

        elif account_info: # account info is provided
            pass

        else:
            raise ValueError(f"Credentials not found in environment variable '{account_key}' or file '{account_file}'")

        credentials = service_account.Credentials.from_service_account_info(account_info)
        return credentials

    def _build_table_query(self,
        table_id: str,
        columns: Optional[List[str]],
        limit: Optional[int],
        where_clause: Optional[str],
        order_clause: Optional[Union[str, bool]],
        distinct: bool,
    ) -> str:
        """
        Construct a SELECT statement for a fully-qualified table that honours helper
        parameters such as projected columns, filters, ordering, limits, and DISTINCT.

        Args:
            table_id (str): Fully-qualified identifier ``project.dataset.table``.
            columns (list[str] | None): Explicit column list to project.
            limit (int | None): Optional row cap (positive integer).
            where_clause (str | None): Optional WHERE fragment injected verbatim.
            order_clause (str | bool | None): ORDER BY clause or ``True`` for first column.
            distinct (bool): Emit ``SELECT DISTINCT`` when True.

        Returns:
            str: Fully rendered SQL statement.

        Raises:
            ValueError: If columns/limit arguments are invalid.
            TypeError: If ``order_clause`` is not a supported type.

        Used By:
            load
        """
        column_expr = "*"
        if columns:
            cleaned = [name.strip() for name in columns if name and name.strip()]
            if not cleaned:
                raise ValueError("columns must contain at least one non-empty column name when provided")
            column_expr = ", ".join(f"`{col}`" for col in cleaned)

        select_keyword = "SELECT DISTINCT" if distinct else "SELECT"
        query = f"{select_keyword} {column_expr} FROM `{table_id}`"

        if where_clause:
            query += f" WHERE {where_clause}"

        if order_clause:
            if isinstance(order_clause, bool):
                if order_clause is True:
                    query += " ORDER BY 1"
            elif isinstance(order_clause, str):
                if order_clause.strip():
                    query += f" ORDER BY {order_clause}"
            else:
                raise TypeError("order_clause must be a string, True, False, or None")

        if limit is not None:
            if limit <= 0:
                raise ValueError("limit must be a positive integer")
            query += f" LIMIT {limit}"
        return query

    def _save_to_table(self,
        table_id: str,
        data: Union[pd.DataFrame, List[Dict[str, Any]], Dict[str, Any]],
        write_mode: str,
        schema: Optional[List[SchemaField]],
    ) -> bigquery.job.LoadJob:
        """
        Run a load job that ingests dictionaries or DataFrames into ``table_id`` with the
        requested write disposition (truncate vs append) and schema.

        Args:
            table_id (str): Fully-qualified table name receiving the rows.
            data (DataFrame | list[dict] | dict): Rows to ingest.
            write_mode (str): ``WRITE_TRUNCATE`` or ``WRITE_APPEND``.
            schema (list[SchemaField] | None): Optional schema override for load job.

        Returns:
            google.cloud.bigquery.job.LoadJob: Completed BigQuery load job.

        Raises:
            ValueError: If write_mode/data validation fails.
            TypeError: If ``data`` uses unsupported structures.

        Used By:
            truncate, append, upsert
        """

        if write_mode not in self.valid_write_mode:
            raise ValueError(f"write_mode must be one of: {self.valid_write_mode}")

        data = self._validate_data(data)

        if not isinstance(data, pd.DataFrame):
            data = pd.DataFrame(data)

        job_config = bigquery.LoadJobConfig(write_disposition=write_mode, schema=schema)
        job = self.client.load_table_from_dataframe(data, table_id, job_config=job_config, location=self.location)
        job.result()
        return job

    def _split_table_id(self, table_id: str) -> Tuple[str, str, str]:
        """
        Parse and cache ``project.dataset.table`` strings to avoid repeated splits when
        constructing API paths or referencing cached metadata.

        Args:
            table_id (str): Fully-qualified identifier to decompose.

        Returns:
            tuple[str, str, str]: ``(project, dataset, table)`` components.

        Raises:
            ValueError: If ``table_id`` is not in the expected dotted format.

        Used By:
            _get_stream_resources, upsert
        """
        if table_id not in self._table_ref_cache:
            parts = table_id.split(".")
            if len(parts) != 3 or not all(part.strip() for part in parts):
                raise ValueError("table_id must be in the form project.dataset.table")
            self._table_ref_cache[table_id] = (parts[0], parts[1], parts[2])
        return self._table_ref_cache[table_id]

    def _resolve_dataset_reference(self, dataset_id: str) -> bigquery.DatasetReference:
        """
        Normalize dataset identifiers to ``bigquery.DatasetReference`` instances.

        Args:
            dataset_id (str): Dataset identifier (``dataset`` or ``project.dataset``).

        Returns:
            bigquery.DatasetReference: Reference suitable for dataset APIs.

        Raises:
            ValueError: If ``dataset_id`` is empty or malformed.
        """
        if not dataset_id or not dataset_id.strip():
            raise ValueError("dataset_id must be provided")

        dataset_id = dataset_id.strip().strip("`")
        if "." in dataset_id:
            parts = dataset_id.split(".")
            if len(parts) != 2 or not all(parts):
                raise ValueError("dataset_id must be 'project.dataset' when project is provided")
            project, dataset = parts
        else:
            project = self.project_id
            dataset = dataset_id

        return bigquery.DatasetReference(project, dataset)

    @staticmethod
    def _validate_data(data: Union[pd.DataFrame, List[Dict[str, Any]], Dict[str, Any]]) -> Union[pd.DataFrame, List[Dict[str, Any]]]:
        """
        Normalize supported payload shapes (dict, list[dict], DataFrame) and confirm they
        contain at least one row before sending them to BigQuery APIs.

        Args:
            data (DataFrame | list[dict] | dict): User-provided payload to normalize.

        Returns:
            DataFrame | list[dict]: Non-empty, normalized rows.

        Raises:
            ValueError: If ``data`` is None or empty once normalized.
            TypeError: If ``data`` uses unsupported shapes or element types.

        Used By:
            _save_to_table (truncate and upsert), stream, upsert
        """
        if data is None:
            raise ValueError("data must not be None")
        elif isinstance(data, pd.DataFrame):
            if data.empty:
                raise ValueError("dataframe must contain at least one row")
            return data
        elif isinstance(data, dict):
            return [data]
        elif isinstance(data, list):
            if not data:
                raise ValueError("data list must contain at least one row")
            elif not all(isinstance(item, dict) for item in data):
                raise TypeError("When providing a list, all items must be dictionaries representing rows")
            return data
        else:
            raise TypeError("data must be a pandas DataFrame, a list of dictionaries, or a single row dictionary")

    def query(self, sql: str, *, as_dict: bool = False) -> Union[pd.DataFrame, List[Dict[str, Any]]]:
        """
        Execute an arbitrary SQL string through the BigQuery client and materialize the
        result via the Storage API reader for efficiency.

        Args:
            sql (str): The SQL text to send to BigQuery. Must be non-empty.

        Kwargs:
            as_dict (bool): When True, return ``list[dict]`` records instead of a DataFrame.

        Returns:
            pandas.DataFrame | list[dict[str, Any]]: Query results in the requested format.

        Raises:
            ValueError: If ``sql`` is empty or only whitespace.

        Used By:
            load, concurrent
        """
        if not sql or not sql.strip():
            raise ValueError("SQL string must be provided")

        job = self.client.query(sql, location=self.location)
        df = job.to_dataframe(bqstorage_client=self.read_client)

        if as_dict:
            result = df.to_dict(orient="records")
        else:
            result = df

        row_count = len(result)
        self.logger.debug(f"Executed query; rows={row_count}")
        return result

    def load(self,
        table_id: str,
        *,
        columns: Optional[List[str]] = None,
        limit: Optional[int] = None,
        where_clause: Optional[str] = None,
        order_clause: Optional[Union[str, bool]] = False,
        distinct: bool = False,
        as_dict: bool = False,
    ) -> Union[pd.DataFrame, List[Dict[str, Any]]]:
        """
        Read rows from a fully-qualified table by composing a SELECT statement with
        optional projection, filtering, ordering, and limit helpers.

        Args:
            table_id (str): Fully-qualified ``project.dataset.table`` identifier to read from.

        Kwargs:
            columns (list[str]): Optional explicit column list; defaults to all ``*`` when omitted.
            limit (int): Optional maximum rows to read; defaults to no limit.
            where_clause (str): Optional SQL WHERE fragment applied as provided.
            order_clause (str | bool): Optional ORDER BY clause, or ``True`` to sort by the first column.
            distinct (bool): When True, emit ``SELECT DISTINCT``.
            as_dict (bool): When True, return ``list[dict]`` instead of a DataFrame.

        Returns:
            pandas.DataFrame | list[dict[str, Any]]: Table rows in the requested format.

        Raises:
            ValueError: If helper parameters are invalid (e.g., bad limit or empty column list).
            TypeError: If ``order_clause`` is provided in an unsupported type.

        Used By:
            concurrent
        """

        sql = self._build_table_query(table_id, columns, limit, where_clause, order_clause, distinct)
        result = self.query(sql, as_dict=as_dict)
        row_count = len(result)
        self.logger.debug(f"Loaded table {table_id} query; rows={row_count}")
        return result

    def truncate(self,
        table_id: str,
        data: Union[pd.DataFrame, List[Dict[str, Any]], Dict[str, Any]],
        *,
        schema: Optional[List[SchemaField]] = None,
    ) -> bigquery.job.LoadJob:
        """
        Load rows into ``table_id`` using ``WRITE_TRUNCATE`` so any existing data is
        replaced atomically via a single load job.

        Args:
            table_id (str): Fully-qualified table target.
            data (DataFrame | list[dict] | dict): Rows to load.

        Kwargs:
            schema (list[SchemaField]): Optional schema override for the load job (defaults to None).

        Returns:
            google.cloud.bigquery.job.LoadJob: Completed job object produced by the API.

        Raises:
            ValueError: If ``data`` is empty or otherwise invalid.

        Used By:
            concurrent
        """
        job = self._save_to_table(table_id, data, "WRITE_TRUNCATE", schema)
        self.logger.debug(f"Truncated table {table_id} via load job {job.job_id}")
        return job

    def append(self,
        table_id: str,
        data: Union[pd.DataFrame, List[Dict[str, Any]], Dict[str, Any]],
        *,
        schema: Optional[List[SchemaField]] = None,
    ) -> bigquery.job.LoadJob:
        """
        Append rows to ``table_id`` using ``WRITE_APPEND`` so existing data is preserved.

        Args:
            table_id (str): Fully-qualified table target.
            data (DataFrame | list[dict] | dict): Rows to add to the table.

        Kwargs:
            schema (list[SchemaField]): Optional schema override for the load job (defaults to None).

        Returns:
            google.cloud.bigquery.job.LoadJob: Completed job object produced by the API.

        Raises:
            ValueError: If ``data`` is empty or otherwise invalid.

        Used By:
            concurrent
        """
        job = self._save_to_table(table_id, data, "WRITE_APPEND", schema)
        self.logger.debug(f"Appended to table {table_id} via load job {job.job_id}")
        return job

    def upsert(
        self,
        table_id: str,
        data: Union[pd.DataFrame, List[Dict[str, Any]], Dict[str, Any]],
        key_columns: List[str],
        *,
        schema: Optional[List[SchemaField]] = None,
        temp_prefix: str = "_tmp_upsert",
    ) -> bigquery.job.QueryJob:
        """
        Merge payload rows into ``table_id`` by loading them into a temporary table and
        issuing a BigQuery ``MERGE`` statement keyed on ``key_columns``.

        Args:
            table_id (str): Fully-qualified destination table.
            data (DataFrame | list[dict] | dict): Rows to merge into the table.
            key_columns (list[str]): Column names that uniquely identify a row.

        Kwargs:
            schema (list[SchemaField]): Optional schema subset describing the data payload.
            temp_prefix (str): Prefix for the temporary staging table name.

        Returns:
            google.cloud.bigquery.job.QueryJob: Completed MERGE job object.

        Raises:
            ValueError: If ``key_columns`` are missing or payload columns conflict with the table schema.
            google.api_core.GoogleAPICallError: If BigQuery load or merge jobs fail.

        Used By:
            concurrent
        """

        if not key_columns:
            raise ValueError("key_columns must contain at least one column name")

        normalized = self._validate_data(data)
        if isinstance(normalized, pd.DataFrame):
            df = normalized.copy()
        else:
            df = pd.DataFrame(normalized)

        if df.empty:
            raise ValueError("upsert data must contain at least one row")

        project, dataset, table_name = self._split_table_id(table_id)
        target_table = self.client.get_table(table_id)
        target_schema_map = {field.name: field for field in target_table.schema}

        if schema is not None:
            schema_map = {field.name: field for field in schema}
            extra_columns = [name for name in schema_map if name not in target_schema_map]
            if extra_columns:
                raise ValueError(f"Schema override references unknown columns: {extra_columns}")
        else:
            schema_map = target_schema_map

        missing_schema_columns = [col for col in df.columns if col not in schema_map]
        if missing_schema_columns:
            raise ValueError(f"Payload columns not found in target schema: {missing_schema_columns}")

        missing_keys = [col for col in key_columns if col not in df.columns]
        if missing_keys:
            raise ValueError(f"key_columns missing from payload: {missing_keys}")

        required_columns = [
            field.name
            for field in target_schema_map.values()
            if (field.mode or "").upper() == "REQUIRED"
        ]
        missing_required = [col for col in required_columns if col not in df.columns]
        if missing_required:
            raise ValueError(f"Payload missing required columns for insert: {missing_required}")

        upsert_columns = [col for col in df.columns if col in schema_map]
        staging_fields: List[SchemaField] = [schema_map[col] for col in upsert_columns]

        df = df.loc[:, upsert_columns]

        safe_table_name = re.sub(r"[^A-Za-z0-9_]+", "_", table_name)
        temp_table_name = f"{temp_prefix}_{safe_table_name}_{uuid.uuid4().hex}"
        temp_table_id = f"{project}.{dataset}.{temp_table_name}"
        temp_table = bigquery.Table(temp_table_id, schema=staging_fields)

        self.client.create_table(temp_table)
        merge_job: Optional[bigquery.job.QueryJob] = None
        try:
            self._save_to_table(temp_table_id, df, "WRITE_TRUNCATE", staging_fields)

            on_clause = " AND ".join(
                [f"T.`{col}` = S.`{col}`" for col in key_columns]
            )
            update_columns = [col for col in upsert_columns if col not in key_columns]
            set_clause = ", ".join([f"T.`{col}` = S.`{col}`" for col in update_columns])
            insert_columns = ", ".join([f"`{col}`" for col in upsert_columns])
            values_clause = ", ".join([f"S.`{col}`" for col in upsert_columns])

            merge_components = [
                f"MERGE `{table_id}` AS T",
                f"USING `{temp_table_id}` AS S",
                f"ON {on_clause}",
            ]

            if update_columns:
                merge_components.append(f"WHEN MATCHED THEN UPDATE SET {set_clause}")

            merge_components.append(
                f"WHEN NOT MATCHED THEN INSERT ({insert_columns}) VALUES ({values_clause})"
            )

            merge_sql = "\n".join(merge_components)
            job_config = bigquery.QueryJobConfig()
            merge_job = self.client.query(merge_sql, job_config=job_config, location=self.location)
            merge_job.result()
        finally:
            try:
                self.client.delete_table(temp_table_id, not_found_ok=True)
            except Exception as exc:
                self.logger.warning(f"Failed to delete temp table {temp_table_id}: {exc}")

        if merge_job is None:
            raise RuntimeError("Upsert merge job did not complete as expected")

        self.logger.debug(f"Upserted {len(df)} rows into {table_id} via temp table {temp_table_name}")
        return merge_job

    def concurrent(self,
        tasks: List[Dict[str, Any]],
        *,
        execute_futures: bool = True,
        max_workers: int = 8,
    ) -> Union[Dict[str, Dict[str, Any]], Dict[str, Future]]:
        """
        Dispatch multiple helper operations (query, load, truncate, append, upsert, warm_stream)
        via a thread pool so independent workloads can execute in parallel.

        Args:
            tasks (list[dict]): Each dict must describe a task with ``type`` and ``key`` fields.

        Kwargs:
            execute_futures (bool): When True, wait for every task and return their results;
                when False, return the raw future map so callers can await manually.
            max_workers (int | None): Optional thread cap; defaults to len(tasks) when omitted.

        Returns:
            dict[str, dict]: Mapping of task key -> {result, error} when ``execute_futures`` is True.
            dict[concurrent.futures.Future, str]: Future map when ``execute_futures`` is False.

        Raises:
            ValueError: If an unsupported task type is provided.

        Used By:
            None.
        """

        if not tasks:
            return {}

        for index, task in enumerate(tasks):
            missing = [field for field in ("type", "key") if field not in task]
            if missing:
                raise ValueError(
                    f"Task at index {index} missing required field(s): {', '.join(missing)}"
                )

        seen_keys: set[str] = set()
        effective_workers = max(1, min(len(tasks), max_workers))

        def _dispatch(task: Dict[str, Any]) -> Dict[str, Any]:
            task_type = task["type"]
            key = task["key"]

            if task_type not in {"query", "load", "truncate", "append", "upsert", "warm_stream"}:
                raise ValueError(f"Unsupported task type '{task_type}'.")

            kwargs = {k: v for k, v in task.items() if k not in {"type", "key"}}

            try:
                if task_type == "query":
                    payload = self.query(**kwargs)
                elif task_type == "load":
                    payload = self.load(**kwargs)
                elif task_type == "truncate":
                    payload = self.truncate(**kwargs)
                elif task_type == "append":
                    payload = self.append(**kwargs)
                elif task_type == "upsert":
                    payload = self.upsert(**kwargs)
                elif task_type == "warm_stream":
                    payload = self.warm_stream(**kwargs)
                else:   
                    raise RuntimeError(f"Unhandled task type '{task_type}'.")

                return {"result": payload, "error": None}
            except Exception as error:
                self.logger.error(f"Concurrent task '{key}' of type '{task_type}' failed: {error}")
                return {"result": None, "error": str(error)}

        executor = ThreadPoolExecutor(max_workers=effective_workers)
        future_map: Dict[Future, str] = {}

        for task in tasks:
            key = task["key"]
            if key in seen_keys:
                executor.shutdown(wait=False, cancel_futures=True)
                raise ValueError(f"Duplicate task key '{key}' detected; keys must be unique")
            seen_keys.add(key)
            future = executor.submit(_dispatch, task)
            future_map[future] = key

        if execute_futures:
            results = self._execute_future_map(future_map)
            executor.shutdown(wait=True)
            self.logger.debug(f"Completed concurrent tasks; count={len(results)}")
            return results

        executor.shutdown(wait=False)
        self.logger.debug(f"Dispatched concurrent tasks; count={len(future_map)}")
        return future_map

    @staticmethod
    def _execute_future_map(future_map: Dict[Future, str]) -> Dict[str, Dict[str, Any]]:
        """
        Materialize the results of futures produced by ``concurrent`` while keeping their
        user-supplied keys aligned with each completed future.

        Args:
            future_map (dict[Future, str]): Mapping of future -> user key from ``concurrent``.

        Returns:
            dict[str, dict[str, Any]]: Final results keyed by the original task keys.

        Raises:
            None.

        Used By:
            None.
        """
        results: Dict[str, Dict[str, Any]] = {}
        for future in as_completed(future_map):
            key = future_map[future]
            results[key] = future.result()

        return results

    def stream(self,
        table_id: str,
        data: Union[pd.DataFrame, List[Dict[str, Any]], Dict[str, Any]],
    ) -> bq_writer.AppendRowsFuture:
        """
        Stream rows to BigQuery via the Storage Write API, returning the append future so
        callers can wait for completion or attach callbacks.

        Args:
            table_id (str): Fully-qualified destination table.
            data (DataFrame | list[dict] | dict): Payload containing one or more rows.

        Returns:
            google.cloud.bigquery_storage_v1.writer.AppendRowsFuture: Future representing the append RPC.

        Raises:
            ValueError: If ``data`` is empty after normalization.
            TypeError: If ``data`` contains unsupported structures for the table schema.

        Used By:
            concurrent
        """

        validated = self._validate_data(data)

        if isinstance(validated, pd.DataFrame):
            rows = validated.to_dict(orient="records")
        else:
            rows = validated

        if not rows:
            raise ValueError("stream data must contain at least one row")

        resources = self._get_stream_resources(table_id)

        proto_rows = bq_storage_types.ProtoRows()
        for row in rows:
            serialized = self._serialize_row(resources, row)
            proto_rows.serialized_rows.append(serialized)

        request = bq_storage_types.AppendRowsRequest()
        proto_data = bq_storage_types.AppendRowsRequest.ProtoData()
        proto_data.rows = proto_rows
        request.proto_rows = proto_data

        future = resources.stream.send(request)
        future.add_done_callback(lambda f, tid=table_id: self._handle_append_future(tid, f))
        self.logger.debug(f"Streamed {len(rows)} rows to {table_id}")
        return future

    def warm_stream(self, table_id: str, *, dummy_append: bool=True) -> None:
        """
        Prime or refresh the cached streaming resources for ``table_id`` so the next real
        append avoids expensive schema negotiation.

        Args:
            table_id (str): Fully-qualified destination table.

        Kwargs:
            dummy_append (bool): When True, send an empty append request to proactively warm the stream.

        Returns:
            None.

        Raises:
            google.api_core.GoogleAPICallError: If the warm-up append fails unexpectedly.

        Used By:
            stream, concurrent
        """
        # ensure fresh stream/schema by clearing any cached entry before rebuilding
        with self._stream_lock:
            cached = self._stream_cache.pop(table_id, None)
        if cached:
            try:
                cached.stream.close()
            except Exception as exc:
                self.logger.debug(f"Failed to close cached stream for {table_id}: {exc}")

        resources = self._get_stream_resources(table_id)

        if dummy_append:
            empty_request = bq_storage_types.AppendRowsRequest()
            empty_proto_data = bq_storage_types.AppendRowsRequest.ProtoData()
            empty_proto_data.rows = bq_storage_types.ProtoRows()
            empty_request.proto_rows = empty_proto_data
            future = resources.stream.send(empty_request)
            try:
                future.result()
            except Exception as exc:
                message = str(exc)
                if "Rows must be specified" in message:
                    self.logger.debug(f"Warm stream dummy append for {table_id} received expected empty-request response.")
                else:
                    self.logger.warning(f"Warm stream dummy append for {table_id} failed: {exc}")
        self.logger.debug(f"Warm stream completed for {table_id}")

    def _get_stream_resources(self, table_id: str) -> "_StreamResources":
        """
        Build or fetch the cached AppendRowsStream, dynamic proto message type, and schema
        metadata required to serialize rows for the Storage Write API.

        Args:
            table_id (str): Fully-qualified table name to stream into.

        Returns:
            _StreamResources: Cached stream, message class, schema map, and descriptor pool.

        Raises:
            google.cloud.exceptions.NotFound: If the referenced table does not exist.

        Used By:
            stream, warm_stream
        """
        with self._stream_lock:
            cached = self._stream_cache.get(table_id)
            if cached:
                return cached

            project, dataset, table = self._split_table_id(table_id)
            table_obj = self.client.get_table(table_id)
            descriptor = self._schema_to_descriptor(table_obj.schema)

            stream_name = f"{self.write_client.table_path(project, dataset, table)}/_default"

            proto_schema = bq_storage_types.ProtoSchema()
            proto_schema.proto_descriptor.CopyFrom(descriptor)

            request_template = bq_storage_types.AppendRowsRequest()
            request_template.write_stream = stream_name
            proto_data = bq_storage_types.AppendRowsRequest.ProtoData()
            proto_data.writer_schema = proto_schema
            request_template.proto_rows = proto_data

            append_stream = bq_writer.AppendRowsStream(self.write_client, request_template)

            file_descriptor_proto = descriptor_pb2.FileDescriptorProto()
            file_descriptor_proto.name = f"{dataset}_{table}_stream.proto"
            file_descriptor_proto.package = "bqstream"
            file_descriptor_proto.message_type.add().CopyFrom(descriptor)

            pool = descriptor_pool.DescriptorPool()
            pool.Add(file_descriptor_proto)
            message_descriptor = pool.FindMessageTypeByName("bqstream.Row")
            message_cls = self._build_message_class(pool, message_descriptor)

            schema_map = {field.name: field for field in table_obj.schema}
            resources = _StreamResources(
                stream=append_stream,
                message_cls=message_cls,
                schema_map=schema_map,
                descriptor_pool=pool,
            )
            self._stream_cache[table_id] = resources
            return resources

    @staticmethod
    def _sanitize_proto_name(name: str) -> str:
        """
        Transform arbitrary column names into proto-safe CamelCase identifiers so nested
        RECORD fields can be represented as generated message types.

        Args:
            name (str): Original column/field name to sanitize.

        Returns:
            str: CamelCase proto-safe identifier.

        Raises:
            None.

        Used By:
            _next_nested_message_name
        """
        cleaned = re.sub(r"[^0-9A-Za-z_]", "_", name or "")
        cleaned = re.sub(r"^[^A-Za-z_]+", "", cleaned)
        parts = [part for part in cleaned.split("_") if part]
        camel = "".join(part[:1].upper() + part[1:] for part in parts)
        return camel or "Field"

    def _next_nested_message_name(self, base: str, existing: Dict[str, None]) -> str:
        """
        Generate unique, proto-safe nested message names to avoid collisions while
        translating RECORD/STRUCT columns into descriptors.

        Args:
            base (str): Suggested field name to derive the nested message name from.
            existing (dict[str, None]): Lookup of already allocated names for the descriptor.

        Returns:
            str: Unique nested message identifier.

        Raises:
            None.

        Used By:
            _schema_to_descriptor
        """
        candidate_base = self._sanitize_proto_name(base)
        candidate = candidate_base
        index = 1
        while candidate in existing:
            candidate = f"{candidate_base}{index}"
            index += 1
        existing[candidate] = None
        return candidate

    def _schema_to_descriptor(
        self, schema: List[SchemaField], *, message_name: str = "Row"
    ) -> descriptor_pb2.DescriptorProto:
        """
        Convert a BigQuery table schema into a proto2 DescriptorProto so rows can be
        serialized for the Storage Write API.

        Args:
            schema (list[SchemaField]): BigQuery schema describing the table.
            message_name (str): Root message name to use for the descriptor.

        Kwargs:
            None (``message_name`` is a keyword-only parameter already documented).

        Returns:
            google.protobuf.descriptor_pb2.DescriptorProto: Descriptor matching the schema.

        Raises:
            None.

        Used By:
            _get_stream_resources
        """
        descriptor = descriptor_pb2.DescriptorProto()
        descriptor.name = message_name

        nested_names: Dict[str, None] = {}

        for index, field in enumerate(schema, start=1):
            normalized_type = (field.field_type or "").upper()
            field_descriptor = descriptor.field.add()
            field_descriptor.name = field.name
            field_descriptor.json_name = field.name
            field_descriptor.number = index

            mode = (field.mode or "").upper()
            if mode == "REPEATED":
                field_descriptor.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
            elif mode == "REQUIRED":
                field_descriptor.label = descriptor_pb2.FieldDescriptorProto.LABEL_REQUIRED
            else:
                field_descriptor.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL

            if normalized_type in {"RECORD", "STRUCT"}:
                nested_name = self._next_nested_message_name(field.name, nested_names)
                nested_descriptor = self._schema_to_descriptor(
                    list(field.fields), message_name=nested_name
                )
                descriptor.nested_type.add().CopyFrom(nested_descriptor)
                field_descriptor.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
                field_descriptor.type_name = nested_descriptor.name
                continue

            field_descriptor.type = self._PROTO_TYPE_MAP.get(
                normalized_type, descriptor_pb2.FieldDescriptorProto.TYPE_STRING
            )

            if normalized_type not in self._PROTO_TYPE_MAP:
                self.logger.warning(f"Defaulting field '{field.name}' of type '{field.field_type}' to STRING for streaming writes.")

        return descriptor

    def _serialize_row(self, resources: "_StreamResources", row: Dict[str, Any]) -> bytes:
        """
        Populate the cached proto message class with row values and serialize it into
        bytes ready for AppendRows requests.

        Args:
            resources (_StreamResources): Cached writer artifacts for the table.
            row (dict[str, Any]): Single row payload to encode.

        Returns:
            bytes: Serialized proto row.

        Raises:
            ValueError: If serialization fails due to incompatible field values.

        Used By:
            stream
        """
        message = resources.message_cls()
        self._populate_message_from_row(
            message,
            resources.schema_map,
            row,
        )
        return message.SerializeToString()

    def _populate_message_from_row(
        self,
        message: proto_message.Message,
        schema_map: Dict[str, SchemaField],
        row: Mapping[str, Any],
        *,
        field_path: str = "",
    ) -> None:
        """
        Traverse a nested row mapping and assign converted values to the dynamic proto
        message while preserving nested/REPEATED semantics.

        Args:
            message (proto.Message): Mutable proto instance being populated.
            schema_map (dict[str, SchemaField]): Mapping of field name -> schema field.
            row (Mapping[str, Any]): Data to write into the proto.
            field_path (str): Dot-qualified context for error reporting.

        Kwargs:
            None (``field_path`` is keyword-only for clarity).

        Returns:
            None.

        Raises:
            ValueError: If nested payloads cannot be coerced into the schema definition.
            TypeError: When encountering incompatible types for RECORD/repeated fields.

        Used By:
            _serialize_row
        """
        for key, value in row.items():
            current_path = f"{field_path}.{key}" if field_path else key
            field = schema_map.get(key)
            if field is None:
                raise ValueError(f"Payload column '{current_path}' not found in destination schema")
            if value is None:
                continue

            normalized_type = (field.field_type or "").upper()
            mode = (field.mode or "").upper()

            try:
                if normalized_type in {"RECORD", "STRUCT"}:
                    if mode == "REPEATED":
                        target = getattr(message, key)
                        nested_schema_map = {
                            nested.name: nested for nested in field.fields
                        }
                        iterable_value = self._coerce_repeated_values(
                            value, current_path, allow_mapping_wrap=True, as_record=True
                        )
                        for item in iterable_value:
                            if item is None:
                                continue
                            if not isinstance(item, Mapping):
                                raise TypeError(f"Expected mapping elements for repeated RECORD field '{current_path}'")
                            nested_message = target.add()
                            self._populate_message_from_row(
                                nested_message,
                                nested_schema_map,
                                item,
                                field_path=current_path,
                            )
                    else:
                        if not isinstance(value, Mapping):
                            raise TypeError(f"Expected mapping value for RECORD field '{current_path}'")
                        nested_message = getattr(message, key)
                        nested_schema_map = {nested.name: nested for nested in field.fields}
                        self._populate_message_from_row(
                            nested_message,
                            nested_schema_map,
                            value,
                            field_path=current_path,
                        )
                    continue

                if mode == "REPEATED":
                    target = getattr(message, key)
                    iterable_value = self._coerce_repeated_values(value, current_path)
                    for item in iterable_value:
                        converted = self._convert_field_value(normalized_type, item)
                        if converted is not None:
                            target.append(converted)
                else:
                    converted = self._convert_field_value(normalized_type, value)
                    if converted is not None:
                        setattr(message, key, converted)
            except Exception as exc:
                raise ValueError(f"Failed to encode field '{current_path}' with value '{value}': {exc}") from exc

    def _coerce_repeated_values(
        self,
        value: Any,
        field_path: str,
        *,
        allow_mapping_wrap: bool = False,
        as_record: bool = False,
    ) -> Iterable[Any]:
        """
        Normalize arbitrary Python objects into iterables suitable for repeated proto
        fields, applying helpful coercions for mappings and pandas objects.

        Args:
            value (Any): User-supplied repeated field payload.
            field_path (str): Dot-qualified field name for error context.
            allow_mapping_wrap (bool): When True, wrap mappings in a single-element list.
            as_record (bool): When True, attempt pandas ``to_dict('records')`` coercion.

        Kwargs:
            None (all parameters are explicit keyword-only above).

        Returns:
            Iterable[Any]: Iterable of values acceptable for repeated proto fields.

        Raises:
            TypeError: If ``value`` cannot be coerced into an iterable form.

        Used By:
            _populate_message_from_row
        """
        if value is None:
            raise TypeError(f"Expected iterable for repeated field '{field_path}'")

        if isinstance(value, (list, tuple)):
            return value

        if allow_mapping_wrap and isinstance(value, Mapping):
            return [value]

        if as_record and hasattr(value, "to_dict"):
            try:
                records = value.to_dict(orient="records")  # type: ignore[call-arg]
            except TypeError:
                pass
            else:
                if isinstance(records, list):
                    return records

        if isinstance(value, pd.Series):
            return value.tolist()

        if hasattr(value, "tolist") and not isinstance(value, (str, bytes, bytearray)):
            converted = value.tolist()  # type: ignore[attr-defined]
            if isinstance(converted, list):
                return converted

        if isinstance(value, Iterable) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            return value

        raise TypeError(f"Expected iterable for repeated field '{field_path}'")

    def _convert_field_value(self, field_type: str, value: Any) -> Optional[Any]:
        """
        Convert Python primitives into the scalar types expected by generated proto
        message fields, handling NUMERIC, TIMESTAMP, JSON, and other BigQuery variants.

        Args:
            field_type (str): BigQuery field type identifier (upper/lower case tolerated).
            value (Any): Value to convert into a proto-compatible scalar.

        Returns:
            Any | None: Converted value ready for proto assignment, or None to skip.

        Raises:
            TypeError: If ``value`` cannot be interpreted for the requested ``field_type``.

        Used By:
            _populate_message_from_row
        """
        if value is None:
            return None

        field_type = (field_type or "").upper()
        if isinstance(value, pd.Timestamp):
            value = value.to_pydatetime()

        if field_type in {"INT64", "INTEGER"}:
            if isinstance(value, numbers.Integral):
                return int(value)
            if isinstance(value, (float, decimal.Decimal)):
                return int(value)
            return int(str(value))

        if field_type in {"FLOAT", "FLOAT64", "DOUBLE"}:
            return float(value)

        if field_type in {"BOOL", "BOOLEAN"}:
            if isinstance(value, str):
                return value.lower() in {"true", "1", "t", "yes"}
            return bool(value)

        if field_type == "BYTES":
            if isinstance(value, bytes):
                return value
            return str(value).encode("utf-8")

        if field_type in {"NUMERIC", "BIGNUMERIC"}:
            if isinstance(value, decimal.Decimal):
                return format(value, "f")
            return str(value)

        if field_type == "TIMESTAMP":
            if isinstance(value, datetime.datetime):
                if value.tzinfo is None:
                    value = value.replace(tzinfo=datetime.timezone.utc)
                else:
                    value = value.astimezone(datetime.timezone.utc)
                return int(value.timestamp() * 1_000_000)
            if isinstance(value, (int, float, decimal.Decimal)):
                return int(decimal.Decimal(value) * decimal.Decimal(1_000_000))
            if isinstance(value, str):
                parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=datetime.timezone.utc)
                else:
                    parsed = parsed.astimezone(datetime.timezone.utc)
                return int(parsed.timestamp() * 1_000_000)
            raise TypeError(f"Unsupported TIMESTAMP value type: {type(value)!r}")

        if field_type in {"DATE", "TIME", "DATETIME", "JSON", "GEOGRAPHY"}:
            if isinstance(value, (dict, list)):
                return json.dumps(value)
            if isinstance(value, datetime.date) and field_type == "DATE":
                return value.isoformat()
            if isinstance(value, datetime.time) and field_type == "TIME":
                return value.isoformat()
            if isinstance(value, datetime.datetime) and field_type == "DATETIME":
                return value.isoformat()
            return str(value)

        return str(value)

    def _schema_field_to_dict(self, field: SchemaField, *, include_nested: bool) -> Dict[str, Any]:
        """
        Convert a ``SchemaField`` (possibly nested) into a serializable dict.

        Args:
            field (SchemaField): BigQuery schema description.

        Returns:
            dict: Serializable representation including nested children.
        """
        column = {
            "name": field.name,
            "type": field.field_type,
            "mode": field.mode,
            "description": field.description,
            "fields": [],
        }
        if include_nested and field.fields:
            column["fields"] = [
                self._schema_field_to_dict(nested, include_nested=include_nested)
                for nested in field.fields
            ]
        return column

    def get_dataset_schema(self, dataset_id: str, *, depth: str = "dataset") -> Dict[str, Any]:
        """
        Retrieve metadata (description, labels, tables, columns) for a dataset.

        Args:
            dataset_id (str): Dataset identifier (``dataset`` or ``project.dataset``).

        Returns:
            dict: Structured dataset metadata including table/column descriptions.

        Raises:
            ValueError: If ``dataset_id`` is empty or malformed.
            google.api_core.GoogleAPICallError: If the dataset lookup fails.
        """
        depth = depth.lower()
        valid_depth = {"dataset", "table", "column"}
        if depth not in valid_depth:
            raise ValueError(f"depth must be one of {valid_depth}")

        dataset_ref = self._resolve_dataset_reference(dataset_id)
        dataset = self.client.get_dataset(dataset_ref)

        tables: List[Dict[str, Any]] = []
        if depth in {"table", "column"}:
            for table_item in self.client.list_tables(dataset_ref):
                table = self.client.get_table(table_item.reference)
                partitioning = None
                if table.time_partitioning:
                    partitioning = {
                        "type": table.time_partitioning.type_,
                        "field": table.time_partitioning.field,
                        "expiration_ms": table.time_partitioning.expiration_ms,
                    }

                columns: List[Dict[str, Any]] = []
                if depth == "column":
                    columns = [
                        self._schema_field_to_dict(field, include_nested=True)
                        for field in table.schema
                    ]

                tables.append(
                    {
                        "table_id": table.table_id,
                        "full_table_id": getattr(table, "full_table_id", None),
                        "table_type": table.table_type,
                        "num_rows": getattr(table, "num_rows", None),
                        "table_description": table.description,
                        "labels": dict(table.labels or {}),
                        "partitioning": partitioning,
                        "clustering_fields": list(table.clustering_fields or []),
                        "columns": columns,
                    }
                )

        schema: Dict[str, Any] = {
            "project_id": dataset.project,
            "dataset_id": dataset.dataset_id,
            "full_dataset_id": getattr(dataset, "full_dataset_id", None),
            "location": dataset.location,
            "dataset_description": dataset.description,
            "labels": dict(dataset.labels or {}),
            "default_table_expiration_ms": dataset.default_table_expiration_ms,
            "tables": tables,
        }
        return schema

    def get_project_schema(self, *, depth: str = "dataset") -> Dict[str, Any]:
        """
        Enumerate every dataset (and optionally tables/columns) in the authenticated project.

        Args:
            depth (str): One of ``dataset``, ``table``, ``column`` controlling detail.

        Returns:
            dict: Mapping containing project id and dataset catalog entries.

        Raises:
            ValueError: If ``depth`` is invalid.
        """
        depth = depth.lower()
        valid_depth = {"dataset", "table", "column"}
        if depth not in valid_depth:
            raise ValueError(f"depth must be one of {valid_depth}")

        datasets: List[Dict[str, Any]] = []
        for dataset_item in self.client.list_datasets(self.project_id):
            full_dataset_id = f"{dataset_item.project}.{dataset_item.dataset_id}"
            datasets.append(self.get_dataset_schema(full_dataset_id, depth=depth))

        return {"project_id": self.project_id, "datasets": datasets}

    def _handle_append_future(self, table_id: str, future: bq_writer.AppendRowsFuture) -> None:
        """
        Observe append futures and log exceptions so streaming errors do not get lost
        when callers ignore the returned future.

        Args:
            table_id (str): Fully-qualified table identifier for logging context.
            future (AppendRowsFuture): Future returned by the Storage Write API.

        Returns:
            None.

        Raises:
            None (errors are logged instead of re-raised).

        Used By:
            stream
        """
        try:
            future.result()
        except Exception as exc:
            self.logger.error(f"BigQuery streaming append failed for {table_id}: {exc}")

    def _build_message_class(
        self,
        pool: descriptor_pool.DescriptorPool,
        descriptor: descriptor_pb2.DescriptorProto,
    ) -> Type[proto_message.Message]:
        """
        Retrieve a dynamic proto message class for ``descriptor``, falling back to
        ``MessageFactory`` helpers depending on the available protobuf features.

        Args:
            pool (descriptor_pool.DescriptorPool): Pool containing the descriptor.
            descriptor (DescriptorProto): Proto definition to materialize into a class.

        Returns:
            Type[proto.Message]: Dynamic protobuf message class usable for serialization.

        Raises:
            RuntimeError: If a message class cannot be constructed from the descriptor.

        Used By:
            _get_stream_resources
        """
        try:
            return pool.GetMessageClass(descriptor.full_name)  # type: ignore[attr-defined]
        except AttributeError:
            pass

        try:
            factory = message_factory.MessageFactory(pool)
            return factory.GetPrototype(descriptor)  # type: ignore[attr-defined]
        except AttributeError:
            try:
                return message_factory.GetMessageClass(descriptor)  # type: ignore[attr-defined]
            except AttributeError as exc:
                raise RuntimeError("Unable to construct protobuf message class for streaming rows") from exc
