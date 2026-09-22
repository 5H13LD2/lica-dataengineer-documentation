-- Bounded review bundle for customer-authored free-text continuity.
-- This query deliberately does not classify semantic quality with phrase
-- matching.  A capable reviewer/model should judge the complete adjacent
-- turns, while deterministic monitoring is limited to cohort and delivery.

DECLARE observation_cutoff DATETIME DEFAULT
  DATETIME_SUB(CURRENT_DATETIME('Asia/Manila'), INTERVAL 5 MINUTE);
DECLARE window_start DATETIME DEFAULT
  DATETIME_SUB(observation_cutoff, INTERVAL 24 HOUR);

WITH ordered AS (
  SELECT
    row_id,
    request_id,
    ts,
    user_id,
    session_id,
    release_version,
    git_sha,
    flow_stage_after,
    delivery_status,
    user_text,
    response_text,
    tool_calls,
    tool_failures,
    LAG(user_text) OVER (PARTITION BY user_id ORDER BY ts, row_id) AS prior_user_text,
    LAG(response_text) OVER (PARTITION BY user_id ORDER BY ts, row_id) AS prior_response_text
  FROM `gulong-chatbot-459723.gulong_chatbot_live.v_runtime_v7_free_text_turns`
  WHERE service_environment = 'live'
    AND runtime_host = 'vm-live'
    AND ts >= window_start
    AND ts < observation_cutoff
    AND NULLIF(TRIM(user_text), '') IS NOT NULL
)
SELECT *
FROM ordered
ORDER BY ts DESC
LIMIT 200;
