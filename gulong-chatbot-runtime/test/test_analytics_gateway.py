import threading

from runtime.gateways.analytics_gateway import BigQueryAnalyticsGateway, MemoryAnalyticsGateway
from runtime.runtime_app import build_analytics_gateway
from runtime.shared.provider_registry import register_analytics_writer
from runtime.storage.bigquery.bigquery_client import _load_service_account_mapping
import pytest

from runtime.shared.analytics_schema import turn_trace_log_schema
from runtime.storage import postgres_analytics_writer as pg_writer
from runtime.storage.bigquery.bigquery_client import BQWriterConfig, BigQueryBatchWriter
from runtime.storage.postgres_analytics_writer import DualAnalyticsWriter, _has_column, build_postgres_analytics_config


class FakeWriter:
    def __init__(self, *, fail_flush: bool = False):
        self.fail_flush = fail_flush
        self.enqueued = []
        self.flushed = []
        self.async_flushed = []

    def enqueue(self, table, rows, *, schema=None, key_columns=None):
        self.enqueued.append(
            {
                "table": table,
                "rows": list(rows),
                "schema": schema,
                "key_columns": key_columns,
            }
        )

    def flush(self, table):
        if self.fail_flush:
            raise RuntimeError("flush failed")
        self.flushed.append(table)

    def flush_async(self, table):
        self.async_flushed.append(table)


def test_bigquery_analytics_gateway_buffers_normalized_rows_until_turn_dispatch():
    writer = FakeWriter()
    gateway = BigQueryAnalyticsGateway(writer=writer)

    gateway.enqueue_request_state_log(
        {
            "request_id": "req_1",
            "attempt_count": "1",
            "tokens_in": "10",
            "tokens_out": "2",
        }
    )
    gateway.enqueue_turn_trace_log(
        {
            "request_id": "req_1",
            "turn_latency_ms": "123",
            "llm_calls": "1",
            "tool_calls": "0",
            "tool_failures": "0",
        }
    )

    assert [item["table"] for item in writer.enqueued] == ["request_state_log", "turn_trace_log"]
    assert writer.flushed == []
    assert writer.async_flushed == []
    assert writer.enqueued[0]["rows"][0]["attempt_count"] == 1
    assert writer.enqueued[1]["rows"][0]["turn_latency_ms"] == 123
    assert writer.enqueued[0]["key_columns"] is None
    assert writer.enqueued[1]["key_columns"] is None


def test_bigquery_analytics_gateway_appends_runtime_log_rows():
    writer = FakeWriter()
    gateway = BigQueryAnalyticsGateway(writer=writer)

    gateway.enqueue_assistant_log({"request_id": "req_1"})
    gateway.enqueue_tool_output_log({"request_id": "req_1"})
    gateway.enqueue_error_log({"request_id": "req_1"})
    gateway.enqueue_slots_log({"request_id": "req_1"})
    gateway.enqueue_debug_log({"request_id": "req_1"})
    gateway.enqueue_request_state_log({"request_id": "req_1"})
    gateway.enqueue_request_attempt_log({"request_id": "req_1"})
    gateway.enqueue_turn_trace_log({"request_id": "req_1"})
    gateway.enqueue_turn_fact_log({"request_id": "req_1"})
    gateway.enqueue_llm_span_log({"request_id": "req_1"})
    gateway.enqueue_tool_call_log({"request_id": "req_1"})

    assert [item["table"] for item in writer.enqueued] == [
        "assistant_log",
        "tool_output_log",
        "error_log",
        "slots_log",
        "debug_log",
        "request_state_log",
        "request_attempt_log",
        "turn_trace_log",
        "turn_fact_log",
        "llm_span_log",
        "tool_call_log",
    ]
    assert all(item["key_columns"] is None for item in writer.enqueued)
    assert all(item["rows"][0].get("row_id") for item in writer.enqueued)


