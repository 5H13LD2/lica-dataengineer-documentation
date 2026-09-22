-- Runtime V7 BigQuery freshness check for the customer-serving VM path.
-- Use a settled cutoff because BigQuery landing is asynchronous.  Compare
-- CloudSQL with the same Asia/Manila DATETIME bounds and DISTINCT row_id.

DECLARE observation_cutoff DATETIME DEFAULT
  DATETIME_SUB(CURRENT_DATETIME('Asia/Manila'), INTERVAL 5 MINUTE);
DECLARE window_start DATETIME DEFAULT
  DATETIME_SUB(observation_cutoff, INTERVAL 24 HOUR);

WITH table_health AS (
  SELECT 'request_state_log' AS table_name, COUNT(DISTINCT row_id) AS row_count, MAX(ts) AS latest_ts
  FROM `gulong-chatbot-459723.gulong_chatbot_live.request_state_log`
  WHERE service_environment = 'live' AND runtime_host = 'vm-live'
    AND ts >= window_start AND ts < observation_cutoff
  UNION ALL
  SELECT 'request_attempt_log', COUNT(DISTINCT row_id), MAX(ts)
  FROM `gulong-chatbot-459723.gulong_chatbot_live.request_attempt_log`
  WHERE service_environment = 'live' AND runtime_host = 'vm-live'
    AND ts >= window_start AND ts < observation_cutoff
  UNION ALL
  SELECT 'turn_trace_log', COUNT(DISTINCT row_id), MAX(ts)
  FROM `gulong-chatbot-459723.gulong_chatbot_live.turn_trace_log`
  WHERE service_environment = 'live' AND runtime_host = 'vm-live'
    AND ts >= window_start AND ts < observation_cutoff
  UNION ALL
  SELECT 'turn_fact_log', COUNT(DISTINCT row_id), MAX(ts)
  FROM `gulong-chatbot-459723.gulong_chatbot_live.turn_fact_log`
  WHERE service_environment = 'live' AND runtime_host = 'vm-live'
    AND ts >= window_start AND ts < observation_cutoff
  UNION ALL
  SELECT 'llm_span_log', COUNT(DISTINCT row_id), MAX(ts)
  FROM `gulong-chatbot-459723.gulong_chatbot_live.llm_span_log`
  WHERE service_environment = 'live' AND runtime_host = 'vm-live'
    AND ts >= window_start AND ts < observation_cutoff
  UNION ALL
  SELECT 'tool_call_log', COUNT(DISTINCT row_id), MAX(ts)
  FROM `gulong-chatbot-459723.gulong_chatbot_live.tool_call_log`
  WHERE service_environment = 'live' AND runtime_host = 'vm-live'
    AND ts >= window_start AND ts < observation_cutoff
  UNION ALL
  SELECT 'interaction_event_log', COUNT(DISTINCT row_id), MAX(ts)
  FROM `gulong-chatbot-459723.gulong_chatbot_live.interaction_event_log`
  WHERE service_environment = 'live' AND runtime_host = 'vm-live'
    AND ts >= window_start AND ts < observation_cutoff
)
SELECT
  table_name,
  row_count,
  latest_ts,
  DATETIME_DIFF(observation_cutoff, latest_ts, MINUTE) AS settled_freshness_minutes
FROM table_health
ORDER BY table_name;
