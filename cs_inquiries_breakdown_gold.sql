#standardSQL
CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.cs_inquiries_breakdown_gold`
PARTITION BY report_date
CLUSTER BY agent_group, agent_key, agent_name
AS
WITH reporting_base AS (
  /*
    Source-of-truth inquiry counts and reporting dimensions.
    This guarantees total_inquiries stays aligned with the same reporting
    grain and ownership logic already used in p_looker_agent_daily_conversion.
  */
  SELECT
    report_date,
    agent_group,
    agent_key,
    agent_name,
    total_inquiries
  FROM `gulong-chatbot-459723.gulong_reporting.p_looker_agent_daily_conversion`
),

date_bounds AS (
  /*
    Bound upstream partition scans to the reporting window represented in
    the source-of-truth table.
  */
  SELECT
    MIN(report_date) AS min_report_date,
    MAX(report_date) AS max_report_date
  FROM reporting_base
),

session_base AS (
  /*
    Inquiry-session grain for CS reply metrics.
    We keep session-level response calculations separate from the authoritative
    inquiry-count base so that reporting totals remain consistent with p_looker.
  */
  SELECT
    inquiry_day AS report_date,
    user_id AS customer_id,
    silver_session_id,
    first_user_message_at AS first_customer_message_at,
    LEAD(first_user_message_at) OVER (
      PARTITION BY user_id
      ORDER BY first_user_message_at, silver_session_id
    ) AS next_session_start_at
  FROM `gulong-chatbot-459723.gulong_core.fb_inquiry_sessions`
  CROSS JOIN date_bounds d
  WHERE business_unit = 'gulong'
    AND channel = 'manychat'
    AND inquiry_day BETWEEN d.min_report_date AND d.max_report_date
),

latest_reporting_assignment AS (
  /*
    Reuse the production reporting mapping from inquiry_assignments.
    Keep reporting dimensions on the assignment-side grain only.
  */
  SELECT
    silver_session_id,
    COALESCE(agent_reporting_group, 'unknown') AS agent_group,
    COALESCE(agent_reporting_name, 'Unassigned') AS agent_name,
    ROW_NUMBER() OVER (
      PARTITION BY silver_session_id
      ORDER BY assignment_at DESC, assignment_event_id DESC
    ) AS rn
  FROM `gulong-chatbot-459723.gulong_core.inquiry_assignments`
  CROSS JOIN date_bounds d
  WHERE business_unit = 'gulong'
    AND silver_session_id IS NOT NULL
    AND inquiry_day BETWEEN d.min_report_date AND d.max_report_date
),

session_with_agent AS (
  /*
    One row per session with reporting dimensions attached for reply metrics.
    Sessions without assignment mapping are retained as unassigned; the final
    table will still use reporting_base as the authoritative inquiry count.
  */
  SELECT
    s.report_date,
    s.customer_id,
    s.silver_session_id,
    s.first_customer_message_at,
    s.next_session_start_at,
    COALESCE(a.agent_group, 'unknown') AS agent_group,
    COALESCE(a.agent_name, 'Unassigned') AS agent_name
  FROM session_base s
  LEFT JOIN latest_reporting_assignment a
    ON a.silver_session_id = s.silver_session_id
   AND a.rn = 1
),

first_cs_reply AS (
  /*
    First human CS reply after the session's first customer message.
    The upper bound prevents a later session's reply from being attached
    to the earlier session when a customer has multiple sessions.
  */
  SELECT
    s.silver_session_id,
    MIN(m.datetime) AS first_cs_reply_at
  FROM session_with_agent s
  LEFT JOIN `gulong-chatbot-459723.manychat_data.messages` m
    ON m.datetime >= DATETIME((SELECT min_report_date FROM date_bounds))
   AND m.datetime < DATETIME(DATE_ADD((SELECT max_report_date FROM date_bounds), INTERVAL 2 DAY))
   AND m.user_id = s.customer_id
   AND m.business_unit = 'gulong'
   AND m.role = 'agent'
   AND m.type = 'msgout_lc'
   AND m.datetime >= s.first_customer_message_at
   AND (
     s.next_session_start_at IS NULL
     OR m.datetime < s.next_session_start_at
   )
  GROUP BY s.silver_session_id
),

session_metrics AS (
  /*
    Session-level reply facts keyed by assignment-side reporting name/group.
    Note: this currently aggregates by agent_group + agent_name on the
    operational side. If duplicate display names are introduced in the future,
    the session-side key should be upgraded to a first-class production key.
  */
  SELECT
    s.report_date,
    s.agent_group,
    s.agent_name,
    s.silver_session_id,
    s.customer_id,
    s.first_customer_message_at,
    r.first_cs_reply_at,
    DATETIME_DIFF(r.first_cs_reply_at, s.first_customer_message_at, MINUTE) AS cs_response_minutes
  FROM session_with_agent s
  LEFT JOIN first_cs_reply r
    ON r.silver_session_id = s.silver_session_id
),

agent_day_rollup AS (
  /*
    Reply metrics at the reporting grain before attaching the final agent_key.
  */
  SELECT
    report_date,
    agent_group,
    agent_name,
    COUNTIF(cs_response_minutes >= 0) AS total_cs_replied,
    AVG(IF(cs_response_minutes >= 0, cs_response_minutes, NULL)) AS avg_cs_response_minutes,
    APPROX_QUANTILES(IF(cs_response_minutes >= 0, cs_response_minutes, NULL), 100)[OFFSET(50)] AS median_cs_response_minutes
  FROM session_metrics
  GROUP BY report_date, agent_group, agent_name
)

SELECT
  b.report_date,
  b.agent_group,
  b.agent_key,
  b.agent_name,
  b.total_inquiries,
  COALESCE(r.total_cs_replied, 0) AS total_cs_replied,
  r.avg_cs_response_minutes,
  SAFE_DIVIDE(COALESCE(r.total_cs_replied, 0), b.total_inquiries) AS cs_reply_rate,
  r.median_cs_response_minutes,
  CURRENT_DATETIME('Asia/Manila') AS gold_loaded_at
FROM reporting_base b
LEFT JOIN agent_day_rollup r
  ON r.report_date = b.report_date
 AND r.agent_group = b.agent_group
 AND r.agent_name = b.agent_name;
