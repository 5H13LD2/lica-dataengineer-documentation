-- Runtime V7 normalized warehouse consumer surfaces.
--
-- These views intentionally do not revive assistant_log/tool_output_log/error_log.
-- Runtime V7 emits normalized rows; turn_trace_log is the canonical customer-turn
-- record and contains enough evidence to reconstruct the rendered reply, model
-- spans, tool calls, state snapshots, and errors.
--
-- All timestamps are DATETIME values written in Asia/Manila local time.  Consumers
-- comparing BigQuery with the VM CloudSQL mirror must use the same Manila-local
-- cutoff and a minimum five-minute observation lag.

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_chatbot_live.v_runtime_v7_turns` AS
WITH ranked AS (
  SELECT
    turn_trace_log.*,
    ROW_NUMBER() OVER (
      PARTITION BY row_id
      ORDER BY ts DESC, request_id DESC
    ) AS row_rank
  FROM `gulong-chatbot-459723.gulong_chatbot_live.turn_trace_log` AS turn_trace_log
  WHERE row_id IS NOT NULL
)
SELECT
  row_id,
  request_id,
  ts,
  trace_id,
  session_id,
  user_id,
  channel_user_id,
  user_id_source,
  channel,
  business_unit,
  runtime_version,
  request_source,
  orchestration_mode,
  flow_stage_after,
  turn_latency_ms,
  llm_calls,
  tool_calls,
  tool_failures,
  CASE
    WHEN JSON_QUERY(request_payload, '$.flow_context.promo_action_context') IS NOT NULL
      OR JSON_QUERY(request_payload, '$.flow_context.choice_action_context') IS NOT NULL
      OR JSON_QUERY(request_payload, '$.flow_context.choice_action_runtime_context') IS NOT NULL
      THEN 'guided_action'
    ELSE 'free_text'
  END AS input_mode,
  JSON_VALUE(request_payload, '$.user_text') AS user_text,
  JSON_VALUE(final_response, '$.text') AS response_text,
  JSON_VALUE(final_response, '$.delivery_result.status') AS delivery_status,
  request_payload,
  channel_context,
  llm_spans,
  tool_call_records,
  memory_bank,
  slots,
  compatibility_state,
  canonical_state_snapshot,
  errors,
  final_response,
  tagging,
  service_environment,
  runtime_host,
  release_version,
  git_sha
FROM ranked
WHERE row_rank = 1;

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_chatbot_live.v_runtime_v7_free_text_turns` AS
SELECT *
FROM `gulong-chatbot-459723.gulong_chatbot_live.v_runtime_v7_turns`
WHERE input_mode = 'free_text';

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_chatbot_live.v_runtime_v7_tool_calls` AS
SELECT * EXCEPT (row_rank)
FROM (
  SELECT
    tool_call_log.*,
    ROW_NUMBER() OVER (
      PARTITION BY row_id
      ORDER BY ts DESC, request_id DESC, call_index DESC
    ) AS row_rank
  FROM `gulong-chatbot-459723.gulong_chatbot_live.tool_call_log` AS tool_call_log
  WHERE row_id IS NOT NULL
)
WHERE row_rank = 1;

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_chatbot_live.v_runtime_v7_llm_spans` AS
SELECT * EXCEPT (row_rank)
FROM (
  SELECT
    llm_span_log.*,
    ROW_NUMBER() OVER (
      PARTITION BY row_id
      ORDER BY ts DESC, request_id DESC, span_index DESC
    ) AS row_rank
  FROM `gulong-chatbot-459723.gulong_chatbot_live.llm_span_log` AS llm_span_log
  WHERE row_id IS NOT NULL
)
WHERE row_rank = 1;

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_chatbot_live.v_runtime_v7_interactions` AS
SELECT * EXCEPT (row_rank)
FROM (
  SELECT
    interaction_event_log.*,
    ROW_NUMBER() OVER (
      PARTITION BY row_id
      ORDER BY ts DESC, request_id DESC
    ) AS row_rank
  FROM `gulong-chatbot-459723.gulong_chatbot_live.interaction_event_log` AS interaction_event_log
  WHERE row_id IS NOT NULL
)
WHERE row_rank = 1;

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_chatbot_live.v_runtime_v7_errors` AS
WITH canonical_turns AS (
  SELECT *
  FROM `gulong-chatbot-459723.gulong_chatbot_live.v_runtime_v7_turns`
),
turn_errors AS (
  SELECT
    turns.row_id,
    turns.request_id,
    turns.ts,
    turns.trace_id,
    turns.session_id,
    turns.user_id,
    turns.channel,
    turns.business_unit,
    turns.runtime_version,
    turns.service_environment,
    turns.runtime_host,
    turns.release_version,
    turns.git_sha,
    'turn' AS error_source,
    JSON_VALUE(error_item, '$.error_type') AS error_type,
    COALESCE(
      JSON_VALUE(error_item, '$.error'),
      JSON_VALUE(error_item, '$.error_message')
    ) AS error_message,
    error_item AS error_payload
  FROM canonical_turns AS turns,
  UNNEST(IFNULL(JSON_QUERY_ARRAY(turns.errors), [])) AS error_item
),
tool_errors AS (
  SELECT
    row_id,
    request_id,
    ts,
    trace_id,
    session_id,
    user_id,
    channel,
    business_unit,
    runtime_version,
    service_environment,
    runtime_host,
    release_version,
    git_sha,
    'tool' AS error_source,
    tool_name AS error_type,
    error AS error_message,
    TO_JSON(STRUCT(tool_name, call_index, args, summary_context)) AS error_payload
  FROM `gulong-chatbot-459723.gulong_chatbot_live.v_runtime_v7_tool_calls`
  WHERE NOT COALESCE(ok, FALSE) OR NULLIF(error, '') IS NOT NULL
)
SELECT * FROM turn_errors
UNION ALL
SELECT * FROM tool_errors;
