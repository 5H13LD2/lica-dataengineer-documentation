-- Cloud SQL PostgreSQL DDL for Runtime V7 analytics parity storage.
-- BigQuery remains the reporting surface during migration. These tables mirror
-- runtime/shared/analytics_schema.py so VM-served traffic can be compared
-- against BigQuery using request_id, trace_id, session_id, user_id, and turn ids.

CREATE SCHEMA IF NOT EXISTS runtime_shadow;

CREATE TABLE IF NOT EXISTS runtime_shadow.assistant_log (
  row_id TEXT PRIMARY KEY,
  request_id TEXT,
  ts TIMESTAMP WITHOUT TIME ZONE,
  trace_id TEXT,
  session_id TEXT,
  user_id TEXT,
  channel TEXT,
  platform TEXT,
  business_unit TEXT,
  message TEXT,
  has_tools BOOLEAN,
  delivery_suppressed BOOLEAN,
  suppress_reason TEXT,
  elapsed_ms BIGINT,
  llm_calls BIGINT,
  tool_calls BIGINT,
  tool_failures BIGINT,
  tool_rounds BIGINT,
  request_payload JSONB,
  llm_spans JSONB,
  tagging_error TEXT,
  tagging_error_label TEXT
);

CREATE TABLE IF NOT EXISTS runtime_shadow.tool_output_log (
  row_id TEXT PRIMARY KEY,
  request_id TEXT,
  ts TIMESTAMP WITHOUT TIME ZONE,
  trace_id TEXT,
  session_id TEXT,
  user_id TEXT,
  tool_name TEXT,
  ok BOOLEAN,
  error TEXT,
  args JSONB,
  data JSONB
);

CREATE TABLE IF NOT EXISTS runtime_shadow.error_log (
  row_id TEXT PRIMARY KEY,
  request_id TEXT,
  ts TIMESTAMP WITHOUT TIME ZONE,
  trace_id TEXT,
  session_id TEXT,
  user_id TEXT,
  error TEXT
);

CREATE TABLE IF NOT EXISTS runtime_shadow.slots_log (
  row_id TEXT PRIMARY KEY,
  request_id TEXT,
  ts TIMESTAMP WITHOUT TIME ZONE,
  trace_id TEXT,
  session_id TEXT,
  user_id TEXT,
  channel TEXT,
  business_unit TEXT,
  slots JSONB,
  slots_meta JSONB
);

CREATE TABLE IF NOT EXISTS runtime_shadow.debug_log (
  row_id TEXT PRIMARY KEY,
  request_id TEXT,
  ts TIMESTAMP WITHOUT TIME ZONE,
  trace_id TEXT,
  session_id TEXT,
  user_id TEXT,
  channel TEXT,
  business_unit TEXT,
  debug_payload JSONB
);

CREATE TABLE IF NOT EXISTS runtime_shadow.request_state_log (
  row_id TEXT PRIMARY KEY,
  request_id TEXT,
  ts TIMESTAMP WITHOUT TIME ZONE,
  trace_id TEXT,
  session_id TEXT,
  user_id TEXT,
  channel TEXT,
  business_unit TEXT,
  runtime_version TEXT,
  message_id TEXT,
  idempotency_key TEXT,
  request_source TEXT,
  status TEXT,
  attempt_count BIGINT,
  llm_executed BOOLEAN,
  last_error_type TEXT,
  last_error_stage TEXT,
  tokens_in BIGINT,
  tokens_out BIGINT,
  flow_stage_after TEXT,
  delivery_status TEXT,
  request_payload JSONB,
  final_response JSONB,
  meta JSONB
);

CREATE TABLE IF NOT EXISTS runtime_shadow.request_attempt_log (
  row_id TEXT PRIMARY KEY,
  request_id TEXT,
  ts TIMESTAMP WITHOUT TIME ZONE,
  trace_id TEXT,
  session_id TEXT,
  user_id TEXT,
  channel TEXT,
  business_unit TEXT,
  runtime_version TEXT,
  attempt_no BIGINT,
  stage TEXT,
  event_type TEXT,
  retryable BOOLEAN,
  latency_ms BIGINT,
  backoff_seconds BIGINT,
  session_locked BOOLEAN,
  llm_executed BOOLEAN,
  tokens_in BIGINT,
  tokens_out BIGINT,
  error_type TEXT,
  error_message TEXT,
  model TEXT,
  meta JSONB
);