def test_bigquery_analytics_gateway_appends_runtime_logs_without_merge_keys():
    writer = FakeWriter()
    gateway = BigQueryAnalyticsGateway(writer=writer)

    gateway.enqueue_assistant_log({"request_id": "req_1", "elapsed_ms": "10"})
    gateway.enqueue_tool_output_log({"request_id": "req_1", "tool_name": "search"})
    gateway.enqueue_error_log({"request_id": "req_1", "error_type": "test"})
    gateway.enqueue_slots_log({"request_id": "req_1", "slot_summary": {}})
    gateway.enqueue_debug_log({"request_id": "req_1", "debug_payload": {}})
    gateway.enqueue_request_state_log({"request_id": "req_1", "attempt_count": "1"})
    gateway.enqueue_request_attempt_log({"request_id": "req_1", "attempt_no": "1"})
    gateway.enqueue_turn_trace_log({"request_id": "req_1", "turn_latency_ms": "20"})
    gateway.enqueue_turn_fact_log({"request_id": "req_1", "tokens_total": "3"})
    gateway.enqueue_llm_span_log({"request_id": "req_1", "span_index": "0"})
    gateway.enqueue_tool_call_log({"request_id": "req_1", "call_index": "0"})

    assert {item["table"] for item in writer.enqueued} == {
        "assistant_log",
        "tool_output_log",
        "error_log",
        "slots_log",
        "debug_log",
        "request_state_log",
        "request_attempt_log",
        "turn_trace_log",
        "turn_fact_log",
        "llm_span_log",
        "tool_call_log",
    }
    assert all(item["key_columns"] is None for item in writer.enqueued)
    assert all(item["rows"][0].get("row_id") for item in writer.enqueued)


def test_bigquery_analytics_gateway_does_not_call_blocking_flush_and_updates_fallback():
    fallback = MemoryAnalyticsGateway()
    writer = FakeWriter(fail_flush=True)
    gateway = BigQueryAnalyticsGateway(writer=writer, fallback=fallback)

    gateway.enqueue_debug_log({"request_id": "req_1"})
    gateway.enqueue_turn_trace_log({"request_id": "req_1", "turn_latency_ms": "123"})

    assert writer.flushed == []
    assert writer.async_flushed == []
    assert fallback.last_turn_trace_log()["request_id"] == "req_1"


def test_bigquery_analytics_gateway_dispatches_completed_normalized_turn_batches():
    writer = FakeWriter()
    gateway = BigQueryAnalyticsGateway(writer=writer)

    gateway.enqueue_turn_fact_log({"request_id": "req_1"})
    gateway.enqueue_interaction_event_log({"request_id": "req_1", "event_type": "choice_clicked"})
    gateway.flush_normalized_async()

    assert writer.async_flushed == sorted(gateway._NORMALIZED_TABLES)


def test_bigquery_batch_writer_flush_async_does_not_block_caller():
    writer = BigQueryBatchWriter(
        config=BQWriterConfig(
            project_id="test-project",
            dataset_id="analytics",
            max_rows=100,
            max_age_s=60,
        )
    )
    write_started = threading.Event()
    release_write = threading.Event()

    def slow_write(*_args, **_kwargs):
        write_started.set()
        release_write.wait(timeout=2)

    writer._write_rows = slow_write
    writer.enqueue("turn_trace_log", [{"request_id": "req_1"}])
    writer.flush_async("turn_trace_log")

    assert write_started.wait(timeout=1)
    release_write.set()


def test_bigquery_batch_network_write_does_not_hold_enqueue_lock():
    writer = BigQueryBatchWriter(
        config=BQWriterConfig(
            project_id="test-project",
            dataset_id="analytics",
            max_rows=100,
            max_age_s=60,
        )
    )
    write_started = threading.Event()
    release_write = threading.Event()
    enqueue_finished = threading.Event()

    def slow_write(*_args, **_kwargs):
        write_started.set()
        release_write.wait(timeout=2)

    writer._write_rows = slow_write
    writer.enqueue("debug_log", [{"request_id": "req_1"}])
    flush_thread = threading.Thread(target=writer.flush, args=("debug_log",))
    flush_thread.start()
    assert write_started.wait(timeout=1)

    enqueue_thread = threading.Thread(
        target=lambda: (
            writer.enqueue("turn_fact_log", [{"request_id": "req_1"}]),
            enqueue_finished.set(),
        )
    )
    enqueue_thread.start()

    assert enqueue_finished.wait(timeout=0.5)
    release_write.set()
    flush_thread.join(timeout=1)
    enqueue_thread.join(timeout=1)


def test_bigquery_analytics_gateway_adds_runtime_metadata(monkeypatch):
    monkeypatch.setenv("SERVICE_ENVIRONMENT", "shadow")
    monkeypatch.setenv("RUNTIME_HOST", "chatbot-runtime-vm")
    monkeypatch.setenv("RELEASE_VERSION", "rel-1")
    monkeypatch.setenv("GIT_SHA", "abc123")
    writer = FakeWriter()
    gateway = BigQueryAnalyticsGateway(writer=writer)

    gateway.enqueue_turn_trace_log({"request_id": "req_1"})

    row = writer.enqueued[0]["rows"][0]
    assert row["service_environment"] == "shadow"
    assert row["runtime_host"] == "chatbot-runtime-vm"
    assert row["release_version"] == "rel-1"
    assert row["git_sha"] == "abc123"
    assert {field["name"] for field in writer.enqueued[0]["schema"]} >= {
        "service_environment",
        "runtime_host",
        "release_version",
        "git_sha",
    }