CREATE TABLE IF NOT EXISTS runtime_shadow.turn_trace_log (
  row_id TEXT PRIMARY KEY,
  request_id TEXT,
  ts TIMESTAMP WITHOUT TIME ZONE,
  trace_id TEXT,
  session_id TEXT,
  user_id TEXT,
  channel_user_id TEXT,
  user_id_source TEXT,
  channel TEXT,
  business_unit TEXT,
  runtime_version TEXT,
  request_source TEXT,
  orchestration_mode TEXT,
  flow_stage_after TEXT,
  turn_latency_ms BIGINT,
  llm_calls BIGINT,
  tool_calls BIGINT,
  tool_failures BIGINT,
  request_payload JSONB,
  channel_context JSONB,
  llm_spans JSONB,
  tool_call_records JSONB,
  active_agents JSONB,
  agent_graph JSONB,
  memory_bank JSONB,
  slots JSONB,
  compatibility_state JSONB,
  canonical_state_snapshot JSONB,
  errors JSONB,
  final_response JSONB,
  tagging JSONB
);

CREATE TABLE IF NOT EXISTS runtime_shadow.turn_fact_log (
  row_id TEXT PRIMARY KEY,
  request_id TEXT,
  ts TIMESTAMP WITHOUT TIME ZONE,
  trace_id TEXT,
  session_id TEXT,
  user_id TEXT,
  channel TEXT,
  business_unit TEXT,
  runtime_version TEXT,
  request_source TEXT,
  orchestration_mode TEXT,
  flow_stage_after TEXT,
  turn_latency_ms BIGINT,
  tokens_in BIGINT,
  tokens_out BIGINT,
  tokens_total BIGINT,
  llm_calls BIGINT,
  tool_calls BIGINT,
  tool_failures BIGINT,
  has_tools BOOLEAN,
  out_of_flow_signal TEXT,
  response_bubble_count BIGINT,
  request_payload JSONB
);

CREATE TABLE IF NOT EXISTS runtime_shadow.llm_span_log (
  row_id TEXT PRIMARY KEY,
  request_id TEXT,
  ts TIMESTAMP WITHOUT TIME ZONE,
  trace_id TEXT,
  session_id TEXT,
  user_id TEXT,
  channel TEXT,
  business_unit TEXT,
  runtime_version TEXT,
  span_index BIGINT,
  component TEXT,
  agent_id TEXT,
  agent_role TEXT,
  parent_span_id TEXT,
  model TEXT,
  provider TEXT,
  tokens_in BIGINT,
  tokens_out BIGINT,
  latency_ms BIGINT,
  meta JSONB
);

CREATE TABLE IF NOT EXISTS runtime_shadow.tool_call_log (
  row_id TEXT PRIMARY KEY,
  request_id TEXT,
  ts TIMESTAMP WITHOUT TIME ZONE,
  trace_id TEXT,
  session_id TEXT,
  user_id TEXT,
  channel TEXT,
  business_unit TEXT,
  runtime_version TEXT,
  call_index BIGINT,
  tool_call_id TEXT,
  tool_name TEXT,
  component TEXT,
  agent_id TEXT,
  agent_role TEXT,
  ok BOOLEAN,
  error TEXT,
  latency_ms BIGINT,
  artifact_id TEXT,
  args JSONB,
  summary_context JSONB,
  presentation JSONB
);

DO $$
DECLARE
  target_table_name TEXT;
  target_column_name TEXT;
BEGIN
  FOREACH target_table_name IN ARRAY ARRAY[
    'assistant_log',
    'tool_output_log',
    'error_log',
    'slots_log',
    'debug_log',
    'request_state_log',
    'request_attempt_log',
    'turn_trace_log',
    'turn_fact_log',
    'llm_span_log',
    'tool_call_log'
  ]
  LOOP
    FOREACH target_column_name IN ARRAY ARRAY['ts', 'request_id', 'trace_id', 'session_id', 'user_id']
    LOOP
      IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'runtime_shadow'
          AND table_name = target_table_name
          AND column_name = target_column_name
      ) THEN
        EXECUTE format(
          'CREATE INDEX IF NOT EXISTS %I ON runtime_shadow.%I (%I)',
          target_table_name || '_' || target_column_name || '_idx',
          target_table_name,
          target_column_name
        );
      END IF;
    END LOOP;
  END LOOP;
END $$;