def test_bigquery_analytics_gateway_preserves_explicit_runtime_metadata(monkeypatch):
    monkeypatch.setenv("SERVICE_ENVIRONMENT", "shadow")
    monkeypatch.setenv("RUNTIME_HOST", "chatbot-runtime-vm")
    writer = FakeWriter()
    gateway = BigQueryAnalyticsGateway(writer=writer)

    gateway.enqueue_turn_trace_log(
        {
            "request_id": "req_1",
            "service_environment": "live",
            "runtime_host": "gulong-chatbot-runtime-live",
        }
    )

    row = writer.enqueued[0]["rows"][0]
    assert row["service_environment"] == "live"
    assert row["runtime_host"] == "gulong-chatbot-runtime-live"


def test_dual_analytics_writer_fans_out_rows():
    primary = FakeWriter()
    secondary = FakeWriter()
    writer = DualAnalyticsWriter(primary=primary, secondary=secondary)

    writer.enqueue("turn_fact_log", [{"row_id": "row_1", "tokens_total": 12}], key_columns=["row_id"])
    writer.flush("turn_fact_log")

    assert primary.enqueued[0]["table"] == "turn_fact_log"
    assert secondary.enqueued[0]["rows"][0]["row_id"] == "row_1"
    assert primary.flushed == ["turn_fact_log"]
    assert secondary.flushed == ["turn_fact_log"]


def test_dual_analytics_writer_async_flush_dispatches_primary_only():
    primary = FakeWriter()
    secondary = FakeWriter()
    writer = DualAnalyticsWriter(primary=primary, secondary=secondary)

    writer.flush_async("turn_trace_log")

    assert primary.async_flushed == ["turn_trace_log"]
    assert secondary.async_flushed == []


def test_dual_analytics_writer_fail_open_preserves_primary_on_secondary_error():
    primary = FakeWriter()
    secondary = FakeWriter()

    def fail_enqueue(*_args, **_kwargs):
        raise RuntimeError("postgres down")

    secondary.enqueue = fail_enqueue
    writer = DualAnalyticsWriter(primary=primary, secondary=secondary, fail_open=True)

    writer.enqueue("assistant_log", [{"row_id": "row_1"}], key_columns=["row_id"])

    assert primary.enqueued[0]["rows"][0]["row_id"] == "row_1"


def test_postgres_analytics_config_validates_identifiers():
    cfg = build_postgres_analytics_config(
        dsn="postgresql://runtime:test@127.0.0.1/db",
        schema="runtime_shadow",
        ensure_tables=False,
    )

    assert cfg.schema == "runtime_shadow"
    assert cfg.ensure_tables is False


def test_bigquery_gateway_uses_configured_writer_provider(tmp_path):
    writer = FakeWriter()
    register_analytics_writer("fake_dual_provider", lambda _cfg: writer)
    config_path = tmp_path / "bq_analytics.json"
    config_path.write_text(
        """
{
  "enabled": true,
  "gateway": "bigquery",
  "provider": "fake_dual_provider",
  "project_id": "test-project",
  "dataset": "analytics",
  "location": "asia-southeast1",
  "credentials_json": null
}
""".strip(),
        encoding="utf-8",
    )

    gateway = build_analytics_gateway(str(config_path))
    gateway.enqueue_turn_fact_log({"request_id": "req_provider", "tokens_total": "3"})

    assert writer.enqueued[0]["table"] == "turn_fact_log"
    assert writer.enqueued[0]["rows"][0]["request_id"] == "req_provider"


def test_postgres_analytics_row_id_column_detection_handles_schema_dicts():
    columns = [{"name": "row_id", "type": "STRING"}, {"name": "request_id", "type": "STRING"}]

    assert _has_column(columns, "row_id") is True
    assert _has_column(columns, "missing") is False


def test_postgres_analytics_json_schema_columns_wrap_string_scalars_as_jsonb():
    if pg_writer.Jsonb is None:
        pytest.skip("psycopg Jsonb adapter is not installed")

    json_columns = pg_writer._json_columns(turn_trace_log_schema())
    wrapped = pg_writer._coerce_value("plain scalar from compact trace", is_json="final_response" in json_columns)

    assert isinstance(wrapped, pg_writer.Jsonb)


def test_bigquery_credentials_accept_python_literal_mapping():
    raw = "{'type': 'service_account', 'project_id': 'gulong-chatbot-459723'}"

    parsed = _load_service_account_mapping(raw)

    assert parsed["type"] == "service_account"
    assert parsed["project_id"] == "gulong-chatbot-459723"
